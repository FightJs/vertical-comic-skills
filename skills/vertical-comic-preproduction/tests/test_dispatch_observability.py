"""Dispatch latency/recovery semantics; synthetic timestamps, no service calls."""
import json,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts')]
from worker_watchdog import dispatch_alerts
from execution_timing import checked_invocation_event
from production_metrics import build
from prepared_job_store import state_basis

class DispatchObservability(unittest.TestCase):
    def test_wait_kinds_and_pause_exclusion(self):
        now=datetime.now(timezone.utc)
        at=lambda n:(now-timedelta(seconds=n)).isoformat()
        rows=[{'panel_id':'P1','attempt_id':'A1','ready_at':at(120)},
              {'panel_id':'P2','attempt_id':'A2','registered_at':at(120)},
              {'panel_id':'P3','attempt_id':'A3','invocation_requested_at':at(700)},
              {'panel_id':'P4','attempt_id':'A4','native_completed_at':at(60)}]
        alerts=dispatch_alerts(rows,now=now,free_channels=1)
        self.assertEqual({a['kind'] for a in alerts},{'READY_NOT_DISPATCHED','REGISTERED_NOT_OBSERVED','LONG_INVOCATION','RETURN_NOT_SAVED'})
        self.assertTrue(all(not a['retry_allowed'] for a in alerts))
        self.assertEqual(dispatch_alerts(rows,now=now,free_channels=1,paused=True),[])
        self.assertEqual(dispatch_alerts(rows,now=now,free_channels=1,emitted=[a['event_id'] for a in alerts]),[])
        rows[0]['excluded_wait_seconds']={'ready_at':100}
        self.assertEqual(dispatch_alerts(rows[:1],now=now,free_channels=1),[])
    def test_local_invocation_cannot_be_native_start(self):
        event={'kind':'STARTED','at':datetime.now(timezone.utc).isoformat(),'source_kind':'observed_executor_outcome','source_locator':'synthetic://local'}
        with self.assertRaisesRegex(ValueError,'SOURCE_REQUIRED'):checked_invocation_event(event)
        event.update(kind='REQUESTED');self.assertEqual(checked_invocation_event(event),event)
    def test_progress_counter_does_not_invalidate_but_revocation_does(self):
        before={'authority_revision':1,'approval_revocations':[],'source_script':{'sha256':'a'}}
        after={**before,'authority_revision':2,'panels':[{'status':'GENERATED'}]}
        self.assertEqual(state_basis(before),state_basis(after))
        after['approval_revocations']=['approval-A'];self.assertNotEqual(state_basis(before),state_basis(after))
    def test_missing_native_times_stay_unknown_and_overlaps_not_summed_as_wall(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'00_输入审计'/'生产流程.json';path.parent.mkdir()
            rows=[{'panel_id':p,'attempt_id':p,'round_id':1,'status':'IN_FLIGHT',
                   'registered_at':'2026-01-01T00:00:00+00:00',
                   'invocation_requested_at':'2026-01-01T00:00:10+00:00',
                   'native_started_at':'2026-01-01T00:00:20+00:00',
                   'native_completed_at':'2026-01-01T00:01:20+00:00',
                   'saved_at':'2026-01-01T00:01:25+00:00'} for p in ('P1','P2')]
            rows.append({'panel_id':'P3','attempt_id':'A3','status':'IN_FLIGHT','round_id':1,'submitted_at':'2026-01-01T00:00:00+00:00'})
            path.write_text(json.dumps({'book_id':'B','episode_id':'E','panels':rows}))
            report=build([path]);phase=report['timing']['phase_windows']['native_call_span']
            self.assertEqual(phase['samples'],2);self.assertEqual(phase['union_seconds'],60);self.assertEqual(phase['sum_seconds_not_wall_time'],120)
            self.assertEqual(report['timing']['timestamp_coverage']['native_started_at'],2)

if __name__=='__main__':unittest.main()
