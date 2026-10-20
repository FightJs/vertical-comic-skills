"""Evidence-preserving caching, scope isolation, and bounded repeated work."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from audit_fixtures import contexts, write
from codex_reference_contract import file_session, read_json, read_json_readonly
from continuity_context import load_context
from panel_readiness import compatible_collection, approval_errors_for, review_context
import panel_readiness


class AuditCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packets = contexts(self.root, 4)
        self.packet = self.packets[-1]
        self.context = read_json(self.root/self.packet['continuity_context']['path'])
        self.source = self.context['sources'][0]
        self.state = {**self.source, 'book_id': 'BENCH', 'readiness_policy': 'panel_readiness_v1'}

    def test_readonly_and_mutable_apis_are_isolated(self):
        path = self.root/self.source['shot_manifest']['path']
        with file_session():
            ro = read_json_readonly(path)
            with self.assertRaises(TypeError):ro['panels'][0]['locked_script'] = 'changed'
            with self.assertRaises(TypeError):ro['panels'].append({})
            mutable = read_json(path)
            mutable['panels'][0]['locked_script'] = 'changed'
            self.assertNotEqual(mutable, ro)
            self.assertEqual(read_json(path), ro)

    def test_signatures_are_computed_once_per_file(self):
        old = self.source['shot_approval']['artifacts'][1]
        new = self.source['shot_manifest']
        with patch('panel_readiness.design_signature', wraps=panel_readiness.design_signature) as signatures:
            with file_session() as memo:
                for _ in range(3):
                    for i in range(1, 5):
                        self.assertTrue(compatible_collection(self.root, old, new, [f'P{i:03}'], 'BENCH', 'E000'))
                self.assertEqual(signatures.call_count, 8)
                self.assertEqual(memo['audit_statistics']['collection_pair']['runs'], 1)

    def test_changed_row_or_shared_header_cannot_reuse_approval(self):
        old = self.source['shot_approval']['artifacts'][1]
        shots = read_json(self.root/self.source['shot_manifest']['path'])
        shots['panels'][0]['locked_script'] = 'different'
        changed = write(self.root, 'changed.json', shots)
        with file_session():
            self.assertFalse(compatible_collection(self.root, old, changed, ['P001'], 'BENCH', 'E000'))
            self.assertTrue(compatible_collection(self.root, old, changed, ['P002'], 'BENCH', 'E000'))
            self.assertFalse(compatible_collection(self.root, old, changed, ['P002'], 'BENCH', 'OTHER'))
        shots['style'] = 'different'
        header = write(self.root, 'header.json', shots)
        with file_session():
            self.assertFalse(compatible_collection(self.root, old, header, ['P002'], 'BENCH', 'E000'))

    def test_context_results_do_not_share_mutable_maps_or_rows(self):
        with file_session() as memo:
            first, errors = load_context(self.packet, self.root)
            self.assertEqual(errors, [])
            first['E000-P001']['locked_script'] = 'caller mutation'
            first.clear()
            second, errors = load_context(self.packet, self.root, readonly=True)
            self.assertEqual(errors, [])
            self.assertEqual(second['E000-P001']['locked_script'], 'SYNTHETIC P001')
            with self.assertRaises(TypeError):second['E000-P001']['locked_script'] = 'bad'
            second['P004'] = {'local': True}
            third, _ = load_context(self.packet, self.root, readonly=True)
            self.assertNotIn('E000-P004', third)
            self.assertEqual(memo['audit_statistics']['continuity_context'], {'runs': 1, 'hits': 2})

    def test_context_cache_is_bound_to_current_panel_and_book(self):
        with file_session():
            self.assertEqual(load_context(self.packet, self.root)[1], [])
            for changed in ({**self.packet, 'book_id': 'OTHER'},
                            {**self.packet, 'panels': [{'panel_id': 'P002'}]}):
                self.assertTrue(load_context(changed, self.root)[1])

    def test_candidate_result_never_becomes_real_approval(self):
        context = copy.deepcopy(self.context)
        context['sources'][0]['shot_approval'] = None
        packet = {**self.packet, 'continuity_context': write(self.root, 'candidate.json', context)}
        with file_session():
            with review_context(self.state, self.root, True):
                self.assertEqual(load_context(packet, self.root)[1], [])
            self.assertTrue(load_context(packet, self.root)[1])

    def test_inline_revocation_and_scope_changes_are_not_cached(self):
        proof = copy.deepcopy(self.source['shot_approval'])
        artifacts = [self.source['visual_basis'], self.source['shot_manifest']]
        with file_session():
            self.assertEqual(approval_errors_for(self.state, self.root, 'shot_design', artifacts, ['P001'], proof), [])
            proof['status'] = 'REVOKED'
            self.assertTrue(approval_errors_for(self.state, self.root, 'shot_design', artifacts, ['P001'], proof))
            proof['status'] = 'APPROVED';proof['panel_ids'] = ['P002']
            self.assertTrue(approval_errors_for(self.state, self.root, 'shot_design', artifacts, ['P001'], proof))

    def test_index_lookup_scope_cannot_expand_original_approval(self):
        proof = write(self.root, 'proof.json', self.source['shot_approval'])
        index = write(self.root, 'index.json', {'policy': 'approval_index_v1', 'entries': [
            {'phase': 'shot_design', 'book_id': 'BENCH', 'episode_ids': ['E000'], 'panel_ids': ['P001'], 'approval': proof}]})
        state = {**self.state, 'approval_index': index}
        artifacts = [self.source['visual_basis'], self.source['shot_manifest']]
        with file_session():
            self.assertEqual(approval_errors_for(state, self.root, 'shot_design', artifacts, ['P001']), [])
            self.assertTrue(approval_errors_for(state, self.root, 'shot_design', artifacts, ['P002']))
            self.assertTrue(approval_errors_for(state, self.root, 'generation_package', artifacts, ['P001']))

    def test_nested_dependency_mutation_is_detected_even_without_reread(self):
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(load_context(self.packet, self.root)[1], [])
                path = self.root/self.source['shot_approval']['artifacts'][1]['path']
                path.write_text('{}', encoding='utf-8')

    def test_cache_hit_checks_nested_dependencies(self):
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(load_context(self.packet, self.root)[1], [])
                path = self.root/self.source['visual_basis']['path']
                path.write_text('{}', encoding='utf-8')
                self.assertTrue(load_context(self.packet, self.root)[1])

    def test_retargeted_reference_cannot_reuse_cached_approval(self):
        old = self.source['shot_approval']['artifacts'][1]
        link = self.root/'link.json'
        try:link.symlink_to(self.root/old['path'])
        except OSError:self.skipTest('symbolic links unavailable on this test host')
        alias = {**old, 'path': 'link.json'}
        other = write(self.root, 'other.json', {'panels': []})
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertTrue(compatible_collection(self.root, alias, self.source['shot_manifest'], ['P001'], 'BENCH', 'E000'))
                link.unlink();link.symlink_to(self.root/other['path'])
                self.assertFalse(compatible_collection(self.root, alias, self.source['shot_manifest'], ['P001'], 'BENCH', 'E000'))

    def test_runtime_source_revocation_invalidates_context(self):
        source = {k:v for k,v in self.source.items() if k not in ('visual_approval', 'shot_approval')}
        source.update(approval_resolution='source_runtime_gates_v1', source_state_file='00/state.json')
        state = {**self.state, 'gates': {'visual_basis': self.source['visual_approval'], 'shot_design': self.source['shot_approval']}}
        write(self.root, '00/state.json', state)
        context = {**self.context, 'sources': [source]}
        packet = {**self.packet, 'continuity_context': write(self.root, 'runtime-context.json', context)}
        with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(load_context(packet, self.root)[1], [])
                state['gates']['shot_design']['status'] = 'REVOKED'
                write(self.root, '00/state.json', state)
                self.assertTrue(load_context(packet, self.root)[1])
        with file_session():self.assertTrue(load_context(packet, self.root)[1])

    def test_cached_validator_transfers_transitive_dependencies(self):
        from audit_cache import derived
        from codex_reference_contract import digest, memoized_validation
        path=self.root/self.source['visual_basis']['path']
        def validate():
            digest(path)
            return []
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(memoized_validation('test','evidence',validate),[])
                self.assertEqual(derived('test-parent','key',lambda:memoized_validation('test','evidence',validate)),[])
                path.write_text('{}',encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
                    derived('test-parent','key',lambda:[])

    def test_runtime_source_rejects_wrong_book_and_mixed_approvals(self):
        from continuity_context import runtime_source_state
        source = {k:v for k,v in self.source.items() if k not in ('visual_approval','shot_approval')}
        source.update(approval_resolution='source_runtime_gates_v1',source_state_file='00/state.json')
        write(self.root,'00/state.json',self.state)
        for invalid in ({**source,'source_state_file':'../state.json'},
                        {**source,'visual_approval':self.source['visual_approval']},
                        {**source,'episode_id':'OTHER'}):
            with self.assertRaises(ValueError):runtime_source_state(invalid,self.root,'BENCH')
        with self.assertRaises(ValueError):runtime_source_state(source,self.root,'OTHER')

    def test_35_panel_contexts_reuse_source_signatures(self):
        root = self.root/'large'
        packets = contexts(root, 35)
        with patch('panel_readiness.design_signature', wraps=panel_readiness.design_signature) as signatures:
            with file_session():
                for packet in packets:
                    self.assertEqual(load_context(packet, root, readonly=True)[1], [])
                self.assertEqual(signatures.call_count, 70)


if __name__ == '__main__':unittest.main()
