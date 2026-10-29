"""Explicit pause can bridge known boot epochs without charging downtime."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'))
import runtime_clock as c

def stamp(wall,mono,boot):return {'wall':wall,'mono':mono,'host':'synthetic-host','boot':boot}
class PausedEpochTests(unittest.TestCase):
    def test_paused_reboot_preserves_both_running_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);c.initialize(p,'production',14400,at=stamp(1000,0,'a'))
            for action,key,at in [('start','s',stamp(1000,0,'a')),('pause','p',stamp(1040,40,'a')),('resume','r',stamp(8000,10,'b'))]:c.event(p,action,key,at=at)
            result=c.status(p,at=stamp(8030,40,'b'))
            self.assertEqual(result['state'],'RUNNING');self.assertEqual(result['active_seconds'],70)
            self.assertEqual(result['remaining_seconds'],14330)
    def test_running_reboot_stays_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);c.initialize(p,'production',14400,at=stamp(1000,0,'a'));c.event(p,'start','s',at=stamp(1000,0,'a'))
            self.assertEqual(c.status(p,at=stamp(8000,10,'b'))['state'],'TIME_UNCERTAIN')
