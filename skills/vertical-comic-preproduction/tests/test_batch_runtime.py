"""Batch isolation, explicit grouped approval and local capacity transactions."""
from _portable_config import config_path
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests')]
from codex_reference_contract import digest
from runtime_snapshot import create,verify,SKILLS
from review_policy import proposal,approvals,question_action,technical_errors
from staged_workflow import approval_errors
from slot_leases import allocate,effective_control,release_unsubmitted,advance,POLICY
from episode_dispatch_queue import reserve_ready
from parallel_dispatch import context_errors,receipt_errors,handoff_readiness
from production_runtime import commit_updates
from test_parallel_dispatch import DispatchTests


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.skills=self.root/'installed'
        for name in SKILLS:
            p=self.skills/name;p.mkdir(parents=True);(p/'SKILL.md').write_text(name, encoding='utf-8', newline='\n')
        p=self.skills/SKILLS[0]/'scripts';p.mkdir();(p/'runtime.py').write_text('frozen', encoding='utf-8', newline='\n')
        self.source=p/'runtime.py'

    def test_install_change_does_not_change_frozen_runtime_and_no_hardlink(self):
        ref=create(self.root/'batch',skills_root=self.skills)
        self.source.write_text('new installation', encoding='utf-8', newline='\n')
        frozen=verify(ref);actual=Path(frozen['scripts'])/'runtime.py'
        self.assertEqual(actual.read_text(encoding='utf-8-sig'),'frozen')
        self.assertNotEqual(actual.stat().st_ino,self.source.stat().st_ino)
        verify(ref,executing_script=actual)
        with self.assertRaisesRegex(ValueError,'快照scripts'):verify(ref,executing_script=self.source)

    def test_tamper_added_import_and_manifest_are_rejected(self):
        ref=create(self.root/'batch',skills_root=self.skills);scripts=Path(verify(ref)['scripts'])
        extra=scripts/'shadow.py';extra.write_text('added', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError,'集合变化'):verify(ref)
        extra.unlink();(scripts/'runtime.py').write_text('tampered', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError,'文件已变化'):verify(ref)
        with self.assertRaises(ValueError):create(self.root/'batch',skills_root=self.skills)

    def test_real_project_rules_are_copied_and_read_without_live_root(self):
        from usage_config import read_config,memory_source
        from rule_memory import source_index,load_selected,select
        config=read_config(config_path())
        source=memory_source(config)
        ref=create(self.root/'batch',skills_root=self.skills,memory_source=source)
        frozen=verify(ref)['memory_source'];root,index=source_index(frozen)
        self.assertNotEqual(str(root),source['root'])
        for rule in index['rules']:
            self.assertEqual(digest(root/rule['file']['path']),rule['file']['sha256'])
        # Even an equal-content alternate root cannot replace the selected source.
        with self.assertRaisesRegex(ValueError,'不得把冻结规则来源'):
            source_index({**frozen,'root':source['root']})

    def test_init_binds_real_snapshot_toolchain_and_rule_source(self):
        ref=create(self.root/'batch',memory_source=None)
        out=self.root/'episode'
        cmd=[sys.executable, '-X', 'utf8',str(ROOT/'scripts/init_preproduction.py'),'--output',str(out),
             '--book','test','--episode','E001','--runtime-snapshot',ref['path']]
        p=subprocess.run(cmd,capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stderr)
        state=json.loads((out/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(state['runtime_snapshot'],ref)
        self.assertEqual(state['toolchain']['root'],verify(ref)['scripts'])
        code="import sys,json;sys.path.insert(0,sys.argv[1]);from execution_contract import state_errors;from pathlib import Path;s=json.loads(Path(sys.argv[2]).read_text());print(json.dumps(state_errors(s,Path(sys.argv[3]))))"
        checked=subprocess.run([sys.executable, '-X', 'utf8','-c',code,verify(ref)['scripts'],str(out/'00_输入审计/生产流程.json'),str(out)],capture_output=True,text=True, encoding='utf-8')
        self.assertEqual(checked.returncode,0,checked.stderr)
        self.assertEqual(json.loads(checked.stdout),[])
        installed=subprocess.run([sys.executable, '-X', 'utf8','-c',code,str(ROOT/'scripts'),str(out/'00_输入审计/生产流程.json'),str(out)],capture_output=True,text=True, encoding='utf-8')
        self.assertTrue(any('快照scripts' in e for e in json.loads(installed.stdout)))


class GroupedReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        refs=[]
        for name in ('basis','shots','package'):
            p=self.root/(name+'.json');p.write_text('{}', encoding='utf-8', newline='\n');refs.append({'path':p.name,'sha256':digest(p)})
        self.basis,self.shots,self.package=refs
        self.items=[{'item_id':'B','phase':'shot_design','panel_ids':['P001'],
                     'artifacts':refs[:2],'summary':'镜头'},
                    {'item_id':'PACKAGE','phase':'generation_package','panel_ids':['P001'],
                     'artifacts':refs,'summary':'实际包'}]
        self.review=proposal('book','E021',self.items,self.root)
        self.message={'source_kind':'user_message','quote':'批准B与生图包所列P001','source_locator':'actual-message:1'}

    def test_one_reply_produces_two_separate_gate_valid_proofs(self):
        proofs=approvals(self.review,['B','PACKAGE'],self.message,self.root)
        self.assertEqual([p['phase'] for p in proofs],['shot_design','generation_package'])
        self.assertEqual(approval_errors(proofs[0],self.root,self.items[0]['artifacts'],'book','E021'),[])
        self.assertEqual(approval_errors(proofs[1],self.root,self.items[1]['artifacts'],'book','E021'),[])
        only=approvals(self.review,['B'],{**self.message,'quote':'仅批准B'},self.root)
        self.assertEqual(len(only),1)
        self.assertTrue(approval_errors(only[0],self.root,[self.package],'book','E021'))

    def test_same_event_reuses_question_but_changed_scope_does_not(self):
        pending=[{'event_id':self.review['event_id'],'status':'PENDING','question_id':'q1'}]
        self.assertEqual(question_action(self.review,pending)['action'],'KEEP_PENDING')
        items=copy.deepcopy(self.items);items[0]['panel_ids'].append('P002')
        new=proposal('book','E021',items,self.root)
        self.assertEqual(question_action(new,pending)['action'],'ASK_READY_ITEMS')
        self.review['items']=items
        with self.assertRaises(ValueError):approvals(self.review,['B'],self.message,self.root)

    def test_technical_authority_cannot_expand_operation_panel_or_version(self):
        review=proposal('book','E021',[{'item_id':'T','phase':'technical_operations','panel_ids':['P001'],
            'artifacts':[self.basis],'summary':'只归一','operations':['equal_scale_normalize'],
            'constraints':['保留全部画面与原图']}],self.root)
        proof=approvals(review,['T'],self.message,self.root)[0]
        self.assertEqual(technical_errors(proof,self.root,'book','E021','P001','equal_scale_normalize',[self.basis]),[])
        self.assertTrue(technical_errors(proof,self.root,'book','E021','P002','equal_scale_normalize',[self.basis]))
        self.assertTrue(technical_errors(proof,self.root,'book','E021','P001','information_preserving_crop',[self.basis]))
        with self.assertRaises(ValueError):approvals(review,['T'],{'source_kind':'config'},self.root)


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.h=DispatchTests('test_valid_snapshot_read_only');self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.h.state.update(execution_mode='episode_async_v1',optimization_policy='scoped_episode_review_v1',
            preparation_policy='episode_preparation_v1',runtime={'dispatch_policy':POLICY},
            panels=[{'panel_id':p,'status':'PENDING','round_id':1,'attempt_id':p+'-r1'} for p in ('P001','P002')])
        self.h.state['batch_plan']=self.h.write(self.h.episode,'plan.json',{'batches':[{'batch_id':'EPISODE','panel_ids':['P001','P002']}]})
        for p in self.h.state['panels']:
            p['package_manifest']=self.h.write(self.h.episode,p['panel_id']+'.json',{
                'round_context':{'batch_id':'EPISODE','round_id':1,'attempt_id':p['attempt_id']},'panels':[{'panel_id':p['panel_id']}]})
        self.h.control['permits']=[];self.h.control['jobs'][0].update(active_batch_id='EPISODE',max_inflight=2)
        self.h.flush();allocate(self.h.control_path,digest(self.h.control_path),{'job21':1})

    @staticmethod
    def gate(state,root,check='status',requested=None):
        return ({'next_action':'SUBMIT_READY_EPISODE_REQUESTS','eligible_panel_ids':['P001','P002']}
                if check=='status' else {'ready_panel_ids':['P001','P002']})

    def reserve(self):
        with patch('scoped_episode_workflow.evaluate_episode',side_effect=self.gate):
            return reserve_ready(self.h.state_path,digest(self.h.state_path),digest(self.h.control_path))

    def state(self):return json.loads(self.h.state_path.read_text(encoding='utf-8-sig'))
    def control(self):return json.loads(self.h.control_path.read_text(encoding='utf-8-sig'))

    def test_local_reservation_never_writes_control_and_respects_slot(self):
        original=self.h.control_path.read_bytes();r=self.reserve();state=self.state()
        self.assertEqual(len(r['reserved']),1);self.assertEqual(self.h.control_path.read_bytes(),original)
        receipt=r['reserved'][0]['receipt']
        self.assertTrue(receipt['lease_id'])
        self.assertEqual(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',receipt),[])
        self.assertEqual(self.reserve()['status'],'CAPACITY_FULL')
        self.assertTrue(handoff_readiness(self.control(),state,'job21',old_writer_stopped=True))

    def test_submit_unknown_commit_consumes_slot_without_root_handshake(self):
        self.reserve();original=self.h.control_path.read_bytes()
        update={'panel_id':'P001','attempt_id':'P001-r1','round_id':1,'status':'IN_FLIGHT'}
        with patch('staged_workflow.preflight_many',return_value={'ready_panel_ids':['P001']}):
            commit_updates(self.h.state_path,digest(self.h.state_path),[update])
        self.assertEqual(self.state()['dispatch_ledger'][0]['status'],'IN_FLIGHT')
        receipt=self.state()['dispatch_ledger'][0]
        self.assertTrue(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',receipt))
        update['status']='RESULT_UNKNOWN'
        with patch('batch_round.attempt_errors',return_value=[]):
            commit_updates(self.h.state_path,digest(self.h.state_path),[update])
        self.assertEqual(self.state()['dispatch_ledger'][0]['status'],'RESULT_UNKNOWN')
        self.assertEqual(self.h.control_path.read_bytes(),original)
        self.assertEqual(self.reserve()['status'],'CAPACITY_FULL')
        with self.assertRaises(ValueError):release_unsubmitted(self.h.state_path,digest(self.h.state_path),['P001'])
        with self.assertRaisesRegex(ValueError,'活动或未知'):
            allocate(self.h.control_path,digest(self.h.control_path),{'job21':2},old_writers_stopped=True)

    def test_release_restores_original_packet_and_can_reserve_same_attempt(self):
        self.reserve();release_unsubmitted(self.h.state_path,digest(self.h.state_path),['P001'])
        state=self.state();self.assertEqual(state['dispatch_ledger'][0]['status'],'RELEASED')
        self.assertNotIn('dispatch_receipt',json.loads((self.h.episode/state['panels'][0]['package_manifest']['path']).read_text(encoding='utf-8-sig')))
        self.reserve();state=self.state();advance(state,'P001','IN_FLIGHT')
        self.assertEqual(state['dispatch_ledger'][-1]['status'],'IN_FLIGHT')

    def test_global_overallocation_stale_control_and_live_reassignment_rejected(self):
        with self.assertRaises(ValueError):allocate(self.h.control_path,digest(self.h.control_path),{'job21':6},old_writers_stopped=True)
        with self.assertRaisesRegex(ValueError,'旧写入者'):allocate(self.h.control_path,digest(self.h.control_path),{'job21':2})
        with self.assertRaisesRegex(ValueError,'CONTROL_CHANGED'):allocate(self.h.control_path,'bad',{'job21':2},old_writers_stopped=True)
        allocate(self.h.control_path,digest(self.h.control_path),{'job21':2},old_writers_stopped=True)
        self.assertEqual(len(self.reserve()['reserved']),2)

    def test_completed_output_frees_local_slot_and_receipt_binds_real_hash(self):
        first=self.reserve()['reserved'][0];state=self.state()
        advance(state,'P001','IN_FLIGHT')
        output=self.h.write(self.h.episode,'returned-output.json',{'actual_test_bytes':True})
        state['panels'][0].update(status='GENERATED',output=output)
        advance(state,'P001','GENERATED',output)
        self.h.state_path.write_text(json.dumps(state), encoding='utf-8', newline='\n')
        self.assertEqual(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',first['receipt'],output['sha256']),[])
        self.assertTrue(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',first['receipt'],'0'*64))
        self.assertEqual([x['panel_id'] for x in self.reserve()['reserved']],['P002'])
        # Completed jobs can still adopt their original verified outputs.
        release_unsubmitted(self.h.state_path,digest(self.h.state_path),['P002'])
        control=self.control();control['jobs'][0]['status']='COMPLETED'
        self.h.control_path.write_text(json.dumps(control), encoding='utf-8', newline='\n')
        self.assertEqual(receipt_errors(self.h.context,self.h.episode,'book','E021','P001',first['receipt'],output['sha256']),[])

    def test_unknown_resolution_requires_actual_bound_evidence_and_preserves_history(self):
        self.reserve();state=self.state()
        advance(state,'P001','IN_FLIGHT');state['panels'][0]['status']='IN_FLIGHT'
        original=self.h.write(self.h.episode,'unknown.json',{'attempt_id':'P001-r1','status':'RESULT_UNKNOWN','source_locator':'synthetic://transport','evidence':'synthetic unknown'})
        state['panels'][0].update(status='RESULT_UNKNOWN',call_evidence=original)
        advance(state,'P001','RESULT_UNKNOWN');self.h.state_path.write_text(json.dumps(state), encoding='utf-8', newline='\n')
        actual=self.h.write(self.h.episode,'service.json',{'synthetic_verified_no_output':True})
        failure=self.h.write(self.h.episode,'failed.json',{'attempt_id':'P001-r1','status':'CALL_FAILED','source_locator':'synthetic://service','evidence':'synthetic verified no output'})
        report={'policy':'unknown_result_resolution_v1','status':'REVIEWED','panel_id':'P001','attempt_id':'P001-r1','round_id':1,'original_call_evidence':original,'reviewer':'SYNTHETIC','evidence':'synthetic checked service','source_locator':'synthetic://service','service_evidence':actual,'conclusion':'CONFIRMED_NO_OUTPUT'}
        ref=self.h.write(self.h.episode,'resolution.json',report)
        update={'panel_id':'P001','attempt_id':'P001-r1','round_id':1,'status':'CALL_FAILED','call_evidence':failure}
        with self.assertRaises(ValueError):commit_updates(self.h.state_path,digest(self.h.state_path),[update])
        commit_updates(self.h.state_path,digest(self.h.state_path),[update],resolution_ref=ref)
        self.assertEqual(self.state()['dispatch_ledger'][0]['status'],'COMPLETED')
        self.assertEqual(self.state()['unknown_resolutions']['P001-r1'],ref)
        self.assertEqual(json.loads((self.h.episode/original['path']).read_text(encoding='utf-8-sig'))['status'],'RESULT_UNKNOWN')


class FeasibilityAndBoundaryTests(unittest.TestCase):
    def test_new_semantic_template_requires_current_crop_review(self):
        from execution_contract import semantic_template
        from visual_evidence import feasibility_errors
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            def write(name,value):
                p=root/name;p.write_text(json.dumps(value), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(p)}
            panel={'panel_id':'P001','visible_region':'胸口以上','framing':{'required_visible':['膝上双手']}}
            state={'book_id':'UNIT','episode_id':'E001','preparation_policy':'episode_preparation_v1',
                   'runtime':{'question_policy':'grouped_review_v1'},
                   'source_snapshot':write('source.json',{'panel_ids':['P001']}),
                   'visual_basis':write('basis.json',{}),'shot_manifest':write('shots.json',{'panels':[panel]})}
            check=semantic_template(state,root,'EPISODE')['panels'][0]['checks']['framing_feasibility']
            self.assertEqual(check['status'],'UNREVIEWED')
            self.assertEqual(check['expected']['crop_and_required_information']['required_visible'],['膝上双手'])
            self.assertTrue(feasibility_errors(panel,check))
            check.update(status='PASS',evidence='SYNTHETIC adjusted to include required hands')
            self.assertEqual(feasibility_errors(panel,check),[])
            panel['visible_region']='腰以上'
            self.assertTrue(feasibility_errors(panel,check))

    def test_explicit_comparison_only_hold_does_not_block_generation_but_stops_final(self):
        import test_episode_async as fixture
        from scoped_episode_workflow import evaluate_episode
        h=fixture.EpisodeAsyncTests('test_later_independent_panels_ready_before_first_images_or_C')
        h.setUp();self.addCleanup(h.doCleanups)
        state,shots=h.state(2)
        state['runtime']={'question_policy':'grouped_review_v1'}
        state['holds']=[{'scope':'panels','panel_ids':['P001'],'dimension':'boundary_comparison',
                         'comparison_only':True,'evidence':'SYNTHETIC pending actual boundary comparison only'}]
        with patch('execution_contract.state_errors',return_value=[]), \
             patch('scoped_episode_workflow.binding_errors',return_value=[]), \
             patch('batch_workflow.completed_errors',return_value=[]), \
             patch('production_runtime.package_review_errors',return_value=[]), \
             patch('batch_workflow.batch_review_errors',return_value=[]):
            report=evaluate_episode(state,h.root)
            self.assertEqual(report['eligible_panel_ids'],['P001','P002'],report)
            state['holds'].append({'scope':'states','state_keys':shots[0]['visual_state_keys'],
                                   'evidence':'SYNTHETIC uncertain design still must stop'})
            blocked=evaluate_episode(state,h.root)
            self.assertNotEqual(blocked['next_action'],'SUBMIT_READY_EPISODE_REQUESTS',blocked)
            state['holds'].pop()
            for row in state['panels']:row.update(status='VISUAL_PASS',round_id=1,attempt_id=row['panel_id']+'-r1',output=h.fixture.write(row['panel_id']+'.json',{'test':True}))
            final=evaluate_episode(state,h.root,'scope_complete')
            self.assertEqual(final['next_action'],'WAIT_EPISODE_CONTINUITY',final)


if __name__=='__main__':unittest.main()
