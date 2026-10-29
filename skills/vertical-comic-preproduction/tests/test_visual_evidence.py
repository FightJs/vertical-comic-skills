"""Behavioral contracts for actual comic continuity, detail review and repairs."""
import _historical_fixture
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from visual_evidence import (POLICY, context_for, execution_block, packet_errors,
    shot_collection_errors, review_template, review_errors, repair_source_errors,
    repair_binding_errors, comparison_errors, basis_errors)


def fixture():
    basis = {'visual_evidence_policy': POLICY, 'reference_files': [{'sha256': 'scene'}, {'sha256': 'costume'}],
        'scene_layouts': {'HALL': {'layout_id': 'hall-v1',
            'entities': {'TABLE': '主桌', 'STAGE': '舞台'},
            'relations': [{'id': 'table-stage', 'subject': 'TABLE', 'object': 'STAGE',
                           'expected': '主桌位于舞台前方，二者之间没有其他宾客桌', 'reference_sha256': 'scene'}]}},
        'appearance_details': {'earring': {'subject_id': 'A', 'costume_state': 'silver',
            'expected': '单层水滴耳坠，顶部小菱形连接件', 'reference_sha256': 'costume'}}}
    panel = {'panel_id': 'P001', 'scene_id': 'HALL', 'visual_evidence_policy': POLICY,
        'framing': {'background_level': 'anchor_only'}, 'memory_tags': [],
        'continuity_contract': {'subjects': {'A': {'costume_state': 'silver'}}},
        'reference_images': [{'sha256': 'scene'}, {'sha256': 'costume'}],
        'visual_evidence': {'scene_run_id': 'banquet', 'previous_panel_id': None,
            'spatial_applicability': 'REQUIRED', 'spatial_reason': '主桌与舞台同时提供定位',
            'blocking': {'A': {'position': 'SEAT-1', 'facing': 'TABLE', 'presence': 'present', 'basis': '已批座位'}},
            'changes': [], 'visibility': {
                'A': {'status': 'visible', 'expected': '人物位于主桌靠舞台一侧座位', 'basis': '本格机位'},
                'STAGE': {'status': 'visible', 'expected': '人物背后为舞台，无宾客桌插入', 'basis': '场景原板'}},
            'hands': {'applicability': 'REQUIRED', 'basis': '右手握杯'},
            'detail_visibility': {'earring': {'status': 'visible', 'basis': '双耳入画'}},
            'checks': [
                {'id': 'S1', 'kind': 'space', 'subject_ids': ['TABLE', 'STAGE'], 'expected': '舞台和主桌之间不增加宾客桌'},
                {'id': 'P1', 'kind': 'presence', 'subject_ids': ['A'], 'expected': '人物仍在SEAT-1，没有换座位'},
                {'id': 'H1', 'kind': 'hand', 'subject_ids': ['A.right_hand'], 'expected': '拇指与掌部连接自然，杯柄遮挡其余手指'},
                {'id': 'D1', 'kind': 'accessory', 'subject_ids': ['A'], 'detail_id': 'earring', 'expected': '耳坠只有一层水滴'},
                {'id': 'Q1', 'kind': 'clarity', 'subject_ids': ['A'], 'expected': '焦内眼线、首饰和手指轮廓可辨，无涂抹'}]}}
    panel['visual_evidence_context'] = context_for(basis, panel)
    panel['visual_execution_block'] = execution_block(panel)
    panel['prompt'] = panel['visual_execution_block']
    return basis, panel


def reviewed(panel):
    item = {'image_sha256': 'actual-image', 'image_size': [1000, 1200]}
    review = review_template(panel)
    review['full_image_review'] = {'status': 'PASS', 'evidence': '实际全图与当前批准布局对照'}
    for row in review['observations']:
        row.update(status='PASS', reviewer='test reviewer', observed='逐项实际观察记录：'+row['expected'],
                   view={'image_sha256': 'actual-image', 'scale': 'original_pixels', 'region': [20,30,400,500]})
    ev=panel['visual_evidence']
    for name, plan in [('visibility_observations', ev['visibility']), ('detail_visibility_observations', ev['detail_visibility'])]:
        review[name] = {key: {'status': 'PASS', 'actual_visibility': row['status'], 'observed': '具体入画/遮挡已核对'} for key,row in plan.items()}
    item['visual_evidence_review'] = review
    return item


def actual_fixture(test):
    """Actual gates and actual files with synthetic pixels/approvals, without mocks."""
    from test_half_workflow import ActualHalfGateTests
    h=ActualHalfGateTests('test_real_qa_round_report_and_first_half_approval')
    h.setUp();test.addCleanup(h.doCleanups)
    extra,template=fixture();p=h.panel
    basis=json.loads((h.root/h.state['visual_basis']['path']).read_text(encoding='utf-8-sig'))
    layout=extra['scene_layouts']['HALL']
    layout['relations'][0]['reference_sha256']=p['reference_images'][0]['sha256']
    detail=extra['appearance_details']['earring']
    detail.update(costume_state='D_A',reference_sha256=p['reference_images'][1]['sha256'])
    basis.update(visual_evidence_policy=POLICY,scene_layouts={'S':layout},appearance_details={'earring':detail})
    p.update(visual_evidence_policy=POLICY,visual_evidence=template['visual_evidence'])
    p['visual_evidence_context']=context_for(basis,p)
    p['visual_execution_block']=execution_block(p)
    p['prompt']+='\n'+p['visual_execution_block']
    (h.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n')
    h.h.shots[0].update(copy.deepcopy(p))
    h.h.manifest['visual_evidence_policy']=POLICY
    h.state['visual_evidence_policy']=POLICY
    h.state['visual_basis']=h.h.f.write('basis-quality.json',basis)
    h.state['gates']['visual_basis']=h.h.approve([h.state['source_script'],h.state['source_snapshot'],h.state['visual_basis']])
    h.sync()
    return h,basis


def finish_quality_review(h, record, *, failure=False):
    qa=json.loads((h.root/record['qa_report']['path']).read_text(encoding='utf-8-sig'));item=qa['panels'][0]
    visual=reviewed(h.panel)['visual_evidence_review']
    for row in visual['observations']:
        row['view'].update(image_sha256=item['image_sha256'],region=[0,0,90,160])
        if failure and row['kind']=='hand':row.update(status='FAIL',observed='SYNTHETIC extra digit failure')
    item['visual_evidence_review']=visual
    record['qa_report']=h.h.f.write('quality-reviewed.json',qa)
    return qa


class VisualEvidenceTests(unittest.TestCase):
    def test_legacy_contract_is_not_silently_migrated(self):
        self.assertEqual(packet_errors({}, {}, {}, {}), [])
        self.assertEqual(review_errors({}, {}), [])
        self.assertEqual(repair_source_errors({'operation':'repair'}), [])

    def test_actual_prompt_and_approved_context_are_required(self):
        basis,p=fixture()
        self.assertEqual(packet_errors(basis,p,p,basis), [])
        bad=copy.deepcopy(p);bad['prompt']='人物在酒店'
        self.assertTrue(packet_errors(basis,p,bad,basis))
        bad=copy.deepcopy(p);bad['visual_evidence_context']['layout']['relations'][0]['expected']='舞台移到门外'
        self.assertTrue(packet_errors(basis,p,bad,basis))
        bad=copy.deepcopy(p);bad.pop('visual_evidence_policy')
        self.assertTrue(packet_errors(basis,p,bad,basis))

    def test_current_costume_details_cannot_be_omitted_or_reference_dropped(self):
        basis,p=fixture();bad=copy.deepcopy(p)
        bad['visual_evidence']['detail_visibility']={};bad['visual_evidence_context']['details']={}
        self.assertTrue(packet_errors(basis,p,bad,basis))
        bad=copy.deepcopy(p);bad['reference_images']=[{'sha256':'scene'}]
        self.assertTrue(packet_errors(basis,p,bad,basis))

    def test_world_state_survives_camera_change_and_scene_cut(self):
        basis,p=fixture();q=copy.deepcopy(p);q['panel_id']='P003';q['visual_evidence']['previous_panel_id']='P001'
        q['visual_evidence']['visibility']['A']['expected']='人物投影到画面右侧，但仍坐SEAT-1'
        other={'panel_id':'P002','scene_id':'OTHER'}
        self.assertEqual(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,other,q]},blocked=['P002']), [])
        q['visual_evidence']['blocking']['A']['position']='SEAT-2'
        self.assertTrue(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,q]}))
        q['visual_evidence']['changes']=[{'entity_id':'A','field':'position','from':'SEAT-1','to':'SEAT-2','basis':'源稿明确移动座位'}]
        self.assertEqual(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,q]}), [])

    def test_people_cannot_disappear_by_deleting_their_state(self):
        basis,p=fixture();q=copy.deepcopy(p);q['panel_id']='P002';q['visual_evidence']['previous_panel_id']='P001'
        q['visual_evidence']['blocking']={}
        self.assertTrue(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,q]}))

    def test_same_hotel_asset_does_not_merge_different_physical_rooms(self):
        basis,p=fixture();layout=basis['scene_layouts'].pop('HALL');layout['scene_id']='HOTEL'
        basis['scene_layouts']={'banquet':copy.deepcopy(layout),'corridor':copy.deepcopy(layout)}
        p['scene_id']='HOTEL';p['visual_evidence']['space_id']='banquet'
        q=copy.deepcopy(p);q['panel_id']='P002';q['visual_evidence']['space_id']='corridor'
        q['visual_evidence']['scene_run_id']='walk';q['visual_evidence']['blocking']['A']['position']='走廊东侧'
        back=copy.deepcopy(p);back['panel_id']='P003';back['visual_evidence']['previous_panel_id']='P001'
        self.assertEqual(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,q,back]}),[])
        back['visual_evidence']['blocking']['A']['position']='另一个座位'
        self.assertTrue(shot_collection_errors(basis,basis,{'visual_evidence_policy':POLICY,'panels':[p,q,back]}))

    def test_true_occlusion_does_not_require_five_visible_fingers(self):
        _,p=fixture();item=reviewed(p)
        self.assertEqual(review_errors(p,item), [])
        # A global PASS or thumbnail alone cannot replace the original-pixel observation.
        item['visual_evidence_review']['observations'][2]['view']['scale']='thumbnail'
        self.assertTrue(review_errors(p,item))

    def test_returned_image_and_regions_are_bound_not_merely_checklist_pass(self):
        _,p=fixture();item=reviewed(p)
        item['image_sha256']='different-attempt'
        self.assertTrue(review_errors(p,item))

    def test_declared_image_size_cannot_enlarge_the_real_inspection_bounds(self):
        _,p=fixture();item=reviewed(p)
        item['image_size']=[9000,9000]
        item['visual_evidence_review']['observations'][2]['view']['region']=[0,0,8000,8000]
        errors=review_errors(p,item,image_size=(1000,1200))
        self.assertTrue(any('尺寸与实际' in e for e in errors))
        self.assertTrue(any('有效区域' in e for e in errors))
        item=reviewed(p);item['visual_evidence_review']['observations'][3]['view']['region']=[0,0,3000,3000]
        self.assertTrue(review_errors(p,item))
        item=reviewed(p);item['visual_evidence_review']['visibility_observations']['A']['actual_visibility']='out_of_frame'
        self.assertTrue(review_errors(p,item))

    def test_real_predecessor_change_invalidates_only_comparison(self):
        _,p=fixture();p['visual_evidence']['previous_panel_id']='P000';item=reviewed(p)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'prior.png';path.write_bytes(b'real returned evidence')
            import hashlib
            ref={'path':'prior.png','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            item['visual_evidence_review']['continuity_comparisons']=[{'panel_id':'P000','image':ref,'status':'PASS','observed':'原座位、舞台及人物变化合理'}]
            self.assertEqual(comparison_errors(p,item,{'P000':{'output':ref}},d), [])
            self.assertTrue(comparison_errors(p,item,{'P000':{'output':{**ref,'sha256':'new'}}},d))

    def test_repair_requires_actual_same_panel_base_and_preserved_fixes(self):
        _,p=fixture();p['operation']='repair'
        self.assertTrue(repair_source_errors(p))
        p['repair_source']={'image_sha256':'base','source_attempt_id':'P001-r1',
            'selection_reason':'原始PNG线条清晰，集中修手，保留已确认耳环', 'preserved_features':['保留单层水滴耳环']}
        p['reference_images'].append({'sha256':'base','alias':'@REPAIR_TARGET','role':'edit_target'})
        p['reference_bindings']=[{'alias':'@REPAIR_TARGET','purpose':'framing'}]
        p['prompt']+='\n保留单层水滴耳环'
        self.assertEqual(repair_source_errors(p), [])
        self.assertTrue(repair_binding_errors(p,{'attempt_id':'P002-r1','output':{'sha256':'base'}}))
        self.assertEqual(repair_binding_errors(p,{'attempt_id':'P001-r1','output':{'sha256':'base'}}), [])

    def test_failed_local_review_is_required_but_does_not_block_failure_registration(self):
        from _historical_fixture import evaluate
        from historical_engines.batch_round import attempt_errors
        h,_=actual_fixture(self)
        self.assertEqual(evaluate(h.state,h.root,'generate','P001')['status'],'PASS')
        record=h.returned(fail=True)
        self.assertTrue(attempt_errors(h.state,h.root,record))
        finish_quality_review(h,record,failure=True)
        self.assertEqual(attempt_errors(h.state,h.root,record),[])

    def test_fully_reviewed_return_uses_actual_QA_gate_without_mocks(self):
        from staged_workflow import qa_errors
        h,_=actual_fixture(self);record=h.returned()
        self.assertTrue(qa_errors(h.root,record))
        finish_quality_review(h,record)
        self.assertEqual(qa_errors(h.root,record),[])

    def test_edit_target_is_not_promoted_to_asset_or_style(self):
        from visual_evidence import repair_basis
        from codex_reference_contract import digest
        basis,p=fixture();p['operation']='repair'
        with tempfile.TemporaryDirectory() as d:
            image=Path(d)/'original-return.png';image.write_bytes(b'synthetic actual output')
            output={'path':image.name,'sha256':digest(image)}
            p['repair_source']={'source_attempt_id':'first','image_sha256':output['sha256'],
                'selection_reason':'原图清晰','preserved_features':['保留脸型']}
            p['prompt']+='\n保留脸型'
            p['reference_images'].append({**output,'alias':'@REPAIR_TARGET','role':'edit_target'})
            p['reference_bindings']=[{'alias':'@REPAIR_TARGET','purpose':'framing'}]
            state={'visual_evidence_policy':POLICY};record={'attempt_history':[{'attempt_id':'first','output':output}]}
            updated=repair_basis(state,d,p,basis,{'P001':record})
            self.assertIn(output,updated['reference_files']);self.assertNotIn(output,basis['reference_files'])
            p['reference_bindings'][0]['purpose']='style'
            with self.assertRaises(ValueError):repair_basis(state,d,p,basis,{'P001':record})

    def test_real_episode_repair_authorization_and_input_gate_keep_the_failed_image(self):
        from historical_engines.batch_round import snapshot
        from codex_reference_contract import digest
        from continuity_contract import reference_usage_block
        from production_runtime import authorize_episode_repair
        from historical_engines.batch_workflow import input_errors
        h,basis=actual_fixture(self)
        h.state['execution_mode']='episode_async_v1';h.h.manifest['execution_mode']='episode_async_v1'
        h.h.manifest['round_context']['batch_id']='EPISODE';h.sync()
        old=h.returned(fail=True);finish_quality_review(h,old,failure=True)
        panel=copy.deepcopy(h.panel)
        panel.update(operation='repair',prompt_file='P001/repair-prompt.txt',panel_json_file='P001/repair-panel.json',generation_execution={'status':'NOT_RUN'})
        target=copy.deepcopy(panel['reference_images'][0])
        target.update(alias='@REPAIR_TARGET',path=old['output']['path'],sha256=old['output']['sha256'],role='edit_target')
        panel['reference_images'].append(target)
        panel['reference_bindings'].append({'alias':'@REPAIR_TARGET','purpose':'framing','subject_ids':['P001'],
            'allowed_transfer':['composition','crop'],'forbidden_transfer':['pose']})
        usage=reference_usage_block(panel['reference_bindings'],panel['reference_images'])
        panel['prompt']=panel['prompt'].replace(panel['reference_usage_block'],usage);panel['reference_usage_block']=usage
        panel['repair_source']={'image_sha256':old['output']['sha256'],'source_attempt_id':old['attempt_id'],
            'selection_reason':'SYNTHETIC original returned PNG','preserved_features':['保留原脸型与耳环']}
        panel['repair_focus']={'failed_transfers':['pose']}
        panel['prompt']+='\n修正手指结构\n保留原脸型与耳环'
        (h.root/panel['prompt_file']).write_text(panel['prompt'], encoding='utf-8', newline='\n')
        h.h.f.write(panel['panel_json_file'],panel)
        packet={**h.h.manifest,'round_context':{'batch_id':'EPISODE','round_id':2,'attempt_id':'UNIT-R2'},'panels':[panel]}
        ref=h.h.f.write('repair-packet.json',packet)
        auth={'policy':'episode_repair_v1','panel_id':'P001','failed_attempt':snapshot(old),
            'route':'targeted_image_repair','reviewer':'SYNTHETIC','evidence':'SYNTHETIC hand failure',
            'repair_constraints':['修正手指结构'],'new_attempt_id':'UNIT-R2','new_package_manifest':ref,'new_shot_subset':old['shot_subset']}
        h.h.f.write('repair-auth.json',auth)
        path=h.root/'00_输入审计/生产流程.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(h.state), encoding='utf-8', newline='\n')
        self.assertEqual(authorize_episode_repair(path,digest(path),'repair-auth.json')['status'],'REPAIR_AUTHORIZED')
        state=json.loads(path.read_text(encoding='utf-8-sig'));row=state['panels'][0]
        self.assertEqual(input_errors(state,h.root,row,h.h.shots[0],basis,{'P001':row}),[])
        # Input gate must reject using a different panel's or unrecorded base.
        panel['repair_source']['source_attempt_id']='OTHER-PANEL'
        row['package_manifest']=h.h.f.write('repair-packet-bad.json',{**packet,'panels':[panel]})
        with self.assertRaises(ValueError):input_errors(state,h.root,row,h.h.shots[0],basis,{'P001':row})

    def test_actual_status_commit_rejects_invented_predecessor_comparison(self):
        from production_runtime import commit_updates
        from codex_reference_contract import digest
        h,_=actual_fixture(self)
        h.panel['visual_evidence']['previous_panel_id']='P000'
        h.h.shots[0]['visual_evidence']=copy.deepcopy(h.panel['visual_evidence']);h.sync()
        record=h.returned();qa=finish_quality_review(h,record)
        qa['panels'][0]['visual_evidence_review']['continuity_comparisons']=[{
            'panel_id':'P000','image':{'path':'invented.png','sha256':'invented'},
            'status':'PASS','observed':'SYNTHETIC invented comparison'}]
        record['qa_report']=h.h.f.write('invented-comparison.json',qa)
        record['status']='GENERATED'
        path=h.root/'00_输入审计/生产流程.json';path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(h.state), encoding='utf-8', newline='\n')
        before=path.read_bytes()
        with self.assertRaises(ValueError):
            commit_updates(path,digest(path),[{'panel_id':'P001','attempt_id':record['attempt_id'],
                'round_id':record['round_id'],'status':'VISUAL_PASS'}])
        self.assertEqual(path.read_bytes(),before)

    def test_unapproved_layout_source_is_rejected(self):
        basis,_=fixture();basis['scene_layouts']['HALL']['relations'][0]['reference_sha256']='unapproved'
        self.assertTrue(basis_errors(basis))

    def test_atlas_must_include_the_actual_jewelry_region(self):
        from visual_evidence import detail_carried
        detail={'reference_sha256':'board','source_region':[20,30,40,50]}
        atlas=[{'source_regions':[{'source_file':{'sha256':'board'},'crop_rect_pixels':[0,0,10,10]}]}]
        self.assertFalse(detail_carried(detail,atlas))
        atlas[0]['source_regions'][0]['crop_rect_pixels']=[10,20,50,60]
        self.assertTrue(detail_carried(detail,atlas))

    def test_review_derivatives_preserve_original_pixels_and_do_not_fill_pass(self):
        from PIL import Image
        from visual_evidence import write_review_regions
        with tempfile.TemporaryDirectory() as d:
            original=Path(d)/'original.png'
            source=Image.new('RGB',(30,40),(120,40,210));source.save(original)
            before=original.read_bytes()
            result=write_review_regions(original,[{'check_id':'H1','region':[4,5,20,30]}],Path(d)/'review')
            self.assertEqual(original.read_bytes(),before)
            self.assertEqual(result['status'],'UNREVIEWED')
            with Image.open(result['regions'][0]['inspection_file']['path']) as region:
                self.assertEqual(region.size,(16,25));self.assertEqual(region.tobytes(),source.crop((4,5,20,30)).tobytes())

    def test_real_tool_input_export_rejects_missing_constraint_block(self):
        from test_codex_reference_contract import ReferenceTests
        from codex_reference_contract import validate_panel, final_prompt
        fx=ReferenceTests('test_valid_reference_route');fx.setUp()
        self.addCleanup(fx.doCleanups)
        basis,template=fixture();p=fx.panel
        basis['scene_layouts']['S']=basis['scene_layouts'].pop('HALL')
        basis['reference_files']=fx.refs
        basis['scene_layouts']['S']['relations'][0]['reference_sha256']=fx.refs[1]['sha256']
        basis['appearance_details']['earring'].update(costume_state='D_A',reference_sha256=fx.refs[2]['sha256'])
        p.update(visual_evidence_policy=POLICY,visual_evidence=template['visual_evidence'])
        p['visual_evidence_context']=context_for(basis,p)
        p['visual_execution_block']=execution_block(p)
        p['prompt']=final_prompt(p['reference_usage_block']+'\n'+p['visual_execution_block'],p['negative_prompt'])
        (fx.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n')
        errors,plan=validate_panel(p,fx.root)
        self.assertEqual(errors,[]);self.assertIn(p['visual_execution_block'],plan['arguments']['prompt'])
        p['prompt']=final_prompt(p['reference_usage_block'],p['negative_prompt'])
        (fx.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n')
        errors,plan=validate_panel(p,fx.root)
        self.assertIsNone(plan);self.assertTrue(any('具体空间' in e for e in errors))

    def test_actual_qa_entry_rejects_thumbnail_only_and_accepts_complete_observations(self):
        from test_codex_reference_contract import ReferenceTests
        from codex_reference_contract import digest
        from continuity_contract import dimension_template,check_dimension_report
        fx=ReferenceTests('test_valid_reference_route');fx.setUp();self.addCleanup(fx.doCleanups)
        _,p=fixture();p['scene_id']='S'
        # Use the existing full reference/continuity fixture; all pixels are synthetic test data.
        actual=fx.panel
        actual.update(visual_evidence_policy=POLICY,visual_evidence=p['visual_evidence'],visual_evidence_context=p['visual_evidence_context'])
        manifest_path=fx.root/'manifest.json';manifest_path.write_text(json.dumps(fx.manifest), encoding='utf-8', newline='\n')
        image=fx.root/fx.refs[2]['path'];item=reviewed(actual)
        item.update(panel_id='P001',image=str(image),image_sha256=digest(image),image_size=[90,160],ratio_check='PASS',dimension_review=dimension_template(actual))
        for row in item['visual_evidence_review']['observations']:
            row['view'].update(image_sha256=digest(image),region=[0,0,90,160])
        for row in item['dimension_review'].values():row.update(status='PASS',reviewer='synthetic reviewer',evidence='synthetic protocol observation')
        report={'source_manifest_sha256':digest(manifest_path),'panels':[item],'errors':[]}
        self.assertEqual(check_dimension_report(fx.manifest,report,manifest_path)['errors'],[])
        item['visual_evidence_review']['observations'][2]['view']['scale']='thumbnail'
        self.assertTrue(check_dimension_report(fx.manifest,report,manifest_path)['errors'])

    def test_new_initializer_enables_quality_but_does_not_overwrite_old_state(self):
        import subprocess
        script=Path(__file__).resolve().parents[1]/'scripts/init_preproduction.py'
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'episode'
            cmd=[sys.executable, '-X', 'utf8',str(script),'--output',str(root),'--book','SYNTHETIC_TEST','--episode','E001','--panel-count','1']
            subprocess.run(cmd,check=True,capture_output=True)
            for name in ['00_输入审计/生产流程.json','01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json']:
                self.assertEqual(json.loads((root/name).read_text(encoding='utf-8-sig'))['visual_evidence_policy'],POLICY)
            path=root/'00_输入审计/生产流程.json';state=json.loads(path.read_text(encoding='utf-8-sig'));state.pop('visual_evidence_policy');path.write_text(json.dumps(state), encoding='utf-8', newline='\n');before=path.read_bytes()
            subprocess.run(cmd,check=True,capture_output=True)
            self.assertEqual(path.read_bytes(),before)


if __name__ == '__main__': unittest.main()
