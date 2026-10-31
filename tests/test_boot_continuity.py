import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'))
import runtime_clock as c
class BootTests(unittest.TestCase):
    def stamp(self,boot,n):return {'boot':boot,'host':'same','wall':1000+n,'mono':n}
    def test_microsecond_label_drift_does_not_drop_time(self):
        self.assertEqual(c.elapsed(self.stamp('{ sec = 123, usec = 999 }',0),self.stamp('{ sec = 123, usec = 222 }',100)),100)
    def test_old_label_to_session_identity(self):
        self.assertEqual(c.elapsed(self.stamp('darwin:123:999',0),self.stamp('darwin-session:abc:123',100)),100)
    def test_real_session_change_rejected_even_same_second(self):
        with self.assertRaises(ValueError):c.elapsed(self.stamp('darwin-session:abc:123',0),self.stamp('darwin-session:def:123',100))
    def test_label_drift_never_hides_monotonic_reset(self):
        with self.assertRaises(ValueError):c.elapsed(self.stamp('darwin:123:999',100),self.stamp('darwin:123:222',1))

    def test_stable_session_detects_reboot_with_equal_legacy_label(self):
        a={**self.stamp('darwin:123:999',0),'boot_session':'one'}
        b={**self.stamp('darwin:123:999',100),'boot_session':'two'}
        with self.assertRaises(ValueError):c.elapsed(a,b)
