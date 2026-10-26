"""Deterministic scheduling deadlines; no image calls or platform adaptation."""
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'))
import runtime_clock as c

def stamp(n):return {'wall':1000+n,'mono':n,'host':'test','boot':'boot'}
class HardDeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.directory=self.root/'00_任务协调'
        c.initialize(self.directory,'production',at=stamp(0),hard_deadline=True)
        c.event(self.directory,'start','start',at=stamp(0))
    def test_pause_excluded_from_active_budget(self):
        c.event(self.directory,'pause','p',at=stamp(100));c.event(self.directory,'resume','r',at=stamp(10000))
        value=c.status(self.directory,at=stamp(10020))
        self.assertEqual(value['active_seconds'],120);self.assertEqual(value['remaining_seconds'],14280)
        self.assertEqual(value['schedule_stage'],'PRODUCE');self.assertTrue(value['optional_work_allowed'])
    def test_target_and_hard_boundary_exact(self):
        for n,stage,allowed in [(8999,'PRODUCE',True),(9000,'CONVERGE',True),(10799,'CONVERGE',True),(10800,'TARGET_OVERRUN',True),(14399,'TARGET_OVERRUN',True),(14400,'HARD_STOP',False)]:
            with self.subTest(n=n):
                value=c.status(self.directory,at=stamp(n))
                self.assertEqual(value['schedule_stage'],stage);self.assertEqual(value['new_calls_allowed'],allowed)
    def test_three_hours_allows_generation_and_review_until_hard_stop(self):
        with patch.object(c,'instant',return_value=stamp(10800)):
            self.assertTrue(c.require_dispatch(self.root)['new_calls_allowed'])
            self.assertEqual(c.require_step(self.root,'qa-save')['schedule_stage'],'TARGET_OVERRUN')
            self.assertTrue(c.require_step(self.root,'compile')['new_calls_allowed'])
        with patch.object(c,'instant',return_value=stamp(14400)):
            with self.assertRaisesRegex(ValueError,'LIMIT_REACHED'):c.require_step(self.root,'final-check')
    def test_optional_work_rejected_in_convergence(self):
        with patch.object(c,'instant',return_value=stamp(9000)):
            with self.assertRaisesRegex(ValueError,'CONVERGE'):c.require_step(self.root,'compile',optional=True)
            self.assertIsNotNone(c.require_step(self.root,'compile'))
    def test_restart_never_resets_origin(self):
        c.initialize(self.directory,'production',at=stamp(12000),hard_deadline=True)
        self.assertEqual(c.status(self.directory,at=stamp(12000))['remaining_seconds'],2400)
        with self.assertRaisesRegex(ValueError,'SCOPE_CONFLICT'):c.initialize(self.directory,'production',14399,hard_deadline=True)
    def test_cannot_extend_above_four_hours(self):
        with self.assertRaisesRegex(ValueError,'MAX_14400'):c.initialize(self.root/'other','production',18000,hard_deadline=True)
    def test_all_episodes_share_parent_deadline(self):
        with patch.object(c,'instant',return_value=stamp(14400)):
            for episode in ('E026','E030'):
                with self.assertRaisesRegex(ValueError,'LIMIT_REACHED'):c.require_dispatch(self.root/episode/'00_输入审计/生产流程.json')
    def test_shorter_limit_is_respected(self):
        directory=self.root/'short';c.initialize(directory,'preparation',3600,at=stamp(0),hard_deadline=True)
        c.event(directory,'start','start',at=stamp(0))
        self.assertEqual(c.status(directory,at=stamp(3600))['remaining_seconds'],0)
    def test_legacy_clock_still_excludes_pause(self):
        d=self.root/'old/00_任务协调';c.initialize(d,'production',at=stamp(0));c.event(d,'start','s',at=stamp(0))
        c.event(d,'pause','p',at=stamp(100));c.event(d,'resume','r',at=stamp(10000))
        self.assertEqual(c.status(d,at=stamp(10020))['remaining_seconds'],14280)
    def test_context_prevents_origin_reset(self):
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        p=self.directory/'runtime-clock.json';v=json.loads(p.read_text());v['created']=stamp(200);p.write_text(json.dumps(v))
        with patch.object(c,'instant',return_value=stamp(300)),self.assertRaisesRegex(ValueError,'ORIGIN_CHANGED'):
            c.require_dispatch(self.root)
    def test_lost_or_changed_clock_cannot_disable_new_context(self):
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        (self.directory/'runtime-clock.json').unlink()
        with self.assertRaisesRegex(ValueError,'LEDGER_MISSING'):c.require_step(self.root)
    def test_pause_wait_user_and_resume_do_not_reset_prior_active_time(self):
        c.event(self.directory,'wait_user','wait',at=stamp(10800))
        c.event(self.directory,'resume','resume',at=stamp(86400))
        with patch.object(c,'instant',return_value=stamp(86401)):
            value=c.require_dispatch(self.root)
            self.assertEqual(value['remaining_seconds'],3599)
            self.assertTrue(value['new_calls_allowed'])
    def test_successful_finish_does_not_become_late_when_inspected_later(self):
        c.event(self.directory,'finish','done',at=stamp(10000))
        value=c.status(self.directory,at=stamp(20000))
        self.assertEqual(value['wall_seconds'],10000);self.assertEqual(value['remaining_seconds'],4400)
    def test_policy_removal_cannot_reenable_steps(self):
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        p=self.directory/'runtime-clock.json';v=json.loads(p.read_text());v.pop('deadline_policy');p.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'SCOPE_MISMATCH'):c.require_step(self.root)
    def test_public_entry_defaults_to_four_hours(self):
        import inspect,comic_start
        self.assertEqual(inspect.signature(comic_start.prepare).parameters['runtime_limit_seconds'].default,14400)
        self.assertEqual(inspect.signature(comic_start.receive).parameters['runtime_limit_seconds'].default,14400)
    def test_entry_charges_observed_precheck_time(self):
        import comic_start
        run=self.root/'receiver'
        with patch('runtime_clock_context.resolve',return_value={'session_id':'synthetic'}),patch.object(c,'bind',return_value={}),patch.object(c,'instant',return_value=stamp(100)):
            result=comic_start.start_clock(run,'production',14400,None,started=stamp(0))
        self.assertEqual(result['runtime_clock']['remaining_seconds'],14300)
        self.assertEqual(result['runtime_clock']['deadline_policy'],c.DEADLINE_POLICY)

    def test_unchanged_clock_status_does_not_rewrite_ledger(self):
        c.status(self.directory,at=stamp(1))
        with patch.object(c,'atomic_json',wraps=c.atomic_json) as write:
            c.status(self.directory,at=stamp(2))
        self.assertEqual(write.call_count,0)

