"""Scoped preparation using actual shared gates and isolated synthetic artifacts."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).resolve().parent)]
import test_execution_lifecycle as fixtures
from codex_reference_contract import checked_file,read_json,digest,file_session
from scoped_inputs import PREPARATION,approval_for
from execution_contract import CHECKS,toolchain
from production_runtime import DEFAULTS,episode_bundle,package_review_errors,compile_jobs
from panel_readiness import POLICY,report,compatible_collection,review_context
from continuity_context import load_context
from staged_workflow import evaluate

def fixture(root,candidate=False):
    s,m,p,old=fixtures.build_calibration(root)
    source=fixtures.read(root,s['source_snapshot']);order=source['panel_ids'];panels=[]
    from repair_prompt_package import camera_block,content_block
    from identity_confirmation import execution_block
    from continuity_contract import reference_usage_block
    for i,pid in enumerate(order):
        row=copy.deepcopy(old['panels'][min(i,1)]);prior=row['panel_id'];row.update(panel_id=pid,source_panel_id='E000-'+pid,calibration_anchor=False,camera_position={'x':i+1,'y':2,'z':1.6},camera_view_id='CAM'+str(i+1),camera_view_signature='SYNTHETIC proven camera '+str(i+1),adjacent_change_reason='SYNTHETIC visible camera position changes',prompt_file=pid+'/prompt.txt',panel_json_file=pid+'/提示词.json')
        row['state_review_policy']='merge_into_C' if i<2 else 'merge_into_D'
        if i:
            row['continuity_contract']['scene'].update(previous_panel_id=order[i-1],mode='same_scene_new_view')
            row['continuity_contract']['qa_requirements']['framing']['subject_ids']=[pid]
        for b in row['reference_bindings']:
            if b['subject_ids']==[prior]:b['subject_ids']=[pid]
        for b in row['character_bindings']:b['asset_exemption']['panel_ids']=[pid]
        row['scene_binding']['asset_exemption']['panel_ids']=[pid]
        row['camera_execution_block']=camera_block(row,row,None,None);row['content_execution_block']=content_block(row,row);row['identity_execution_block']=execution_block(row,m['identity_registry']);row['reference_usage_block']=reference_usage_block(row['reference_bindings'],row['reference_images'])
        row['prompt']='\n\n'.join(row[k] for k in ('camera_execution_block','content_execution_block','identity_execution_block','reference_usage_block','style_execution_block','negative_prompt'))
        panels.append(row)
    metadata={**m,'preparation_policy':PREPARATION,'readiness_policy':POLICY,'source_snapshot':s['source_snapshot']}
    shots={**metadata,'panels':panels};shot_ref=fixtures.write(root,'full-shots.json',shots)
    s.update(preparation_policy=PREPARATION,readiness_policy=POLICY,runtime=copy.deepcopy(DEFAULTS),visual_basis=s['half_inputs']['H001']['visual_basis'],shot_manifest=shot_ref,episode_order=['E999','E000']);s.pop('half_inputs');s.pop('half_gates')
    audit={'policy':'semantic_audit_v1','book_id':s['book_id'],'episode_id':s['episode_id'],'source_snapshot':s['source_snapshot'],'visual_basis':s['visual_basis'],'shot_manifest':shot_ref,'panel_ids':order,'panels':[{'panel_id':pid,'status':'REVIEWED','reviewer':'SYNTHETIC','evidence':'Synthetic local design review, not actual user approval','checks':{k:{'status':'PASS','evidence':'Synthetic checked local design'} for k in CHECKS}} for pid in order]}
    s['semantic_audit']=fixtures.write(root,'full-audit.json',audit)
    s['gates']['visual_basis']=fixtures.approve([s['source_script'],s['source_snapshot'],s['visual_basis']])
    s['gates']['shot_design']=None if candidate else {**fixtures.approve([s['visual_basis'],shot_ref,s['semantic_audit']]),'panel_ids':order}
    for i,row in enumerate(panels):
        pid=row['panel_id'];record=s['panels'][i];packet={**metadata,'panels':[copy.deepcopy(row)],'round_context':{'batch_id':'H001' if i<2 else 'H002','round_id':1,'attempt_id':pid+'-r1'}}
        if i:
            source_ref={'root':str(root),'episode_id':s['episode_id'],'source_script':s['source_script'],'source_snapshot':s['source_snapshot'],'visual_basis':s['visual_basis'],'shot_manifest':shot_ref,'visual_approval':s['gates']['visual_basis'],'shot_approval':s['gates']['shot_design']}
            context={'policy':'approved_shot_context_v1','book_id':s['book_id'],'current':{'episode_id':s['episode_id'],'panel_id':pid},'episode_order':s['episode_order'],'sources':[source_ref],'entries':[{'source':0,'panel_id':p} for p in order[:i]]}
            packet['continuity_context']=fixtures.write(root,pid+'-context.json',context)
        (root/pid).mkdir(exist_ok=True);(root/row['prompt_file']).write_text(row['prompt'], encoding='utf-8', newline='\n');fixtures.write(root,row['panel_json_file'],row)
        record['package_manifest']=fixtures.write(root,pid+'-packet.json',packet);record['shot_subset']=fixtures.write(root,pid+'-subset.json',packet)
    s['toolchain']=toolchain();return s,shots

def approve_package(root,s,bundle,ids):
    ref=fixtures.write(root,'bundle-'+str(len(s.get('generation_packages',{}).get('EPISODE',[])))+'.json',bundle)
    s.setdefault('generation_packages',{}).setdefault('EPISODE',[]).append(ref)
    proof={**fixtures.approve([ref,s['visual_basis'],s['shot_manifest']]),'panel_ids':ids}
    proof_ref=fixtures.write(root,'package-proof-'+str(len(s['generation_packages']['EPISODE']))+'.json',proof)
    index=fixtures.read(root,s['approval_index']) if s.get('approval_index') else {'policy':'approval_index_v1','entries':[]}
    index['entries'].append({'phase':'generation_package','book_id':s['book_id'],'episode_ids':[s['episode_id']],'panel_ids':ids,'approval':proof_ref})
    s['approval_index']=fixtures.write(root,'approval-index.json',index)

class ScopedPreparation(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'episode';self.state,self.shots=fixture(self.root)
    def test_boundary_missing_only_blocks_first_with_no_image_dependency(self):
        value=report(self.state,self.root);self.assertEqual(value['global_errors'],[]);self.assertEqual(value['blocked_panel_ids'],['P001']);self.assertEqual(value['prepared_panel_ids'],['P002','P003','P004'])
        self.assertIn('P001',value['ready_for_review_ids'])
    def test_real_image_dependency_inherits_hold(self):
        self.shots['panels'][1]['generation_dependencies']=['P001'];self.update_shots()
        value=report(self.state,self.root);self.assertIn('P002',value['blocked_panel_ids']);self.assertIn('P002',value['ready_for_review_ids'])
    def update_shots(self):
        self.state['shot_manifest']=fixtures.write(self.root,'changed-shots.json',self.shots)
        audit=fixtures.read(self.root,self.state['semantic_audit']);audit['shot_manifest']=self.state['shot_manifest'];self.state['semantic_audit']=fixtures.write(self.root,'changed-audit.json',audit)
    def test_unknown_design_propagates_but_boundary_only_does_not(self):
        self.shots['panels'][0]['hold_reasons']=['SYNTHETIC unresolved body pose'];self.update_shots()
        self.assertEqual(report(self.state,self.root)['blocked_panel_ids'],['P001','P002','P003','P004'])
    def test_global_wrong_audit_version_never_partially_releases(self):
        audit=fixtures.read(self.root,self.state['semantic_audit']);audit['episode_id']='OTHER';self.state['semantic_audit']=fixtures.write(self.root,'wrong-audit.json',audit)
        value=report(self.state,self.root);self.assertTrue(value['global_errors']);self.assertEqual(value['prepared_panel_ids'],[])
    def test_actual_partial_bundle_and_generate_before_boundary_ready(self):
        bundle=episode_bundle(self.state,self.root);self.assertEqual(bundle['panel_ids'],['P001','P002','P003','P004']);self.assertEqual(bundle['coverage'],'partial');self.assertEqual(bundle['approval_panel_ids'],['P002','P003','P004'],bundle);self.assertEqual(bundle['pending_panel_ids'],['P001'])
        approve_package(self.root,self.state,bundle,['P002'])
        compiled=compile_jobs(self.state,self.root);self.assertEqual([j['panel_id'] for j in compiled['jobs']],['P002'],compiled)
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['status'],'HOLD')
        self.assertEqual(evaluate(self.state,self.root,'generate','P003')['status'],'HOLD')
        self.assertEqual(package_review_errors(self.state,self.root,{'batch_id':'H001'},self.state['panels'][0]),['缺少覆盖本格实际prompt/参考/版本的生图包用户批准'])
    def test_candidate_current_design_is_readable_but_not_dispatch_authority(self):
        root=self.root.parent/'candidate';state,shots=fixture(root,True)
        packet=fixtures.read(root,state['panels'][1]['package_manifest'])
        self.assertTrue(load_context(packet,root)[1])
        with review_context(state,root,True):self.assertEqual(load_context(packet,root)[1],[])
        self.assertTrue(load_context(packet,root)[1])
        bundle=episode_bundle(state,root);self.assertIn('P002',bundle['approval_panel_ids'],bundle)
        self.assertEqual(evaluate(state,root,'generate','P002')['status'],'HOLD')
    def test_scope_union_does_not_expand_either_original_approval(self):
        first={**fixtures.approve([self.state['visual_basis'],self.state['shot_manifest'],self.state['semantic_audit']]),'panel_ids':['P001']}
        second={**first,'panel_ids':['P002']};ref=fixtures.write(self.root,'second-B.json',second)
        self.state['approval_index']=fixtures.write(self.root,'index.json',{'policy':'approval_index_v1','entries':[{'phase':'shot_design','book_id':'UNIT','episode_ids':['E000'],'panel_ids':['P002'],'approval':ref}]})
        original=copy.deepcopy(first);artifacts=[self.state['visual_basis'],self.state['shot_manifest'],self.state['semantic_audit']]
        self.assertEqual(approval_for(self.state,self.root,'shot_design',artifacts,['P001','P002'],first),[])
        self.assertTrue(approval_for(self.state,self.root,'shot_design',artifacts,['P003'],first));self.assertEqual(first,original)
    def test_unrelated_changed_row_reuses_original_B_but_changed_row_cannot(self):
        original=self.state['shot_manifest'];proof=self.state['gates']['shot_design'];self.shots['panels'][0]['camera_view_signature']='SYNTHETIC changed first shot';self.update_shots()
        self.assertTrue(compatible_collection(self.root,original,self.state['shot_manifest'],['P002'],'UNIT','E000'))
        refs=[self.state['visual_basis'],self.state['shot_manifest'],self.state['semantic_audit']]
        self.assertEqual(approval_for(self.state,self.root,'shot_design',refs,['P002'],proof),[])
        self.assertTrue(approval_for(self.state,self.root,'shot_design',refs,['P001'],proof))
    def test_new_reference_state_never_reuses_unchanged_row_approval(self):
        original=self.state['shot_manifest'];self.shots['identity_registry']['characters']['A']['canonical_name']='OTHER';self.update_shots()
        self.assertFalse(compatible_collection(self.root,original,self.state['shot_manifest'],['P002'],'UNIT','E000'))
    def test_missing_one_package_does_not_erase_other_candidate_inputs(self):
        self.state['panels'][2].pop('package_manifest')
        bundle=episode_bundle(self.state,self.root)
        self.assertEqual(bundle['approval_panel_ids'],['P002','P004']);self.assertIn('P003',bundle['candidate_technical_errors'])
    def test_missing_dependency_plan_does_not_erase_independent_inputs(self):
        self.shots['panels'][2]['generation_dependencies']=['P002'];self.update_shots()
        bundle=episode_bundle(self.state,self.root)
        self.assertIn('P002',bundle['approval_panel_ids']);self.assertNotIn('P003',bundle['approval_panel_ids']);self.assertIn('P003',bundle['candidate_technical_errors'])
    def test_broad_hold_is_not_relabeled_as_boundary_only(self):
        self.state['holds']=[{'scope':'panels','panel_ids':['P001'],'dimension':'boundary_comparison','evidence':'Missing previous episode comparison'},
                             {'scope':'states','state_keys':[self.shots['panels'][0]['visual_state_keys'][0]],'evidence':'Actual uncertain shared state'}]
        value=report(self.state,self.root);self.assertNotIn('P001',value['ready_for_review_ids']);self.assertEqual(value['prepared_panel_ids'],[])
    def test_later_half_hold_remains_local_during_preparation(self):
        self.state['holds']=[{'scope':'half','half_ids':['H002'],'evidence':'SYNTHETIC H002 unresolved preparation'}]
        value=report(self.state,self.root);self.assertEqual(value['prepared_panel_ids'],['P002']);self.assertIn('P003',value['blocked_panel_ids'])
    def test_missing_later_metadata_does_not_globally_block_ready_half(self):
        self.shots['panels'][3]['generation_dependencies']=None;self.update_shots()
        value=report(self.state,self.root);self.assertEqual(value['global_errors'],[]);self.assertIn('P004',value['blocked_panel_ids']);self.assertIn('P002',value['prepared_panel_ids'])
        self.assertIn('P002',episode_bundle(self.state,self.root)['approval_panel_ids'])
    def test_one_ready_unapproved_panel_does_not_block_approved_panel(self):
        # The episode is first in its actual test batch; no external boundary is needed.
        self.state['episode_order']=['E000']
        for r in self.state['panels'][1:]:
            packet=fixtures.read(self.root,r['package_manifest']);ctx=fixtures.read(self.root,packet['continuity_context']);ctx['episode_order']=['E000']
            packet['continuity_context']=fixtures.write(self.root,r['panel_id']+'-first-episode-context.json',ctx)
            r['package_manifest']=fixtures.write(self.root,r['panel_id']+'-first-episode-packet.json',packet)
            r['shot_subset']=r['package_manifest']
        self.state['gates']['shot_design']={**self.state['gates']['shot_design'],'panel_ids':['P002']}
        bundle=episode_bundle(self.state,self.root);self.assertIn('P001',bundle['approval_panel_ids'])
        approve_package(self.root,self.state,bundle,['P002'])
        self.assertEqual([j['panel_id'] for j in compile_jobs(self.state,self.root)['jobs']],['P002'])
        self.assertEqual(evaluate(self.state,self.root,'generate','P001')['status'],'HOLD')
    def test_one_return_cannot_unlock_first_half_C_or_second_half(self):
        bundle=episode_bundle(self.state,self.root);approve_package(self.root,self.state,bundle,['P002'])
        r=self.state['panels'][1];packet=fixtures.read(self.root,r['package_manifest']);p=packet['panels'][0]
        fixtures.create_return(self.root,self.state,packet,p,'VISUAL_PASS',1)
        result=evaluate(self.state,self.root);self.assertNotIn(result['next_action'],('WAIT_FIRST_HALF_APPROVAL','READY_TO_PACKAGE'),result)
        self.assertEqual(evaluate(self.state,self.root,'generate','P003')['status'],'HOLD')
    def test_candidate_mode_cannot_extend_to_a_foreign_episode(self):
        from panel_readiness import candidate_source
        packet=fixtures.read(self.root,self.state['panels'][1]['package_manifest']);source=fixtures.read(self.root,packet['continuity_context'])['sources'][0]
        with review_context(self.state,self.root,True):
            self.assertTrue(candidate_source(source));self.assertFalse(candidate_source({**source,'episode_id':'E999'}))
            self.assertFalse(candidate_source({**source,'root':str(self.root.parent)}))
    def test_context_builder_preserves_union_of_actual_scoped_proofs(self):
        from continuity_context import build
        first={**self.state['gates']['shot_design'],'panel_ids':['P001']};second={**first,'panel_ids':['P002']}
        original=copy.deepcopy(first);self.state['gates']['shot_design']=first
        ref=fixtures.write(self.root,'second-context-B.json',second)
        self.state['approval_index']=fixtures.write(self.root,'context-index.json',{'policy':'approval_index_v1','entries':[{'phase':'shot_design','book_id':'UNIT','episode_ids':['E000'],'panel_ids':['P002'],'approval':ref}]})
        ctx=build(self.state,self.root,'P003');self.assertEqual(ctx['sources'][0]['shot_approvals'],[first,second]);self.assertEqual(first,original)
        packet=fixtures.read(self.root,self.state['panels'][2]['package_manifest']);packet['continuity_context']=fixtures.write(self.root,'union-context.json',ctx)
        self.assertEqual(load_context(packet,self.root)[1],[])
        ctx['sources'][0]['shot_approvals']=[first];packet['continuity_context']=fixtures.write(self.root,'incomplete-union-context.json',ctx)
        self.assertTrue(load_context(packet,self.root)[1])
    def test_actual_unchanged_package_and_B_reused_after_other_row_changed(self):
        bundle=episode_bundle(self.state,self.root);approve_package(self.root,self.state,bundle,['P002'])
        original_bundle=copy.deepcopy(bundle);self.shots['panels'][3]['camera_view_signature']='SYNTHETIC fourth row new design';self.update_shots()
        compiled=compile_jobs(self.state,self.root);self.assertEqual([j['panel_id'] for j in compiled['jobs']],['P002'],compiled)
        self.assertEqual(bundle,original_bundle)
    def test_readiness_CLI_is_only_a_read_only_preparation_report(self):
        state_ref=fixtures.write(self.root,'00_输入审计/生产流程.json',self.state)
        before=(self.root/state_ref['path']).read_bytes()
        cmd=fixtures.cli(fixtures.BASE/'scripts/production_runtime.py','--state',self.root/state_ref['path'],'--action','readiness')
        self.assertEqual(cmd.returncode,0,cmd.stdout+cmd.stderr);value=json.loads(cmd.stdout)
        self.assertFalse(value['dispatch_authorized']);self.assertEqual(value['prepared_panel_ids'],['P002','P003','P004'])
        self.assertEqual((self.root/state_ref['path']).read_bytes(),before)

if __name__=='__main__':unittest.main()
