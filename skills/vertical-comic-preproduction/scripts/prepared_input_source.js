/* Evaluate in the tool host. request sends correlated JSONL to one real
   generation_host; it must return the actual result, not a fabricated ack.
   This source prepares inputs only. It never grants authority or invokes images. */
(function createPreparedInputSource({request, panels, workers = 'all', bufferSize = 8, pollMs = 1000}) {
  if (typeof request !== 'function' || (workers !== 'all' && (!Number.isInteger(workers) || workers < 1)) ||
      !Number.isInteger(bufferSize) || bufferSize < 1 || !Number.isInteger(pollMs) || pollMs < 100 || pollMs > 30000)
    throw new Error('PREPARED_SOURCE_CONFIGURATION_INVALID');
  const queue = [], seen = new Set();
  let finished = false, failure, finalResult, latest, closed = false;
  let requests = 0, peakBuffered = 0, delivered = 0;
  // Start, but do not await the whole preparation before consuming ready inputs.
  const completion = Promise.resolve().then(() => request({action:'prepare-inputs', workers,
    ...(panels === undefined ? {} : {panels})})).then(result => {
    finalResult = result;
    if (!result || result.error) failure = new Error(result?.error || 'PREPARATION_RESULT_MISSING');
    return result;
  }, error => { failure = error; return {status:'HOLD', error:String(error)}; }).finally(() => { finished = true; });
  const delay = () => new Promise(resolve => setTimeout(resolve, pollMs));
  async function pull() {
    if (closed) return null;
    while (!queue.length) {
      // A ready snapshot read before completion cannot certify the final queue.
      const completedBeforeRead = finished;
      latest = await request({action:'ready-inputs', limit:bufferSize,
        exclude_record_digests:[...seen], record_timing:false,
        ...(panels === undefined ? {} : {panels})});
      requests++;
      if (!latest || latest.error || !Array.isArray(latest.jobs))
        throw new Error(latest?.error || 'READY_INPUTS_RESPONSE_INVALID');
      for (const ref of latest.jobs) {
        if (!ref.record_digest || !ref.prepared_input_id || !ref.attempt_id)
          throw new Error('READY_INPUT_REFERENCE_INVALID');
        if (!seen.has(ref.record_digest)) { seen.add(ref.record_digest); queue.push(ref); }
      }
      if (queue.length > bufferSize) throw new Error('READY_INPUTS_BUFFER_LIMIT_EXCEEDED');
      peakBuffered = Math.max(peakBuffered, queue.length);
      if (queue.length) break;
      if (completedBeforeRead) {
        if (failure || latest.preparation_error) throw failure || new Error(latest.preparation_error);
        if (!latest.preparation_complete) throw new Error('PREPARATION_COMPLETION_NOT_OBSERVED');
        // Blocked/invalidated panels remain in snapshot(); EOF is not delivery success.
        closed = true;
        return null;
      }
      if(Number.isInteger(latest.revision)) {
        // Notifications wait outside the state writer. Revision closes the gap
        // between the empty snapshot and subscription (no lost publication).
        await request({action:'wait-prepared-change',revision:latest.revision,timeout_seconds:2,record_timing:false});
      }else await delay(); // Explicit compatibility with an older frozen host.
    }
    delivered++;
    return queue.shift();
  }
  let reading = Promise.resolve();
  return {
    nextPrepared() { const result = reading.then(pull); reading = result.catch(() => {}); return result; },
    completion,
    snapshot: () => ({finished, closed, finalResult, latest, requests, delivered, peakBuffered,
      error:failure ? String(failure) : null})
  };
})
