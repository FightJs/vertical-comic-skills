"""Isolated synthetic handoffs; real frozen compiler, no image-service calls."""
import copy,json,shutil,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import handoff_zip as h
from runtime_snapshot import create
import test_production_runtime as runtime_fixtures

class HandoffZipTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.root=self.base/'候选包';self.root.mkdir()
        (self.root/'交接说明.md').write_text('SYNTHETIC TEST ONLY; no real approval')
        (self.root/'接包生产执行要求.md').write_text('SYNTHETIC test reception steps')
        self.put('source.json',{'panel_ids':['P001']});self.put('proof.json',{'test':'SYNTHETIC; not human evidence'})
        ref=self.ref('proof.json')
        self.index={'policy':h.POLICY,'package_id':'TEST_ONLY','book_id':'UNIT','episodes':[{'episode_id':'E000','panel_ids':['P001'],'halves':{'H001':['P001'],'H002':[]},'source_snapshot':self.ref('source.json'),'runtime_manifest':ref,'approval_evidence':ref,'path_binding_plan':ref,'panels':[{'panel_id':'P001','classification':'READY_H001','history':{'status':'NEVER_SUBMITTED','reviewer':'SYNTHETIC','conclusion':'Isolated synthetic fixture; not production history','evidence':[ref],'attempts':[],'auto_corrections_used':0,'remaining_auto_corrections':1}}]}]}
        self.save()
    def put(self,name,value):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value));return self.ref(name)
    def ref(self,name):return {'path':name,'sha256':h.sha(self.root/name)}
    def save(self):self.put(h.INDEX,self.index)
    def candidate(self):
        self.save();out=self.base/'candidate.zip';h.pack(self.root,out);return out
    def extracted(self,z):return Path(h.extract(z,self.base/'fresh',reserve_bytes=0)['root'])
    def test_roundtrip_unicode_no_original_mutation(self):
        self.put('a/file.json',{'nested':True});self.put('a.b',{'flat':True})
        before=h.files(self.root);z=self.candidate();received=self.extracted(z)
        self.assertEqual(h.files(self.root),before);self.assertEqual(h.files(received),before)
        self.assertFalse((self.root/h.INVENTORY).exists())
    def test_external_sha256_checked_before_extraction(self):
        z=self.candidate();side=self.base/'candidate.zip.sha256';side.write_text('0'*64+'  candidate.zip\n')
        with self.assertRaisesRegex(ValueError,'外部SHA256'):h.extract(z,self.base/'bad-sha',reserve_bytes=0,checksum_file=side)
        self.assertFalse((self.base/'bad-sha').exists())
        side.write_text(h.sha(z)+'  candidate.zip\n');h.extract(z,self.base/'correct-sha',reserve_bytes=0,checksum_file=side)

    def test_self_contained_marker_alone_cannot_turn_candidate_into_release(self):
        z=self.candidate();fake=self.base/'fake-formal.zip'
        with zipfile.ZipFile(z) as original,zipfile.ZipFile(fake,'w') as target:
            for info in original.infolist():
                body=original.read(info)
                if info.filename.endswith('/'+h.INVENTORY):
                    manifest=json.loads(body);manifest['container_policy']='self_contained_handoff_v1'
                    body=json.dumps(manifest).encode()
                target.writestr(info,body)
        with self.assertRaisesRegex(ValueError,'正式发布证据'):h.check_delivery_archive(fake)

    def test_missing_reference_rejected(self):
        (self.root/'proof.json').unlink()
        with self.assertRaises(ValueError):self.candidate()
    def test_unknown_history_not_ready_and_budget_not_reset(self):
        row=self.index['episodes'][0]['panels'][0];hist=row['history']
        hist.update(status='UNRESOLVED',attempts=[{'attempt_id':'unknown1','kind':'auto_correction','status':'UNKNOWN','evidence':[self.ref('proof.json')]}])
        self.save()
        with self.assertRaisesRegex(ValueError,'预算'):h.audit_index(self.root)
        hist.update(auto_corrections_used=1,remaining_auto_corrections=0);self.save()
        with self.assertRaisesRegex(ValueError,'未知历史'):h.audit_index(self.root)
        row.update(classification='HOLD',blockers=[{'reason':'UNKNOWN','owner':'front-end','resolution':'recover actual terminal result'}]);self.save();h.audit_index(self.root)
    def test_completed_attempt_missing_actual_output_rejected(self):
        hist=self.index['episodes'][0]['panels'][0]['history'];hist.update(status='RECONCILED',attempts=[{'attempt_id':'one','kind':'initial','status':'COMPLETED','evidence':[self.ref('proof.json')]}]);self.save()
        with self.assertRaises(ValueError):h.audit_index(self.root)
    def test_changed_source_order_and_half_rejected(self):
        self.index['episodes'][0]['halves']['H001']=[];self.save()
        with self.assertRaisesRegex(ValueError,'半话'):h.audit_index(self.root)
    def test_source_adaptation_ids_rejected(self):
        self.index['episodes'][0]['source_snapshot']=self.put('other.json',{'panel_ids':['WRONG']});self.save()
        with self.assertRaisesRegex(ValueError,'源快照格序'):h.audit_index(self.root)
    def test_path_escape_duplicate_case_and_symlink_rejected(self):
        for names in [('root/../bad',),('root/A','root/a')]:
            with self.subTest(names=names):
                z=self.base/'bad.zip'
                with zipfile.ZipFile(z,'w') as f:
                    for n in names:f.writestr(n,'bad')
                with zipfile.ZipFile(z) as f:
                    with self.assertRaises(ValueError):h.zip_inventory(f)
        (self.root/'link').symlink_to(self.root/'proof.json')
        with self.assertRaises(ValueError):self.candidate()
    def test_damaged_inventory_and_no_overwrite(self):
        z=self.candidate()
        with self.assertRaises(ValueError):h.pack(self.root,z)
        received=self.extracted(z)
        with self.assertRaises(ValueError):h.extract(z,received.parent,reserve_bytes=0)
        with zipfile.ZipFile(z,'a') as f:f.writestr(self.root.name+'/unlisted','bad')
        with self.assertRaises(ValueError):h.extract(z,self.base/'tamper',reserve_bytes=0)
    def real_fixture(self):
        fixture=runtime_fixtures.RuntimeTests('test_bulk_same_verdict_as_full_single_panel_gate_and_real_arguments');fixture.setUp();self.addCleanup(fixture.doCleanups)
        state=fixture.scoped()
        # Explicit synthetic historical call/output evidence, never actual human evidence.
        shutil.copytree(fixture.root,self.root/'run-template')
        hist=self.index['episodes'][0]['panels'][0]['history'];hist.update(status='RECONCILED',attempts=[{'attempt_id':'SYNTHETIC-r1','kind':'initial','status':'COMPLETED','evidence':[self.ref('run-template/req.json'),self.ref('run-template/res.json')],'output':self.ref('run-template/synthetic-output.png'),'qa':self.ref('run-template/qa.json')}])
        snapshot=create(self.root/'runtime')
        self.index['episodes'][0]['runtime_manifest']={'path':'runtime/manifest.json','sha256':snapshot['sha256']}
        z=self.candidate();received=self.extracted(z)
        run=self.base/'run';shutil.copytree(received/'run-template',run)
        state['runtime_snapshot']={'path':str(received/'runtime/manifest.json'),'sha256':snapshot['sha256']}
        (run/'00_输入审计').mkdir();(run/'00_输入审计/state.json').write_text(json.dumps(state));(run/'mapping.json').write_text(json.dumps({'test':'SYNTHETIC relocation mapping; relative original inputs'}))
        index=self.base/'run-index.json';index.write_text(json.dumps({'package_id':'TEST_ONLY','episodes':[{'episode_id':'E000','state':'00_输入审计/state.json','binding_evidence':{'path':'mapping.json','sha256':h.sha(run/'mapping.json')}}]}))
        return z,received,run,index,state
    def test_real_frozen_gate_relocated_then_formal_zip_roundtrip(self):
        z,received,run,index,state=self.real_fixture();before=h.files(received)
        result=h.rehearse(z,received,run,index,self.base/'report',timeout=15)
        self.assertEqual(result['status'],'RELEASE_CANDIDATE',result);self.assertEqual(result['ready_h001_count'],1)
        self.assertEqual(result['image_calls'],0);self.assertEqual(h.files(received),before)
        raw=json.loads((self.base/'report/E000_stdout.json').read_text());self.assertFalse(raw['candidate_only']);self.assertEqual(len(raw['jobs']),1)
        for path in raw['jobs'][0]['arguments']['referenced_image_paths']:self.assertTrue(Path(path).resolve().is_relative_to(run.resolve()))
        report=self.base/'report/演练报告.json';approval=self.base/'approval.json';approval.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message','source_locator':'SYNTHETIC_NOT_REAL','quote':'SYNTHETIC TEST ONLY','candidate_zip_sha256':h.sha(z),'rehearsal_report_sha256':h.sha(report)}))
        with self.assertRaisesRegex(ValueError,'direct_delivery_v2'):h.release(z,report,approval,self.base/'formal.zip')

    def test_declared_ready_but_real_gate_hold_prevents_release(self):
        z,received,run,index,state=self.real_fixture();state['holds']=['SYNTHETIC system HOLD'];(run/'00_输入审计/state.json').write_text(json.dumps(state))
        result=h.rehearse(z,received,run,index,self.base/'report',timeout=15)
        self.assertEqual(result['status'],'HOLD',result);self.assertEqual(result['ready_h001_count'],0)
        approval=self.base/'approval.json';approval.write_text('{}')
        with self.assertRaises(ValueError):h.release(z,self.base/'report/演练报告.json',approval,self.base/'formal.zip')
    def test_old_machine_runtime_path_rejected_before_gate(self):
        z,received,run,index,state=self.real_fixture();state['runtime_snapshot']['path']='/old/machine/manifest.json';(run/'00_输入审计/state.json').write_text(json.dumps(state))
        result=h.rehearse(z,received,run,index,self.base/'report',timeout=15)
        self.assertEqual(result['status'],'HOLD');self.assertIn('未绑定',str(result['results']))
    def test_local_state_cannot_switch_to_another_source_order(self):
        z,received,run,index,state=self.real_fixture()
        changed=run/'different-source.json';changed.write_text(json.dumps({'panel_ids':['P001','P999']}))
        state['source_snapshot']={'path':changed.name,'sha256':h.sha(changed)}
        (run/'00_输入审计/state.json').write_text(json.dumps(state))
        result=h.rehearse(z,received,run,index,self.base/'report',timeout=15)
        self.assertEqual(result['status'],'HOLD');self.assertIn('生产源序',str(result['results']))

    def test_mismatched_export_approval_rejected(self):
        z=self.candidate();report=self.base/'report.json';report.write_text(json.dumps({'policy':h.POLICY,'source_kind':'observed_frozen_gate_rehearsal','status':'RELEASE_CANDIDATE','originals_unchanged':True,'image_calls':0,'candidate_zip_sha256':h.sha(z),'ready_h001_count':1,'results':[{'status':'REHEARSED','errors':[]}]}));approval=self.base/'approval.json';approval.write_text('{}')
        with self.assertRaises(ValueError):h.release(z,report,approval,self.base/'formal.zip')

if __name__=='__main__':unittest.main()
