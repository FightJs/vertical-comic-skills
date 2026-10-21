"""Wardrobe anchors, single-frame content and real gate integration; synthetic pixels."""
import copy,json,sys,tempfile,unittest,subprocess
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import appearance_lock as lock
import test_visual_evidence as visual_fixtures
from visual_evidence import basis_errors,context_for,execution_block,packet_errors,panel_errors,review_template,review_errors
from input_quality import scene_reference_errors
from repair_input_guard import repair_errors as repair_guard


def configure(basis,panel,region=None):
    for x in (basis,panel):x.update(appearance_policy=lock.APPEARANCE,frame_policy=lock.FRAME)
    details=basis['appearance_details'];ear=details['earring']
    ear.update(category='accessory',presence='present',count=1,design={'style':'单层水滴耳坠','color':'银色','material':'银与透明石'},
        placement={'side_basis':'wearer_anatomical','side':'left','body_part':'ear_lobe','anchor':'左耳垂穿孔处','attachment':'耳钩连接耳垂','motion':'natural_swing'},
        source_region=region or [0,0,8,8],readability_evidence='SYNTHETIC test provenance only, no actual jewelry observation')
    coat=copy.deepcopy(ear);coat.update(category='garment',expected='当前黑色西装外套与内搭层次固定',design={'style':'双排扣西装与深色内搭','color':'黑色','material':'哑光衣料'},placement={'side_basis':'wearer_anatomical','side':'bilateral','body_part':'torso','anchor':'身体躯干外层','attachment':'外套覆盖内搭','motion':'drape'})
    details['coat']=coat
    panel['frame_plan']={'layout':'single_scene','source_layout':'single','selected_scene':'人物坐在主桌边握杯','omitted_scenes':[],'selection_reason':'本格唯一主要动作'}
    panel['visual_evidence']['detail_visibility'].update(coat={'status':'visible','basis':'躯干入画'})
    for did,row in panel['visual_evidence']['detail_visibility'].items():row['projection']={'surface':'direct','screen_position':'本机位人物对应部位可见','occlusion':'真实衣领/发丝遮挡，不改变归属'}
    panel['visual_evidence']['checks'].append({'id':'COAT','kind':'accessory','subject_ids':[ear['subject_id']],'detail_id':'coat','expected':coat['expected']})
    panel['visual_evidence_context']=context_for(basis,panel)
    panel['visual_execution_block']=execution_block(panel);panel['prompt']=panel['visual_execution_block']
    return basis,panel


def fixture():
    b,p=visual_fixtures.fixture();return configure(b,p)


def reviewed(panel):
    item=visual_fixtures.reviewed(panel);review=item['visual_evidence_review']
    if lock.single(panel):review['frame_observation'].update(status='PASS',reviewer='SYNTHETIC',image_sha256=item['image_sha256'],scene_count=1,layout='single_scene',observed='SYNTHETIC single continuous scene')
    for did,row in review.get('appearance_observations',{}).items():
        d=lock.visible_details(panel)[did];p=d['placement'];check=next(c for c in review['observations'] if c.get('detail_id')==did)
        row.update(status='PASS',reviewer='SYNTHETIC',observed='SYNTHETIC detail observation',side_evidence='SYNTHETIC full image body orientation and native region compared',actual_owner=d['subject_id'],actual_costume_state=d['costume_state'],actual_side=p['side'],actual_body_part=p['body_part'],actual_finger=p.get('finger'),actual_count=d['count'],observation_id=check['id'])
        for c in row['checks'].values():c.update(status='PASS',observed='SYNTHETIC inspected exact requirement')
    return item

class AppearanceLockTests(unittest.TestCase):
    def test_legacy_unchanged_and_policy_cannot_be_dropped(self):
        b,p=visual_fixtures.fixture();self.assertEqual(packet_errors(b,p,p,b),[])
        b,p=fixture();bad=copy.deepcopy(p);bad.pop('appearance_policy');self.assertTrue(packet_errors(b,p,bad,b))
        bad=copy.deepcopy(p);bad.pop('frame_policy');self.assertTrue(packet_errors(b,p,bad,b))
    def test_complete_wardrobe_and_anchor_enter_actual_prompt(self):
        b,p=fixture();self.assertEqual(basis_errors(b),[]);self.assertEqual(packet_errors(b,p,p,b),[])
        for value in ['左耳垂穿孔处','wearer','双排扣西装与深色内搭','自身侧=left','数量1','一个连续场景']:
            if value=='wearer':continue
            self.assertIn(value,p['prompt'])
    def test_missing_anchor_design_side_count_or_clear_provenance_rejected(self):
        for key in ['placement','design','count','readability_evidence','source_region']:
            b,p=fixture();b['appearance_details']['earring'].pop(key)
            self.assertTrue(basis_errors(b),key)
        b,p=fixture();b['appearance_details']['earring']['placement']['side']='screen_left';self.assertTrue(basis_errors(b))
        b,p=fixture();b['appearance_details']['earring'].update(presence='absent',count=1);self.assertTrue(basis_errors(b))
    def test_exact_hand_and_finger_required_for_ring(self):
        b,p=fixture();d=b['appearance_details']['earring'];d['placement'].update(body_part='finger',side='right')
        self.assertTrue(basis_errors(b));d['placement']['finger']='ring';self.assertEqual(basis_errors(b),[])
    def test_details_cannot_move_to_other_character_or_costume(self):
        for key,value in [('subject_id','B'),('costume_state','different')]:
            b,p=fixture();p['visual_evidence_context']['details']['earring'][key]=value
            self.assertTrue(packet_errors(b,p,p,b),key)
        b,p=fixture();next(c for c in p['visual_evidence']['checks'] if c.get('detail_id')=='earring')['subject_ids']=['B'];self.assertTrue(panel_errors(p))
    def test_earring_alone_cannot_replace_whole_wardrobe_state(self):
        b,p=fixture();b['appearance_details'].pop('coat');p['visual_evidence']['detail_visibility'].pop('coat');p['visual_evidence_context']=context_for(b,p)
        self.assertTrue(panel_errors(p))
    def test_camera_reversal_changes_projection_not_wearer_side(self):
        b,p=fixture();q=copy.deepcopy(p);q['visual_evidence']['detail_visibility']['earring']['projection']['screen_position']='反打后投影到画面另一侧'
        q['visual_execution_block']=execution_block(q);q['prompt']=q['visual_execution_block']
        self.assertEqual(panel_errors(q,prompt=True),[]);self.assertIn('自身侧=left',q['prompt'])
    def test_mirror_requires_reflection_basis_and_keeps_anatomical_side(self):
        b,p=fixture();row=p['visual_evidence']['detail_visibility']['earring']['projection'];row['surface']='mirror_reflection'
        self.assertTrue(panel_errors(p));row['reflection_basis']='SYNTHETIC批准镜中人物反射方向';p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertEqual(panel_errors(p,prompt=True),[]);self.assertIn('自身侧=left',p['prompt'])
    def test_real_occlusion_does_not_require_invented_visible_accessory(self):
        b,p=fixture();p['visual_evidence']['detail_visibility']['earring']={'status':'occluded','basis':'左耳被发丝完全遮挡'}
        p['prompt']=p['visual_execution_block']=execution_block(p);self.assertEqual(panel_errors(p,prompt=True),[])
        item=reviewed(p);self.assertNotIn('earring',item['visual_evidence_review']['appearance_observations']);self.assertEqual(review_errors(p,item),[])
    def test_absence_means_no_added_jewelry_not_a_missing_reference(self):
        b,p=fixture();b['appearance_details']['earring'].update(presence='absent',count=0,expected='左耳明确不佩戴耳饰');p['visual_evidence_context']=context_for(b,p);p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertEqual(packet_errors(b,p,p,b),[]);self.assertIn('保持无该装饰',p['prompt'])
    def test_two_scene_source_chooses_one_without_mutating_locked_script(self):
        from repair_prompt_package import content_block
        b,p=fixture();p['locked_script']={'event_text':'画面一：人物握杯；画面二：另一个人走入走廊'};original=copy.deepcopy(p['locked_script'])
        p['frame_plan'].update(source_layout='multiple',omitted_scenes=['另一个人走入走廊'],selection_reason='优先主要动作')
        p['prompt']=p['visual_execution_block']=execution_block(p);block=content_block(p,p)
        self.assertEqual(p['locked_script'],original);self.assertIn('人物坐在主桌边握杯',block);self.assertNotIn('另一个人走入走廊',block)
        self.assertEqual(lock.prompt_errors(p),[]);p['prompt']+='另一个人走入走廊';self.assertTrue(lock.prompt_errors(p))
    def test_split_layout_or_changed_selected_scene_rejected(self):
        b,p=fixture();q=copy.deepcopy(p);q['frame_plan']['layout']='two_panels';self.assertTrue(packet_errors(b,p,q,b))
        q=copy.deepcopy(p);q['frame_plan']['selected_scene']='另一幅画面';q['visual_execution_block']=execution_block(q);q['prompt']=q['visual_execution_block'];self.assertTrue(packet_errors(b,p,q,b))
    def test_review_starts_unreviewed_and_wrong_side_or_owner_never_passes(self):
        b,p=fixture();self.assertEqual(review_template(p)['frame_observation']['status'],'UNREVIEWED');self.assertTrue(review_errors(p,visual_fixtures.reviewed(p)))
        item=reviewed(p);self.assertEqual(review_errors(p,item),[])
        for key,value in [('actual_side','right'),('actual_owner','B'),('actual_count',2),('actual_costume_state','other')]:
            bad=copy.deepcopy(item);bad['visual_evidence_review']['appearance_observations']['earring'][key]=value;self.assertTrue(review_errors(p,bad),key)
    def test_blurry_or_wrong_attached_detail_not_hidden_by_global_pass(self):
        b,p=fixture();item=reviewed(p)
        for key in ['clarity','attachment','screen_position','design']:
            bad=copy.deepcopy(item);bad['visual_evidence_review']['appearance_observations']['earring']['checks'][key]['status']='FAIL';self.assertTrue(review_errors(p,bad))
        bad=copy.deepcopy(item);bad['visual_evidence_review']['appearance_observations']['earring']['observation_id']='COAT';self.assertTrue(review_errors(p,bad))
    def test_multiple_frames_reported_as_fail_without_fake_success(self):
        b,p=fixture();item=reviewed(p);frame=item['visual_evidence_review']['frame_observation'];frame.update(scene_count=2,layout='multiple_scenes')
        self.assertTrue(review_errors(p,item));frame['status']='FAIL'
        self.assertEqual(review_errors(p,item,require_pass=False),[]);self.assertTrue(review_errors(p,item,require_pass=True))
    def test_actual_reference_crop_bounds_and_owner_use_are_checked(self):
        from PIL import Image
        from codex_reference_contract import digest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);Image.new('RGB',(64,64),'gray').save(root/'costume.png');b,p=fixture()
            for d in b['appearance_details'].values():d['reference_sha256']=digest(root/'costume.png')
            p['visual_evidence_context']=context_for(b,p);p['reference_images']=[{'path':'costume.png','sha256':digest(root/'costume.png'),'alias':'COSTUME'}];p['reference_bindings']=[{'alias':'COSTUME','purpose':'costume_state','subject_ids':['A']}]
            self.assertEqual(scene_reference_errors(p,root),[])
            p['reference_bindings'][0]['subject_ids']=['B'];self.assertTrue(scene_reference_errors(p,root));p['reference_bindings'][0]['subject_ids']=['A']
            p['visual_evidence_context']['details']['earring']['source_region']=[0,0,65,64];self.assertTrue(scene_reference_errors(p,root))
    def test_repair_specifies_changed_and_preserved_details_and_recompiles(self):
        b,p=fixture();p['operation']='repair';self.assertTrue(lock.repair_errors(p));self.assertTrue(any('修哪些细节' in x for x in repair_guard(p)))
        p['appearance_repair']={'correct_detail_ids':['earring'],'preserve_detail_ids':['coat'],'instructions':{'earring':'将耳坠恢复到角色自身左耳垂'}};p['repair_focus']={'failed_transfers':['accessories']};p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertEqual(lock.repair_errors(p),[]);self.assertIn('保持已正确的细节：coat',p['prompt'])
        p['appearance_repair']['preserve_detail_ids']=[];self.assertTrue(lock.repair_errors(p))
    def test_new_initializer_propagates_flags_without_approval(self):
        base=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'rv';subprocess.run([sys.executable, '-X', 'utf8','-B',str(base/'scripts/init_preproduction.py'),'--book','SYNTHETIC','--episode','E000','--output',str(root)],check=True,capture_output=True)
            for rel in ['00_输入审计/生产流程.json','01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json']:
                d=json.loads((root/rel).read_text(encoding='utf-8-sig'));self.assertEqual(d['appearance_policy'],lock.APPEARANCE);self.assertEqual(d['frame_policy'],lock.FRAME)
            self.assertEqual(json.loads((root/'00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'))['gates'],{})
    def test_real_complete_gate_carries_constraints_and_detects_removed_actual_block(self):
        from PIL import Image
        from staged_workflow import evaluate
        h,b=visual_fixtures.actual_fixture(self);p=h.panel
        costume=next(r for r in p['reference_images'] if r['sha256']==b['appearance_details']['earring']['reference_sha256'])
        with Image.open(h.root/costume['path']) as im:box=[0,0,min(8,im.width),min(8,im.height)]
        original_prompt=p['prompt'];configure(b,p,box);p['prompt']=original_prompt+'\n'+p['visual_execution_block']
        h.state.update(appearance_policy=lock.APPEARANCE,frame_policy=lock.FRAME);h.h.manifest.update(appearance_policy=lock.APPEARANCE,frame_policy=lock.FRAME)
        h.state['visual_basis']=h.h.f.write('basis-appearance.json',b);h.state['gates']['visual_basis']=h.h.approve([h.state['source_script'],h.state['source_snapshot'],h.state['visual_basis']])
        h.h.shots[0].update(copy.deepcopy(p));(h.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n');h.sync()
        result=evaluate(h.state,h.root,'generate','P001');self.assertEqual(result['status'],'PASS',result)
        record=h.returned();qa=json.loads((h.root/record['qa_report']['path']).read_text(encoding='utf-8-sig'));item=qa['panels'][0]
        self.assertEqual(item['visual_evidence_review']['frame_observation']['status'],'UNREVIEWED')
        self.assertEqual(set(item['visual_evidence_review']['appearance_observations']),{'earring','coat'})
        self.assertTrue(review_errors(p,item,image_size=item['image_size']))
        p['prompt']='忽略服饰细节';(h.root/'P001/prompt.txt').write_text(p['prompt'], encoding='utf-8', newline='\n');h.sync()
        self.assertEqual(evaluate(h.state,h.root,'generate','P001')['status'],'HOLD')

class PreparedAppearanceTests(unittest.TestCase):
    def test_bilateral_total_is_not_visible_count_and_wrong_count_fails_qa(self):
        b,p=fixture();d=b['appearance_details']['earring'];d['count']=2;d['placement']['side']='bilateral'
        p['visual_evidence_context']=context_for(b,p)
        self.assertTrue(lock.panel_errors(p))
        p['visual_evidence']['detail_visibility']['earring']['projection']['visible_count']=1
        p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertEqual(lock.panel_errors(p),[])
        self.assertIn('数量2',p['prompt']);self.assertIn('本镜头可见数量=1',p['prompt'])
        item=reviewed(p);row=item['visual_evidence_review']['appearance_observations']['earring']
        self.assertTrue(review_errors(p,item))  # helper counted total, not visible
        row['actual_count']=1;self.assertEqual(review_errors(p,item),[])
        row['expected']['placement']['anchor']='wrong anchor'
        self.assertTrue(review_errors(p,item))

    def test_occluded_accessory_stays_on_body_without_forcing_it_visible(self):
        from rule_memory import inspection_plan
        b,p=fixture();p['visual_evidence']['detail_visibility']['earring']={'status':'occluded','basis':'自身左耳被头发完全遮住'}
        p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertIn('左耳垂穿孔处',p['prompt']);self.assertIn('不为展示该细节',p['prompt'])
        item=reviewed(p);self.assertEqual(review_errors(p,item),[])
        targets=[t for g in inspection_plan(p,item,'synthetic')['groups'] for t in g['targets']]
        target=next(t for t in targets if t.get('detail_id')=='earring')
        self.assertEqual(target['field'],'detail_visibility_observations')
        item['visual_evidence_review']['detail_visibility_observations']['earring']['actual_visibility']='visible'
        self.assertTrue(review_errors(p,item))

    def test_long_execution_text_and_rule_constraints_survive_compilation(self):
        from repair_prompt_package_v2 import compact,build_prompt
        tail='必须保留右手无名指戒指及其连接位置'
        long='准确当前动作与场景。'*160+tail
        self.assertTrue(compact({'required':[long]}).endswith(tail))
        b,p=fixture();line='左耳坠连接于左耳垂，不能漂移到后脑。'
        p['memory_applications']={'generation':[{'decision':'APPLIED','memory_id':'SYNTHETIC','prompt_constraints':[line,line]}]}
        prompt,_,_=build_prompt(p,'eye_level','medium','3:4','正前方','面向人物','眼平','腰以上',[],None,None,'SYNTHETIC',long)
        self.assertIn(tail,prompt);self.assertEqual(prompt.count(line),1)
        p['operation']='repair';p['appearance_repair']={'correct_detail_ids':[],'preserve_detail_ids':['earring','coat'],'instructions':{}}
        p['prompt']=p['visual_execution_block']=execution_block(p)
        self.assertEqual(lock.repair_errors(p),[])
        self.assertIn('保持已正确的细节：earring、coat',p['prompt'])

if __name__=='__main__':unittest.main()
