import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from worker_watchdog import DEFAULTS, evaluate, record_progress, check_ledger, acknowledge


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / "00_输入审计" / "worker_watchdog.json"
        self.ledger.parent.mkdir()
        self.evidence = self.root / "shot.json"
        self.evidence.write_text('{"shot":"real saved artifact"}', encoding="utf-8", newline='\n')
        self.event = {"stage":"shot_design", "kind":"shot_saved", "blocker_id":"B:P001",
                      "evidence":{"path":"shot.json", "sha256": hashlib.sha256(self.evidence.read_bytes()).hexdigest()}}
        self.start = "2026-10-14T00:00:00Z"

    def test_two_thresholds_dedupe_across_resume_and_duplicate_evidence(self):
        self.assertEqual(record_progress(self.ledger,self.root,self.event,now=self.start)["status"],"PROGRESS_RECORDED")
        first = check_ledger(self.ledger,{"panels":[]},now="2026-10-14T00:06:00Z")
        self.assertEqual([a["level"] for a in first["alerts"]],["T1"])
        acknowledge(self.ledger,{"panels":[]},[first["alerts"][0]["event_id"]],now="2026-10-14T00:06:00Z")
        self.assertEqual(check_ledger(self.ledger,{"panels":[]},now="2026-10-14T00:07:00Z")["alerts"],[])
        self.assertEqual(record_progress(self.ledger,self.root,self.event,now="2026-10-14T00:09:00Z")["status"],"DUPLICATE_EVIDENCE")
        late = check_ledger(self.ledger,{"panels":[]},now="2026-10-14T00:13:00Z")
        self.assertEqual([a["level"] for a in late["alerts"]],["T2"])
        acknowledge(self.ledger,{"panels":[]},[late["alerts"][0]["event_id"]],now="2026-10-14T00:13:00Z")
        self.assertEqual(check_ledger(self.ledger,{"panels":[]},now="2026-10-14T00:30:00Z")["alerts"],[])

    def test_human_wait_exempt_and_cross_episode_local_handoff(self):
        snapshot={"stage":"image_review","last_progress_at":self.start,"blocker_id":"C", "wait_kind":"HUMAN_C"}
        self.assertEqual(evaluate(snapshot,now="2026-10-14T01:00:00Z")["state"],"WAIT_HUMAN")
        snapshot.update(wait_kind="CROSS_EPISODE",local_episode_complete=True)
        result=evaluate(snapshot,now="2026-10-14T01:00:00Z")
        self.assertEqual(result["state"],"LOCAL_HANDOFF_READY")
        self.assertEqual(result["alerts"],[])

    def test_inflight_uses_own_clock_never_authorizes_retry(self):
        snapshot={"stage":"generation","last_progress_at":self.start,"blocker_id":"H001",
                  "requests":[{"panel_id":"P001","attempt_id":"A1","status":"IN_FLIGHT","submitted_at":self.start}]}
        result=evaluate(snapshot,now="2026-10-14T00:31:00Z")
        self.assertEqual(result["state"],"REQUESTS_IN_FLIGHT")
        self.assertEqual([a["level"] for a in result["alerts"]],["T1","T2"])
        self.assertIn("HOLD_DUPLICATE_RETRY",result["alerts"][1]["action"])

    def test_unchanged_or_forged_evidence_cannot_reset_clock(self):
        bad=json.loads(json.dumps(self.event));bad["evidence"]["sha256"]="0"*64
        with self.assertRaises(ValueError):record_progress(self.ledger,self.root,bad,now=self.start)
        self.assertFalse(self.ledger.exists())
        record_progress(self.ledger,self.root,self.event,now=self.start)
        with self.assertRaises(ValueError):acknowledge(self.ledger,{"panels":[]},["invented"],now="2026-10-14T00:06:00Z")
        self.assertEqual(json.loads(self.ledger.read_text(encoding='utf-8-sig'))["emitted"],[])
        self.assertEqual(DEFAULTS["request_warning_seconds"],900)

    def test_runtime_cli_records_and_reads_episode_sidecar(self):
        from production_runtime import DEFAULTS as RUNTIME_DEFAULTS
        state_path=self.ledger.parent/"生产流程.json"
        state_path.write_text(json.dumps({"episode_id":"E021","runtime":RUNTIME_DEFAULTS,"panels":[]}), encoding='utf-8', newline='\n')
        event_path=self.root/"event.json"
        event_path.write_text(json.dumps(self.event), encoding='utf-8', newline='\n')
        script=Path(__file__).resolve().parents[1]/"scripts"/"production_runtime.py"
        record=subprocess.run([sys.executable, '-X', 'utf8',str(script),"--state",str(state_path),"--action","watch-progress",
                               "--watch-event",str(event_path)],capture_output=True,text=True,check=True, encoding='utf-8')
        self.assertEqual(json.loads(record.stdout)["status"],"PROGRESS_RECORDED")
        checked=subprocess.run([sys.executable, '-X', 'utf8',str(script),"--state",str(state_path),"--action","watch-check"],
                               capture_output=True,text=True,check=True, encoding='utf-8')
        self.assertEqual(json.loads(checked.stdout)["policy"],"worker_watchdog_v1")



class ExecutorLifecycleTests(unittest.TestCase):
    def test_definitive_termination_reconciles_once_without_assuming_no_image(self):
        from worker_watchdog import evaluate
        snapshot={'stage':'generation','executor_lifecycle':{'state':'TERMINATED','executor_id':'synthetic-cell',
            'source_locator':'synthetic://host-terminal','event_id':'terminal-1'},
            'requests':[{'panel_id':'P001','attempt_id':'a1','status':'RESULT_UNKNOWN'}]}
        result=evaluate(snapshot);self.assertEqual(result['state'],'EXECUTOR_TERMINATED')
        event=result['alerts'][0];self.assertEqual(event['action'],'RECONCILE_CAPTURED_RETURNS_AND_REMOTE_OUTCOMES')
        snapshot['emitted']=[event['event_id']]
        self.assertEqual(evaluate(snapshot)['alerts'],[])
        snapshot['executor_lifecycle'].pop('source_locator')
        with self.assertRaises(ValueError):evaluate(snapshot)

if __name__ == "__main__":
    unittest.main()
