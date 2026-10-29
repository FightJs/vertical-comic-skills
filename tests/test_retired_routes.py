"""Release and update boundaries for removed production engines."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import sync_skills as sync

class RetiredRouteTests(unittest.TestCase):
    def test_retired_executable_and_import_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts=Path(tmp)/'vertical-comic-preproduction/scripts';scripts.mkdir(parents=True)
            (scripts/'runtime_capabilities.json').write_text(json.dumps({'production_executor':'whole_episode_light_v1'}))
            path=scripts/'half_workflow.py';path.write_text('pass')
            with self.assertRaisesRegex(ValueError,'Retired production engine'):sync.check_production_routes(Path(tmp))
            path.unlink();path=scripts/'current.py';path.write_text('from batch_workflow import input_errors')
            with self.assertRaisesRegex(ValueError,'Retired production import'):sync.check_production_routes(Path(tmp))
            path.write_text('from production_evidence import input_errors');sync.check_production_routes(Path(tmp))

    def test_update_removes_tracked_engine_and_keeps_backup_and_user_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);sync.install(home)
            old=home/'skills/vertical-comic-preproduction/scripts/half_workflow.py'
            original=b'# synthetic retired engine, never invoked\n';old.write_bytes(original)
            marker=home/'skill-bundles/vertical-comic-skills/installed.json'
            record=json.loads(marker.read_text());record['files'][old.relative_to(home).as_posix()]=hashlib.sha256(original).hexdigest()
            marker.write_text(json.dumps(record))
            user=home/sync.USER_ADDITIONS/'personal.txt';user.write_bytes(b'personal content')
            result=sync.install(home)
            self.assertFalse(old.exists())
            self.assertEqual((Path(result['backup'])/old.relative_to(home)).read_bytes(),original)
            self.assertEqual(user.read_bytes(),b'personal content')
