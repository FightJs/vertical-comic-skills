import contextlib, importlib, io, json, os, pathlib, subprocess, sys, tempfile, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/vertical-comic-preproduction/scripts'
sys.path.insert(0,str(SCRIPTS))
import runtime_clock as c
from runtime_clock_hook import handle
from runtime_clock_setup import setup

def stamp(n,boot='boot',wall=None):
    return {'wall':1000+n if wall is None else wall,'mono':n,'host':'test','boot':boot}

class RuntimeClockTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.temp.name).resolve()
        self.clock=self.root/'run/00_任务协调'
        c.initialize(self.clock,'production',10800,at=stamp(0))
    def tearDown(self): self.temp.cleanup()
    def event(self,action,n,key=None):
        c.event(self.clock,action,key or action+str(n),at=stamp(n))
    def test_pause_excluded_parallel_single_budget(self):
        self.event('start',0);self.event('pause',40);self.event('resume',7240)
        v=c.status(self.clock,at=stamp(7270))
        self.assertEqual(v['active_seconds'],70)
        self.assertEqual(v['excluded_seconds'],7200)
        self.assertEqual(v['remaining_seconds'],10730)
        self.assertEqual(c.locate(self.root/'run/E001/00_输入审计/生产流程.json'),self.clock)
        self.assertEqual(c.locate(self.root/'run/E002/state.json'),self.clock)
    def test_duplicate_interrupt_does_not_charge_gap(self):
        self.event('start',0);self.event('pause',10,'one');self.event('pause',12,'one')
        self.assertEqual(c.status(self.clock,at=stamp(100))['active_seconds'],10)
        self.event('resume',100);self.event('resume',101)
        self.assertEqual(c.status(self.clock,at=stamp(110))['active_seconds'],20)
    def test_conflicting_id_rejected(self):
        self.event('start',0,'same');self.event('pause',1,'same')
        with self.assertRaisesRegex(ValueError,'ID_CONFLICT'):c.status(self.clock,at=stamp(5))
    def test_finished_and_limit(self):
        self.event('start',0);self.event('finish',10810)
        v=c.status(self.clock,at=stamp(20000))
        self.assertEqual(v['active_seconds'],10810);self.assertEqual(v['remaining_seconds'],0)
        with self.assertRaisesRegex(ValueError,'FINISHED'): c.require_running(self.root/'run/state.json')
    def test_reboot_and_clock_jump_not_fabricated(self):
        self.event('start',0)
        self.assertEqual(c.status(self.clock,at=stamp(5,boot='other'))['state'],'TIME_UNCERTAIN')
        self.assertEqual(c.status(self.clock,at=stamp(5,wall=2000))['state'],'TIME_UNCERTAIN')
    def test_hook_cli_receives_without_coordinator_lock(self):
        home=self.root/'home';session='realistic-session-id'
        c.bind(self.clock,session,home)
        self.event('start',0)
        payload={'session_id':session,'turn_id':'turn1','hook_event_name':'Interrupt'}
        # Explicit adapter wiring proof; not a claim of UI trust.
        with c.file_lock(self.clock/'clock.lock'):
            self.assertEqual(handle(payload,home)['status'],'RECORDED')
        v=c.status(self.clock)
        self.assertTrue(v['hook_event_observed']);self.assertEqual(v['state'],'TIME_UNCERTAIN')
        # Different boot in deterministic fixture is deliberately diagnosed.
        self.assertEqual(handle({'session_id':'unrelated','hook_event_name':'Interrupt'},home)['status'],'UNBOUND')
    def test_actual_hook_subprocess_and_duplicate_delivery(self):
        directory=self.root/'actual-hook';home=self.root/'hook-home'
        c.initialize(directory,'production');c.event(directory,'start','start-real')
        c.bind(directory,'session-real',home)
        payload=json.dumps({'session_id':'session-real','turn_id':'turn-real','hook_event_name':'Interrupt'})
        env=dict(os.environ,CODEX_HOME=str(home))
        for _ in range(2):
            subprocess.run([sys.executable,'-B',str(SCRIPTS/'runtime_clock_hook.py')],input=payload,text=True,env=env,check=True,capture_output=True)
        first=c.status(directory);second=c.status(directory)
        self.assertEqual(first['state'],'PAUSED');self.assertTrue(first['hook_event_observed'])
        self.assertEqual(first['active_seconds'],second['active_seconds'])
        self.assertFalse(first['automatic_pause_verified'])

    def test_paused_blocks_new_work_but_not_saved_return_path(self):
        self.event('start',0);self.event('pause',1)
        with self.assertRaisesRegex(ValueError,'PAUSED'):c.require_running(self.root/'run/state.json')
        self.assertIsNone(c.require_running(self.root/'legacy/state.json'))
        self.assertEqual(c.status(self.clock,at=stamp(100))['active_seconds'],1)
    def test_setup_preserves_other_hooks_and_is_idempotent(self):
        home=self.root/'home';installed=home/'skills/vertical-comic-preproduction/scripts';installed.mkdir(parents=True)
        (installed/'runtime_clock_hook.py').write_text('# fixture')
        path=home/'hooks.json';original={'description':'keep','hooks':{'Stop':[{'hooks':[{'type':'command','command':'echo keep'}]}]}}
        path.write_text(json.dumps(original))
        preview=setup(home);self.assertEqual(json.loads(path.read_text()),original)
        first=setup(home,apply=True);second=setup(home,apply=True)
        self.assertEqual(json.loads(path.read_text())['hooks']['Stop'],original['hooks']['Stop'])
        self.assertTrue(pathlib.Path(first['backup']).is_file())
        self.assertEqual(second['status'],'CONFIGURED_TRUST_NOT_VERIFIED')
    def test_real_cli_pause_and_query(self):
        d=self.root/'cli'
        def run(*args):
            return json.loads(subprocess.check_output([sys.executable,'-B',str(SCRIPTS/'runtime_clock.py'),*args,'--directory',str(d)],text=True))
        run('init','--role','preparation');run('start');v=run('pause');after=run('status')
        self.assertEqual(v['state'],'PAUSED');self.assertEqual(v['active_seconds'],after['active_seconds'])
        self.assertEqual(run('resume')['state'],'RUNNING')

if __name__=='__main__': unittest.main()
