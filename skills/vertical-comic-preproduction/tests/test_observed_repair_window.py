import json,sys,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import test_stage_deadlines as fixtures
from codex_reference_contract import read_json
from stage_deadlines import checkpoint
class WindowTests(unittest.TestCase):
    def test_preparation_does_not_consume_window_and_pause_is_excluded(self):
        f=fixtures.StageDeadlineTests();self.addCleanup(f.doCleanups);h,p,row,proposal=f.fixture()
        state=read_json(p);state['repair_window_policy']='observed_repair_window_v2';p.write_text(json.dumps(state))
        self.assertFalse(checkpoint(p,'repair',row['panel_id'])['started'])
        f.now=1000
        self.assertFalse(checkpoint(p,'repair',row['panel_id'])['degraded'])
        state['panels'][0].update(status='VISUAL_FAIL',qa_report={'path':'qa','sha256':'real-test-binding'},repair_planning_started_active_seconds=1000)
        p.write_text(json.dumps(state));self.assertEqual(checkpoint(p,'repair',row['panel_id'])['active_elapsed_seconds'],0)
        import runtime_clock
        f.now=1010;runtime_clock.event(f.clock,'pause','p');f.now=2010;runtime_clock.event(f.clock,'resume','r')
        f.now=2020;self.assertEqual(checkpoint(p,'repair',row['panel_id'])['active_elapsed_seconds'],20)
        f.now=2490;self.assertTrue(checkpoint(p,'repair',row['panel_id'])['degraded'])
    def test_recovery_uses_persisted_start_not_replay_time(self):
        f=fixtures.StageDeadlineTests();self.addCleanup(f.doCleanups);h,p,row,proposal=f.fixture()
        state=read_json(p);state['repair_window_policy']='observed_repair_window_v2'
        state['panels'][0].update(status='VISUAL_FAIL',qa_report={'path':'qa','sha256':'x'},repair_planning_started_active_seconds=10)
        p.write_text(json.dumps(state));f.now=500
        self.assertTrue(checkpoint(p,'repair',row['panel_id'])['degraded'])
