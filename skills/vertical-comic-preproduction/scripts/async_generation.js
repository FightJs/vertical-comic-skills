/* Load this function into functions.exec; inject authorized tools and serialized receipt persistence.
   This is not a shell image backend. It never selects a model or fabricates tool arguments. */
(async function runHalfWave(jobs, limit, invoke, onResult, options = {}) {
  if (!Array.isArray(jobs) || !Number.isInteger(limit) || limit < 1 || typeof invoke !== 'function' || typeof onResult !== 'function')
    throw new Error('jobs/confirmed concurrency/invoke/onResult required');
  const target = j => j.kind === 'asset' ? j.asset_id : j.panel_id;
  const panelKeys = jobs.map(j => `${j.job_id}\u0000${j.kind === 'asset' ? 'asset' : 'panel'}\u0000${target(j)}`);
  if (jobs.some(j => !j.job_id || !target(j) || !j.attempt_id || ![undefined, 'panel', 'asset', 'repair'].includes(j.kind) || (j.kind !== 'asset' && (!j.batch_id || ![1, 2].includes(j.round_id)))) || new Set(panelKeys).size !== jobs.length)
    throw new Error('Missing immutable job/panel/batch/round/attempt or duplicate active panel');
  // Observed built-in local-reference limit. Full per-panel preflight remains
  // mandatory; this is a last check on the actual exported tool arguments.
  for (const job of jobs) {
    if (job.candidate_only === true) throw new Error("CANDIDATE_HOLD: review-only jobs cannot be submitted");
    const refs = job.arguments?.referenced_image_paths;
    if (refs !== undefined && (!Array.isArray(refs) || refs.length > 5))
      throw new Error(`REFERENCE_LIMIT_HOLD: ${job.panel_id}, referenced_image_paths must contain at most 5 paths`);
    if (Array.isArray(refs) && new Set(refs).size !== refs.length)
      throw new Error(`REFERENCE_DUPLICATE_HOLD: ${job.panel_id}, merge same-file purposes before submitting`);
  }
  if (jobs.some(j => j.managed_submission_required === true) && typeof options.onBeforeInvoke !== 'function')
    throw new Error('SUBMISSION_HOLD: managed jobs require durable onBeforeInvoke');
  if (options.onBeforeInvoke !== undefined && typeof options.onBeforeInvoke !== 'function') throw new Error('onBeforeInvoke must be a function');
  if (options.onReviewReady !== undefined && typeof options.onReviewReady !== "function") throw new Error("onReviewReady must be a function");
  if (options.onReviewBatchReady !== undefined && typeof options.onReviewBatchReady !== "function") throw new Error("onReviewBatchReady must be a function");
  if (options.onLongRequest !== undefined && typeof options.onLongRequest !== "function") throw new Error("onLongRequest must be a function");
  if (options.onPersisted !== undefined && typeof options.onPersisted !== "function") throw new Error("onPersisted must be a function");
  if (options.onInputHeadRefresh !== undefined && typeof options.onInputHeadRefresh !== "function") throw new Error("onInputHeadRefresh must be a function");
  if (options.onInputHeadRefresh && jobs.some(j => j.kind !== 'asset' && (!j.book_id || !j.episode_id)))
    throw new Error("INPUT_HEAD_SCOPE_HOLD: exact book/episode required before invoking");
  const requestWarningMs = options.requestWarningMs ?? 900000;
  const requestEscalationMs = options.requestEscalationMs ?? 1800000;
  if (!Number.isInteger(requestWarningMs) || !Number.isInteger(requestEscalationMs) ||
      requestWarningMs < 1 || requestEscalationMs <= requestWarningMs)
    throw new Error("request watchdog thresholds must be positive, ordered milliseconds");
  const reviewGroupSize = options.reviewGroupSize ?? 4;
  const reviewMaxWaitMs = options.reviewMaxWaitMs ?? 30000;
  if (!Number.isInteger(reviewGroupSize) || reviewGroupSize < 3 || reviewGroupSize > 5 ||
      !Number.isInteger(reviewMaxWaitMs) || reviewMaxWaitMs < 1 || reviewMaxWaitMs > 30000)
    throw new Error("review group 3..5 and max wait 1..30000ms required");
  const serviceLimit = options.maxConsecutiveServiceErrors ?? 3;
  if (!Number.isInteger(serviceLimit) || serviceLimit < 1) throw new Error('positive service error limit required');
  function errorData(err, seen = new WeakSet()) {
    if (err === null || typeof err !== 'object') return {name: 'Error', message: String(err)};
    if (seen.has(err)) return '[Circular]';
    seen.add(err);
    function plain(value) {
      if (value instanceof Error) return errorData(value, seen);
      if (typeof value === 'bigint') return String(value);
      if (value === null || typeof value !== 'object') return value;
      if (seen.has(value)) return '[Circular]';
      seen.add(value);
      return Array.isArray(value) ? value.map(plain) : Object.fromEntries(Object.entries(value).filter(([,v]) => typeof v !== 'function').map(([k,v]) => [k,plain(v)]));
    }
    const fields = new Set([...Object.getOwnPropertyNames(err), 'name', 'message', 'stack', 'cause']);
    const value = Object.fromEntries([...fields].filter(k => err[k] !== undefined && typeof err[k] !== 'function').map(k => [k,plain(err[k])]));
    value.name ??= 'Error'; value.message ??= String(err);
    return value;
  }
  function classify(item, err) {
    item.error = errorData(err); item.reason = item.error.message;
    item.outcome_hint = /referenced_image_paths.*at most 5/i.test(item.reason) ? 'INPUT_REJECTED' : 'RESULT_UNKNOWN';
    item.service_error = /connection failed|error sending request|decoding response body|service unavailable/i.test(item.reason);
  }
  const reviewSignals = [];
  let pendingReview = [], reviewTimer;
  function flushReview() {
    if (reviewTimer !== undefined) { clearTimeout(reviewTimer); reviewTimer = undefined; }
    if (!pendingReview.length) return;
    const entries = pendingReview; pendingReview = [];
    const signal = Promise.resolve().then(() => options.onReviewBatchReady(entries)).catch(err => {
      for (const {item} of entries) {
        item.review_signal_error = String(err); item.review_signal_error_detail = errorData(err);
      }
    });
    reviewSignals.push(signal);
  }
  function notifyReview(job, item) {
    if (options.onReviewBatchReady) {
      pendingReview.push({job, item});
      if (job.review_priority || pendingReview.length >= reviewGroupSize) flushReview();
      else if (reviewTimer === undefined) reviewTimer = setTimeout(flushReview, reviewMaxWaitMs);
    } else if (options.onReviewReady) {
      const signal = Promise.resolve().then(() => options.onReviewReady(job, item)).catch(err => {
        item.review_signal_error = String(err); item.review_signal_error_detail = errorData(err);
      });
      reviewSignals.push(signal);
    }
  }
  const results = Array(jobs.length);
  let cursor = 0, stop = false, serviceErrors = 0, persistence = Promise.resolve();
  async function worker() {
    while (!stop && cursor < jobs.length) {
      const index = cursor++, job = jobs[index];
      let item = {job_id: job.job_id, kind: job.kind ?? 'panel', panel_id: job.panel_id, asset_id: job.asset_id, attempt_id: job.attempt_id, batch_id: job.batch_id, round_id: job.round_id, ...(job.ready_at ? {ready_at:job.ready_at} : {})};
      if (options.onBeforeInvoke && job.kind !== 'asset') {
        try {
          const ack = await options.onBeforeInvoke(job);
          if (ack?.status !== 'SUBMISSION_REGISTERED' || ack.invoke_allowed !== true ||
              ack.scope?.book_id !== job.book_id || ack.scope?.episode_id !== job.episode_id ||
              ack.panel_id !== job.panel_id || ack.attempt_id !== job.attempt_id || ack.round_id !== job.round_id ||
              !job.dispatch_receipt?.permit_id || ack.permit_id !== job.dispatch_receipt.permit_id)
            throw new Error('SUBMISSION_HOLD: no fresh exact registration; do not repeat image call');
        } catch (err) {
          stop = true; item.status = 'NOT_DISPATCHED'; item.outcome_hint = 'CHECK_SUBMISSION_REGISTRATION';
          item.submission_error = errorData(err); results[index] = item; continue;
        }
      }
      item.submitted_at = new Date().toISOString();
      const longRequestTimers = [];
      if (options.onLongRequest) {
        for (const [level, delay] of [['T1', requestWarningMs], ['T2', requestEscalationMs]]) {
          longRequestTimers.push(setTimeout(() => {
            const eventId = `request:${target(job)}:${job.attempt_id}:${level}`;
            const signal = Promise.resolve().then(() => options.onLongRequest(job, item, level, {event_id: eventId})).catch(err => {
              item.watchdog_signal_error ??= [];
              item.watchdog_signal_error.push({level, detail: errorData(err)});
            });
            reviewSignals.push(signal);
          }, delay));
        }
      }
      try {
        item.result = await invoke(job); item.transport_status = 'FULFILLED'; item.status = 'FULFILLED';
        item.outcome_hint = item.result === undefined ? 'NO_RESULT_CAPTURED' : 'INSPECT_REAL_OUTPUT';
        if (item.result?.isError === true) {
          item.status = 'REJECTED';
          classify(item, item.result.error ?? item.result.content?.filter(x => x.type === 'text').map(x => x.text).join('\n') ?? 'Tool returned isError');
        }
      }
      catch (err) { item.transport_status = 'REJECTED'; item.status = 'REJECTED'; classify(item, err); }
      for (const timer of longRequestTimers) clearTimeout(timer);
      if (item.service_error) { serviceErrors++; if (serviceErrors >= serviceLimit) { stop = true; item.dispatch_stop_reason = 'SERVICE_ERROR_CIRCUIT'; } }
      else if (item.status === 'FULFILLED' && item.result !== undefined) serviceErrors = 0;
      item.returned_at = new Date().toISOString();
      results[index] = item;
      // Single-writer persistence, without serializing the image calls themselves.
      const save = persistence.then(() => { item.save_started_at = new Date().toISOString(); return onResult(job, item); });
      persistence = save.catch(() => {});
      try {
        await save;
        item.saved_at = new Date().toISOString();
        if (options.onPersisted) {
          // Persist final save timing in the same single-writer lane. This hook
          // records metadata only; no retry and no visual verdict is implied.
          const timedSave = persistence.then(() => options.onPersisted(job, item));
          persistence = timedSave.catch(() => {});
          await timedSave;
        }
        if (options.onInputHeadRefresh && job.kind !== 'asset') {
          // Refresh only after the real save and final timing persistence. This
          // callback invokes capture/bind, never image tools or QA approval.
          const refresh = persistence.then(() => options.onInputHeadRefresh(job, item));
          persistence = refresh.catch(() => {});
          try {
            const head = await refresh;
            const sha = v => typeof v === 'string' && /^[0-9a-f]{64}$/.test(v);
            if (head?.status !== 'BOUND_NOT_DISPATCHABLE' || head.dispatch_authorized !== false ||
                head.scope?.book_id !== job.book_id || head.scope?.episode_id !== job.episode_id ||
                !sha(head.head_sha256) || !sha(head.state_sha256) || !sha(head.control_sha256))
              throw new Error('INPUT_HEAD_HOLD: missing or mismatched bound head acknowledgement');
            item.input_read_head = head;
          } catch (err) {
            // Saved bytes and original attempt remain real. Stop new invocations,
            // retain existing in-flight results and do not repeat onResult.
            stop = true;
            item.input_head_refresh_error = String(err);
            item.input_head_refresh_error_detail = errorData(err);
          }
        }
        if (item.status === 'FULFILLED' && item.result !== undefined && item.output_saved !== false) {
          // Signal persisted outputs now, without holding an image-call slot during review.
          notifyReview(job, item);
        }
      }
      catch (err) { stop = true; item.persistence_error = String(err); item.persistence_error_detail = errorData(err); }
    }
  }
  const workers = await Promise.allSettled(Array.from({length: Math.min(limit, jobs.length)}, () => worker()));
  const workerErrors = workers.filter(x => x.status === 'rejected').map(x => errorData(x.reason));
  await persistence;
  flushReview();
  await Promise.allSettled(reviewSignals);
  return jobs.map((job, i) => results[i] || {job_id: job.job_id, kind: job.kind ?? 'panel', panel_id: job.panel_id, asset_id: job.asset_id, attempt_id: job.attempt_id, batch_id: job.batch_id, round_id: job.round_id, status: 'NOT_DISPATCHED', ...(workerErrors.length ? {worker_errors: workerErrors, outcome_hint: 'CHECK_UNTRACKED_WORKER'} : {})});
})
