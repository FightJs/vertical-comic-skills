import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from agent_capacity import ensure

class AgentCapacityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'config.toml'

    def write(self, text): self.path.write_text(text, encoding='utf-8')
    def read(self): return tomllib.loads(self.path.read_text(encoding='utf-8'))

    def test_missing_config(self):
        result=ensure(self.path)
        self.assertEqual(result['status'],'CONFIG_UPDATED')
        self.assertEqual(self.read()['agents']['max_concurrent_threads_per_session'],6)
        self.assertIsNone(result['current_session_capacity'])
        self.assertEqual(result['current_session_capacity_status'],'unknown')
        self.assertEqual(list(self.path.parent.iterdir()),[self.path])

    def test_change_preserves_others_and_is_idempotent(self):
        original='# header\n[agents]\nmax_concurrent_threads_per_session = 5 # limit\nenabled = false\n\n[other]\nvalue = "x"\n'
        self.write(original);result=ensure(self.path)
        self.assertEqual(result['status'],'CONFIG_UPDATED')
        data=self.read();self.assertEqual(data['agents'],{'max_concurrent_threads_per_session':6,'enabled':True})
        self.assertEqual(data['other'],{'value':'x'});self.assertIn('# limit',self.path.read_text())
        after=self.path.read_bytes();result=ensure(self.path)
        self.assertEqual(result['status'],'CONFIGURED');self.assertEqual(self.path.read_bytes(),after)

    def test_existing_high_is_not_decreased(self):
        self.write('[agents]\nmax_concurrent_threads_per_session=9\n')
        original=self.path.read_bytes();r=ensure(self.path)
        self.assertEqual(r['configured_limit'],9);self.assertEqual(original,self.path.read_bytes())

    def test_legacy_and_conflict(self):
        self.write('[agents]\nmax_threads=4\n');self.assertEqual(ensure(self.path)['status'],'CONFIG_UPDATED')
        self.assertEqual(self.read()['agents']['max_threads'],6)
        self.write('[agents]\nmax_threads=4\nmax_concurrent_threads_per_session=5\n');original=self.path.read_bytes()
        self.assertEqual(ensure(self.path)['status'],'CONFIGURATION_ERROR');self.assertEqual(original,self.path.read_bytes())

    def test_invalid_or_unexpected_format_is_untouched(self):
        for text in ('[agents\n', 'agents = { max_threads = 4 }\n', '[agents]\nmax_threads = "bad"\n'):
            self.write(text);before=self.path.read_bytes()
            self.assertEqual(ensure(self.path)['status'],'CONFIGURATION_ERROR');self.assertEqual(self.path.read_bytes(),before)

    def test_check_is_read_only(self):
        self.assertEqual(ensure(self.path,write=False)['status'],'CONFIGURATION_NEEDED')
        self.assertFalse(self.path.exists())

    def test_failed_replace_preserves_original(self):
        self.write('[agents]\nmax_threads=4\n');before=self.path.read_bytes()
        with patch('agent_capacity.os.replace',side_effect=OSError('denied')):
            self.assertEqual(ensure(self.path)['status'],'CONFIGURATION_ERROR')
        self.assertEqual(self.path.read_bytes(),before);self.assertEqual(list(self.path.parent.iterdir()),[self.path])

class EntryTests(unittest.TestCase):
    def test_only_formal_entry_runs_ensure(self):
        import comic_start
        import contextlib
        import io
        for action in ('prepare','receive','receive-resume'):
            args={'prepare':['prepare','--project','/tmp','--book','B','--episodes','E001'],
                  'receive':['receive','--zip','/tmp/x.zip'],
                  'receive-resume':['receive-resume','--run-root','/tmp/x']}[action]
            with patch.object(sys,'argv',['comic_start.py',*args]), \
                 patch('agent_capacity.ensure',return_value={'status':'CONFIGURED'}) as check, \
                 patch.object(comic_start,'prepare',return_value={'status':'OK'}), \
                 patch.object(comic_start,'receive',return_value={'status':'OK'}), \
                 patch.object(comic_start,'receive_resume',return_value={'status':'OK'}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(comic_start.main(),0)
                self.assertEqual(check.call_count, 0 if action == 'receive-resume' else 1)

    def test_explicit_lower_workers_only_checks(self):
        import comic_start
        import contextlib
        import io
        args=['comic_start.py','prepare','--project','/tmp','--book','B','--episodes','E001','--workers','2']
        with patch.object(sys,'argv',args), patch('agent_capacity.ensure',return_value={'status':'CONFIGURATION_NEEDED'}) as check, \
             patch.object(comic_start,'prepare',return_value={'status':'OK'}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(comic_start.main(),0);check.assert_called_once_with(write=False)

if __name__=='__main__':unittest.main()
