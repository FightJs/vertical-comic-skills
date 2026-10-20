"""Live diagnostics and durable failure evidence, without gate authority."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import audit_process
import audit_progress


class AuditProgressTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)

    def run_child(self,code,**kwargs):
        return audit_process.run([sys.executable,'-u','-c',code],cwd=self.root,
            stdout_path=self.root/'stdout.json',stderr_path=self.root/'stderr.txt',
            timeout=kwargs.pop('timeout',3),progress_stream=kwargs.pop('progress_stream',io.StringIO()),**kwargs)

    def test_heartbeat_reports_long_step_without_approval(self):
        observed=threading.Event()
        class HeartbeatSink(io.StringIO):
            def write(inner,line):
                count=super().write(line)
                event=json.loads(line)
                if event.get('panel_id')=='P003' and event['status']=='RUNNING':observed.set()
                return count
        stream=HeartbeatSink()
        with audit_progress.session('E000',enabled=True,stream=stream,interval=.02):
            audit_progress.mark('all_inputs',panel_id='P003',total=4)
            self.assertTrue(observed.wait(3),'No heartbeat arrived while the step was still running')
        events=[json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertGreaterEqual(len(events),3)
        self.assertTrue(any(e['panel_id']=='P003' and e['status']=='RUNNING' for e in events))
        self.assertTrue(all(e['not_approval_evidence'] for e in events))

    def test_error_progress_does_not_claim_finished(self):
        stream=io.StringIO()
        with self.assertRaises(ValueError):
            with audit_progress.session('E000',enabled=True,stream=stream):raise ValueError('fixture')
        self.assertEqual(json.loads(stream.getvalue().splitlines()[-1])['status'],'STOPPED_WITH_ERROR')

    def test_stderr_is_forwarded_before_child_finishes(self):
        # Child cannot exit until the live sink observes its diagnostic.
        marker=self.root/'seen'
        class Sink(io.StringIO):
            def write(inner,line):marker.touch();return super().write(line)
        code="import sys,time,pathlib; print('LIVE',file=sys.stderr,flush=True); p=pathlib.Path('seen')\nwhile not p.exists(): time.sleep(.01)\nprint('{}')"
        result=self.run_child(code,progress_stream=Sink())
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stderr,'LIVE\n')

    def test_timeout_preserves_partial_output_and_last_progress(self):
        event=json.dumps({'policy':'audit_progress_v1','stage':'all_inputs','panel_id':'P003'})
        code=f"import sys,time; print('{{',flush=True); print({event!r},file=sys.stderr,flush=True); time.sleep(10)"
        with self.assertRaises(subprocess.TimeoutExpired) as caught:self.run_child(code,timeout=2)
        self.assertEqual(caught.exception.stdout,'{\n')
        self.assertEqual(audit_process.last_progress(caught.exception.stderr)['panel_id'],'P003')
        self.assertEqual((self.root/'stderr.txt').read_text(encoding='utf-8'),caught.exception.stderr)

    def test_parent_exception_kills_its_child(self):
        original=subprocess.Popen.wait;children=[]
        def interrupt(process,*args,**kwargs):
            children.append(process)
            if len(children)==1:raise KeyboardInterrupt()
            return original(process,*args,**kwargs)
        with patch.object(subprocess.Popen,'wait',interrupt):
            with self.assertRaises(KeyboardInterrupt):self.run_child('import time; time.sleep(10)')
        self.assertIsNotNone(children[0].poll())

    def test_disk_error_is_fatal_but_display_error_is_not(self):
        real_open=Path.open
        class BadLog(io.StringIO):
            def write(self,value):raise OSError('synthetic disk full')
        def open_log(path,*args,**kwargs):
            if path.name=='stderr.txt' and args and args[0]=='x':return BadLog()
            return real_open(path,*args,**kwargs)
        with patch.object(Path,'open',open_log):
            with self.assertRaisesRegex(OSError,'evidence could not be saved'):
                self.run_child("import sys; print('diagnostic',file=sys.stderr); print('{}')")
        (self.root/'stdout.json').unlink()
        result=self.run_child("import sys; print('diagnostic',file=sys.stderr); print('{}')",progress_stream=BadLog())
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stderr,'diagnostic\n')


if __name__=='__main__':unittest.main()
