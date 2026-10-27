"""Background compiler/gates, synthetic contracts and real isolated CLI runs. No paid calls."""
from _portable_config import config_path
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from visual_evidence import (BACKGROUND_POLICY, POLICY, background_config_errors,
    binding_errors, basis_errors, context_for, execution_block, framing_execution_block,
    panel_errors, packet_errors, review_template, review_errors)
from test_visual_evidence import fixture, reviewed as original_reviewed
BASE = Path(__file__).resolve().parents[1]


def background_fixture(mode='scene_flat'):
    basis, panel = fixture()
    basis['background_policy'] = panel['background_policy'] = BACKGROUND_POLICY
    basis['scene_background_profiles'] = {'hall-night': {
        'profile_id': 'hall-night', 'scene_id': 'HALL', 'space_id': 'HALL',
        'scene_run_id': 'banquet', 'base_color': '暖灰米色', 'line_color': '灰褐色',
        'lighting': '左前上方暖光，人物受光不变', 'reference_sha256': 'scene'}}
    panel['framing'].update(background_treatment=mode, body_crop='waist_up',
        focus='握杯表情', required_visible=['表情', '握杯手与杯柄'],
        background_plan={'reason':'本格重点是握杯反应', 'profile_id':'hall-night',
            'retain':[{'id':'TABLE','expected':'下缘主桌桌沿，手与杯柄完整入画'}],
            'omit':[{'id':'WALL_GRAIN','expected':'远处墙面纹理'}],
            'sharp_focus':['眼睛、单层水滴耳坠、右手与杯柄']})
    panel['visible_region']='腰以上，右手杯柄不截断，主桌桌沿在下缘'
    recompile(basis,panel)
    return basis,panel


def reviewed(panel):
    item=original_reviewed(panel)
    obs=item['visual_evidence_review']['background_observation']
    obs.update(image_sha256=item['image_sha256'],observed='SYNTHETIC模式观察记录',sharpness_observed='SYNTHETIC眼睛耳饰手部轮廓记录')
    for key in ('retained','omitted'):
        obs[key]={entity:'SYNTHETIC逐项观察：'+entity for entity in obs[key]}
    return item


def recompile(basis,panel):
    panel['visual_evidence_context']=context_for(basis,panel)
    panel['visual_execution_block']=execution_block(panel)
    panel['prompt']=panel['visual_execution_block']


def actual_background_packet(test):
    from test_codex_reference_contract import ReferenceTests
    from codex_reference_contract import validate_panel
    fx=ReferenceTests('test_valid_reference_route');fx.setUp();test.addCleanup(fx.doCleanups)
    fx.use_no_composition_reference()
    b,template=background_fixture();p=fx.panel
    original_prompt=p['prompt']
    p['continuity_contract']['required_visible']=copy.deepcopy(template['framing']['required_visible'])
    p.update(background_policy=BACKGROUND_POLICY,visual_evidence_policy=POLICY,
             visual_evidence=copy.deepcopy(template['visual_evidence']),
             framing=copy.deepcopy(template['framing']),visible_region=template['visible_region'])
    profile=b['scene_background_profiles']['hall-night'];profile.update(scene_id=p['scene_id'],space_id=p['scene_id'])
    b['scene_layouts']={p['scene_id']:b['scene_layouts']['HALL']}
    p['visual_evidence_context']=context_for(b,p)
    p['visual_execution_block']=execution_block(p)
    p['prompt']=original_prompt+'\n'+p['visual_execution_block']
    (fx.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n')
    errors,_=validate_panel(p,fx.root);test.assertEqual(errors,[])
    return fx,p


class BackgroundPolicyTests(unittest.TestCase):
    def test_all_four_modes_and_legacy_depth_keep_original_invariants(self):
        for mode in ('clear_limited','scene_flat','scene_softened','scene_outline','approved_depth_of_field'):
            with self.subTest(mode=mode):
                b,p=background_fixture()
                p['framing']['background_treatment']=mode
                if mode=='approved_depth_of_field':p['framing']['background_treatment_basis']='SYNTHETIC批准：脸手清楚，远景指定景深'
                recompile(b,p)
                self.assertEqual(packet_errors(b,p,p,b),[])
                self.assertIn('下缘主桌桌沿',p['prompt'])
                self.assertIn('拇指与掌部连接自然',p['prompt'])
                self.assertIn('单层水滴',p['prompt'])
                self.assertEqual(p['prompt'].count('本格构图与背景处理'),1)

    def test_retained_and_omitted_same_id_is_rejected(self):
        b,p=background_fixture();p['framing']['background_plan']['omit'][0]['id']='TABLE'
        self.assertTrue(panel_errors(p))
        with self.assertRaises(ValueError):execution_block(p)

    def test_required_information_cannot_be_omitted(self):
        _,p=background_fixture();p['framing']['background_plan']['omit'][0]['expected']='握杯手与杯柄'
        self.assertTrue(panel_errors(p))

    def test_missing_plan_focus_or_reason_cannot_compile(self):
        for key in ('reason','profile_id','retain','omit','sharp_focus'):
            b,p=background_fixture();del p['framing']['background_plan'][key]
            self.assertTrue(panel_errors(p),key)
            with self.assertRaises((ValueError,KeyError)):execution_block(p)

    def test_profiles_cannot_cross_scene_space_or_continuous_state(self):
        for field in ('scene_id','space_id','scene_run_id'):
            b,p=background_fixture();b['scene_background_profiles']['hall-night'][field]='OTHER'
            p['visual_evidence_context']=context_for(b,p)
            self.assertTrue(panel_errors(p),field)

    def test_actual_reference_and_approved_profile_are_required(self):
        b,p=background_fixture();p['reference_images']=[{'sha256':'costume'}]
        self.assertTrue(packet_errors(b,p,p,b))
        b,p=background_fixture();p['visual_evidence_context']['background_profile']['base_color']='红'
        self.assertTrue(packet_errors(b,p,p,b))
        b,p=background_fixture();b['scene_background_profiles']['hall-night']['reference_sha256']='unapproved'
        self.assertTrue(basis_errors(b))

    def test_background_policy_cannot_be_dropped_from_only_one_document(self):
        b,p=background_fixture();bad=copy.deepcopy(p);bad.pop('background_policy')
        self.assertTrue(packet_errors(b,p,bad,b))
        self.assertTrue(binding_errors(b,{'visual_evidence_policy':POLICY}))

    def test_new_mode_cannot_be_smuggled_into_legacy_packet(self):
        _,p=background_fixture();p.pop('background_policy')
        self.assertTrue(panel_errors(p))

    def test_context_free_shot_check_is_structural_but_compiler_needs_profile(self):
        from visual_evidence import framing_errors
        b,p=background_fixture();p.pop('visual_evidence_context')
        self.assertEqual(framing_errors(p),[])
        with self.assertRaises(ValueError):framing_execution_block(p)
        self.assertEqual(panel_errors(p,context_for(b,p)),[])

    def test_bed_support_and_contact_survive_background_simplification(self):
        b,p=background_fixture();p['visual_evidence']['checks'].extend([
            {'id':'BED','kind':'space','subject_ids':['A','BED'], 'expected':'身体承托在床垫，被单覆盖至腰，床沿与地板分离'},
            {'id':'CONTACT','kind':'contact','subject_ids':['A','CUP'],'expected':'右手拇指与食指接触杯柄',
             'actor':'A','actor_limb':'自身右臂','target':'CUP','target_part':'杯柄','visible_path':'肩肘腕连续至杯柄'}])
        recompile(b,p)
        self.assertIn('身体承托在床垫',p['prompt'])
        self.assertIn('肩肘腕连续至杯柄',p['prompt'])
        p['visual_evidence']['spatial_applicability']='NOT_VISIBLE'
        self.assertTrue(panel_errors(p))

    def test_environment_omission_is_not_person_departure(self):
        b,p=background_fixture();p['framing']['background_plan']['omit'].append({'id':'STAGE','expected':'舞台内部纹理不绘出'})
        p['visual_evidence']['visibility']['STAGE']['status']='omitted_by_design'
        recompile(b,p);self.assertEqual(panel_errors(p),[])
        p['visual_evidence']['visibility']['A']['status']='omitted_by_design'
        self.assertTrue(panel_errors(p))

    def test_accessory_visibility_cannot_be_omitted_by_background_design(self):
        b,p=background_fixture();p['visual_evidence']['detail_visibility']['earring']['status']='omitted_by_design'
        self.assertTrue(panel_errors(p))

    def test_qa_template_never_prefills_pass_and_changes_invalidate_old_review(self):
        b,p=background_fixture();item=reviewed(p)
        self.assertEqual(review_errors(p,item),[])
        self.assertEqual(review_template(p)['full_image_review']['status'],'UNREVIEWED')
        p['framing']['background_treatment']='scene_outline';recompile(b,p)
        self.assertTrue(review_errors(p,item))

    def test_background_observation_must_be_actual_complete_and_image_bound(self):
        b,p=background_fixture();item=reviewed(p)
        for mutate in ('drop','hash','retained','sharpness'):
            bad=copy.deepcopy(item);review=bad['visual_evidence_review']
            if mutate=='drop':review.pop('background_observation')
            elif mutate=='hash':review['background_observation']['image_sha256']='different'
            elif mutate=='retained':review['background_observation']['retained']={}
            else:review['background_observation']['sharpness_observed']=''
            self.assertTrue(review_errors(p,bad),mutate)

    def test_person_cannot_be_listed_as_omitted_and_retained_anchor_cannot_be_offscreen(self):
        _,p=background_fixture();p['framing']['background_plan']['omit'].append({'id':'A','expected':'人物不画'})
        self.assertTrue(panel_errors(p))
        _,p=background_fixture();p['visual_evidence']['visibility']['TABLE']={'status':'out_of_frame','expected':'不见','basis':'测试'}
        self.assertTrue(panel_errors(p))

    def test_retained_anchor_plan_cannot_change_after_B(self):
        b,p=background_fixture();bad=copy.deepcopy(p)
        bad['framing']['background_plan']['retain'][0]['expected']='主桌移到门外'
        recompile(b,bad);self.assertTrue(packet_errors(b,p,bad,b))

    def test_actual_prompt_without_current_background_block_is_rejected(self):
        b,p=background_fixture();p['prompt']='人物握杯，背景随意'
        self.assertTrue(packet_errors(b,p,p,b))

    def test_repair_guard_checks_background_even_without_visual_target(self):
        from repair_input_guard import repair_errors
        _,p=background_fixture();p['operation']='repair';p['prompt']='仅换背景'
        self.assertTrue(any('背景' in e for e in repair_errors(p)))

    def test_actual_package_signature_changes_with_plan(self):
        from production_runtime import package_signature
        fx,p=actual_background_packet(self)
        one=package_signature({'panels':[p]},fx.root)
        p['framing']['background_plan']['reason']='本格仍是握杯，修改取舍说明'
        two=package_signature({'panels':[p]},fx.root)
        self.assertNotEqual(one,two)

    def test_real_QA_cli_keeps_background_observation_unreviewed(self):
        fx,p=actual_background_packet(self)
        fx.manifest['background_policy']=BACKGROUND_POLICY
        fx.manifest['visual_evidence_policy']=POLICY
        fx.write('manifest.json',fx.manifest)
        output=fx.root/'bg-qa'
        subprocess.run([sys.executable, '-X', 'utf8','-B',str(BASE/'scripts/make_generation_qa.py'),
            '--package',str(fx.root),'--manifest','manifest.json','--images',str(fx.root),
            '--image-path',str(fx.root/fx.refs[2]['path']),'--output',str(output),
            '--skip-contact-sheet'],check=True,capture_output=True)
        report=json.loads((output/'生成图QA报告.json').read_text(encoding='utf-8-sig'))
        self.assertEqual(report['errors'],[])
        row=report['panels'][0]
        self.assertEqual(row['visual_evidence_review']['background_observation']['observed'],'')
        self.assertEqual(row['framing_review_focus']['background_plan'],p['framing']['background_plan'])
        self.assertEqual(row['dimension_review']['background_space']['status'],'UNREVIEWED')
        self.assertTrue(review_errors(p,row))

    def test_standalone_shot_validator_rejects_root_policy_drop(self):
        from validate_preproduction import Gate
        _,p=background_fixture();gate=Gate(Path('.'))
        gate.check_shots({'panels':[p]})
        self.assertTrue(any('BACKGROUND_HOLD' in e for e in gate.errors))

    def test_softened_default_and_explicit_legacy_preference_are_accepted(self):
        config=json.loads((BASE/'assets/templates/默认使用配置.json').read_text(encoding='utf-8'))
        self.assertEqual(config['background']['closeup_preference'], 'scene_softened')
        self.assertEqual(background_config_errors(config['background']), [])
        legacy=dict(config['background'], closeup_preference='scene_flat')
        self.assertEqual(background_config_errors(legacy), [])
        self.assertTrue(background_config_errors(dict(legacy, closeup_preference='unknown')))
        self.assertTrue(background_config_errors(dict(legacy, extra=True)))

    def test_bad_config_is_rejected(self):
        for v in ({},None,{'policy':BACKGROUND_POLICY,'selection':'all_flat','closeup_preference':'scene_flat'}):
            self.assertTrue(background_config_errors(v))

    def test_real_project_config_and_new_snapshot_initialization(self):
        from usage_config import read_config,memory_source
        from runtime_snapshot import create,verify
        config=read_config(config_path())
        self.assertEqual(config['background']['policy'],BACKGROUND_POLICY)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);snapshot=create(root/'snapshot',memory_source=memory_source(config))
            self.assertEqual(verify(snapshot)['data']['policy'],'batch_snapshot_v1')
            subprocess.run([sys.executable, '-X', 'utf8','-B',str(BASE/'scripts/init_preproduction.py'),
                '--config',config_path(),
                '--runtime-snapshot',snapshot['path'],'--book','SYNTHETIC','--episode','E021',
                '--output',str(root/'new-rv')],check=True,capture_output=True)
            for name in ('00_输入审计/生产流程.json','01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json'):
                self.assertEqual(json.loads((root/'new-rv'/name).read_text(encoding='utf-8-sig'))['background_policy'],BACKGROUND_POLICY)
            state=json.loads((root/'new-rv/00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(state['gates'],{})
            self.assertEqual(state['panels'],[])

    def test_config_free_new_run_opts_in_but_old_config_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            subprocess.run([sys.executable, '-X', 'utf8','-B',str(BASE/'scripts/init_preproduction.py'),'--book','SYNTHETIC','--episode','E000','--output',str(root/'fresh')],check=True,capture_output=True)
            state=json.loads((root/'fresh/00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(state['background_policy'],BACKGROUND_POLICY)
            from usage_config import read_config
            config=json.loads(Path(config_path()).read_text(encoding='utf-8-sig'));config.pop('background');config['runtime'].pop('snapshot_policy')
            cp=root/'old-config.json';cp.write_text(json.dumps(config), encoding='utf-8', newline='\n')
            self.assertNotIn('background',read_config(cp))
            subprocess.run([sys.executable, '-X', 'utf8','-B',str(BASE/'scripts/init_preproduction.py'),'--config',str(cp),'--book','SYNTHETIC','--episode','E021','--output',str(root/'legacy')],check=True,capture_output=True)
            self.assertNotIn('background_policy',json.loads((root/'legacy/00_输入审计/生产流程.json').read_text(encoding='utf-8-sig')))

if __name__=='__main__':unittest.main()
