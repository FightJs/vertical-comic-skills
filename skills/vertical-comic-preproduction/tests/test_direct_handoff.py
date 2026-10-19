"""Direct handoff: current contracts, real frozen gates, synthetic human evidence."""
import copy,json,shutil,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import handoff_zip as h
import handoff_delivery as d
import test_panel_readiness as f
from runtime_snapshot import create
from continuity_context import portable_context,load_context
from production_runtime import compile_jobs,episode_bundle,EPISODE_DEFAULTS
from execution_contract import toolchain

class DirectHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.package=self.base/'package';self.package.mkdir()
        self.template=self.package/'template/E000';self.state,self.shots=f.fixture(self.template)
        s=self.state;s['episode_order']=['E000']
        # An existing full-preparation fixture; never invent production approval.
        s.update(execution_mode='episode_async_v1',optimization_policy='scoped_episode_review_v1')
        s['runtime']=copy.deepcopy(EPISODE_DEFAULTS)
        self.shots.update(execution_mode=s['execution_mode'],optimization_policy=s['optimization_policy'])
        for p in self.shots['panels']:p['state_review_policy']='merge_into_D'
        s['shot_manifest']=f.fixtures.write(self.template,'portable-shots.json',self.shots)
        audit=f.fixtures.read(self.template,s['semantic_audit']);audit['shot_manifest']=s['shot_manifest'];s['semantic_audit']=f.fixtures.write(self.template,'portable-audit.json',audit)
        s['gates']['shot_design']={**f.fixtures.approve([s['visual_basis'],s['shot_manifest'],s['semantic_audit']]),'panel_ids':['P001','P002','P003','P004']}
        for r,p in zip(s['panels'],self.shots['panels']):
            packet=f.fixtures.read(self.template,r['package_manifest']);packet.update(portability_policy='approved_relative_inputs_v1',execution_mode=s['execution_mode'],optimization_policy=s['optimization_policy'],panels=[copy.deepcopy(p)],round_context={'batch_id':'EPISODE','round_id':1,'attempt_id':r['panel_id']+'-r1'})
            if packet.get('continuity_context'):
                ctx=f.fixtures.read(self.template,packet['continuity_context']);ctx['episode_order']=['E000']
                for src in ctx['sources']:src.update(shot_manifest=s['shot_manifest'],shot_approval=s['gates']['shot_design'])
                ctx=portable_context(ctx,self.template)
                packet['continuity_context']=f.fixtures.write(self.template,r['panel_id']+'-portable-context.json',ctx)
            r['package_manifest']=f.fixtures.write(self.template,r['panel_id']+'-portable-packet.json',packet);r['shot_subset']=r['package_manifest']
        source=f.fixtures.read(self.template,s['source_snapshot'])
        from scoped_inputs import build_plan
        s['batch_plan']=f.fixtures.write(self.template,'episode-plan.json',build_plan(s,source))
        bundle=episode_bundle(s,self.template);f.approve_package(self.template,s,bundle,source['panel_ids'])
        compiled=compile_jobs(s,self.template,['P001','P002']);self.assertEqual([r['panel_id'] for r in compiled['jobs']],['P001','P002'],compiled)
        # Freeze only after all installed code/docs are stable. Rebind addresses in bind.
        snapshot=create(self.package/'runtime');s['toolchain']=toolchain()
        self.state_ref=f.fixtures.write(self.template,'00_输入审计/生产流程.json',s)
        (self.package/'交接说明.md').write_text('SYNTHETIC DIRECT TEST; no real human approval')
        (self.package/'接包生产执行要求.md').write_text('SYNTHETIC bind -> rehearse -> H001')
        (self.package/'history.json').write_text('{"synthetic":true}')
        (self.package/'binding-plan.md').write_text('SYNTHETIC portable runtime-only binding')
        template_ref=self.put('template-index.json',{'policy':d.TEMPLATE,'episode_id':'E000','root':'template/E000','state_file':self.state_ref['path'],'files':h.files(self.template)})
        self.index={'policy':h.POLICY,'delivery_policy':d.DIRECT,'package_id':'SYNTHETIC_DIRECT','book_id':s['book_id'],'episodes':[{'episode_id':'E000','panel_ids':source['panel_ids'],'halves':{'H001':['P001','P002'],'H002':['P003','P004']},'source_snapshot':self.ref('template/E000/'+s['source_snapshot']['path']),'production_source_snapshot':self.ref('template/E000/'+s['source_snapshot']['path']),'source_script':self.ref('template/E000/'+s['source_script']['path']),'visual_basis':self.ref('template/E000/'+s['visual_basis']['path']),'shot_manifest':self.ref('template/E000/'+s['shot_manifest']['path']),'runtime_manifest':self.ref('runtime/manifest.json'),'approval_evidence':self.ref('template/E000/'+s['approval_index']['path']),'path_binding_plan':self.ref('binding-plan.md'),'run_template':template_ref,'generation_review_packages':[self.ref('template/E000/'+r['path']) for r in s['generation_packages']['EPISODE']],'panels':[{'panel_id':pid,'classification':'READY_H001' if i<2 else 'PREPARED_H002','history':{'status':'NEVER_SUBMITTED','reviewer':'SYNTHETIC','conclusion':'Isolated synthetic fixture; not real calls','evidence':[self.ref('history.json')],'attempts':[],'auto_corrections_used':0,'remaining_auto_corrections':1}} for i,pid in enumerate(source['panel_ids'])]}]}
        self.save()
    def ref(self,name):return {'path':name,'sha256':h.sha(self.package/name)}
    def put(self,name,value):
        p=self.package/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2));return self.ref(name)
    def save(self):self.put(h.INDEX,self.index)
    def pipeline(self):
        z=self.base/'candidate.zip';h.pack(self.package,z)
        received=Path(h.extract(z,self.base/'extracted',reserve_bytes=0)['root'])
        bound=d.bind(received,self.base/'local-run')
        report=h.rehearse(z,received,bound['run_root'],bound['run_index'],self.base/'rehearsal',timeout=20)
        return z,received,bound,report
    def test_direct_bound_run_real_full_episode_gates_and_conditional_release(self):
        before=h.files(self.package);z,received,bound,report=self.pipeline()
        self.assertEqual(report['status'],'RELEASE_CANDIDATE',report)
        self.assertEqual(h.files(self.package),before)
        prep=json.loads((self.base/'rehearsal/E000_preparation.json').read_text());self.assertEqual(prep['prepared_panel_ids'],['P001','P002','P003','P004'])
        review=d.input_review(received,self.index)
        auth=self.base/'conditional-export.json';auth.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message','source_locator':'SYNTHETIC_NOT_REAL_USER','quote':'SYNTHETIC approve exact final inputs; export if real rehearsal passes','authorization_mode':'approved_inputs_auto_export_v1','package_id':self.index['package_id'],'approved_input_digest':review['approved_input_digest'],'after_successful_rehearsal':True}))
        out=self.base/'formal.zip';released=h.release(z,self.base/'rehearsal/演练报告.json',auth,out)
        self.assertEqual(released['status'],'RELEASED_DIRECT_DELIVERY_ZIP')
        formal=Path(h.extract(out,self.base/'received-on-another-path',reserve_bytes=0,checksum_file=Path(str(out)+'.sha256'))['root'])
        bound2=d.bind(formal,self.base/'another-local-run');self.assertNotEqual(bound['run_root'],bound2['run_root'])
        second=h.rehearse(out,formal,bound2['run_root'],bound2['run_index'],self.base/'second-rehearsal',timeout=20)
        self.assertEqual(second['status'],'RELEASE_CANDIDATE',second);self.assertEqual(second['image_calls'],0)
    def test_one_ready_cannot_hide_later_hold_or_unknown(self):
        row=self.index['episodes'][0]['panels'][-1];row.update(classification='HOLD',blockers=[{'reason':'budget unknown','owner':'front','resolution':'reconcile'}])
        self.assertTrue(d.closure(self.package,self.index))
        row['classification']='WAIT_DEPENDENCY';row['production_dependency']={'kind':'prior_image','episode_id':'E000','panel_id':'P001','completion_plan':self.ref('history.json')}
        row['history']['status']='UNRESOLVED';self.assertTrue(d.closure(self.package,self.index))
    def test_only_real_internal_forward_dependencies_can_remain(self):
        row=self.index['episodes'][0]['panels'][-1];row.update(classification='WAIT_DEPENDENCY',production_dependency={'kind':'prior_image','episode_id':'E000','panel_id':'P001','completion_plan':self.ref('history.json')})
        self.assertEqual(d.closure(self.package,self.index),[])
        row['production_dependency']['panel_id']='P999';self.assertTrue(d.closure(self.package,self.index))
    def test_changed_prompt_inputs_change_conditional_export_digest(self):
        old=d.input_review(self.package,self.index)['approved_input_digest']
        p=self.package/self.index['episodes'][0]['generation_review_packages'][0]['path'];p.write_text(p.read_text()+' ')
        with self.assertRaises(ValueError):d.input_review(self.package,self.index)
        self.index['episodes'][0]['generation_review_packages'][0]['sha256']=h.sha(p)
        self.assertNotEqual(d.input_review(self.package,self.index)['approved_input_digest'],old)
    def test_portable_signature_stable_on_move_but_pixels_remain_bound(self):
        from production_runtime import package_signature
        packet=f.fixtures.read(self.template,self.state['panels'][0]['package_manifest'])
        first=package_signature(packet,self.template)
        elsewhere=self.base/'copied-template';shutil.copytree(self.template,elsewhere)
        self.assertEqual(first,package_signature(packet,elsewhere))
        from PIL import Image
        image=elsewhere/first['references'][0]['path'];Image.new('RGB',(5,5),'red').save(image)
        with self.assertRaises(ValueError):package_signature(packet,elsewhere)
        self.assertEqual(first['portability_policy'],'approved_relative_inputs_v1')
    def test_handoff_scope_and_history_are_bound_by_conditional_authorization(self):
        old=d.input_review(self.package,self.index)['approved_input_digest']
        self.index['episodes'][0]['panels'][0]['history']['conclusion']='changed budget audit conclusion'
        self.assertNotEqual(old,d.input_review(self.package,self.index)['approved_input_digest'])
    def test_formal_release_rejects_hidden_hold_even_if_another_panel_is_ready(self):
        row=self.index['episodes'][0]['panels'][-1];row.update(classification='HOLD',blockers=[{'reason':'budget unresolved','owner':'front','resolution':'reconcile'}]);self.save()
        z=self.base/'candidate.zip';h.pack(self.package,z)
        report=self.base/'fake-report.json';report.write_text('{}');auth=self.base/'fake-auth.json';auth.write_text('{}')
        with self.assertRaisesRegex(ValueError,'HOLD未关闭'):h.release(z,report,auth,self.base/'should-not-exist.zip')
        self.assertFalse((self.base/'should-not-exist.zip').exists())

    def test_rule_memory_same_bytes_relocate_without_reading_old_root(self):
        import test_rule_memory as memory_fixture
        from rule_memory import binding_errors,source_index
        original=memory_fixture.library(self.base/'origin-memory')
        original['index_sha256']=h.sha(Path(original['root'])/original['index'])
        new_root=self.base/'moved-memory';shutil.copytree(original['root'],new_root)
        moved={**original,'root':str(new_root)}
        shutil.rmtree(original['root'])
        self.assertEqual(binding_errors({'memory_source':moved},shots={'memory_source':original}),[])
        source_index(moved)
        (new_root/'记忆索引.json').write_text('{}')
        self.assertTrue(binding_errors({'memory_source':moved},shots={'memory_source':original}))

    def test_template_mutation_does_not_bind_and_does_not_create_run(self):
        (self.template/'unexpected.txt').write_text('not frozen')
        with self.assertRaisesRegex(ValueError,'清单'):d.bind(self.package,self.base/'bad-run')
        self.assertFalse((self.base/'bad-run').exists())

if __name__=='__main__':unittest.main()
