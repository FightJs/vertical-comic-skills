"""Common-cause review is required only after six actual visual failures."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_reference_contract import digest
from production_runtime import record_episode_diagnosis
from episode_repair import systemic_errors


class EpisodeDiagnosisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / '00_输入审计').mkdir()
        self.path = self.root / '00_输入审计/生产流程.json'
        self.ids = [f'P{i:03d}' for i in range(1, 7)]
        self.state = {'execution_mode': 'episode_async_v1', 'book_id': 'TEST',
            'episode_id': 'E001', 'review_policy': {'systemic_failure_count_gt': 5},
            'panels': [{'panel_id': p, 'status': 'VISUAL_FAIL'} for p in self.ids]}
        self.path.write_text(json.dumps(self.state), encoding='utf-8', newline='\n')
        report = {'policy': 'episode_failure_diagnosis_v1', 'status': 'REVIEWED',
            'book_id': 'TEST', 'episode_id': 'E001', 'reviewer': 'TEST REVIEW',
            'evidence': '六张实图均出现相同承托错误', 'common_cause': '床面承托约束未进入提示词',
            'reviewed_failure_panel_ids': self.ids}
        (self.root / 'diagnosis.json').write_text(json.dumps(report), encoding='utf-8', newline='\n')

    def test_atomic_record_binds_actual_report(self):
        self.assertTrue(systemic_errors(self.state, self.state['panels'], self.root))
        with patch('production_evidence.attempt_errors', return_value=[]):
            value = record_episode_diagnosis(self.path, digest(self.path), 'diagnosis.json')
        self.assertEqual(value['status'], 'DIAGNOSIS_RECORDED')
        state = json.loads(self.path.read_text(encoding='utf-8-sig'))
        self.assertEqual(systemic_errors(state, state['panels'], self.root), [])
        (self.root / 'diagnosis.json').write_text('{}', encoding='utf-8', newline='\n')
        self.assertTrue(systemic_errors(state, state['panels'], self.root))

    def test_stale_state_and_incomplete_coverage_rejected(self):
        with patch('production_evidence.attempt_errors', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'STATE_CHANGED'):
                record_episode_diagnosis(self.path, '0'*64, 'diagnosis.json')
            report = json.loads((self.root / 'diagnosis.json').read_text(encoding='utf-8-sig'))
            report['reviewed_failure_panel_ids'] = self.ids[:5]
            (self.root / 'diagnosis.json').write_text(json.dumps(report), encoding='utf-8', newline='\n')
            with self.assertRaisesRegex(ValueError, '覆盖当前全部'):
                record_episode_diagnosis(self.path, digest(self.path), 'diagnosis.json')


if __name__ == '__main__':
    unittest.main()
