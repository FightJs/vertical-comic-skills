import sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_light_review as fixtures
from codex_reference_contract import read_json
from generation_host import prepare_qa
from workflow_session import WorkflowSession

class ReviewTicketTests(unittest.TestCase):
    def test_actual_observation_auto_identity_and_unrelated_scope_not_rechecked(self):
        f=fixtures.LightReviewTests();self.addCleanup(f.doCleanups)
        h,path,row,proposal=f.fixture()
        from unittest.mock import patch
        import review_queue
        original=review_queue.build_queue
        def scoped(state,root,batch,**kw):
            self.assertEqual(batch['panel_ids'],[row['panel_id']])
            return original(state,root,batch,**kw)
        with patch.object(review_queue,'build_queue',side_effect=scoped):
            queue=prepare_qa(read_json(path),h.root,[row['panel_id']])
        ticket=queue['items'][0]['review_ticket']
        observation={k:v for k,v in proposal.items() if k not in {'panel_id','attempt_id','qa_template','base_qa'}}
        result=WorkflowSession().execute({'action':'review-submit-batch','state':str(path),
            'observations':[{'review_ticket':ticket,'observation':observation}]})
        self.assertEqual(result['results'][0]['status'],'QA_AND_DECISION_SAVED',result)
        state=read_json(path)
        self.assertEqual(state['delivery_materials'][row['panel_id']]['policy'],'observed_delivery_material_v1')
        stale=WorkflowSession().execute({'action':'review-submit-batch','state':str(path),
            'observations':[{'review_ticket':ticket,'observation':observation}]})
        self.assertEqual(stale['results'][0]['status'],'HOLD')

if __name__=='__main__':unittest.main()
