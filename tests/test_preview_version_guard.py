"""A remote preview must not silently replace newer local maintenance work."""
import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'))
import update_skills
class PreviewVersionTests(unittest.TestCase):
    def test_older_preview_keeps_local_install_without_starting_installer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);home=root/'home';marker=home/'skill-bundles/vertical-comic-skills/installed.json';marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({'version':'v2026.10.27.2','files':{},'source':{'channel':'local'}}));before=marker.read_bytes()
            payload=root/'payload';payload.mkdir();(payload/'VERSION').write_text('v2026.10.27.1\n')
            with patch.object(update_skills,'unpack',return_value=payload),patch.object(update_skills,'validate_payload'),patch.object(update_skills.subprocess,'run') as invoke:
                result=update_skills.apply_archive(home,root/'unused.zip',root/'work',source={'channel':'preview','commit':'observed-test'})
            self.assertEqual(result['status'],'AHEAD_OF_PREVIEW');self.assertEqual(result['changed_files'],0)
            self.assertEqual(marker.read_bytes(),before);invoke.assert_not_called()
            self.assertFalse((payload/'release-origin.json').exists())
if __name__=='__main__':unittest.main()
