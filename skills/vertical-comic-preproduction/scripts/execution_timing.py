"""Observed event times only. Never reconstruct missing service or human times."""
from datetime import datetime, timezone

POLICY = 'observed_execution_timing_v1'


def observe(state, row, event):
    if state.get('timing_policy') != POLICY:
        return
    if event not in {'ready', 'qa_registered'}:
        raise ValueError('Unknown observed execution event')
    stamp = datetime.now(timezone.utc).isoformat()
    key = 'ready_at' if event == 'ready' else 'qa_recorded_at'
    # A new attempt must not inherit the previous attempt's observation.
    observations = row.setdefault('timing_observations', {})
    if observations.get('attempt_id') != row['attempt_id']:
        observations.clear()
        observations['attempt_id'] = row['attempt_id']
    if key not in observations:
        observations[key] = {'at': stamp, 'source': 'validated_reservation' if event == 'ready' else 'validated_qa_registration'}
        if event == 'qa_registered':
            observations[key]['qa_report'] = row.get('qa_report')
        row[key] = stamp
