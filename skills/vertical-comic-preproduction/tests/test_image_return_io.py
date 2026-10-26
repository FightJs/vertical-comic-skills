"""Returned byte recovery; no image service or production state."""
import base64,io,json,sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from image_return_io import persist,hint_paths

class ReturnedBytesTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        b=io.BytesIO();Image.new('RGB',(9,16),'blue').save(b,format='PNG');self.png=b.getvalue()
    def raw(self,value):
        p=self.root/'actual.json';p.write_text(json.dumps(value,ensure_ascii=False));return p
    def url(self,data=None):return 'data:image/png;base64,'+base64.b64encode(data or self.png).decode()
    def test_two_windows_drives_unicode_spaces_and_newlines(self):
        path=r'C:\工作目录\有 空格\图片.png'
        hint='Generated images are saved to C:\\目录 as '+path+' by default.\nOther text'
        self.assertEqual(hint_paths(hint),[path]);self.assertEqual(hint_paths('https://host/image.png'),[])
    def test_data_only_and_identical_retry_preserve_exact_raw_bytes(self):
        raw=self.raw({'image_url':self.url()});before=raw.read_bytes()
        a=persist(raw,self.root/'saved');b=persist(raw,self.root/'saved')
        self.assertEqual(a,b);self.assertEqual((self.root/'saved/raw-return.json').read_bytes(),before)
        self.assertEqual(a['visual_review'],'UNREVIEWED');self.assertEqual(a['image_calls'],0)
    def test_local_path_with_spaces_and_quotes(self):
        image=self.root/'人物 有空格.png';image.write_bytes(self.png)
        result=persist(self.raw({'output_hint':'Saved as "'+str(image)+'".'}),self.root/'saved')
        self.assertEqual(len(result['outputs']),1)
    def test_full_byte_disagreement_is_rejected_and_raw_retained(self):
        b=io.BytesIO();Image.new('RGB',(9,16),'red').save(b,format='PNG')
        image=self.root/'other.png';image.write_bytes(b.getvalue())
        with self.assertRaisesRegex(ValueError,'BYTES_MISMATCH'):
            persist(self.raw({'image_url':self.url(),'local_paths':[str(image)]}),self.root/'saved')
        self.assertTrue((self.root/'saved/raw-return.json').exists())
    def test_multiple_images_need_selection_and_can_resume(self):
        b=io.BytesIO();Image.new('RGB',(9,16),'red').save(b,format='PNG')
        raw=self.raw({'results':[{'image_url':self.url()},{'image_url':self.url(b.getvalue())}]})
        with self.assertRaisesRegex(ValueError,'MULTIPLE'):persist(raw,self.root/'saved')
        out=persist(raw,self.root/'saved',selected_index=1);self.assertEqual(len(out['outputs']),2)
    def test_http_only_empty_and_malformed_return_preserve_raw(self):
        for i,value in enumerate([{'image_url':'https://host/image.png'},{}, {'image_url':'data:image/png;base64,not_valid'}]):
            with self.assertRaises(ValueError):persist(self.raw(value),self.root/str(i))
            self.assertTrue((self.root/str(i)/'raw-return.json').exists())
    def test_changed_return_cannot_overwrite_evidence(self):
        raw=self.raw({'image_url':self.url()});persist(raw,self.root/'saved')
        raw=self.raw({'image_url':self.url(),'new':'changed'})
        with self.assertRaisesRegex(ValueError,'CONFLICT'):persist(raw,self.root/'saved')

if __name__=='__main__':unittest.main()
