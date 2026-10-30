"""Policy revision preserves charged time, pauses and content-bound context."""
from pathlib import Path
import json, sys, tempfile, unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'))
import runtime_clock as c

def stamp(n):return {'wall':1000+n,'mono':n,'host':'test','boot':'boot'}

class ClockAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.d=self.root/'00_任务协调'
        c.initialize(self.d,'production',14400,hard_deadline=True,at=stamp(0))
        # A real old-contract ledger, not a new clock with a renewed start.
        p=self.d/'runtime-clock.json';value=json.loads(p.read_text())
        value.update(deadline_policy=c.LEGACY_DEADLINE_POLICY,target_seconds=10800)
        p.write_text(json.dumps(value))
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        c.event(self.d,'start','s',at=stamp(0))

    def amend(self):return c.amend_policy(self.d,reason='4h target, 7h hard stop',source_ref='synthetic:user-message')

    def test_expired_legacy_clock_resumes_with_only_remaining_time_and_same_context(self):
        with patch.object(c,'instant',return_value=stamp(14500)),patch('runtime_clock_context.require_bound'):
            self.assertEqual(c.status(self.d)['schedule_stage'],'HARD_STOP')
            before=(self.d/'runtime-clock.json').read_bytes();context=(self.d/'execution-context.json').read_bytes()
            result=self.amend();self.assertFalse(result['history_reset'])
            self.assertEqual((self.d/'runtime-clock.json').read_bytes(),before)
            self.assertEqual((self.d/'execution-context.json').read_bytes(),context)
            current=c.require_dispatch(self.root)
            self.assertEqual(current['remaining_seconds'],10700)
            self.assertEqual(current['target_remaining_seconds'],0)
            self.assertEqual(current['schedule_stage'],'TARGET_OVERRUN')
            self.assertEqual(self.amend(),result)
        with patch.object(c,'instant',return_value=stamp(25200)),patch('runtime_clock_context.require_bound'):
            with self.assertRaisesRegex(ValueError,'LIMIT_REACHED'):c.require_dispatch(self.root)
            self.assertEqual(c.require_step(self.root,'preserve-delivery')['schedule_stage'],'HARD_STOP')
            with self.assertRaisesRegex(ValueError,'LIMIT_REACHED'):c.require_step(self.root,'qa-save')

    def test_pause_remains_paused_and_long_wait_is_not_charged(self):
        c.event(self.d,'pause','p',at=stamp(14410))
        with patch.object(c,'instant',return_value=stamp(100000)),patch('runtime_clock_context.require_bound'):
            self.amend()
            with self.assertRaisesRegex(ValueError,'PAUSED'):c.require_dispatch(self.root)
        c.event(self.d,'resume','r',at=stamp(100000))
        self.assertEqual(c.status(self.d,at=stamp(100010))['active_seconds'],14420)
        self.assertEqual(c.status(self.d,at=stamp(100010))['remaining_seconds'],10780)

    def test_amendment_cannot_be_reused_after_origin_or_context_change(self):
        with patch.object(c,'instant',return_value=stamp(100)):
            self.amend()
            p=self.d/'execution-context.json';data=json.loads(p.read_text());data['run_id']='other';p.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError,'AMENDMENT_CHANGED'):c.status(self.d)

    def test_wall_and_finished_clocks_cannot_be_extended(self):
        c.event(self.d,'finish','f',at=stamp(10))
        with patch.object(c,'instant',return_value=stamp(11)),self.assertRaisesRegex(ValueError,'RECOVERABLE'):self.amend()
        wall=self.root/'wall';c.initialize(wall,'production',14400,hard_deadline=True,delivery_deadline=True,at=stamp(0))
        with patch.object(c,'instant',return_value=stamp(11)),self.assertRaisesRegex(ValueError,'ACTIVE_ONLY'):
            c.amend_policy(wall,reason='request',source_ref='message')

    def test_amendment_requires_recorded_reason_and_source(self):
        with self.assertRaisesRegex(ValueError,'AUTHORIZATION_REFERENCE_REQUIRED'):
            c.amend_policy(self.d,reason='',source_ref='')
