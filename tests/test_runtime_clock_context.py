import json, os, pathlib, shutil, subprocess, sys, tempfile, unittest
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/vertical-comic-preproduction/scripts'
sys.path.insert(0,str(SCRIPTS))
import runtime_clock as clock
import runtime_clock_context as context
from runtime_clock_hook import handle
from runtime_clock_setup import setup, prepare_runtime
from comic_start import start_clock

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name).resolve()
        self.home=self.root/'codex';self.env=patch.dict(os.environ,{'CODEX_HOME':str(self.home),'CODEX_THREAD_ID':'thread-A'})
        self.env.start()
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def receipt(self,session='thread-A',turn='turn1'):
        return handle({'session_id':session,'turn_id':turn,'hook_event_name':'PreToolUse',
                       'tool_input':{'cmd':'python comic_start.py receive --runtime-limit-seconds 14400'}},self.home)
    def test_wall_deadline_starts_without_optional_host_pause_receipt(self):
        run=self.root/'run'
        result=start_clock(run,'production',14400,None,wall_delivery=True)
        self.assertTrue((run/'00_任务协调/runtime-clock.json').exists())
        self.assertEqual(result['runtime_clock']['delivery_schedule'],clock.DELIVERY_SCHEDULE)
        self.assertTrue(result['runtime_clock']['deadline_includes_pauses'])
        self.assertFalse(result['clock_binding']['session_bound'])
        self.assertFalse(result['clock_binding']['automatic_pause_verified'])
    def test_host_id_mismatch_stale_and_unrelated_do_not_bind(self):
        handle({'session_id':'thread-B','hook_event_name':'PreToolUse','tool_input':{'cmd':'date'}},self.home)
        self.assertFalse(context.context_path('thread-B',self.home).exists())
        self.receipt()
        with self.assertRaisesRegex(ValueError,'MISMATCH'):context.resolve(explicit_session='thread-B')
        observed=context.resolve()
        with self.assertRaisesRegex(ValueError,'STALE'):context.resolve(now=observed['observed_at']+601)
    def test_two_sessions_pause_only_owner_and_resume_explicitly(self):
        self.receipt();a=start_clock(self.root/'a','production',14400,None)['clock_directory']
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'thread-B'}):
            self.receipt('thread-B');b=start_clock(self.root/'b','preparation',14400,None)['clock_directory']
        handle({'session_id':'thread-A','turn_id':'stop-a','hook_event_name':'Interrupt'},self.home)
        paused=clock.status(a)
        self.assertEqual(paused['state'],'PAUSED');self.assertTrue(paused['binding']['session_bound'])
        self.assertEqual(clock.status(b)['state'],'RUNNING')
        self.receipt(turn='status-question')
        self.assertEqual(clock.status(a)['active_seconds'],paused['active_seconds'])
        clock.attach_current(a);clock.event(a,'resume','explicit-work')
        self.assertEqual(clock.status(a)['state'],'RUNNING')
    def test_same_run_cannot_be_taken_by_another_session(self):
        self.receipt();a=start_clock(self.root/'a','production',14400,None)['clock_directory']
        with patch.dict(os.environ,{'CODEX_THREAD_ID':'thread-B'}):
            self.receipt('thread-B')
            with self.assertRaisesRegex(ValueError,'RUN_ALREADY_BOUND'):clock.attach_current(a)
    def test_finished_binding_released_history_retained(self):
        self.receipt();a=start_clock(self.root/'a','production',14400,None)['clock_directory']
        clock.event(a,'finish','delivered');clock.release(a)
        self.assertEqual(handle({'session_id':'thread-A','turn_id':'later','hook_event_name':'Interrupt'},self.home)['status'],'UNBOUND')
        self.assertTrue(list((clock.registry(self.home)/'history').glob('*.json')))
        self.receipt();new=start_clock(self.root/'new','production',14400,None)
        self.assertTrue(new['clock_binding']['session_bound'])
    def test_attach_existing_does_not_rewrite_clock_history(self):
        d=self.root/'old/00_任务协调';clock.initialize(d,'production');clock.event(d,'start','old-start')
        before=(d/'runtime-clock.json').read_bytes();events=sorted(p.read_bytes() for p in (d/'clock-events').glob('*.json'))
        self.receipt();result=clock.attach_current(d)
        self.assertFalse(result['history_recalculated']);self.assertEqual(before,(d/'runtime-clock.json').read_bytes())
        self.assertEqual(events,sorted(p.read_bytes() for p in (d/'clock-events').glob('*.json')))
    def test_stable_runtime_after_removing_downloaded_scripts(self):
        installed=self.home/'skills/vertical-comic-preproduction/scripts';installed.mkdir(parents=True)
        download=self.root/'download';shutil.copytree(SCRIPTS,download,ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('runtime_clock.py','runtime_clock_hook.py','runtime_clock_context.py','platform_io.py'):
            shutil.copy2(download/name,installed/name)
        # Preserve a genuinely unrelated hook while replacing the obsolete repository interpreter.
        hooks=self.home/'hooks.json';hooks.write_text(json.dumps({'hooks':{'Interrupt':[{'hooks':[
            {'type':'command','command':'old-deleted-python '+str(installed/'runtime_clock_hook.py')},
            {'type':'command','command':'echo unrelated'}]}]}}))
        source_home=self.root/'download-source'
        source_runtime=prepare_runtime(source_home,python=sys.executable)
        result=setup(self.home,python=source_runtime['python'],apply=True)
        shutil.rmtree(download);shutil.rmtree(source_home)
        self.assertFalse(pathlib.Path(source_runtime['python']).exists())
        exe=result['runtime']['python'];self.assertTrue(pathlib.Path(exe).is_relative_to(self.home/'skill-bundles'))
        payload={'session_id':'thread-A','turn_id':'fresh','hook_event_name':'PreToolUse',
                 'tool_input':{'cmd':'python comic_start.py receive --runtime-limit-seconds 14400'}}
        subprocess.run([exe,'-B',str(installed/'runtime_clock_hook.py')],input=json.dumps(payload),text=True,check=True,capture_output=True)
        self.assertEqual(context.resolve()['session_id'],'thread-A')
        config=json.loads(hooks.read_text());commands=[x['command'] for row in config['hooks']['Interrupt'] for x in row['hooks']]
        self.assertIn('echo unrelated',commands);self.assertFalse(any('old-deleted-python' in x for x in commands))
        self.assertTrue(pathlib.Path(result['backup']).is_file())
        self.assertEqual(setup(self.home,apply=True)['status'],'CONFIGURED_TRUST_NOT_VERIFIED')

if __name__=='__main__':unittest.main()
