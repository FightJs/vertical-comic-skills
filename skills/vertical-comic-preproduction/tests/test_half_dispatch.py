"""Half per-episode quotas and immutable round receipts, isolated synthetic records."""
import copy
import unittest
import test_parallel_dispatch as fixtures
from parallel_dispatch import receipt_errors

class HalfDispatchTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.DispatchTests('test_valid_snapshot_read_only');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.state,self.control=self.h.state,self.h.control
        ids=[f'P{i:03d}' for i in range(1,5)]
        self.state.update(execution_mode='half_episode_async_v1',panels=[{'panel_id':p,'round_id':1,'attempt_id':p+'-r1'} for p in ids])
        self.state['batch_plan']=self.h.write(self.h.episode,'half-plan.json',{'batches':[{'batch_id':'H001','panel_ids':ids}]})
        self.control['jobs'][0].update(active_batch_id='H001',max_inflight=4)
        self.control['permits'][0].update(batch_id='H001',round_id=1,attempt_id='P001-r1')
        self.h.flush()

    def test_half_permit_valid_without_changing_global_contract(self):self.assertEqual(self.h.check(),[])

    def test_per_episode_limit_blocks_even_if_global_has_space(self):
        self.control['jobs'][0]['max_inflight']=1
        self.control['permits'].append({**self.control['permits'][0],'permit_id':'r2','panel_id':'P002','attempt_id':'P002-r1'})
        self.assertTrue(any('本话活动请求超过' in e for e in self.h.check()))

    def test_global_limit_remains_independent(self):
        self.control['max_inflight']=1
        self.control['permits'].append({**self.control['permits'][0],'permit_id':'r2','panel_id':'P002','attempt_id':'P002-r1'})
        self.assertTrue(any('活动请求超过max_inflight' in e for e in self.h.check()))

    def test_wrong_round_or_attempt_is_blocked(self):
        self.control['permits'][0]['attempt_id']='wrong'
        self.assertTrue(any('批次/轮次/尝试' in e for e in self.h.check()))

    def test_job_limit_cannot_exceed_actual_half_size(self):
        self.control['jobs'][0]['max_inflight']=5
        self.assertTrue(any('不超过本半话格数' in e for e in self.h.check()))

    def test_queued_half_scaffold_does_not_block_active_jobs(self):
        other={**self.control['jobs'][0],'job_id':'job22','episode_id':'E022','root':str(self.h.root/'E022'),'worker_id':None,'status':'QUEUED'}
        self.control['jobs'].append(other)
        self.assertEqual(self.h.check(),[])

    def test_other_episode_waiting_for_review_does_not_hold_current_episode(self):
        other={**self.control['jobs'][0],'job_id':'job22','episode_id':'E022',
            'root':str(self.h.root/'E022'),'worker_id':'worker22','status':'WAIT_REVIEW'}
        self.control['jobs'].append(other)
        self.assertEqual(self.h.check(),[])


    def test_new_first_round_attempt_cannot_replace_completed_original(self):
        self.control['permits'].append({**self.control['permits'][0],'permit_id':'old','status':'COMPLETED','attempt_id':'old-first-attempt','output_sha256':'0'*64})
        self.assertTrue(any('伪装首轮重试' in e for e in self.h.check()))

    def test_receipt_round_must_match_immutable_original_permit(self):
        receipt={**self.h.context,'permit_id':'r1','batch_id':'H001','round_id':1,'attempt_id':'P001-r1'};receipt.pop('control_file')
        self.h.flush();self.assertEqual(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',receipt),[])
        receipt['round_id']=2
        self.assertTrue(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',receipt))

if __name__=='__main__':unittest.main()
