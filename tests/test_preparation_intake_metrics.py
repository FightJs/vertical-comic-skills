"""Synthetic intake/cache and event accounting; no native service claims."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/vertical-comic-preproduction/scripts'))
import source_workbook as source
import script_catalog as catalog
import production_metrics as metrics


class IntakeCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.path = self.root / 'source.xlsx'; self.cache = self.root / 'cache'
        self.write()

    def write(self, text='“原文，不能改！”\n第二行'):
        from openpyxl import Workbook
        book = Workbook(); sheet = book.active; sheet.title = '第1话'
        sheet.append(['格号', '画面内容', '公式']); sheet.append([1, text, '=1+2'])
        sheet['B5'] = '原位留空'; book.save(self.path); book.close()

    def test_snapshot_cache_is_shared_with_catalog_without_second_parse(self):
        first = source.snapshot(self.path, cache_root=self.cache)
        first['sheets'][0]['rows'][1][1]['value'] = 'caller mutation'
        with patch('openpyxl.load_workbook', side_effect=AssertionError('cache must avoid parsing')):
            second = source.snapshot(self.path, cache_root=self.cache)
            hints = catalog.workbook_hints(self.path, cache_root=self.cache)
        self.assertEqual(hints[0]['panel_evidence'][0]['画面内容'], '“原文，不能改！”\n第二行')
        self.assertEqual(second['sheets'][0]['rows'][-1][0]['coordinate'], 'B5')
        self.assertEqual(second['sheets'][0]['rows'][1][2], {'coordinate': 'C2', 'type': 'f', 'value': '=1+2'})
        self.assertEqual(second['source_sha256'], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertTrue(second['payload_sha256'])

    def test_catalog_keeps_datetime_hint_format_while_snapshot_preserves_raw_type(self):
        from datetime import datetime
        from openpyxl import load_workbook
        book = load_workbook(self.path); sheet = book.active
        sheet['B1'] = '当前时间'; sheet['B2'] = datetime(2026, 1, 2, 3, 4, 5)
        book.save(self.path); book.close()
        self.assertEqual(catalog.workbook_hints(self.path, cache_root=self.cache)[0]['panel_evidence'][0]['当前时间'], '2026-01-02 03:04:05')
        cell = source.snapshot(self.path, cache_root=self.cache)['sheets'][0]['rows'][1][1]
        self.assertEqual(cell['type'], 'd'); self.assertEqual(cell['value'], '2026-01-02T03:04:05')

    def test_catalog_reports_raw_cache_reuse_separately_from_hint_derivation(self):
        source.snapshot(self.path, cache_root=self.cache)
        result = catalog.discover(self.root, 'B', ['E001'], cache_root=self.cache)
        self.assertEqual(result['metrics']['raw_workbook_parses'], 0)
        self.assertEqual(result['metrics']['raw_snapshot_cache_reuses'], 1)

    def test_corrupt_cache_and_changed_source_are_reparsed(self):
        first = source.snapshot(self.path, cache_root=self.cache)
        cache_file = next(self.cache.rglob('raw-workbook-*.json'))
        value = json.loads(cache_file.read_text()); value['snapshot']['sheets'] = []
        cache_file.write_text(json.dumps(value))
        self.assertEqual(source.snapshot(self.path, cache_root=self.cache), first)
        self.write('新原文。')
        changed = source.snapshot(self.path, cache_root=self.cache)
        self.assertNotEqual(changed['source_sha256'], first['source_sha256'])
        self.assertEqual(changed['sheets'][0]['rows'][1][1]['value'], '新原文。')

    def test_source_change_during_parse_is_rejected_without_cache(self):
        from openpyxl import load_workbook
        def mutate(*args, **kwargs):
            book = load_workbook(*args, **kwargs)
            self.path.write_bytes(self.path.read_bytes() + b'changed')
            return book
        with patch('openpyxl.load_workbook', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, '变化'):
                source.snapshot(self.path, cache_root=self.cache)
        self.assertFalse(list(self.cache.rglob('*.json')))


class PreparationMetricsTests(unittest.TestCase):
    def test_overlap_is_union_and_missing_native_times_remain_unknown(self):
        events = [
            {'action': 'fragment_submitted', 'at': 0},
            {'action': 'technically_ready', 'at': 2, 'task_id': 'a'},
            {'action': 'dispatch', 'at': 5, 'task_id': 'a'},
            {'action': 'interval', 'payload': {'phase': 'compile', 'started_at': 1, 'completed_at': 6}},
            {'action': 'interval', 'payload': {'phase': 'compile', 'started_at': 4, 'completed_at': 9}},
            {'action': 'compile', 'at': 9, 'payload': {'compiled': 2, 'reused': 3}},
            {'action': 'wait', 'at': 10, 'payload': {'reason': 'HOST_NEEDED'}},
            {'action': 'sealed', 'at': 12}, {'action': 'published', 'at': 14},
        ]
        result = metrics.preparation_metrics(events)
        self.assertEqual(result['wall_seconds'], 14)
        self.assertEqual(result['phase_windows']['compile']['union_seconds'], 8)
        self.assertEqual(result['phase_windows']['compile']['sum_seconds_not_wall_time'], 10)
        self.assertEqual(result['dispatch_gap']['sum_seconds_not_wall_time'], 3)
        self.assertEqual(result['compiled'], 2); self.assertEqual(result['reused'], 3)
        self.assertEqual(result['milestones']['first_fragment_at'], 0)
        self.assertEqual(result['wait_reasons'], {'HOST_NEEDED': 1})
        self.assertIsNone(result['native_call']['union_seconds'])

    def test_resource_wait_is_separate_from_observed_dispatchable_idle(self):
        events = [
            {'action': 'task_ready', 'at': 0, 'task_id': 'a'},
            {'action': 'wait_resource', 'at': 0, 'task_id': 'a', 'payload': {'reason': 'IMAGE_CAPACITY'}},
            {'action': 'interval', 'payload': {'phase': 'wait_resource', 'started_at': 0, 'completed_at': 5}},
            {'action': 'dispatchable', 'at': 5, 'payload': {'task_id': 'a', 'lane': 'image'}},
            {'action': 'claimed', 'at': 7, 'task_id': 'a'},
        ]
        result = metrics.preparation_metrics(events)
        self.assertEqual(result['ready_to_claim']['union_seconds'], 7)
        self.assertEqual(result['dispatchable_to_claim']['union_seconds'], 2)
        self.assertEqual(result['phase_windows']['wait_resource']['union_seconds'], 5)
        self.assertEqual(result['dispatch_gap'], result['ready_to_claim'])
        missing = metrics.preparation_metrics(events[:3] + events[4:])
        self.assertIsNone(missing['dispatchable_to_claim']['union_seconds'])
        self.assertEqual(missing['ready_to_claim']['union_seconds'], 7)

    def test_revoked_capacity_offer_does_not_create_false_idle_window(self):
        result = metrics.preparation_metrics([
            {'action': 'dispatchable', 'at': 1, 'task_id': 'a'},
            {'action': 'wait_resource', 'at': 2, 'task_id': 'a'},
            {'action': 'claimed', 'at': 6, 'task_id': 'a'},
        ])
        self.assertIsNone(result['dispatchable_to_claim']['union_seconds'])

    def test_scheduler_journal_counts_model_tasks_and_reservations_without_native_claims(self):
        events = [
            {'action': 'register', 'at': 0, 'tasks': [{'task_id': 'a', 'lane': 'model', 'kind': 'shot_fragment', 'status': 'PENDING'}]},
            {'action': 'task', 'at': 2, 'task_id': 'a', 'changes': {'status': 'LEASED', 'wait_reason': 'HOST_NEEDED', 'timestamps': {'ready': 0, 'leased': 2}}},
            {'action': 'task', 'at': 4, 'task_id': 'a', 'changes': {'status': 'RUNNING', 'host_id': 'host'}},
            {'action': 'task', 'at': 8, 'task_id': 'a', 'changes': {'status': 'RESULT_SAVED'}},
        ]
        result = metrics.preparation_metrics(events)
        self.assertEqual(result['model_tasks'], 1)
        self.assertEqual(result['dispatch_gap']['union_seconds'], 2)
        self.assertEqual(result['scheduler_inflight_curve'][0], {'at': 2, 'model': 1})
        self.assertEqual(result['wait_reasons'], {'HOST_NEEDED': 1})
        self.assertIsNone(result['native_call']['union_seconds'])
        self.assertIsNone(result['model_actions'])

    def test_scheduler_stop_and_takeover_keep_submitted_work_reserved_until_terminal(self):
        # Actual journal field shape, including attach_host's persistent marker.
        events = [
            {'action': 'register', 'at': 0, 'tasks': [{'task_id': 'a', 'lane': 'image', 'status': 'PENDING', 'native_inflight': False}]},
            {'action': 'task', 'at': 1, 'task_id': 'a', 'changes': {'status': 'LEASED'}},
            {'action': 'task', 'at': 2, 'task_id': 'a', 'changes': {'status': 'RUNNING', 'host_id': 'host', 'native_inflight': True}},
            {'action': 'task', 'at': 3, 'task_id': 'a', 'changes': {'status': 'STOPPED'}},
            {'action': 'task', 'at': 4, 'task_id': 'a', 'changes': {'status': 'BLOCKED'}},
            {'action': 'task', 'at': 5, 'task_id': 'a', 'changes': {'status': 'SUPERSEDED'}},
            {'action': 'owner', 'at': 6, 'owner': {'epoch': 2}},
            {'action': 'task', 'at': 7, 'task_id': 'a', 'changes': {'status': 'STOPPED', 'native_inflight': False}},
        ]
        result = metrics.preparation_metrics(events)
        self.assertEqual(result['scheduler_inflight_curve'], [{'at': t, 'image': 1} for t in range(1, 7)] + [{'at': 7}])
        self.assertEqual(result['inflight_curve'], [])
        self.assertIsNone(result['native_call']['union_seconds'])

    def test_cli_reads_preparation_events_without_production_state(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            events = Path(directory) / 'events.jsonl'
            events.write_text(json.dumps({'event': {'action': 'fragment_submitted', 'at': 1}}) + '\n' + json.dumps({'event': {'action': 'published', 'at': 4}}) + '\n')
            command = [sys.executable, str(Path(metrics.__file__)), '--preparation-events', str(events)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['policy'], 'preparation_metrics_v1')
            self.assertEqual(value['wall_seconds'], 3)

    def test_unclosed_observed_native_call_stays_inflight_without_invented_duration(self):
        result = metrics.preparation_metrics([{'action': 'native_started', 'at': 1, 'task_id': 'a'}])
        self.assertEqual(result['inflight_curve'], [{'at': 1, 'inflight': 1}])
        self.assertEqual(result['unclosed_native_calls'], 1)
        self.assertIsNone(result['native_call']['union_seconds'])

    def test_observed_native_windows_and_duplicate_events(self):
        events = [{'event_id': 'x', 'action': 'native_started', 'at': 1, 'task_id': 'a'},
                  {'event_id': 'x', 'action': 'native_started', 'at': 1, 'task_id': 'a'},
                  {'action': 'native_completed', 'at': 5, 'task_id': 'a'},
                  {'action': 'model_action', 'at': 6, 'task_id': 'a'},
                  {'action': 'task_registered', 'at': 0, 'task_id': 'a', 'payload': {'lane': 'model'}}]
        result = metrics.preparation_metrics(events)
        self.assertEqual(result['native_call']['union_seconds'], 4)
        self.assertEqual(result['duplicate_events_ignored'], 1)
        self.assertEqual(result['model_tasks'], 1); self.assertEqual(result['model_actions'], 1)
        self.assertIsNone(metrics.preparation_metrics([])['wall_seconds'])


if __name__ == '__main__': unittest.main()
