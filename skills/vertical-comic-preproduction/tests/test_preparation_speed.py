"""Approval batching and real semantic CLI transaction regressions; no image calls."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from audit_fixtures import contexts, write
from codex_reference_contract import file_session, read_json, _FILE_SESSION
import panel_readiness as readiness
import input_semantics as sem
import test_input_semantics as semantic_fixture


class BatchedApprovalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        packets = contexts(self.root, 4)
        context = read_json(self.root / packets[-1]['continuity_context']['path'])
        self.source = context['sources'][0]
        self.state = {**self.source, 'book_id': 'BENCH'}
        self.artifacts = [self.source['visual_basis'], self.source['shot_manifest']]
        self.proof = copy.deepcopy(self.source['shot_approval'])
        self.ids = ['P001', 'P002', 'P003', 'P004']

    def check(self, proof=None, **kwargs):
        return readiness.approval_errors_for(self.state, self.root, 'shot_design',
                                             self.artifacts, self.ids, proof, **kwargs)

    def test_one_shared_proof_is_validated_once_for_its_whole_scope(self):
        with patch.object(readiness, '_artifacts_covered', wraps=readiness._artifacts_covered) as calls:
            with file_session(): self.assertEqual(self.check(self.proof), [])
        self.assertEqual(calls.call_count, 1)

    def test_changed_later_row_does_not_block_unchanged_rows(self):
        shots = read_json(self.root / self.source['shot_manifest']['path'])
        shots['panels'][-1]['locked_script'] = 'changed story'
        changed = write(self.root, 'changed.json', shots)
        self.state['shot_manifest'] = changed; self.artifacts[-1] = changed
        with file_session():
            errors = self.check(self.proof)
        self.assertEqual(errors, ['缺少原范围、原版本或未变条目适用的真实批准:P004'])

    def test_two_partial_proofs_cover_union_but_not_gap(self):
        a = {**self.proof, 'panel_ids': self.ids[:2]}
        b = {**self.proof, 'panel_ids': self.ids[2:]}
        with file_session():
            self.assertEqual(self.check(proofs=[a, b]), [])
            b['panel_ids'] = ['P004']
            self.assertEqual(self.check(proofs=[a, b]),
                             ['缺少原范围、原版本或未变条目适用的真实批准:P003'])

    def test_index_scope_remains_narrower_than_the_proof(self):
        proof = write(self.root, 'proof.json', self.proof)
        self.state['approval_index'] = write(self.root, 'index.json', {
            'policy': 'approval_index_v1', 'entries': [{'phase': 'shot_design', 'book_id': 'BENCH',
            'episode_ids': ['E000'], 'panel_ids': ['P001', 'E000-P002'], 'approval': proof}]})
        with file_session():
            self.assertEqual(self.check(), ['缺少原范围、原版本或未变条目适用的真实批准:P003,P004'])

    def test_mixed_preserved_versions_fall_back_to_each_unchanged_row(self):
        # Neither old version covers every current row, but their union does.
        current = read_json(self.root / self.source['shot_manifest']['path'])
        a, b = copy.deepcopy(current), copy.deepcopy(current)
        a['panels'][0]['locked_script'] = 'old first row'
        b['panels'][-1]['locked_script'] = 'old last row'
        self.proof['artifacts'] = [self.source['visual_basis'], write(self.root, 'a.json', a),
                                  write(self.root, 'b.json', b)]
        with file_session(): self.assertEqual(self.check(self.proof), [])

    def test_batched_success_still_detects_evidence_mutation(self):
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(self.check(self.proof), [])
                (self.root / self.source['visual_basis']['path']).write_text('{}', encoding='utf-8', newline='\n')
                self.assertTrue(self.check(self.proof))


class SemanticCliTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = semantic_fixture.RealInputBinding('test_real_final_input_binds_without_mutating_files')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root, self.state = self.fixture.root, self.fixture.state
        self.path = self.root / '00_输入审计/state.json'
        self.path.parent.mkdir(exist_ok=True); self.path.write_text(json.dumps(self.state), encoding='utf-8', newline='\n')

    def cli(self):
        out = io.StringIO()
        with patch.object(sys, 'argv', ['input_semantics.py', '--state', str(self.path)]), redirect_stdout(out):
            code = sem.main()
        return code, json.loads(out.getvalue())

    def test_real_cli_checks_all_panels_in_one_transaction(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        actual = sem.panel_errors; sessions = []
        def observe(*args, **kwargs):
            sessions.append(_FILE_SESSION.get())
            return actual(*args, **kwargs)
        with patch.object(sem, 'panel_errors', side_effect=observe):
            code, report = self.cli()
        self.assertEqual(code, 0); self.assertEqual(report['reviewed_panel_ids'], ['P001','P002','P003','P004'])
        self.assertEqual(len(sessions), 4); self.assertIsNotNone(sessions[0])
        self.assertTrue(all(s is sessions[0] for s in sessions))
        self.assertGreater(sessions[0]['json_hits'], 0)
        self.assertFalse(report['dispatch_authorized']); self.assertEqual(report['image_calls'], 0)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_cli_never_prints_success_if_state_changes_before_transaction_closes(self):
        actual = sem._coverage
        def changed(*args, **kwargs):
            result = actual(*args, **kwargs)
            self.path.write_text(json.dumps({**self.state, 'changed': True}), encoding='utf-8', newline='\n')
            return result
        with patch.object(sem, '_coverage', side_effect=changed): code, report = self.cli()
        self.assertEqual(code, 1); self.assertEqual(report['status'], 'HOLD')
        self.assertIn('CHECK_SNAPSHOT_CHANGED', str(report['errors']))

    def test_public_coverage_detects_changed_input_without_caller_session(self):
        actual = sem._coverage
        def changed(*args, **kwargs):
            result = actual(*args, **kwargs)
            (self.root / self.state['semantic_audit']['path']).write_text('{}', encoding='utf-8', newline='\n')
            return result
        with patch.object(sem, '_coverage', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                sem.coverage(self.state, self.root)


if __name__ == '__main__': unittest.main()
