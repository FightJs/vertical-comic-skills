"""Best-effort audit telemetry on stderr; never a gate, approval or image event."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import sys
import threading
import time

POLICY = 'audit_progress_v1'
_ACTIVE = ContextVar('comic_audit_progress', default=None)


class Progress:
    def __init__(self, episode, stream, interval):
        self.stream, self.interval = stream, interval
        self.started, self.cpu_started = time.monotonic(), time.process_time()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.current = {'episode_id': episode, 'stage': 'starting', 'panel_id': None,
                        'completed': 0, 'total': None, 'status': 'RUNNING'}
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    def emit(self):
        with self.lock:
            event = {'policy': POLICY, **self.current,
                     'elapsed_seconds': round(time.monotonic()-self.started, 3),
                     'cpu_seconds': round(time.process_time()-self.cpu_started, 3),
                     'not_approval_evidence': True}
            try:
                self.stream.write(json.dumps(event, ensure_ascii=False)+'\n')
                self.stream.flush()
            except (OSError, ValueError):
                pass  # Broken progress consumers must not change gate decisions.

    def _heartbeat(self):
        while not self.stop.wait(self.interval):self.emit()

    def update(self, **fields):
        with self.lock:self.current.update(fields)


def mark(stage=None, *, panel_id=None, completed=None, total=None, force=False):
    progress = _ACTIVE.get()
    if progress is None:return
    fields = {'panel_id': panel_id}
    if stage is not None:fields['stage'] = stage
    if completed is not None:fields['completed'] = completed
    if total is not None:fields['total'] = total
    progress.update(**fields)
    if force:progress.emit()


@contextmanager
def session(episode, *, enabled=False, stream=None, interval=10):
    if not enabled or _ACTIVE.get() is not None:
        yield
        return
    if interval <= 0:raise ValueError('Progress interval must be positive')
    progress = Progress(episode, stream if stream is not None else sys.stderr, interval)
    token = _ACTIVE.set(progress)
    progress.emit();progress.thread.start()
    try:
        yield
    except BaseException:
        progress.update(status='STOPPED_WITH_ERROR')
        raise
    else:
        progress.update(status='FINISHED_NOT_AUTHORIZATION')
    finally:
        progress.stop.set();progress.thread.join()
        progress.emit();_ACTIVE.reset(token)
