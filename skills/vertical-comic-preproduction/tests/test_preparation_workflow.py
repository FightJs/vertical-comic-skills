"""Offline workflow regressions, using synthetic source/approval fixtures only."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
import test_direct_handoff as fixtures
from test_panel_readiness import fixture
from test_execution_lifecycle import write, read
import production_runtime as runtime
from panel_readiness import review_context
from continuity_context import load_context
from codex_reference_contract import file_session
from task_context import fresh, ORIGIN_FILE


def authorize(state, root):
    request = {'source_kind':'user_message', 'source_locator':'synthetic://preparation-request',
               'quote':'SYNTHETIC: prepare inputs and rehearse; no image generation'}
    state['preparation_authorization'] = {**request, 'policy':'preparation_authorization_v1',
        'phase':'preparation', 'status':'APPROVED', 'book_id':state['book_id'],
        'episode_id':state['episode_id'], 'panel_ids':read(root,state['source_snapshot'])['panel_ids'],
        'artifacts':[state['source_script'],state['source_snapshot']],
        'evidence':write(root,'preparation-request.json',request)}
    state.pop('production_authorization',None)


class OfflineCompilation(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.DirectHandoffTests();self.addCleanup(self.fx.doCleanups);self.fx.setUp()
        self.state,self.root=self.fx.state,self.fx.template
        authorize(self.state,self.root)

    def test_real_candidate_compile_and_receiver_audit_without_body_authority(self):
        before=copy.deepcopy(self.state)
        for kwargs in ({'candidate':True},{'input_audit':True}):
            result=runtime.compile_jobs(self.state,self.root,['P001','P002'],**kwargs)
            self.assertEqual([j['panel_id'] for j in result['jobs']],['P001','P002'],result)
            self.assertIs(result['dispatch_authorized'],False)
            self.assertTrue(all(j['dispatch_authorized'] is False for j in result['jobs']))
        self.assertEqual(self.state,before)
        self.assertEqual(runtime.compile_jobs(self.state,self.root,['P001'])['jobs'],[])

    def test_actual_cli_and_reservation_never_treat_preparation_as_body_permission(self):
        path=self.root/'00_输入审计/生产流程.json';write(self.root,str(path.relative_to(self.root)),self.state)
        before=path.read_bytes()
        cmd=[sys.executable,'-B',runtime.__file__,'--state',str(path),'--action','compile','--candidate','--panels','P001']
        result=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=30)
        value=json.loads(result.stdout);self.assertEqual(len(value['jobs']),1,value)
        self.assertIs(value['jobs'][0]['dispatch_authorized'],False)
        from staged_workflow import evaluate
        result=evaluate(self.state,self.root,'reservation_batch',{'limit':1,'excluded':[]})
        self.assertFalse(result.get('ready_panel_ids'),result)
        self.assertEqual(path.read_bytes(),before)

    def test_bad_scope_evidence_and_phase_block_offline_compile(self):
        original=copy.deepcopy(self.state['preparation_authorization'])
        for changes in ({'panel_ids':['P002']},{'phase':'generation'},{'quote':'changed'},
                        {'source_kind':'agent_decision'},{'artifacts':[]}):
            self.state['preparation_authorization']={**original,**changes}
            result=runtime.compile_jobs(self.state,self.root,['P001'],candidate=True)
            self.assertEqual(result['jobs'],[],changes)

    def test_candidate_still_checks_actual_input_and_does_not_grant_B(self):
        self.state['gates']['shot_design']=None
        result=runtime.compile_jobs(self.state,self.root,['P001'],candidate=True)
        self.assertEqual(len(result['jobs']),1,result)
        packet=read(self.root,self.state['panels'][0]['package_manifest'])
        packet['panels'][0]['prompt']='WRONG ACTUAL INPUT'
        self.state['panels'][0]['package_manifest']=write(self.root,'bad-input.json',packet)
        result=runtime.compile_jobs(self.state,self.root,['P001'],candidate=True)
        self.assertEqual(result['jobs'],[],result)
        self.assertIsNone(self.state['gates']['shot_design'])

    def test_preparation_only_cannot_audit_a_live_receipt(self):
        packet=read(self.root,self.state['panels'][0]['package_manifest'])
        packet['dispatch_receipt']={'permit_id':'SYNTHETIC-LIVE'}
        self.state['panels'][0]['package_manifest']=write(self.root,'live-packet.json',packet)
        self.assertEqual(runtime.compile_jobs(self.state,self.root,['P001'],candidate=True)['jobs'],[])

    def test_preparation_record_cannot_be_relabelled_as_production_authorization(self):
        self.state['production_authorization']=copy.deepcopy(self.state['preparation_authorization'])
        self.assertEqual(runtime.compile_jobs(self.state,self.root,['P001'])['jobs'],[])

    def test_complete_frozen_handoff_rehearsal_with_preparation_only_authority(self):
        self.fx.refresh_template()
        _,_,bound,report=self.fx.pipeline()
        self.assertEqual(report['status'],'RELEASE_CANDIDATE',report)
        local=Path(bound['run_root'])/'E000'
        state=json.loads((local/'00_输入审计/生产流程.json').read_text(encoding='utf-8'))
        self.assertNotIn('production_authorization',state)
        self.assertEqual(runtime.compile_jobs(state,local,['P001'])['jobs'],[])

    def test_actual_cli_cross_episode_candidate_preflights_before_either_B(self):
        import shutil
        from codex_reference_contract import digest
        state,root=self.state,self.root
        prior_root=self.fx.base/'E999';shutil.copytree(root,prior_root)
        prior=copy.deepcopy(state);prior['episode_id']='E999'
        prior_basis=read(prior_root,prior['visual_basis']);prior_basis['episode_id']='E999'
        prior['visual_basis']=write(prior_root,'prior-basis.json',prior_basis)
        prior_shots=read(prior_root,prior['shot_manifest']);prior_shots['episode_id']='E999'
        prior['shot_manifest']=write(prior_root,'prior-shots.json',prior_shots)
        prior['gates']['visual_basis']={**prior['gates']['visual_basis'],'episode_id':'E999',
            'artifacts':[prior['source_script'],prior['source_snapshot'],prior['visual_basis']]}
        prior['gates']['shot_design']=None
        task=fresh(state['book_id'],['E999','E000'])
        for owner,base in ((state,root),(prior,prior_root)):
            owner['episode_order']=['E999','E000'];owner['task_context']=copy.deepcopy(task)
            write(base,ORIGIN_FILE,{'task_context':task,'episode_id':owner['episode_id'],
                                  'initial_body_calls':0,'initial_asset_calls':0})
            authorize(owner,base)
        write(prior_root,'candidate-state.json',prior)
        source={'root':str(prior_root),'episode_id':'E999',
                **{k:prior[k] for k in ('source_script','source_snapshot','visual_basis','shot_manifest')},
                'approval_resolution':'source_runtime_gates_v1','source_state_file':'candidate-state.json'}
        state['continuity_sources']=[source]
        context={'policy':'approved_shot_context_v1','book_id':state['book_id'],
                 'current':{'episode_id':'E000','panel_id':'P001'},'episode_order':state['episode_order'],
                 'sources':[source],'entries':[{'source':0,'panel_id':'P004'}]}
        context_ref=write(root,'boundary-context.json',context)
        shots=read(root,state['shot_manifest']);shots['continuity_context']=context_ref
        first=shots['panels'][0]
        first['continuity_contract']['scene'].update(mode='same_scene_new_view',previous_panel_id='E999-P004')
        first['adjacent_face_comparison']={'A':{'face_comparable':True,'evidence':'SYNTHETIC visible pair'}}
        state['shot_manifest']=write(root,'batch-candidate-shots.json',shots)
        audit=read(root,state['semantic_audit']);audit['shot_manifest']=state['shot_manifest']
        state['semantic_audit']=write(root,'batch-candidate-audit.json',audit)
        state['gates']['shot_design']=None
        for record,shot in zip(state['panels'],shots['panels']):
            packet=read(root,record['package_manifest']);packet['panels']=[copy.deepcopy(shot)]
            if record['panel_id']=='P001':packet['continuity_context']=context_ref
            else:
                ctx=read(root,packet['continuity_context']);ctx['episode_order']=state['episode_order']
                for src in ctx['sources']:src.update(shot_manifest=state['shot_manifest'],shot_approval=None)
                packet['continuity_context']=write(root,record['panel_id']+'-batch-context.json',ctx)
            write(root,shot['panel_json_file'],shot)
            record['package_manifest']=write(root,record['panel_id']+'-batch-packet.json',packet)
            record['shot_subset']=record['package_manifest']
        path=root/'00_输入审计/生产流程.json';write(root,str(path.relative_to(root)),state)
        cmd=[sys.executable,'-B',runtime.__file__,'--state',str(path),'--action','compile','--candidate','--panels','P001']
        proc=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',timeout=30)
        result=json.loads(proc.stdout)
        self.assertEqual([j['panel_id'] for j in result.get('jobs',[])],['P001'],result)
        self.assertIs(result['dispatch_authorized'],False)
        self.assertEqual(runtime.compile_jobs(state,root,['P001'])['jobs'],[])
        self.assertIsNone(state['gates']['shot_design']);self.assertIsNone(prior['gates']['shot_design'])


class CrossEpisodeCandidates(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.base=Path(tmp.name)
        self.prior_root=self.base/'E000';self.prior,self.shots=fixture(self.prior_root,candidate=True)
        self.root=self.base/'E001';self.root.mkdir()
        self.state=copy.deepcopy(self.prior);self.state['episode_id']='E001'
        for key in ('source_script','source_snapshot','visual_basis','shot_manifest'):
            # The receiving candidate has its own exact local input versions.
            value=read(self.prior_root,self.prior[key]) if key!='source_script' else None
            if value is not None:self.state[key]=write(self.root,key+'.json',value)
            else:
                import shutil
                shutil.copyfile(self.prior_root/self.prior[key]['path'],self.root/'source.txt')
                from codex_reference_contract import digest
                self.state[key]={'path':'source.txt','sha256':digest(self.root/'source.txt')}
        task=fresh(self.prior['book_id'],['E000','E001'])
        for state,root in ((self.prior,self.prior_root),(self.state,self.root)):
            state['episode_order']=['E000','E001'];state['task_context']=copy.deepcopy(task)
            write(root,ORIGIN_FILE,{'task_context':task,'episode_id':state['episode_id'],'initial_body_calls':0,'initial_asset_calls':0})
            authorize(state,root)
        self.save_prior()
        self.source={'root':str(self.prior_root),'episode_id':'E000',
                     **{k:self.prior[k] for k in ('source_script','source_snapshot','visual_basis','shot_manifest')},
                     'approval_resolution':'source_runtime_gates_v1','source_state_file':'candidate-state.json'}
        self.state['continuity_sources']=[copy.deepcopy(self.source)]
        context={'policy':'approved_shot_context_v1','book_id':self.state['book_id'],
                 'current':{'episode_id':'E001','panel_id':'P001'},'episode_order':['E000','E001'],
                 'sources':[self.source],'entries':[{'source':0,'panel_id':'P004'}]}
        self.packet={'book_id':self.state['book_id'],'episode_id':'E001','panels':[{'panel_id':'P001'}],
                     'continuity_context':write(self.root,'context.json',context)}

    def save_prior(self):write(self.prior_root,'candidate-state.json',self.prior)
    def errors(self):
        with review_context(self.state,self.root,True):return load_context(self.packet,self.root)[1]

    def test_same_task_candidate_reads_real_prior_design_without_B_approval(self):
        self.assertEqual(self.errors(),[])
        self.assertTrue(load_context(self.packet,self.root)[1])
        self.assertIsNone(self.prior['gates']['shot_design'])

    def test_not_registered_wrong_task_and_live_context_are_rejected(self):
        for key,value in [('continuity_sources',[]),('parallel_context',{'job_id':'LIVE'}),
                          ('task_context',fresh('UNIT',['E000','E001']))]:
            old=self.state.get(key);self.state[key]=value
            self.assertTrue(self.errors(),key)
            if old is None:self.state.pop(key)
            else:self.state[key]=old

    def test_missing_A_or_preparation_scope_never_bypassed(self):
        self.prior['gates']['visual_basis']=None;self.save_prior();self.assertTrue(self.errors())

    def test_source_edit_invalidates_warm_context(self):
        with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):
            with file_session():
                self.assertEqual(self.errors(),[])
                self.prior['preparation_authorization']['panel_ids']=['P001']
                (self.prior_root/'candidate-state.json').write_text(json.dumps(self.prior),encoding='utf-8')
                self.assertTrue(self.errors())

    def test_registration_edit_cannot_reuse_cached_candidate(self):
        with file_session():
            self.assertEqual(self.errors(),[])
            self.state['continuity_sources']=[]
            self.assertTrue(self.errors())

    def test_semantic_template_uses_batch_candidate_context_and_keeps_unreviewed(self):
        from execution_contract import semantic_template
        from test_rule_memory import library
        self.state['memory_source']=library(self.root/'rules')
        shots=read(self.root,self.state['shot_manifest']);shots['episode_id']='E001'
        shots['continuity_context']=self.packet['continuity_context']
        for panel in shots['panels']:panel['memory_tags']=[]
        shots['panels'][0]['adjacent_face_comparison']={'A':{'face_comparable':True,'evidence':'SYNTHETIC face pair'}}
        self.state['shot_manifest']=write(self.root,'template-shots.json',shots)
        result=semantic_template(self.state,self.root,'EPISODE')
        self.assertEqual(len(result['panels']),4)
        self.assertTrue(all(row['status']=='UNREVIEWED' for row in result['panels']))
        self.assertTrue(all(c['status']=='UNREVIEWED' for row in result['panels'] for c in row['checks'].values()))
        self.assertTrue(load_context(self.packet,self.root)[1])

    def test_portable_cross_episode_context_survives_directory_move(self):
        import shutil
        from continuity_context import binding_errors
        self.source.update(root='../E000',root_mode='context_relative_v1')
        self.state['continuity_sources']=[copy.deepcopy(self.source)]
        context=read(self.root,self.packet['continuity_context']);context['sources']=[copy.deepcopy(self.source)]
        # Context file sits in a child folder; the registered root is relative
        # to the episode root, while the context root is relative to its file.
        context['sources'][0]['root']='../../E000'
        self.packet['continuity_context']=write(self.root,'nested/context.json',context)
        self.assertEqual(binding_errors(self.state,self.root,self.packet,self.root),[])
        self.assertEqual(self.errors(),[])
        moved=self.base.parent/(self.base.name+'-moved')
        self.addCleanup(lambda:shutil.rmtree(moved,ignore_errors=True))
        shutil.move(str(self.base),str(moved));self.root=moved/'E001'
        self.assertEqual(binding_errors(self.state,self.root,self.packet,self.root),[])
        self.assertEqual(self.errors(),[])


class PortableExceptionTests(unittest.TestCase):
    def setUp(self):
        from test_execution_contract import Contracts
        self.fx=Contracts();self.addCleanup(self.fx.doCleanups);self.fx.setUp()
        self.source,self.rule,self.panel,self.app,self.scope,self.value=self.fx.exception()

    def test_relative_exception_survives_move_without_original_path(self):
        import shutil
        from rule_exception import applicable
        root=self.fx.root
        self.value.update(evidence_root='.',evidence_root_mode='exception_relative_v1')
        ref=write(root,'exception.json',self.value);self.panel['rule_exceptions']=[ref]
        self.assertIsNotNone(applicable(self.panel,root,self.rule,'image_review',self.scope))
        moved=root.parent/(root.name+'-moved');self.addCleanup(lambda:shutil.rmtree(moved,ignore_errors=True))
        shutil.move(str(root),str(moved))
        self.assertIsNotNone(applicable(self.panel,moved,self.rule,'image_review',self.scope))
        (moved/self.value['artifacts'][0]['path']).write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):applicable(self.panel,moved,self.rule,'image_review',self.scope)

    def test_relative_evidence_cannot_escape_and_legacy_absolute_still_works(self):
        from rule_exception import applicable
        root=self.fx.root
        self.assertIsNotNone(applicable(self.panel,root,self.rule,'image_review',self.scope))
        for base in ('..',str(root),''):
            self.value.update(evidence_root=base,evidence_root_mode='exception_relative_v1')
            self.panel['rule_exceptions']=[write(root,'bad-exception.json',self.value)]
            with self.assertRaises(ValueError):applicable(self.panel,root,self.rule,'image_review',self.scope)


class PreciseCropTests(unittest.TestCase):
    def test_shared_crop_vocabulary_including_mixed_people(self):
        from validate_preproduction import Gate
        from visual_evidence import BODY_CROP_LABELS
        from test_visual_evidence import fixture as visual_fixture
        _,panel=visual_fixture()
        panel['framing'].update(focus='SYNTHETIC face',crop_reason='SYNTHETIC action',focus_subjects=['A'],required_visible=['A face'])
        for crop in ('upper_thigh_up','knees_up'):
            item=copy.deepcopy(panel);item['framing']['body_crop']=crop
            gate=Gate(Path.cwd());gate.check_framing(item,'P001',True)
            self.assertEqual(gate.errors,[],gate.errors)
            self.assertTrue(BODY_CROP_LABELS[crop])
            item['framing']['body_crop']='mixed';item['characters_visible']=[{'character_id':'A','body_crop':crop}]
            gate=Gate(Path.cwd());gate.check_framing(item,'P001',True);self.assertEqual(gate.errors,[])
        item['characters_visible'][0]['body_crop']='unknown_crop'
        gate=Gate(Path.cwd());gate.check_framing(item,'P001',True);self.assertTrue(gate.errors)

    def test_new_crops_reach_actual_prompt_in_both_compilers(self):
        from repair_prompt_package import content_block
        from repair_prompt_package_v2 import build_prompt,character_details
        for crop,label in [('upper_thigh_up','大腿上段以上'),('knees_up','膝部以上')]:
            panel={'panel_id':'P001','locked_script':{'event_text':'SYNTHETIC standing'},
                   'framing':{'body_crop':crop,'focus':'SYNTHETIC pose','required_visible':['body']},
                   'characters_visible':[{'name':'A','screen_position':'画面左','body_crop':crop}]}
            chars=character_details(panel,'SYNTHETIC standing','eye_level','人物屏幕位置：A=画面左')
            self.assertIn(label,chars)
            self.assertIn(label,content_block(panel,panel))
            prompt,_,_=build_prompt(panel,'eye_level','medium','3:4','SYNTHETIC camera',
                'towards A','eye_level','A standing',[],None,None,'SYNTHETIC camera',chars)
            self.assertIn(label,prompt)

    def test_mixed_crop_cannot_be_copied_to_each_person(self):
        from repair_prompt_package_v2 import character_details
        for crop in (None,'mixed','environment'):
            panel={'framing':{'body_crop':'mixed'},'characters_visible':[{'name':'A','body_crop':crop}]}
            with self.assertRaisesRegex(ValueError,'逐人物body_crop'):
                character_details(panel,'SYNTHETIC standing','eye_level','人物屏幕位置：A=画面左')

if __name__=='__main__':unittest.main()
