"""Minimal publication with actual synthetic PNGs; no image service."""
import copy,io,json,os,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import lean_delivery as lean
import delivery_contract as dc
import delivery_publish as publish


def fixture(root,count=4):
    episode=root/'E001';audit=episode/'00_输入审计';audit.mkdir(parents=True)
    data=io.BytesIO();Image.frombytes('RGB',(96,96),os.urandom(96*96*3)).save(data,format='PNG')
    image=episode/'actual.png';image.write_bytes(data.getvalue())
    ref={'path':'actual.png','sha256':dc.digest(image)}
    source=episode/'source.json';ids=[f'P{i:03}' for i in range(count)]
    source.write_text(json.dumps({'panel_ids':ids,'id_mapping':{'pairs':[{'panel_id':p,'source_panel_id':p} for p in ids]}}))
    state={'book_id':'SYNTHETIC','episode_id':'E001','source_snapshot':{'path':'source.json','sha256':dc.digest(source)},'panels':[]}
    for p in ids:
        row={'panel_id':p,'source_panel_id':p,'status':'VISUAL_PASS','attempt_id':p+'-R1','output':ref,
            'qa_report':{'path':'SYNTHETIC-observation-'+p,'sha256':'a'*64},
            'adoption':{'attempt_id':p+'-R1','decision':{'path':'SYNTHETIC-decision-'+p,'sha256':'b'*64}}}
        state['panels'].append(row);lean.adopt(state,row,{'action':'complete','issues':[]})
    sp=audit/'生产流程.json';sp.write_text(json.dumps(state))
    task=root/'task';identity=dc.initialize(task,'production',[sp],completion_profile=lean.PROFILE)
    return state,sp,task,identity,image


class LeanDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.state,self.sp,self.task,self.identity,self.image=fixture(self.root)
    def save(self):self.sp.write_text(json.dumps(self.state))
    def publish(self):return publish.publish_production(self.identity['path'],self.task/'out')
    def test_exact_images_csv_no_creative_gate_and_one_readback(self):
        with patch('panel_delivery.gate',side_effect=AssertionError('no gate')),patch('panel_delivery.build',side_effect=AssertionError('no build')):
            r=self.publish();value=dc.load_identity(self.identity['path'])
            with patch.object(lean,'inventory',side_effect=AssertionError('no rebuilding at finish')):
                dc.assert_completion(value,self.task/'out'/publish.REPORT,r['artifacts'][0]['path'])
            self.assertEqual(r['lean_timing']['zip_readback_passes'],1)
            self.assertEqual(r['lean_timing']['source_image_read_bytes'],4*self.image.stat().st_size)
            with zipfile.ZipFile(r['artifacts'][0]['path']) as z:
                self.assertEqual(set(z.namelist()),{'E001/'+x['panel_id']+'.png' for x in self.state['panels']}|{lean.CSV})
                self.assertEqual(z.read('E001/P000.png'),self.image.read_bytes())
            self.assertEqual(self.publish(),r)
    def test_automatic_finish_no_legacy_progress_or_review(self):
        import production_progress as progress,task_coordination as tc
        display=self.task/'00_显示进度';progress.initialize(display,'production',[self.sp]);tc.initialize(self.task/'00_任务协调',display)
        with patch('panel_delivery.gate',side_effect=AssertionError('no gate')),patch.object(progress,'episode',side_effect=AssertionError('no evidence graph')):
            r=lean.finalize(self.identity['path'],self.task/'out')
            self.assertEqual(r['status'],'DELIVERY_FINISHED');self.assertEqual(progress.refresh(display)['percent'],100)
        self.image.write_bytes(b'changed')
        self.assertLess(progress.refresh(display)['percent'],100)
    def test_missing_or_changed_image_rejected(self):
        self.image.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'IMAGE_CHANGED'):self.publish()
        self.assertFalse((self.task/'out').exists())
    def test_changed_qa_adoption_or_unknown_not_completed(self):
        for key,value in [('qa_report',{}),('status','RESULT_UNKNOWN'),('adoption',{})]:
            old=copy.deepcopy(self.state);self.state['panels'][0][key]=value;self.save()
            with self.assertRaisesRegex(ValueError,'MATERIAL|UNFINISHED'):lean.inventory(dc.load_identity(self.identity['path']))
            self.state=old;self.save()
    def test_duplicate_mapping_and_unobserved_material_rejected(self):
        self.state['delivery_materials'].clear();self.save()
        with self.assertRaisesRegex(ValueError,'MATERIAL'):self.publish()
    def test_archive_corruption_detected_on_completion(self):
        r=self.publish();path=Path(r['artifacts'][0]['path']);data=bytearray(path.read_bytes());data[55]^=1;path.write_bytes(data)
        with self.assertRaisesRegex(ValueError,'ZIP_CHANGED'):dc.assert_completion(dc.load_identity(self.identity['path']),self.task/'out'/publish.REPORT,path)
    def test_corrupt_archive_rebuilt_without_content_review(self):
        first=self.publish();path=Path(first['artifacts'][0]['path']);path.write_bytes(b'corrupt zip')
        with patch('panel_delivery.gate',side_effect=AssertionError('no gate')),patch('panel_delivery.build',side_effect=AssertionError('no build')):
            second=self.publish()
        self.assertEqual(second['content_validation']['image_count'],4)
        self.assertEqual(len(list(self.task.glob('out.superseded-*'))),1)
        with zipfile.ZipFile(second['artifacts'][0]['path']) as archive:self.assertIsNone(archive.testzip())
    def test_corrected_file_can_retry_pack_without_new_creative_state(self):
        original=self.image.read_bytes();self.image.write_bytes(b'incorrect')
        with self.assertRaises(ValueError):self.publish()
        self.image.write_bytes(original)
        self.assertEqual(self.publish()['content_validation']['image_count'],4)
    def test_wrong_source_mapping_and_missing_image(self):
        source=self.sp.parent.parent/'source.json';value=json.loads(source.read_text())
        value['id_mapping']['pairs'][1]['source_panel_id']='P000';source.write_text(json.dumps(value))
        self.state['source_snapshot']['sha256']=dc.digest(source);self.save()
        with self.assertRaisesRegex(ValueError,'SOURCE_MAPPING'):self.publish()
        value['id_mapping']['pairs'][1]['source_panel_id']='P001';source.write_text(json.dumps(value))
        self.state['source_snapshot']['sha256']=dc.digest(source);self.save();self.image.unlink()
        with self.assertRaisesRegex(ValueError,'IMAGE_MISSING'):self.publish()
    def test_pack_uses_saved_readability_without_image_decode(self):
        with patch('PIL.Image.open',side_effect=AssertionError('no final decode')):
            self.publish()

    def test_authorized_gap_csv_keeps_source_and_reason(self):
        row=self.state['panels'][0];row.pop('adoption');row.pop('output');row['status']='CALL_FAILED'
        row['content_refusal_delivery']={'path':'already-validated-refusal','sha256':'c'*64}
        lean.gap(self.state,row,'CONTENT_REFUSED','moderation_blocked: preserved original error');self.save()
        r=self.publish();self.assertFalse(r['content_validation']['images_complete'])
        with zipfile.ZipFile(r['artifacts'][0]['path']) as z:
            self.assertEqual(len(z.namelist()),4);self.assertIn('moderation_blocked',z.read(lean.CSV).decode('utf-8-sig'))
    def test_real_historical_adoption_imported_once(self):
        from test_delivery_publish import complete_fixture
        h,state,sp=complete_fixture(self)
        lean.import_materials(state,h.root);sp.write_text(json.dumps(state))
        identity=dc.initialize(h.root.parent/'lean-real','production',[sp],completion_profile=lean.PROFILE)
        with patch('panel_delivery.build',side_effect=AssertionError('no full rebuild')):
            r=publish.publish_production(identity['path'],h.root.parent/'lean-output')
        self.assertTrue(r['content_validation']['images_complete'])


if __name__=='__main__':unittest.main()
