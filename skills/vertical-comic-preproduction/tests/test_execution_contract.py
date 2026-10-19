"""Isolated compatibility regressions; synthetic proofs never authorize production."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from PIL import Image
from codex_reference_contract import digest,file_session
from source_adapter import adapted,verify
from reference_atlas import verify_owner
from execution_contract import state_errors,toolchain,semantic_template,semantic_errors
from rule_exception import applicable,locked_hash
from rule_memory import source_index,signature,application_errors,review_template
from identity_confirmation import confirmed,validate_manifest,execution_block
from continuity_contract import reference_usage_block
from staged_workflow import basis_errors,approval_errors
import test_staged_workflow as staged
import test_rule_memory as memory

class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def write(self,name,data):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False));return {'path':name,'sha256':digest(path)}
    def source(self):
        raw={'source_sha256':'source-sha','panel_ids':['E023-P001','E023-P002'],'locked_scripts':{'E023-P001':{'event':'原文\n保持'},'E023-P002':{'dialogue':'不改对白'}},'extras':{'original':True}}
        ref=self.write('raw.json',raw);return adapted(raw,'E023',ref)
    def test_source_map_keeps_raw_ids_text_and_order(self):
        data=self.source();self.assertEqual(verify(data,self.root,'E023'),[])
        self.assertEqual(data['panel_ids'],['P001','P002']);self.assertEqual(data['locked_scripts']['P001'],{'event':'原文\n保持'})
        self.assertEqual(data['id_mapping']['pairs'][1],{'source_panel_id':'E023-P002','panel_id':'P002'})
    def test_source_mutation_wrong_episode_and_collision_hold(self):
        data=self.source();data['locked_scripts']['P001']['event']='changed';self.assertTrue(verify(data,self.root,'E023'))
        with self.assertRaises(ValueError):adapted({'panel_ids':['E024-P001'],'locked_scripts':{'E024-P001':{}}},'E023',{})
        with self.assertRaises(ValueError):adapted({'panel_ids':['P001','E023-P001'],'locked_scripts':{'P001':{},'E023-P001':{}}},'E023',{})
    def test_source_mapping_reuses_literal_original_proof_without_expansion(self):
        data=self.source();ref=self.write('adapted.json',data);proof={'status':'APPROVED','source_kind':'user_message','quote':'SYNTHETIC ONLY','source_locator':'synthetic-unit://not-real','book_id':'UNIT','episode_id':'E023','artifacts':[data['id_mapping']['source_snapshot']]}
        original=copy.deepcopy(proof);self.assertEqual(approval_errors(proof,self.root,[ref],'UNIT','E023'),[]);self.assertEqual(proof,original)
        data['locked_scripts']['P001']['event']='changed';ref=self.write('adapted.json',data);self.assertTrue(approval_errors(proof,self.root,[ref],'UNIT','E023'))
    def atlas(self):
        Image.new('RGB',(4,4),'red').save(self.root/'a.png');Image.new('RGB',(4,4),'blue').save(self.root/'b.png')
        board=Image.new('RGB',(8,4));board.paste(Image.open(self.root/'a.png'),(0,0));board.paste(Image.open(self.root/'b.png'),(4,0));board.save(self.root/'atlas.png')
        regions=[{'subject_id':p,'purpose':'identity','asset_id':p+'-asset','source_file':{'path':f'{p.lower()}.png','sha256':digest(self.root/f'{p.lower()}.png')},'source_version':'v1','crop_rect_pixels':[0,0,4,4],'assembly_region':[i*4,0,(i+1)*4,4]} for i,p in enumerate(['A','B'])]
        ref={'path':'atlas.png','sha256':digest(self.root/'atlas.png'),'derivation_policy':'faithful_atlas_v1','reference_kind':'faithful_reference_atlas','subject_ids':['A','B'],'subject_asset_ids':{p:{'identity':p+'-asset'} for p in ['A','B']},'source_regions':regions,'reviewed':True,'reviewer':'SYNTHETIC','evidence':'Synthetic crop ownership review'}
        return ref,{p:{'sha256':digest(self.root/f'{p.lower()}.png'),'version':'v1'} for p in ['A','B']}
    def test_multi_owner_atlas_is_exact_original_pixels(self):
        ref,assets=self.atlas()
        for p in ['A','B']:self.assertEqual(verify_owner(ref,assets[p],p,'identity',self.root),[])
        basis={'reference_files':[*[r['source_file'] for r in ref['source_regions']],{'sha256':'s'}],'style':{'reference_sha256':['s'],'traits':{}} ,'book_id':'UNIT'}
        panel={'reference_images':[ref,{'sha256':'s','alias':'@STYLE'}],'style_contract':{'reference_aliases':['@STYLE'],'traits':{},'book_id':'UNIT'}}
        self.assertEqual(basis_errors(panel,basis),[])
    def test_atlas_swapped_crop_owner_and_unapproved_source_hold(self):
        ref,assets=self.atlas();ref['source_regions'][0]['assembly_region']=[4,0,8,4]
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',self.root))
        ref,assets=self.atlas();ref['source_regions'][0]['asset_id']='B-asset'
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',self.root))
        ref,assets=self.atlas();assets['A']['sha256']='unapproved'
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',self.root))
    def test_atlas_pixel_changes_resize_and_style_hold(self):
        ref,assets=self.atlas();board=Image.open(self.root/'atlas.png').convert('RGB');board.putpixel((0,0),(0,0,0));board.save(self.root/'atlas.png');ref['sha256']=digest(self.root/'atlas.png')
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',self.root))
        ref,assets=self.atlas();ref['source_regions'][0]['crop_rect_pixels']=[0,0,3,4]
        self.assertTrue(verify_owner(ref,assets['A'],'A','identity',self.root))
        self.assertTrue(verify_owner(ref,assets['A'],'A','style',self.root))
    def test_atlas_success_reused_only_in_one_unchanged_read_transaction(self):
        ref,assets=self.atlas()
        with file_session() as memo:
            self.assertEqual(verify_owner(ref,assets['A'],'A','identity',self.root),[])
            self.assertEqual(verify_owner(ref,assets['A'],'A','identity',self.root),[])
            self.assertEqual(memo['validation_runs'],1);self.assertEqual(memo['validation_hits'],1)
            altered=copy.deepcopy(ref);altered['source_regions'][0]['crop_rect_pixels']=[0,0,3,4]
            self.assertTrue(verify_owner(altered,assets['A'],'A','identity',self.root))
            self.assertTrue(verify_owner(altered,assets['A'],'A','identity',self.root))
            self.assertEqual(memo['validation_runs'],3);self.assertEqual(memo['validation_hits'],1)
        with file_session() as new:
            self.assertEqual(verify_owner(ref,assets['A'],'A','identity',self.root),[])
            self.assertEqual(new['validation_runs'],1);self.assertEqual(new['validation_hits'],0)
    def test_atlas_mutation_never_uses_old_pixel_success(self):
        ref,assets=self.atlas()
        with file_session():
            self.assertEqual(verify_owner(ref,assets['A'],'A','identity',self.root),[])
            Image.new('RGB',(4,4),'green').save(self.root/'a.png')
            errors=verify_owner(ref,assets['A'],'A','identity',self.root)
            self.assertTrue(errors);self.assertIn('CHECK_SNAPSHOT_CHANGED',str(errors))
    def test_real_identity_manifest_accepts_derived_identity_costume(self):
        f=staged.StagedTests('test_actual_style_input_is_exported');f.setUp();self.addCleanup(f.doCleanups);f.real_input()
        root=f.root;panel=f.panel;registry=f.manifest['identity_registry'];original=next(r for r in panel['reference_images'] if 'A' in r.get('subject_ids',[]));binding=panel['character_bindings'][0]
        original.update(asset_id='A-board',version='v1');binding.pop('asset_exemption')
        confirmation=copy.deepcopy(registry['appearance_states']['AP']['confirmation']);confirmation['facets']=['asset_binding']
        registry['assets']['A-board']={'book_id':'UNIT','subject_id':'A','state_id':'AP','status':'APPROVED','purposes':['identity','costume_state'],'version':'v1','sha256':original['sha256'],'confirmation':confirmation}
        source_image=Image.open(root/original['path']).convert('RGBA');source_image.save(root/'atlas.png');w,h=source_image.size
        ref=copy.deepcopy(original);ref.update(alias='@ATLAS',path='atlas.png',sha256=digest(root/'atlas.png'),derivation_policy='faithful_atlas_v1',reference_kind='faithful_reference_atlas',reviewed=True,reviewer='SYNTHETIC',evidence='exact identity/state crop',subject_asset_ids={'A':{}},source_regions=[])
        for purpose,field in [('identity','identity_asset_alias'),('costume_state','costume_asset_alias')]:
            aid=original['asset_id']
            ref['subject_asset_ids']['A'][purpose]=aid;ref['source_regions'].append({'subject_id':'A','purpose':purpose,'asset_id':aid,'source_file':{'path':original['path'],'sha256':original['sha256']},'source_version':original['version'],'crop_rect_pixels':[0,0,w,h],'assembly_region':[0,0,w,h]});binding[field]='@ATLAS'
        for b in panel['reference_bindings']:
            if b['purpose'] in ['identity','costume_state']:b['alias']='@ATLAS'
        panel['reference_images'].append(ref);panel['reference_usage_block']=reference_usage_block(panel['reference_bindings'],panel['reference_images']);panel['identity_execution_block']=execution_block(panel,registry);panel['prompt']='\n\n'.join(panel[k] for k in ('camera_execution_block','content_execution_block','identity_execution_block','reference_usage_block','style_execution_block','negative_prompt'));panel['planned_identity_assets']=[copy.deepcopy(ref)]
        self.assertEqual(validate_manifest(f.manifest,root,prompt=True),[])
        self.assertEqual(validate_manifest(f.manifest,root),[])
        from validate_preproduction import Gate
        (root/'P001/prompt.txt').write_text(panel['prompt']);f.f.write('P001/提示词.json',panel)
        shot=f.f.write('atlas-shot.json',{**f.manifest,'schema':'vertical-comic-shot-design-v1','panels':[copy.deepcopy(panel)]});packet=f.f.write('atlas-manifest.json',f.manifest)
        self.assertEqual(Gate(root,expected_panel_ids=['P001']).run(root/shot['path'],root/packet['path'])['errors'],[])
    def test_original_full_panel_scope_covers_same_episode_local_alias(self):
        evidence=self.write('evidence.json',{'synthetic':True});record={'confirmation':{'status':'CONFIRMED','scope':{'book_id':'UNIT','subject_id':'A','episode_ids':['E023'],'panel_ids':['E023-P001']},'facets':['identity'],'evidence':[evidence]}}
        self.assertTrue(confirmed(record,self.root,'UNIT','E023','P001','A',{'identity'}));self.assertFalse(confirmed(record,self.root,'UNIT','E024','P001','A',{'identity'}))
    def test_toolchain_mixed_versions_hold_legacy_unchanged(self):
        data=self.source();state={'execution_contract':'comic_execution_v2','execution_mode':'half_episode_async_v1','optimization_policy':'scoped_half_review_v1','toolchain':toolchain(),'episode_id':'E023','source_snapshot':self.write('adapted.json',data)}
        self.assertEqual(state_errors(state,self.root),[]);state['toolchain']['files'][0]['sha256']='old';self.assertTrue(state_errors(state,self.root));self.assertEqual(state_errors({},self.root),[])
    def test_finished_record_cannot_change_original_id(self):
        data=self.source();state={'execution_contract':'comic_execution_v2','execution_mode':'half_episode_async_v1','optimization_policy':'scoped_half_review_v1','toolchain':toolchain(),'episode_id':'E023','source_snapshot':self.write('adapted.json',data),'panels':[{'panel_id':'P001','source_panel_id':'E999-P999','status':'VISUAL_PASS'}]}
        self.assertTrue(state_errors(state,self.root));state['panels'][0]['source_panel_id']='E023-P001';self.assertEqual(state_errors(state,self.root),[])
    def test_semantic_template_bound_half_does_not_mark_reviewed(self):
        data=self.source();state={'book_id':'UNIT','episode_id':'E023','source_snapshot':self.write('adapted.json',data),'half_inputs':{'H001':{'visual_basis':{'path':'basis','sha256':'a'},'shot_manifest':{'path':'shots','sha256':'b'}}},'batch_plan':self.write('plan.json',{'batches':[{'batch_id':'H001','panel_ids':['P001']}]})}
        template=semantic_template(state,self.root,'H001');self.assertEqual(template['panels'][0]['status'],'UNREVIEWED');self.assertEqual(template['panel_ids'],['P001']);self.assertEqual(template['source_snapshot'],state['source_snapshot']);self.assertTrue(all(c['status']=='UNREVIEWED' for c in template['panels'][0]['checks'].values()))

    def semantic_memory_fixture(self,human_tag=True):
        import test_execution_lifecycle as lifecycle
        from scoped_inputs import half_view
        root=self.root/'episode';state,manifest,panel,shots=lifecycle.build_calibration(root)
        source=memory.library(root/'rules');index_path=root/'rules/记忆索引.json';index=json.loads(index_path.read_text())
        for rid,tag in (('MEM-005','visual_subjects_present'),('MEM-006','human_figure_visible')):
            rule=copy.deepcopy(index['rules'][0]);rule['id']=rid;rule['trigger']={'any_tags':[tag],'any_visual_terms':[]};index['rules'].append(rule)
        index_path.write_text(json.dumps(index));state['memory_source']=source;shots['memory_source']=source
        for p in shots['panels']:p['memory_tags']=['human_figure_visible'] if human_tag else []
        state['half_inputs']['H001']['shot_manifest']=lifecycle.write(root,'coverage-shots.json',shots)
        audit=semantic_template(state,root,'H001')
        for row in audit['panels']:
            row.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='synthetic actual fixture review')
            for check in row['checks'].values():check.update(status='PASS',evidence='synthetic checked scope')
            row['checks']['rule_triggers']['human_figure_visible']={'decision':'APPLIES','evidence':'synthetic approved human hand visible'}
        state['half_inputs']['H001']['semantic_audit']=lifecycle.write(root,'coverage-audit.json',audit)
        return root,state,audit,{'batch_id':'H001','panel_ids':['P001','P002']},half_view(state,'H001')

    def test_semantic_audit_checks_real_rule_versions_not_just_generic_pass(self):
        root,state,audit,batch,view=self.semantic_memory_fixture()
        self.assertEqual(semantic_errors(view,root,batch),[])
        audit['panels'][0]['checks']['rule_triggers']['matched_rules']=[]
        import test_execution_lifecycle as lifecycle
        state['half_inputs']['H001']['semantic_audit']=lifecycle.write(root,'missing-matches.json',audit)
        self.assertTrue(semantic_errors(view,root,batch))

    def test_semantic_human_applicability_catches_missing_frozen_tag(self):
        root,state,audit,batch,view=self.semantic_memory_fixture(False)
        errors=semantic_errors(view,root,batch)
        self.assertTrue(any('人体适用性' in e for e in errors),errors)

    def test_actual_qa_template_has_one_plan_without_filling_verdicts(self):
        f=staged.StagedTests('test_qa_generates_style_comparison_but_never_pass');f.setUp();self.addCleanup(f.doCleanups)
        report,out=f.f.qa_report();item=report['panels'][0];plan=item['inspection_plan']
        self.assertEqual(plan['status'],'UNREVIEWED');self.assertEqual(plan['image_sha256'],item['image_sha256']);self.assertEqual(plan['source_manifest_sha256'],report['source_manifest_sha256'])
        self.assertEqual(item['style_review']['status'],'UNREVIEWED')
        targets=[t for group in plan['groups'] for t in group['targets']]
        self.assertEqual({t['check'] for t in targets if t['record']=='dimension_review'},set(item['dimension_review']))
    def test_context_builder_uses_existing_real_approval_objects(self):
        import test_execution_lifecycle as lifecycle
        from continuity_context import build,load_context,binding_errors
        root=self.root/'episode';state,manifest,panel,shots=lifecycle.build_calibration(root)
        original=copy.deepcopy(state['half_gates']);context=build(state,root,'P002')
        path=root/'built-context.json';path.write_text(json.dumps(context));packet={**manifest,'panels':[shots['panels'][1]],'continuity_context':{'path':path.name,'sha256':digest(path)}}
        self.assertEqual(load_context(packet,root)[1],[]);self.assertEqual(binding_errors(state,root,packet,root),[]);self.assertEqual(state['half_gates'],original)
    def exception(self):
        source=memory.library(self.root/'library');rule=source_index(source)[1]['rules'][0];panel={'panel_id':'P001','locked_script':{'event_text':'床上'},'memory_tags':['person_on_bed'],'prompt':'SYNTHETIC support constraint'};app=memory.applied(source,'image_review',panel,self.root)
        value={'policy':'scoped_rule_exception_v1','rule_id':rule['id'],'rule_signature':signature(rule),'stages':['image_review'],'book_id':'UNIT','episode_ids':['E023'],'panel_ids':['E023-P001'],'status':'APPROVED','source_kind':'user_message','source_locator':'synthetic-unittest://not-real','quote':'SYNTHETIC approval fixture','locked_script_sha256':locked_hash(panel),'evidence_root':str(self.root),'artifacts':[self.write('source.json',panel['locked_script'])],'waived_checks':{'image_review':['support']},'alternative_checks':{'image_review':['approved_support_alternative']}}
        ref=self.write('exception.json',value);panel['rule_exceptions']=[ref];scope={'book_id':'UNIT','episode_id':'E023'};app['checks']['support']={'status':'USER_EXCEPTION','exception':ref,'evidence':'SYNTHETIC specified scope'};app['alternative_checks']={'approved_support_alternative':{'status':'PASS','evidence':'SYNTHETIC actual alternative check'}}
        return source,rule,panel,app,scope,value
    def test_scoped_exception_requires_alternative_and_current_image(self):
        source,rule,panel,app,scope,value=self.exception()
        self.assertEqual(application_errors(source,'image_review',panel,self.root,applications=[app],image_sha256=app['image_sha256'],scope=scope),[])
        app['alternative_checks']['approved_support_alternative']['status']='UNREVIEWED';self.assertTrue(application_errors(source,'image_review',panel,self.root,applications=[app],image_sha256=app['image_sha256'],scope=scope))
    def test_exception_cannot_expand_episode_rule_or_source(self):
        source,rule,panel,app,scope,value=self.exception();self.assertIsNone(applicable(panel,self.root,rule,'image_review',{'book_id':'UNIT','episode_id':'E024'}))
        panel['locked_script']['event_text']='changed'
        with self.assertRaises(ValueError):applicable(panel,self.root,rule,'image_review',scope)
        source,rule,panel,app,scope,value=self.exception();rule['version']='2'
        with self.assertRaises(ValueError):applicable(panel,self.root,rule,'image_review',scope)
    def test_exception_template_never_prefills_acceptance(self):
        source,rule,panel,app,scope,value=self.exception();template=review_template(source,panel,'image',artifact_root=self.root,scope=scope)[0]
        self.assertEqual(template['checks']['support']['status'],'UNREVIEWED');self.assertEqual(template['checks']['support']['expected_status'],'USER_EXCEPTION');self.assertEqual(template['alternative_checks']['approved_support_alternative']['status'],'UNREVIEWED')

if __name__=='__main__':unittest.main()
