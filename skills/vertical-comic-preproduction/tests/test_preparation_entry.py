"""New runs advertise the scheduler; old coordination remains unchanged."""
import json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).parents[1]/'scripts'),str(Path(__file__).parent)]
import comic_start
import task_coordination

class PreparationEntry(unittest.TestCase):
    def test_prepare_emits_frozen_host_descriptor_without_launching(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'script.xlsx';source.write_bytes(b'SYNTHETIC_NOT_A_WORKBOOK')
            assets=root/'assets';assets.mkdir()
            with patch.dict('os.environ',{'CODEX_HOME':str(root/'codex')}):
                result=comic_start.prepare(root,'SYNTHETIC',['E001'],script=source,assets=assets,runtime_limit_seconds=None)
            host=result['preparation_host'];manifest=json.loads(Path(host['manifest']['path']).read_text())
            self.assertEqual(host['policy'],'preparation_scheduler_v1')
            self.assertEqual(manifest['episode_ids'],['E001'])
            self.assertTrue(manifest['preparation_only'])
            self.assertEqual(manifest['asset_ledger_root'],result['run_root'])
            self.assertTrue(Path(host['entry']).is_relative_to(Path(result['run_root'])/'00_总控/运行版本'))
            self.assertTrue(Path(host['entry']).is_file())
            self.assertFalse(host['dispatch_authorized'])
            state=json.loads(Path(manifest['states'][0]).read_text())
            self.assertEqual(state['preparation_scheduler_policy'],host['policy'])
            coord=Path(result['run_root'])/'00_任务协调'
            self.assertFalse((coord/'coordination.json').exists())
            projection=task_coordination.resume(coord)
            self.assertEqual(projection['policy'],host['policy'])
            self.assertEqual(projection['status'],'HOST_NEEDED')
    def test_new_scheduler_does_not_accept_legacy_mutating_events(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);coord=root/'00_任务协调';coord.mkdir()
            (coord/'preparation-host.json').write_text(json.dumps({'policy':'preparation_scheduler_v1','book_id':'B','episode_ids':['E001'],'states':[]}))
            with self.assertRaisesRegex(ValueError,'SCHEDULER'):
                task_coordination.update(coord,0,{'event_id':'x','action':'register','task_id':'duplicate'})
            self.assertFalse((coord/'coordination.json').exists())
    def test_skill_routes_new_runs_to_actual_scheduler_and_explains_native_boundary(self):
        base=Path(__file__).parents[1]
        entry=(base/'SKILL.md').read_text()
        self.assertIn('preparation_scheduler_v1',entry)
        guide=(base/'references/preparation-scheduler.md').read_text()
        for term in ('HOST_NEEDED','submit-fragments','submit-observations','claim','attach-host','seal','publish','TECHNICALLY_READY','UNKNOWN','operation_id'):
            self.assertIn(term,guide)
        self.assertIn('不修改旧冻结',guide)

    def test_legacy_progress_reads_same_live_scheduler_projection(self):
        from preparation_host import Host
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);coord=root/'00_任务协调';coord.mkdir()
            (coord/'preparation-host.json').write_text(json.dumps({'policy':'preparation_scheduler_v1','book_id':'B','episode_ids':['E001'],'states':[]}))
            host=Host(root)
            try:
                current=host.status()['scheduler']
                projected=task_coordination.resume(coord)
                self.assertEqual(projected['revision'],current['revision'])
                self.assertEqual(projected['tasks'],current['tasks'])
                self.assertFalse((coord/'coordination.json').exists())
                self.assertEqual(task_coordination.finish(coord,current['revision'],root/'missing.zip')['status'],'CONTINUE_REQUIRED')
            finally:host.close()

    def test_existing_unmarked_coordination_still_uses_original_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);coord=root/'coord';display=root/'display';display.mkdir()
            (display/'task.json').write_text(json.dumps({'scope':{'book':'B','episodes':['E001']}}))
            result=task_coordination.initialize(coord,display)
            self.assertEqual(result['policy'],task_coordination.POLICY)
            self.assertTrue((coord/'coordination.json').is_file())

if __name__=='__main__':unittest.main()
