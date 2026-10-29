"""Count real byte reads and computations, not simulated sleeps or image calls."""
import os,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from codex_reference_contract import digest,file_session,read_json
from validation_pool import ValidationPool,session
from audit_cache import derived

class ContentReuseTests(unittest.TestCase):
    def test_shared_bytes_read_once_across_165_operations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'shared.json';path.write_text('{"input":"'+('x'*1024*1024)+'"}')
            pool=ValidationPool();calls=[]
            with session(pool):
                for i in range(165):
                    with file_session():
                        value=derived('approval_proof','unchanged',lambda:(calls.append(1),digest(path))[1])
            self.assertEqual(len(calls),1)
            if os.name=='nt':
                self.assertGreaterEqual(pool.statistics['byte_reads'],165)
            else:
                self.assertEqual(pool.statistics['byte_reads'],1)
                self.assertGreater(pool.statistics['byte_hits'],0)
    def test_same_size_mtime_restored_edit_invalidates_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'input';path.write_bytes(b'old');pool=ValidationPool()
            with session(pool):
                with file_session():first=digest(path)
                old=path.stat();path.write_bytes(b'new');os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
                with file_session():second=digest(path)
            self.assertNotEqual(first,second);self.assertEqual(pool.statistics['byte_reads'],2)
    def test_byte_cache_is_bounded_and_returns_exact_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool=ValidationPool(byte_limit=100)
            with session(pool):
                for i in range(35):
                    p=Path(tmp)/str(i);p.write_text('{"x":'+str(i)+'}')
                    with file_session():self.assertEqual(read_json(p),{'x':i})
                    self.assertLessEqual(pool.byte_size,100)

if __name__=='__main__':unittest.main()
