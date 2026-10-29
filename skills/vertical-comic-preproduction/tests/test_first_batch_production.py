"""Decision/delivery behavior using isolated actual files; no image-service calls."""
import _historical_fixture
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'scripts'), str(Path(__file__).parent)]
from production_decisions import (POLICY, decision_errors, outcome, findings, priority,
                                  repeated_method, register, selected)
from codex_reference_contract import digest
from repair_routes import plan
from panel_delivery import build, gate, export


def issue(category=3, ident='hand', kind='finger', observation='/dimension_review/action_interaction'):
    return {'id': ident, 'category': category, 'kind': kind, 'certainty': 'confirmed',
            'location': 'A角色自身右手', 'problem': '局部手指粘连',
            'target': '理顺指形，保留握杯关系', 'basis': '原批准手部动作与MEM-006',
            'handling': '留人工', 'observations': [observation]}


def decision(record, item, issues=None, action='defer_manual'):
    issues = [issue()] if issues is None else issues
    d = {'policy': POLICY, 'panel_id': record['panel_id'], 'attempt_id': record['attempt_id'],
         'image': record['output'], 'qa_report': record['qa_report'], 'reviewer': 'SYNTHETIC',
         'reason': '人物和背景稳定，局部问题人工更容易处理', 'issues': issues,
         'action': action, 'fix_now': [], 'opportunistic': [], 'manual': [i['id'] for i in issues]}
    if action in {'local_edit', 'regenerate', 'rebuild_inputs'}:
        d.update(fix_now=[i['id'] for i in issues if i['category'] != 3],
                 manual=[i['id'] for i in issues if i['category'] == 3],
                 method_key='one-local-edit', cause_key='grip',
                 preserve_constraints=['保留正确脸、衣装和构图'],
                 factors={k: 'SYNTHETIC具体取舍依据' for k in
                          ('impact','distribution','scope','preservation_risk','history','manual_cost')})
    return d


class FirstBatchTests(unittest.TestCase):
    def fixture(self):
        from test_direct_handoff import DirectHandoffTests
        from types import SimpleNamespace
        from test_execution_lifecycle import write, approve
        from codex_reference_contract import checked_file, read_json, validate_panel
        from make_generation_qa import _main as make_qa
        from contextlib import redirect_stdout
        from PIL import Image
        import io
        original = DirectHandoffTests(); original.setUp(); self.addCleanup(original.doCleanups)
        root=original.template; s=original.state; s['production_policy']=POLICY
        writer=lambda name,value: write(root,name,value)
        h=SimpleNamespace(root=root,h=SimpleNamespace(f=SimpleNamespace(write=writer),approve=approve))
        row=s['panels'][0]; packet=read_json(checked_file(root,row['package_manifest']));panel=packet['panels'][0]
        errors,submission=validate_panel(panel,root); self.assertEqual(errors,[])
        image_dir=root/'synthetic-return';image_dir.mkdir();image=image_dir/'P001.png'
        Image.new('RGB',(90,160),'white').save(image)
        out={'path':image.relative_to(root).as_posix(),'sha256':digest(image)}
        req={'attempt_id':row['attempt_id'],'backend_id':'codex_builtin_imagegen','panel_id':'P001',**submission,
             'source_kind':'observed_tool_call','source_locator':'synthetic://not-real'}
        res={'attempt_id':row['attempt_id'],'status':'COMPLETED','outputs':[out],
             'source_kind':'observed_tool_result','source_locator':'synthetic://not-real'}
        panel['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],
            'request_evidence':writer('req.json',req),'response_evidence':writer('res.json',res)}
        row.update(package_manifest=writer('returned.json',packet),output=out)
        qa_dir=root/'synthetic-qa'
        with redirect_stdout(io.StringIO()):
            code=make_qa(['--package',str(root),'--manifest','returned.json','--images',str(image_dir),
                          '--output',str(qa_dir),'--skip-contact-sheet'])
        self.assertEqual(code,0)
        q=read_json(qa_dir/'生成图QA报告.json');item=q['panels'][0]
        for rv in [*item['dimension_review'].values(),item['style_review']]:
            if rv['status']=='UNREVIEWED':rv.update(status='PASS',reviewer='SYNTHETIC',evidence='Synthetic only')
        for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match',
                    'required_visible_information_preserved','no_extra_offscreen_characters'):item[key]=True
        item['dimension_review']['action_interaction'].update(status='FAIL',reviewer='SYNTHETIC',evidence='SYNTHETIC指形局部粘连')
        row.update(status='VISUAL_FAIL',qa_report=writer('qa-local-fail.json',q),
                   failure_diagnosis={'reviewer':'SYNTHETIC','evidence':'局部指形错误','layer':'generation_execution'})
        d = decision(row,item)
        ref = h.h.f.write('decision.json',d)
        row.update(production_decisions={row['attempt_id']:ref},
                   adoption={'attempt_id':row['attempt_id'],'decision':ref,'reason':'此图主体稳定'})
        cont={'policy':'batch_review_v1','book_id':'UNIT','episode_id':'E000','batch_id':'EPISODE',
              'panel_ids':[r['panel_id'] for r in s['panels']],'status':'PASS','reviewer':'SYNTHETIC','evidence':'单格没有跨格连续性冲突',
              'visual_basis':s['visual_basis'],'shot_manifest':s['shot_manifest'],'outputs':[r.get('output') for r in s['panels']],'previous_outputs':[]}
        s['batch_reviews']={'EPISODE':h.h.f.write('episode-continuity.json',cont)}
        return h,s,row,item,d

    def second_attempt(self,h,s,row,item,call_failed=True):
        from historical_engines.batch_round import snapshot
        from codex_reference_contract import read_json,checked_file
        from production_runtime import authorize_episode_repair
        d=decision(row,item,[issue(2)],'local_edit')
        row['production_decisions'][row['attempt_id']]=h.h.f.write('original-repair-decision.json',d)
        packet=read_json(checked_file(h.root,row['package_manifest']));panel=packet['panels'][0]
        packet['round_context']={'batch_id':'EPISODE','round_id':2,'attempt_id':'P001-r2'}
        constraint=d['issues'][0]['target']
        panel.update(operation='repair',generation_execution={'status':'NOT_RUN'},
            prompt=panel['prompt']+'\n'+constraint+'\n'+d['preserve_constraints'][0],
            prompt_file='P001/repair-prompt.txt',panel_json_file='P001/repair-panel.json')
        (h.root/panel['prompt_file']).write_text(panel['prompt'], encoding='utf-8')
        h.h.f.write(panel['panel_json_file'],panel)
        packet_ref=h.h.f.write('second-packet.json',packet)
        auth={'policy':'episode_repair_v1','panel_id':'P001','failed_attempt':snapshot(row),
            'route':'targeted_image_repair','reviewer':'SYNTHETIC','evidence':'SYNTHETIC局部错误',
            'repair_decision':d,'repair_constraints':[constraint], 'new_attempt_id':'P001-r2',
            'new_package_manifest':packet_ref,'new_shot_subset':row['shot_subset']}
        h.h.f.write('repair-auth.json',auth)
        state_path=h.root/'00_输入审计/生产流程.json';state_path.write_text(json.dumps(s), encoding='utf-8')
        authorize_episode_repair(state_path,digest(state_path),'repair-auth.json')
        updated=json.loads(state_path.read_text(encoding='utf-8-sig'));s.clear();s.update(updated);row=s['panels'][0]
        if call_failed: row.update(status='CALL_FAILED',call_evidence=h.h.f.write('second-call-failed.json',
            {'attempt_id':row['attempt_id'],'status':'CALL_FAILED','source_locator':'synthetic://service',
             'evidence':'SYNTHETIC failed execution, no output'}))
        old=row['attempt_history'][0]
        final=decision(old,item,[issue(2)])
        final_ref=h.h.f.write('old-adopted-final-decision.json',final)
        row['production_decisions'][old['attempt_id']]=final_ref
        row['adoption']={'attempt_id':old['attempt_id'],'decision':final_ref,'reason':'第二次调用失败，采用已审首轮图'}
        return row

    def test_only_category_three_can_export_with_real_fail_and_no_repair(self):
        h,s,row,item,d=self.fixture()
        self.assertEqual(decision_errors(d,row,item),[])
        self.assertFalse(plan(d,row)['image_call_allowed'])
        report=build(s,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'MANUAL_RETOUCH')
        ref=h.h.f.write('delivery-review.json',report)
        self.assertEqual(gate(s,h.root,ref)['status'],'HOLD')
        s['gates']['final']={**h.h.approve([*report['artifacts'],ref]),'panel_ids':report['panel_ids']}
        result=export(s,h.root,ref,h.root/'delivery',allow_partial=True)
        self.assertFalse(result['handoff_complete']);self.assertEqual(result['next_action'],'READY_FOR_PARTIAL_HANDOFF')
        self.assertEqual(result['status'],'PASS'); self.assertEqual(row['status'],'VISUAL_FAIL')
        table=(h.root/'delivery/问题表.md').read_text(encoding='utf-8-sig')
        self.assertIn('局部手指粘连',table); self.assertIn('P001_P001-r1.png',table)
        self.assertEqual(digest(h.root/'delivery/图片/P001_P001-r1.png'),row['output']['sha256'])
        self.assertEqual(result['image_calls'],0)

    def test_concentrated_class_two_is_one_merged_plan(self):
        h,s,r,it,_=self.fixture()
        issues=[issue(2,str(i),'accessory') for i in range(3)]
        d=decision(r,it,issues,'local_edit')
        self.assertEqual(decision_errors(d,r,it),[])
        self.assertEqual(plan(d,r)['route'],'local_edit');self.assertEqual(len(d['fix_now']),3)

    def test_distributed_class_two_can_regenerate(self):
        h,s,r,it,_=self.fixture()
        d=decision(r,it,[issue(2,'a','support'),issue(2,'b','accessory')],'regenerate')
        self.assertEqual(decision_errors(d,r,it),[])
        self.assertEqual(plan(d,r)['route'],'regenerate')

    def test_many_minor_issues_do_not_force_regeneration(self):
        h,s,r,it,_=self.fixture()
        d=decision(r,it,[issue(3,str(i)) for i in range(20)])
        self.assertEqual(decision_errors(d,r,it),[])
        self.assertFalse(plan(d,r)['image_call_allowed'])

    def test_major_error_cannot_be_downgraded_or_made_usable(self):
        h,s,r,it,_=self.fixture()
        for kind in ['identity','core_costume','extra_limb','limb_ownership','action_target']:
            d=decision(r,it,[issue(3,kind,kind)])
            self.assertTrue(decision_errors(d,r,it))
            d['issues'][0]['category']=1
            self.assertEqual(outcome(d),'MANUAL_PRIORITY')
        d=decision(r,it,[{**issue(2),'story_critical':True}])
        self.assertTrue(decision_errors(d,r,it))

    def test_second_attempt_minor_residue_does_not_open_third(self):
        h,s,r,it,d=self.fixture(); r['round_id']=2
        self.assertEqual(plan(d,r)['route'],'stop_diagnose')
        d=decision(r,it,[issue(2)],'local_edit')
        self.assertTrue(decision_errors(d,r,it))

    def test_old_adoption_uses_its_own_issues_and_qa(self):
        h,s,r,it,d=self.fixture()
        r=self.second_attempt(h,s,r,it);old=r['attempt_history'][0]
        self.assertEqual(selected(h.root,r)[0]['output'],old['output'])
        self.assertEqual(selected(h.root,r)[2],it)
        report=build(s,h.root)
        self.assertEqual(report['panels'][0]['attempt_id'],'P001-r1')
        self.assertEqual(report['panels'][0]['issues'][0]['problem'],'局部手指粘连')

    def test_repeated_failed_method_uses_existing_common_cause_report(self):
        h,s,r,it,d=self.fixture()
        d.update(method_key='same-edit',cause_key='grip')
        report={'stopped_methods':[{'method_key':'same-edit','cause_key':'grip'}]}
        ref=h.h.f.write('common-cause.json',report)
        s['episode_failure_diagnosis']={**report,'source':ref}
        self.assertTrue(repeated_method(s,h.root,d))
        d['different_plan']='改用已批准相反视图重新建立腕部遮挡，非重复措辞'
        self.assertFalse(repeated_method(s,h.root,d))

    def test_repair_priority_does_not_starve_first_round(self):
        h,s,r,it,d=self.fixture(); d=decision(r,it,[issue(2,'a','accessory')],'local_edit')
        ref=h.h.f.write('decision-repair.json',d);r['production_decisions'][r['attempt_id']]=ref
        old=copy.deepcopy(r);r.update(attempt_history=[old],status='REPAIR_AUTHORIZED',round_id=2,attempt_id='r2')
        self.assertGreater(priority(s,r,[],h.root),priority(s,{'status':'PENDING'},[],h.root))

    def test_unknown_missing_and_unreviewed_never_disappear(self):
        h,s,r,it,d=self.fixture();r['status']='RESULT_UNKNOWN'
        r.pop('adoption')
        r['call_evidence']=h.h.f.write('unknown-call.json',{'attempt_id':r['attempt_id'],
            'status':'RESULT_UNKNOWN','source_locator':'synthetic://unknown','evidence':'真实请求结果未知，不能重发'})
        report=build(s,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'INCOMPLETE')
        self.assertFalse(report['all_usable'])
        r.pop('output');r.pop('qa_report')
        report=build(s,h.root)
        self.assertEqual(report['panel_ids'],['P001','P002','P003','P004']);self.assertEqual(report['counts'],{'INCOMPLETE':4})

    def test_all_failed_observations_require_explicit_destinations(self):
        h,s,r,it,d=self.fixture()
        it['style_review']['status']='FAIL'
        self.assertTrue(decision_errors(d,r,it))
        self.assertIn('/style_review',findings(it))

    def test_cas_registration_preserves_status_history_and_budget(self):
        h,s,r,it,d=self.fixture();s['panels'][0].pop('production_decisions');s['panels'][0].pop('adoption')
        (h.root/'00_输入审计').mkdir(exist_ok=True)
        path=h.root/'00_输入审计/生产流程.json';path.write_text(json.dumps(s), encoding='utf-8')
        proposal=h.h.f.write('proposal.json',{'panels':[{'panel_id':'P001',
            'decision':h.h.f.write('bound-decision.json',d),'adopt':True,'adoption_reason':'主体稳定'}]})
        before=copy.deepcopy(s)
        self.assertEqual(register(path,digest(path),proposal)['status'],'DECISIONS_RECORDED')
        after=json.loads(path.read_text(encoding='utf-8-sig'));after['panels'][0].pop('adoption');after['panels'][0].pop('production_decisions')
        self.assertEqual(after,before)
        with self.assertRaises(ValueError):register(path,'stale',proposal)

    def test_delivery_index_invalidates_when_decision_changes(self):
        h,s,r,it,d=self.fixture();report=build(s,h.root);ref=h.h.f.write('delivery.json',report)
        r['adoption']['reason']='选择理由改变'
        with self.assertRaises(ValueError):gate(s,h.root,ref)

    def test_production_questions_exclude_manual_retouch_and_keep_event_identity(self):
        from review_policy import production_questions
        h,s,r,it,d=self.fixture()
        self.assertEqual(production_questions(s,h.root)['action'],'NO_PRODUCTION_QUESTION')
        d['issues'][0]['category']=2
        d.update(action='needs_user',question_kind='tradeoff',recommendation='推荐保留主体，人工修手')
        ref=h.h.f.write('tradeoff.json',d);r['production_decisions'][r['attempt_id']]=ref
        first=production_questions(s,h.root);second=production_questions(s,h.root)
        self.assertEqual(len(first['items']),1);self.assertEqual(first,second)
        self.assertEqual(first['items'][0]['panel_id'],'P001')
        pending=[{'event_id':first['items'][0]['event_id'],'status':'PENDING'}]
        self.assertEqual(production_questions(s,h.root,pending)['action'],'KEEP_PENDING')

    def test_local_user_decision_does_not_block_independent_real_gate(self):
        from _historical_fixture import evaluate
        h,s,r,it,d=self.fixture()
        d['issues'][0]['category']=2
        d.update(action='needs_user',question_kind='tradeoff',recommendation='保留主体，手部待人工决定')
        r['production_decisions'][r['attempt_id']]=h.h.f.write('local-question.json',d)
        result=evaluate(s,h.root)
        self.assertEqual(result['eligible_panel_ids'],['P002','P003','P004'],result)
        self.assertEqual(r['status'],'VISUAL_FAIL')

    def test_incremental_review_does_not_repeat_settled_failure(self):
        from review_queue import build_queue
        h,s,r,it,d=self.fixture()
        q=build_queue(s,h.root,{'batch_id':'EPISODE','panel_ids':['P001']},incremental=True)
        self.assertEqual(q['items'],[])
        d['issues'][0]['handling']='新决定另存'
        # A changed file under an old hash is invalid evidence, not a reusable decision.
        (h.root/r['production_decisions'][r['attempt_id']]['path']).write_text(json.dumps(d), encoding='utf-8')
        q=build_queue(s,h.root,{'batch_id':'EPISODE','panel_ids':['P001']},incremental=True)
        self.assertEqual(len(q['items']),1)

    def test_unauthorized_third_round_and_fake_first_round_block_handoff(self):
        h,s,r,it,d=self.fixture()
        r['round_id']=3
        with self.assertRaises(ValueError):build(s,h.root)
        r['round_id']=1;r['attempt_history']=[{'attempt_id':'hidden'}]
        with self.assertRaises(ValueError):build(s,h.root)

    def test_major_material_is_exportable_but_never_all_usable(self):
        h,s,r,it,d=self.fixture();d['issues'][0].update(category=1,kind='limb_ownership')
        ref=h.h.f.write('major.json',d);r['production_decisions'][r['attempt_id']]=ref;r['adoption']['decision']=ref
        report=build(s,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'MANUAL_PRIORITY')
        self.assertFalse(report['all_usable'])

    def test_category_three_alone_cannot_trigger_tradeoff_question(self):
        h,s,r,it,d=self.fixture()
        d.update(action='needs_user',question_kind='tradeoff',recommendation='是否修手指')
        self.assertTrue(decision_errors(d,r,it))

    def test_identity_fail_cannot_be_relabelled_as_minor_finger(self):
        h,s,r,it,d=self.fixture()
        it['dimension_review']['identity'].update(status='FAIL')
        d['issues'][0]['observations'].append('/dimension_review/identity')
        self.assertTrue(decision_errors(d,r,it))

    def test_unfilled_original_qa_flag_remains_incomplete(self):
        from codex_reference_contract import read_json,checked_file
        h,s,r,it,d=self.fixture()
        qa=read_json(checked_file(h.root,r['qa_report']));qa['panels'][0]['camera_match']=None
        r['qa_report']=h.h.f.write('qa-missing-flag.json',qa);d['qa_report']=r['qa_report']
        ref=h.h.f.write('decision-missing-flag.json',d)
        r['production_decisions'][r['attempt_id']]=ref;r['adoption']['decision']=ref
        report=build(s,h.root)
        self.assertEqual(report['panels'][0]['outcome'],'INCOMPLETE')
        self.assertTrue(any('camera_match' in x for x in report['panels'][0]['incomplete_reasons']))

    def test_regenerate_keeps_comparison_source_without_carrying_wrong_image(self):
        from visual_evidence import repair_source_errors, repair_binding_errors
        h,s,r,it,d=self.fixture()
        p={'visual_evidence_policy':'visual_evidence_v1','production_policy':POLICY,
           'operation':'repair','repair_method':'regenerate',
           'repair_source':{'image_sha256':r['output']['sha256'],'source_attempt_id':r['attempt_id'],
                            'selection_reason':'仅供返后比较','preserved_features':['保留脸型']},
           'prompt':'保留脸型','reference_images':[]}
        self.assertEqual(repair_source_errors(p),[])
        self.assertEqual(repair_binding_errors(p,r),[])
        p['reference_images']=[r['output']]
        self.assertTrue(repair_source_errors(p))
        p['reference_images']=[];p.pop('production_policy')
        self.assertTrue(repair_source_errors(p))

    def test_final_approval_cannot_turn_incomplete_scope_into_completed_delivery(self):
        from codex_reference_contract import read_json,checked_file
        h,s,r,it,d=self.fixture()
        qa=read_json(checked_file(h.root,r['qa_report']));qa['panels'][0]['camera_match']=None
        r['qa_report']=h.h.f.write('qa-incomplete.json',qa);d['qa_report']=r['qa_report']
        decision_ref=h.h.f.write('decision-incomplete.json',d)
        r['production_decisions'][r['attempt_id']]=decision_ref;r['adoption']['decision']=decision_ref
        report=build(s,h.root);self.assertFalse(report['handoff_complete'])
        ref=h.h.f.write('delivery-incomplete.json',report)
        s['gates']['final']={**h.h.approve([*report['artifacts'],ref]),'panel_ids':report['panel_ids']}
        result=gate(s,h.root,ref)
        self.assertEqual(result['status'],'HOLD');self.assertEqual(result['next_action'],'COMPLETE_SOURCE_SCOPE')
        with self.assertRaises(ValueError):export(s,h.root,ref,h.root/'must-not-export')
        self.assertFalse((h.root/'must-not-export').exists())

    def test_annotated_major_material_never_claims_all_images_usable(self):
        h,s,r,it,d=self.fixture()
        major=issue(1,kind='major_structure');d.update(issues=[major],manual=[major['id']])
        ref=h.h.f.write('major-material.json',d)
        r['production_decisions'][r['attempt_id']]=ref;r['adoption']['decision']=ref
        report=build(s,h.root)
        self.assertFalse(report['handoff_complete']);self.assertFalse(report['all_usable'])
        self.assertEqual(report['panels'][0]['outcome'],'MANUAL_PRIORITY')


if __name__=='__main__':unittest.main()
