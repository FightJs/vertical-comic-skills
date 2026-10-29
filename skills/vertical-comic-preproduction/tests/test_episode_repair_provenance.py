"""A dispatch receipt may only wrap the exact authorized repair packet."""
import _historical_fixture
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from codex_reference_contract import digest
from historical_engines.batch_round import snapshot
from episode_repair import repair_errors


class EpisodeRepairProvenanceTests(unittest.TestCase):
    def test_receipt_copy_preserves_repair_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(name,value):
                path=root/name;path.write_text(json.dumps(value), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(path)}
            old={'panel_id':'P001','status':'VISUAL_FAIL','round_id':1,'attempt_id':'first'}
            original={'execution_mode':'episode_async_v1','round_context':{
                'batch_id':'EPISODE','round_id':2,'attempt_id':'second'},
                'panels':[{'panel_id':'P001','operation':'repair','prompt':'修正承托'}]}
            original_ref=write('repair.json',original)
            subset_ref=write('subset.json',{'panels':[]})
            auth={'policy':'episode_repair_v1','panel_id':'P001','failed_attempt':snapshot(old),
                'route':'targeted_image_repair','reviewer':'TEST','evidence':'真实失败图',
                'repair_constraints':['修正承托'],'new_attempt_id':'second',
                'new_package_manifest':original_ref,'new_shot_subset':subset_ref}
            auth_ref=write('auth.json',auth)
            receipt={'batch_id':'EPISODE','round_id':2,'attempt_id':'second'}
            dispatched={**original,'dispatch_source_package':original_ref,'dispatch_receipt':receipt}
            dispatch_ref=write('dispatch.json',dispatched)
            row={'panel_id':'P001','status':'REPAIR_AUTHORIZED','round_id':2,'attempt_id':'second',
                'attempt_history':[old],'package_manifest':dispatch_ref,'shot_subset':subset_ref}
            state={'repair_authorizations':{'P001':auth_ref}}
            with patch('episode_repair.attempt_errors',return_value=[]):
                self.assertEqual(repair_errors(state,root,row),[])
                dispatched['panels'][0]['prompt']='换掉约束'
                row['package_manifest']=write('tampered.json',dispatched)
                self.assertTrue(any('仅加回执副本' in e for e in repair_errors(state,root,row)))


if __name__=='__main__':unittest.main()
