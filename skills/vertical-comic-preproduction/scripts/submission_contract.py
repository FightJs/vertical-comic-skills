"""Exact, durable image submission identities. No image calls or extra ledger."""
import hashlib
import json
import datetime
from pathlib import Path

POLICY = 'durable_image_submission_v1'


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def identity(state):
    return (state.get('task_context') or {}).get('task_id') or 'legacy:' + fingerprint(
        [state['book_id'], state['episode_id']])


def panel_job(state, root, record, packet, arguments, *, candidate=False, input_audit=False):
    from runtime_clock import execution_context
    context = execution_context(Path(root)/'00_输入审计/生产流程.json', state=state)
    kind = 'repair' if packet['panels'][0].get('operation') == 'repair' else 'panel'
    receipt = packet.get('dispatch_receipt')
    binding = {'policy': POLICY, 'task_id': identity(state),
               'execution_context': context['reference'] if context else None,
               'input_digest': fingerprint({'arguments': arguments, 'package': record['package_manifest']}),
               'package_manifest': record['package_manifest']}
    return {'kind': kind, 'book_id': state['book_id'], 'episode_id': state['episode_id'],
            'job_id': state.get('parallel_context', {}).get('job_id', state['episode_id']),
            'panel_id': record['panel_id'], 'batch_id': record.get('batch_id',packet.get('round_context',{}).get('batch_id')),
            'round_id': record['round_id'], 'attempt_id': record['attempt_id'],
            'arguments': arguments, 'dispatch_receipt': receipt, 'submission': binding,
            'candidate_only': candidate, 'input_audit_only': input_audit,
            'dispatch_authorized': False if candidate or input_audit else None,
            'managed_submission_required': True}


def validate_job(job, actual):
    if not isinstance(job, dict) or job.get('candidate_only') or job.get('input_audit_only') or job.get('dispatch_authorized') is False:
        raise ValueError('SUBMISSION_HOLD: review/audit input is not dispatchable')
    keys = ('kind', 'book_id', 'episode_id', 'job_id', 'panel_id', 'asset_id',
            'batch_id', 'round_id', 'attempt_id', 'arguments', 'dispatch_receipt', 'submission')
    if any(job.get(k) != actual.get(k) for k in keys):
        raise ValueError('SUBMISSION_HOLD: exact job/input/owner binding changed')


def registration(job):
    key = fingerprint([job['submission']['task_id'], job['job_id'], job['kind'],
                       job.get('panel_id') or job.get('asset_id'), job['attempt_id'], job.get('round_id')])
    return key, {'registration_id': key, 'job_digest': fingerprint(job_binding(job)),
                 'input_digest': job['submission']['input_digest'],
                 'registered_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 'observed_tool_call':False}


def job_binding(job):
    return {k: job.get(k) for k in ('kind', 'book_id', 'episode_id', 'job_id', 'panel_id',
                                   'asset_id', 'batch_id', 'round_id', 'attempt_id',
                                   'arguments', 'dispatch_receipt', 'submission')}


def acknowledgement(job, record, *, fresh, state_sha256):
    return {'policy': POLICY, 'status': 'SUBMISSION_REGISTERED' if fresh else 'ALREADY_REGISTERED',
            'invoke_allowed': fresh, 'registration_id': record['registration_id'],
            'scope': {'task_id': job['submission']['task_id'], 'book_id': job['book_id'],
                      'episode_id': job['episode_id'], 'job_id': job['job_id']},
            'kind': job['kind'], 'panel_id': job.get('panel_id'), 'asset_id': job.get('asset_id'),
            'batch_id': job.get('batch_id'), 'attempt_id': job['attempt_id'], 'round_id': job.get('round_id'),
            'permit_id': (job.get('dispatch_receipt') or {}).get('permit_id'),
            'input_digest': record['input_digest'], 'state_sha256': state_sha256, 'image_calls': 0}

PREPARED_POLICY='prepared_dispatch_v1'

def prepared_panel_job(state, value, receipt):
    row=next(r for r in state['panels'] if r['panel_id']==value['panel_id'])
    return {'kind':'repair' if row['round_id']==2 else 'panel','book_id':state['book_id'],
            'episode_id':state['episode_id'],'job_id':state.get('parallel_context',{}).get('job_id',state['episode_id']),
            'panel_id':row['panel_id'],'source_panel_id':row.get('source_panel_id'),'batch_id':'EPISODE',
            'round_id':row['round_id'],'attempt_id':row['attempt_id'],'arguments':value['arguments'],
            'package_manifest':value['package_manifest'],'dispatch_receipt':receipt,
            'prepared_reference':{k:value[k] for k in ('prepared_input_id','record_digest')},
            'submission':{'policy':PREPARED_POLICY,'task_id':identity(state),
                          'input_digest':value['semantic_input_digest'],
                          'binding_digest':fingerprint(value['arguments']),
                          'authority_revision':state.get('authority_revision',0)},
            'status':'NOT_RUN','candidate_only':False,'input_audit_only':False,'dispatch_authorized':True}


def prepared_acknowledgement(job, record, *, fresh, state_sha256):
    return {**acknowledgement(job,record,fresh=fresh,state_sha256=state_sha256),
            'policy':PREPARED_POLICY,'job_digest':fingerprint(job_binding(job)),
            'binding_digest':job['submission']['binding_digest']}
