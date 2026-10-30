/* Load this function into functions.exec; inject authorized tools and serialized receipt persistence.
   This is not a shell image backend. It never selects a model or fabricates tool arguments. */
(async function runHalfWave(jobs, limit, invoke, onResult, options = {}) {
  if (!Array.isArray(jobs) || !Number.isInteger(limit) || limit < 1 || typeof invoke !== 'function' || typeof onResult !== 'function')
    throw new Error('jobs/confirmed concurrency/invoke/onResult required');
  // Pure SHA-256: functions.exec does not require Node/crypto globals.
  const canonical = v => v === null || typeof v !== 'object' ? JSON.stringify(v) :
    Array.isArray(v) ? '['+v.map(canonical).join(',')+']' :
    '{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}';
  function sha256(text) {
    const bytes=Array.from(unescape(encodeURIComponent(text)),c=>c.charCodeAt(0));
    const bitLength=bytes.length*8; bytes.push(128);while(bytes.length%64!==56)bytes.push(0);
    for(let i=7;i>=0;i--) bytes.push(i>=4?0:(bitLength>>> (i*8))&255);
    const primes=[],K=[],H=[];
    for(let n=2;primes.length<64;n++) {
      if(primes.every(p=>n%p!==0)) {primes.push(n);K.push((Math.cbrt(n)%1*4294967296)|0);if(H.length<8)H.push((Math.sqrt(n)%1*4294967296)|0);}
    }
    const rotr=(x,n)=>(x>>>n)|(x<<(32-n));
    for(let offset=0;offset<bytes.length;offset+=64) {
      const w=Array(64);
      for(let i=0;i<16;i++)w[i]=(bytes[offset+i*4]<<24)|(bytes[offset+i*4+1]<<16)|(bytes[offset+i*4+2]<<8)|bytes[offset+i*4+3];
      for(let i=16;i<64;i++) {const a=w[i-15],b=w[i-2];w[i]=(w[i-16]+(rotr(a,7)^rotr(a,18)^(a>>>3))+w[i-7]+(rotr(b,17)^rotr(b,19)^(b>>>10)))|0;}
      let [a,b,c,d,e,f,g,h]=H;
      for(let i=0;i<64;i++) {const t1=(h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^(~e&g))+K[i]+w[i])|0;
        const t2=((rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b)^(a&c)^(b&c)))|0;
        h=g;g=f;f=e;e=(d+t1)|0;d=c;c=b;b=a;a=(t1+t2)|0;}
      [a,b,c,d,e,f,g,h].forEach((v,i)=>H[i]=(H[i]+v)|0);
    }
    return H.map(v=>(v>>>0).toString(16).padStart(8,'0')).join('');
  }
  for (const key of ['acquireInvocation', 'releaseInvocation', 'onInvocationRequested'])
    if (options[key] !== undefined && typeof options[key] !== 'function') throw new Error(key+' must be a function');
  if (Boolean(options.acquireInvocation) !== Boolean(options.releaseInvocation)) throw new Error('Invocation acquire/release must be paired');
  const preparedMode = options.protocol === 'prepared_dispatch_v1';
  const capacityPollMs=options.capacityPollMs ?? 1000;
  if (!Number.isInteger(capacityPollMs) || capacityPollMs<100 || capacityPollMs>30000)
    throw new Error('capacity poll must be 100..30000ms');
  if (preparedMode && typeof options.onPrepareInvoke !== 'function') throw new Error('onPrepareInvoke required');
  // Keep the exact checked input across the asynchronous registration boundary.
  const freeze = value => {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value); }
    return value;
  };
  jobs = jobs.map(job => freeze(JSON.parse(JSON.stringify(job))));
  const target = j => j.kind === 'asset' ? j.asset_id : j.panel_id;
  const panelKeys = jobs.map(j => `${j.job_id}\u0000${j.kind === 'asset' ? 'asset' : 'panel'}\u0000${target(j)}`);
  if (jobs.some(j => !j.job_id || !target(j) || !j.attempt_id || ![undefined, 'panel', 'asset', 'repair'].includes(j.kind) || (j.kind !== 'asset' && (!j.batch_id || ![1, 2].includes(j.round_id)))) || new Set(panelKeys).size !== jobs.length)
    throw new Error('Missing immutable job/panel/batch/round/attempt or duplicate active panel');
  // Observed built-in local-reference limit. Full per-panel preflight remains
  // mandatory; this is a last check on the actual exported tool arguments.
  for (const job of jobs) {
    if (job.candidate_only === true || job.input_audit_only === true || job.dispatch_authorized === false)
      throw new Error("CANDIDATE_HOLD: review/audit-only jobs cannot be submitted");
    const refs = job.arguments?.referenced_image_paths;
    if (refs !== undefined && (!Array.isArray(refs) || refs.length > 5))
      throw new Error(`REFERENCE_LIMIT_HOLD: ${job.panel_id}, referenced_image_paths must contain at most 5 paths`);
    if (Array.isArray(refs) && new Set(refs).size !== refs.length)
      throw new Error(`REFERENCE_DUPLICATE_HOLD: ${job.panel_id}, merge same-file purposes before submitting`);
  }
  if (!preparedMode && typeof options.onBeforeInvoke !== 'function')
    throw new Error('SUBMISSION_HOLD: all jobs require durable onBeforeInvoke');
  if (!preparedMode && jobs.some(j => j.submission?.policy !== 'durable_image_submission_v1' ||
      !j.submission.task_id || !/^[a-f0-9]{64}$/.test(j.submission.input_digest) || !j.book_id || !j.episode_id))
    throw new Error('SUBMISSION_HOLD: exact compiled job/owner protocol required');
  if (options.onBeforeInvoke !== undefined && typeof options.onBeforeInvoke !== 'function') throw new Error('onBeforeInvoke must be a function');
  if (options.onReviewReady !== undefined && typeof options.onReviewReady !== "function") throw new Error("onReviewReady must be a function");
  if (options.onReviewBatchReady !== undefined && typeof options.onReviewBatchReady !== "function") throw new Error("onReviewBatchReady must be a function");
  if (options.onLongRequest !== undefined && typeof options.onLongRequest !== "function") throw new Error("onLongRequest must be a function");
  if (options.onPersisted !== undefined && typeof options.onPersisted !== "function") throw new Error("onPersisted must be a function");
  if (options.onInputHeadRefresh !== undefined && typeof options.onInputHeadRefresh !== "function") throw new Error("onInputHeadRefresh must be a function");
  if (options.onInputHeadRefresh && jobs.some(j => j.kind !== 'asset' && (!j.book_id || !j.episode_id)))
    throw new Error("INPUT_HEAD_SCOPE_HOLD: exact book/episode required before invoking");
  if (options.onProgress !== undefined && typeof options.onProgress !== 'function') throw new Error('onProgress must be a function');
  const progressIntervalMs = options.progressIntervalMs ?? 600000;
  const serviceProgressIntervalMs = options.serviceProgressIntervalMs ?? 900000;
  const progressPollMs = options.progressPollMs ?? 30000;
  if (![progressIntervalMs, serviceProgressIntervalMs, progressPollMs].every(v => Number.isInteger(v) && v > 0) ||
      progressPollMs > 60000 || serviceProgressIntervalMs < progressIntervalMs)
    throw new Error('progress intervals must be positive, service >= active, poll <= 60000ms');
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
  // Interleave episodes without changing the caller's result order or job identity.
  const order = [];
  const groups = new Map();
  jobs.forEach((job,index) => {
    const key=JSON.stringify([job.book_id,job.episode_id,job.job_id]);
    if (!groups.has(key)) groups.set(key,[]);
    groups.get(key).push(index);
  });
  while ([...groups.values()].some(q=>q.length))
    for (const queue of groups.values()) if (queue.length) order.push(queue.shift());
  const results = Array(jobs.length);
  let cursor = 0, stop = false, serviceErrors = 0, persistence = Promise.resolve();
  // A timer observes counters only. It never races/cancels invoke, releases a
  // permit, writes watchdog progress or invokes an image API a second time.
  let inFlight = 0, submittedCount = 0, returned = 0, persisted = 0, notificationBusy = false;
  let progressTimer, lastProgressAt = 0, lastProgressKey, lastProgressSignal = Promise.resolve();
  const progressErrors = [];
  function signalProgress(force = false, finished = false) {
    if (!options.onProgress || notificationBusy) return;
    const waitKind = inFlight > 0 && returned === persisted && pendingReview.length === 0 ? 'SERVICE' : 'NONE';
    const interval = waitKind === 'SERVICE' ? serviceProgressIntervalMs : progressIntervalMs;
    const key = `${stop}:${finished}`;
    if (!force && key === lastProgressKey && Date.now() - lastProgressAt < interval) return;
    lastProgressKey = key; lastProgressAt = Date.now(); notificationBusy = true;
    const event = {source: 'async_generation', kind: 'display_only', total_jobs: jobs.length,
      submitted: submittedCount, in_flight: inFlight, returned, persisted, wait_kind: waitKind,
      stopped: stop, finished, not_watchdog_progress: true};
    lastProgressSignal = Promise.resolve().then(() => options.onProgress(event)).catch(err => {
      progressErrors.push(errorData(err));
    }).finally(() => { notificationBusy = false; });
  }
  if (options.onProgress) {
    signalProgress(true);
    const poll = () => { signalProgress(); progressTimer = setTimeout(poll, progressPollMs); };
    progressTimer = setTimeout(poll, progressPollMs);
  }
  const seenRegistrations = new Set();
  const saveLanes = new Map();
  function persistFor(job, action) {
    if (!preparedMode) { const work=persistence.then(action); persistence=work.catch(()=>{}); return work; }
    const key=JSON.stringify([job.submission.task_id,job.episode_id,job.job_id]);
    const work=(saveLanes.get(key) ?? Promise.resolve()).then(action);
    saveLanes.set(key,work.catch(()=>{})); return work;
  }
  const pendingRegistrations=new Set();
  const maxPendingRegistrations=options.maxPendingRegistrations ?? 8;
  if (!Number.isInteger(maxPendingRegistrations) || maxPendingRegistrations<1) throw new Error('positive maxPendingRegistrations required');
  let pulling=Promise.resolve(), ended=false;
  async function nextJob() {
    const work=pulling.then(async()=>{
      if (stop) return null;
      if (cursor < order.length) { const index=order[cursor++]; return {index,job:jobs[index]}; }
      if (!preparedMode || !options.nextPrepared || ended) return null;
      const value=await options.nextPrepared();
      if (value == null) { ended=true; return null; }
      const job=freeze(JSON.parse(JSON.stringify(value))), index=jobs.length;
      jobs.push(job);return {index,job};
    }); pulling=work.catch(()=>{});return work;
  }
  async function worker() {
    while (!stop) {
      while (pendingRegistrations.size>=maxPendingRegistrations) await Promise.race(pendingRegistrations);
      const next=await nextJob(); if (!next) break;
      const index=next.index; let job=next.job;
      let item = {job_id: job.job_id, kind: job.kind ?? 'panel', panel_id: job.panel_id, asset_id: job.asset_id, attempt_id: job.attempt_id, batch_id: job.batch_id, round_id: job.round_id, ...(job.ready_at ? {ready_at:job.ready_at} : {})};
      let channel;
      try {
      async function releaseChannel() {
        if (channel === undefined) return;
        const lease=channel; channel=undefined;
        await options.releaseInvocation(lease, job, item);
      }
      {
        try {
          // Backpressure BEFORE durable registration. This lease is a local
          // transport lane, not evidence of remote rendering capacity.
          if (options.acquireInvocation) {
            channel=await options.acquireInvocation(job,()=>stop);
            if (channel == null) {channel=undefined;item.status='CHANNEL_UNAVAILABLE';results[index]=item;continue;}
          }
          let ack;
          if (preparedMode) {
            const expected = job;
            let prepared = await options.onPrepareInvoke(expected);
            if(prepared?.status==='REPAIR_DEFERRED'){
              item.status='REPAIR_DEFERRED';results[index]=item;await releaseChannel();continue;
            }
            while (prepared?.status === 'CAPACITY_FULL' && !prepared?.ack && !stop) {
              // Retain this exact unregistered reference, not a new attempt.
              // Capacity waiting is not a service failure or image retry.
              item.status='CAPACITY_WAIT';results[index]=item;await releaseChannel();
              await new Promise(resolve=>setTimeout(resolve,capacityPollMs));
              if (stop) break;
              if (options.acquireInvocation) {
                channel=await options.acquireInvocation(job,()=>stop);
                if (channel==null) {channel=undefined;throw new Error('CAPACITY_CHANNEL_UNAVAILABLE');}
              }
              if (stop) break;
              prepared=await options.onPrepareInvoke(expected);
            }
            if (stop && prepared?.status==='CAPACITY_FULL') {await releaseChannel();continue;}
            job = freeze(JSON.parse(JSON.stringify(prepared?.job ?? null)));
            ack = prepared?.ack;
            if (!job || job.candidate_only || job.input_audit_only || job.dispatch_authorized !== true ||
                job.submission?.policy !== 'prepared_dispatch_v1' ||
                job.prepared_reference?.prepared_input_id !== expected.prepared_input_id ||
                job.prepared_reference?.record_digest !== expected.record_digest ||
                ['book_id','episode_id','panel_id','attempt_id','round_id'].some(k => job[k] !== expected[k]) ||
                ack?.binding_digest !== job.submission.binding_digest ||
                sha256(canonical(job.arguments)) !== job.submission.binding_digest ||
                !Array.isArray(job.arguments?.referenced_image_paths) || job.arguments.referenced_image_paths.length > 5 ||
                new Set(job.arguments.referenced_image_paths).size !== job.arguments.referenced_image_paths.length)
              throw new Error('PREPARED_FINAL_JOB_MISMATCH');
            item = {...item,job_id:job.job_id,kind:job.kind,registration_id:ack.registration_id};
          } else ack = await options.onBeforeInvoke(job);
          if (ack?.policy !== (preparedMode ? 'prepared_dispatch_v1' : 'durable_image_submission_v1') || ack.status !== 'SUBMISSION_REGISTERED' || ack.invoke_allowed !== true ||
              !/^[a-f0-9]{64}$/.test(ack.registration_id) || seenRegistrations.has(ack.registration_id) ||
              ack.scope?.task_id !== job.submission.task_id || ack.scope?.job_id !== job.job_id ||
              ack.scope?.book_id !== job.book_id || ack.scope?.episode_id !== job.episode_id ||
              ack.kind !== (job.kind ?? 'panel') || (ack.panel_id ?? null) !== (job.panel_id ?? null) ||
              (ack.asset_id ?? null) !== (job.asset_id ?? null) || ack.attempt_id !== job.attempt_id ||
              (ack.batch_id ?? null) !== (job.batch_id ?? null) || (ack.round_id ?? null) !== (job.round_id ?? null) ||
              ack.input_digest !== job.submission.input_digest ||
              (ack.permit_id ?? null) !== (job.dispatch_receipt?.permit_id ?? null)) {
            const failure = new Error('SUBMISSION_HOLD: no fresh exact registration; do not repeat image call');
            failure.registration_ack = ack;
            throw failure;
          }
          if (preparedMode) {
            const keys=['kind','book_id','episode_id','job_id','panel_id','asset_id','batch_id','round_id','attempt_id','arguments','dispatch_receipt','submission'];
            const binding=Object.fromEntries(keys.map(k=>[k,job[k]??null]));
            if (sha256(canonical(binding))!==ack.job_digest) throw new Error('PREPARED_ACK_JOB_DIGEST_MISMATCH');
          }
          seenRegistrations.add(ack.registration_id);
          item.registration_id = ack.registration_id;
        } catch (err) {
          // Only known pre-registration, panel-scoped failures may leave
          // independent jobs running. Corrupt receipts and unknown errors stop.
          const scoped = preparedMode && options.continueIndependent === true &&
            /^(PREPARED_INPUT_CHANGED:|PREPARED_PACKAGE_CHANGED|PREPARED_ATTEMPT_CHANGED|PREPARED_DEPENDENCY_CHANGED:|PANEL_DISPATCH_HELD)/.test(String(err?.message ?? err));
          if (!scoped) stop = true;
          await releaseChannel();
          item.status = 'NOT_DISPATCHED'; item.outcome_hint = 'CHECK_SUBMISSION_REGISTRATION';
          item.submission_error = errorData(err); results[index] = item; continue;
        }
      }
      item.registered_at = new Date().toISOString();
      item.submitted_at = item.registered_at; // Legacy field; not native start evidence.
      try {
        if (options.onInvocationRequested) await options.onInvocationRequested(job, item);
      } catch (err) {
        stop=true;item.status='NOT_DISPATCHED';item.outcome_hint='REGISTERED_NOT_INVOKED';
        item.submission_error=errorData(err);results[index]=item;await releaseChannel();continue;
      }
      item.invocation_requested_at = new Date().toISOString();
      inFlight++; submittedCount++;
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
        item.result = await invoke(job, channel, item); item.transport_status = 'FULFILLED'; item.status = 'FULFILLED';
        item.outcome_hint = item.result === undefined ? 'NO_RESULT_CAPTURED' : 'INSPECT_REAL_OUTPUT';
        if (item.result?.isError === true) {
          item.status = 'REJECTED';
          classify(item, item.result.error ?? item.result.content?.filter(x => x.type === 'text').map(x => x.text).join('\n') ?? 'Tool returned isError');
        }
      }
      catch (err) { item.transport_status = 'REJECTED'; item.status = 'REJECTED'; classify(item, err); }
      inFlight--; returned++;
      for (const timer of longRequestTimers) clearTimeout(timer);
      item.returned_at = new Date().toISOString();
      results[index] = item;
      // Single-writer persistence, without serializing the image calls themselves.
      const capture = () => { item.save_started_at = new Date().toISOString(); return onResult(job, item); };
      const save = preparedMode && options.concurrentCapture ? capture() : persistFor(job,capture);
      persistence = save.catch(() => {});
      try {
        await save;
        // Only a durable, formally settled network failure is isolated per panel.
        // Unknown transport outcomes still trip the shared service circuit.
        const settledNetwork = preparedMode && item.confirmed_no_output === true &&
          /network error|error sending request|econnreset|econnrefused|enotfound/i.test(item.reason || '');
        if (item.service_error && !settledNetwork) {
          serviceErrors++;
          if (serviceErrors >= serviceLimit) { stop = true; item.dispatch_stop_reason = 'SERVICE_ERROR_CIRCUIT'; }
        } else if (settledNetwork || (item.status === 'FULFILLED' && item.result !== undefined)) serviceErrors = 0;
        item.saved_at = new Date().toISOString();
        persisted++;
        if (item.registration_pending) {
          // The durable receipt is the boundary: free the image channel while
          // the owner serializes registration. A single panel error stays local.
          await releaseChannel();
          const registration=Promise.resolve(item.registration_pending).then(()=>{
            item.registered_return_at=new Date().toISOString();
            if (item.status==='FULFILLED' && item.output_saved) notifyReview(job,item);
          }).catch(err=>{item.registration_error=errorData(err);item.outcome_hint='REPLAY_CAPTURED_RETURN';});
          pendingRegistrations.add(registration);
          registration.finally(()=>pendingRegistrations.delete(registration));
        }
        if (options.onPersisted) {
          // Persist final save timing in the same single-writer lane. This hook
          // records metadata only; no retry and no visual verdict is implied.
          const timedSave = persistFor(job, () => options.onPersisted(job, item));
          persistence = timedSave.catch(() => {});
          await timedSave;
        }
        if (!preparedMode && options.onInputHeadRefresh && job.kind !== 'asset') {
          // Refresh only after the real save and final timing persistence. This
          // callback invokes capture/bind, never image tools or QA approval.
          const refresh = persistFor(job, () => options.onInputHeadRefresh(job, item));
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
        if (!item.registration_pending && item.status === 'FULFILLED' && item.result !== undefined && item.output_saved !== false) {
          // Signal persisted outputs now, without holding an image-call slot during review.
          notifyReview(job, item);
        }
      }
      catch (err) { stop = true; item.persistence_error = String(err); item.persistence_error_detail = errorData(err); }
      finally {
        try { await releaseChannel(); }
        catch (err) {stop=true;item.channel_release_error=errorData(err);}
      }
      } finally {
        if (options.onJobSettled) await options.onJobSettled(job,item,{stopped:stop});
      }
    }
  }
  const workers = await Promise.allSettled(Array.from({length: (preparedMode && options.nextPrepared ? limit : Math.min(limit, jobs.length))}, () => worker()));
  const workerErrors = workers.filter(x => x.status === 'rejected').map(x => errorData(x.reason));
  await persistence;
  await Promise.allSettled([...pendingRegistrations]);
  flushReview();
  await Promise.allSettled(reviewSignals);
  if (progressTimer !== undefined) clearTimeout(progressTimer);
  await lastProgressSignal;
  signalProgress(true, true);
  await lastProgressSignal;
  if (progressErrors.length) for (const item of results) if (item) item.progress_signal_errors = progressErrors;
  return jobs.map((job, i) => results[i] || {job_id: job.job_id, kind: job.kind ?? 'panel', panel_id: job.panel_id, asset_id: job.asset_id, attempt_id: job.attempt_id, batch_id: job.batch_id, round_id: job.round_id, status: 'NOT_DISPATCHED', ...(workerErrors.length ? {worker_errors: workerErrors, outcome_hint: 'CHECK_UNTRACKED_WORKER'} : {})});
})
