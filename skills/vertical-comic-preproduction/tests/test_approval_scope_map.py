"""Growing queries retain the original grouped/fallback approval semantics."""
import copy
from unittest.mock import patch
from test_preparation_speed import BatchedApprovalTests
from audit_fixtures import write
from codex_reference_contract import file_session, read_json
from validation_pool import ValidationPool, session
import panel_readiness as r

class ScopeMapTests(BatchedApprovalTests):
    def test_growing_prefixes_compute_coverage_once(self):
        with patch.object(r, '_artifacts_covered', wraps=r._artifacts_covered) as count:
            with file_session() as memo:
                for i in range(1, len(self.ids)+1):
                    self.assertEqual(r.approval_errors_for(self.state,self.root,'shot_design',self.artifacts,self.ids[:i],self.proof), [])
        self.assertEqual(count.call_count,1)
        self.assertEqual(memo['audit_statistics']['approval_scope_map']['runs'],1)

    def test_every_subset_matches_original_grouped_fallback(self):
        from itertools import combinations
        shots=read_json(self.root/self.state['shot_manifest']['path'])
        shots['panels'][2]['locked_script']='revised'
        changed=write(self.root,'revised.json',shots)
        self.state['shot_manifest']=changed;self.artifacts[-1]=changed
        partial={**copy.deepcopy(self.proof),'panel_ids':['P001','P004']}
        for proofs in [[self.proof],[partial],[partial,self.proof]]:
            with file_session():
                for size in range(1,5):
                    for ids in combinations(self.ids,size):
                        original=r._approval_coverage_for(self.state,self.root,'shot_design',self.artifacts,ids,proofs=proofs)
                        missing=[pid for pid in ids if pid not in original]
                        expected=['缺少原范围、原版本或未变条目适用的真实批准:'+','.join(missing)] if missing else []
                        self.assertEqual(r.approval_errors_for(self.state,self.root,'shot_design',self.artifacts,ids,proofs=proofs),expected)

    def test_new_proof_and_revocation_invalidate_pooled_map(self):
        pool=ValidationPool()
        with session(pool):
            with file_session():self.assertEqual(self.check(self.proof),[])
            revoked={**self.proof,'status':'REVOKED'}
            with file_session():self.assertTrue(self.check(revoked))
            with file_session():self.assertEqual(self.check(self.proof),[])

    def test_unknown_panel_does_not_inherit_whole_episode_success(self):
        with file_session():
            self.assertEqual(self.check(self.proof),[])
            self.assertEqual(r.approval_errors_for(self.state,self.root,'shot_design',self.artifacts,['P999'],self.proof),
                ['缺少原范围、原版本或未变条目适用的真实批准:P999'])
