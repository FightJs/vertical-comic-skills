import sys,unittest,tempfile,zipfile,os,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import handoff_transport as t
class TransportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.src=self.root/'source.zip';self.data=os.urandom(120000)
  with zipfile.ZipFile(self.src,'w') as z:
   z.writestr('包/a.png',self.data);z.writestr('包/b.png',self.data)
  for name in ['check_delivery_archive','check_delivery_directory']:
   p=patch('handoff_zip.'+name,return_value={});p.start();self.addCleanup(p.stop)
 def export(self,limit=t.LIMIT):return t.export(self.src,self.root/'out',limit)
 def test_single_exact(self):
  d=self.export();self.assertEqual(d['unique_objects'],1)
  x=t.restore(self.root/'out'/d['files'][0]['path'],self.root/'restore')
  self.assertEqual((Path(x['root'])/'a.png').read_bytes(),self.data)
  self.assertEqual((Path(x['root'])/'b.png').read_bytes(),self.data)
  t.check_receipt(self.root/'out/运输验证.json',self.src)
 def test_split_renamed(self):
  d=self.export(65536);self.assertGreater(len(d['files']),1)
  p=self.root/'out'/d['files'][0]['path'];q=p.with_name('微信改名.zip');p.rename(q)
  t.restore(q,self.root/'restore')
 def test_missing(self):
  d=self.export(65536);(self.root/'out'/d['files'][-1]['path']).unlink()
  with self.assertRaisesRegex(ValueError,'缺少分卷'):t.restore(self.root/'out'/d['files'][0]['path'],self.root/'restore')
 def test_duplicate(self):
  import shutil
  d=self.export(65536);p=self.root/'out'/d['files'][0]['path'];shutil.copyfile(p,p.with_name('副本.zip'))
  with self.assertRaisesRegex(ValueError,'重复分卷'):t.restore(p,self.root/'restore')
 def test_receipt_change(self):
  d=self.export();(self.root/'out'/d['files'][0]['path']).write_bytes(b'bad')
  with self.assertRaises(ValueError):t.check_receipt(self.root/'out/运输验证.json',self.src)
if __name__=='__main__':unittest.main()
