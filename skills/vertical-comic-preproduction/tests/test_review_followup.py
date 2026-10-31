import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_light_review as fixtures
from codex_reference_contract import read_json
from review_followup import submit
class FollowupTests(unittest.TestCase):
    def fixture(self):
        f=fixtures.LightReviewTests();self.addCleanup(f.doCleanups);h,p,r,proposal=f.fixture()
        state=read_json(p);state['review_followup_policy']='observed_followup_v1';p.write_text(json.dumps(state))
        return h,p,r,proposal
    def test_lost_response_replays_without_new_qa_revision(self):
        h,p,r,proposal=self.fixture();first=submit(p,proposal);before=p.read_bytes();second=submit(p,proposal)
        self.assertEqual(first['status'],'QA_AND_DECISION_SAVED');self.assertTrue(second['replayed']);self.assertEqual(before,p.read_bytes())
    def test_followup_failure_preserves_qa_and_replays_only_followup(self):
        h,p,r,proposal=self.fixture()
        with patch('review_followup.follow',side_effect=ValueError('injected')):first=submit(p,proposal)
        self.assertEqual(first['followup']['status'],'HOLD');before=read_json(p)['panels'][0]['qa_report']
        second=submit(p,proposal);self.assertTrue(second['replayed']);self.assertEqual(before,read_json(p)['panels'][0]['qa_report'])
    def test_replay_rejects_replaced_attempt(self):
        h,p,r,proposal=self.fixture();submit(p,proposal)
        state=read_json(p);state['panels'][0]['attempt_id']='other';p.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'VERSION_CHANGED'):submit(p,proposal)
    def test_missing_actual_state_review_not_invented(self):
        h,p,r,proposal=self.fixture()
        with patch('review_followup.barrier_info',return_value={'required':True,'affected_panel_ids':['P002']}):result=submit(p,proposal)
        self.assertEqual(result['followup']['state_review']['status'],'OBSERVATION_REQUIRED')

    def test_delegated_state_review_registers_once(self):
        h,p,r,proposal=self.fixture();state=read_json(p)
        grant={'policy':'user_delegation_v1','status':'AUTHORIZED','source_kind':'user_message',
            'quote':'SYNTHETIC delegated review','source_locator':'fixture://user',
            'book_id':state['book_id'],'episode_ids':[state['episode_id']],
            'panel_ids':{state['episode_id']:[r['panel_id']]},'phases':['state_review'],'constraints':['only observed image']}
        authority=h.h.f.write('state-review-grant.json',grant)
        proposal['state_review']={'verdict':'PASS','observed':'SYNTHETIC same actual image state confirmed','authority':authority}
        with patch('review_followup.barrier_info',return_value={'required':True,'affected_panel_ids':['P002']}):
            first=submit(p,proposal);second=submit(p,proposal)
        self.assertEqual(first['followup']['status'],'FOLLOWUP_COMPLETE',first)
        self.assertEqual(second['followup']['state_review']['status'],'REGISTERED',second)
        index=read_json(h.root/read_json(p)['approval_index']['path'])
        self.assertEqual(len([e for e in index['entries'] if e['phase']=='state_review']),1)
