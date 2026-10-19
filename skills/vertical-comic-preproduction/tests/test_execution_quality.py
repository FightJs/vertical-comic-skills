"""Execution input, triage, deterministic crop and read-only metrics contracts."""
from _portable_config import config_path
import copy,hashlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from test_visual_evidence import fixture
from visual_evidence import context_for,execution_block,packet_errors,panel_errors,basis_errors,feasibility_questions
from input_quality import POLICY,repair_decision_errors
from repair_routes import plan,export_crop
from production_metrics import build

def fx():
 b,p=fixture();b['input_quality_policy']=p['input_quality_policy']=POLICY
 b['appearance_details']['earring']['presence']='present'
 b['scene_views']={'N1':{'view_id':'N1','scene_id':'HALL','space_id':'HALL','description':'北向主桌正视图','camera_axes':['N'],'visible_anchors':['TABLE','STAGE'],'reference_sha256':'scene'}}
 p['visual_evidence']['scene_view']={'view_id':'N1','camera_axis':'N','required_anchors':['TABLE','STAGE'],'direction_basis':'原板视图实际覆盖本机位，SYNTHETIC'}
 p['visual_evidence']['hands']['narrative_role']='critical'
 hand=next(c for c in p['visual_evidence']['checks'] if c['kind']=='hand')
 hand.update(actor='A',actor_limb='自身右臂',action_stage='已握稳杯柄',target='CUP',target_part='杯柄',visible_path='肩肘腕掌连到杯柄',support='杯子由手承托',occlusion='杯柄遮住指节一部分',palm_orientation='掌心朝杯柄',thumb_side='拇指在杯柄外侧对握',forbidden_substitute='不能手停在杯旁')
 p['visual_evidence_context']=context_for(b,p);p['visual_execution_block']=execution_block(p);p['prompt']=p['visual_execution_block']
 return b,p

class ExecutionQualityTests(unittest.TestCase):
 def test_compiled_action_and_view_reach_actual_prompt(self):
  b,p=fx();self.assertEqual(packet_errors(b,p,p,b),[])
  for v in ['已握稳杯柄','肩肘腕掌','掌心朝杯柄','北向主桌正视图']:self.assertIn(v,p['prompt'])
 def test_missing_stage_target_support_or_thumb_stops_submission(self):
  for k in ['action_stage','target_part','support','occlusion','thumb_side','forbidden_substitute']:
   b,p=fx();next(c for c in p['visual_evidence']['checks'] if c['kind']=='hand').pop(k)
   self.assertTrue(panel_errors(p),k)
 def test_wrong_direction_room_anchor_or_reference_is_rejected(self):
  for change in ['axis','room','anchor','actual_reference']:
   b,p=fx()
   if change=='axis':p['visual_evidence']['scene_view']['camera_axis']='S'
   if change=='room':p['visual_evidence_context']['scene_view']['scene_id']='OTHER'
   if change=='anchor':p['visual_evidence']['scene_view']['required_anchors']=['WINDOW']
   if change=='actual_reference':p['reference_images']=[{'sha256':'costume'}]
   self.assertTrue(packet_errors(b,p,p,b),change)
 def test_feasibility_binds_actual_action_changes(self):
  b,p=fx();old=feasibility_questions(p);p['visual_evidence']['checks'][2]['action_stage']='只是靠近杯子'
  self.assertNotEqual(old,feasibility_questions(p))
 def test_quality_not_tied_to_question_UI(self):
  from execution_contract import semantic_checks
  self.assertIn('framing_feasibility',semantic_checks({'input_quality_policy':POLICY}))
 def test_absence_is_explicit_and_carried(self):
  b,p=fx();b['appearance_details']['earring'].update(presence='absent',expected='双耳无耳饰')
  p['visual_evidence_context']=context_for(b,p);p['prompt']=execution_block(p)
  self.assertIn('无该装饰：双耳无耳饰',p['prompt'])
  b['appearance_details']['earring'].pop('presence');self.assertTrue(basis_errors(b))
 def test_old_packets_remain_compatible(self):
  b,p=fixture();self.assertEqual(packet_errors(b,p,p,b),[])
 def test_crop_local_spatial_and_stop_routes(self):
  row={'round_id':1,'output':{'sha256':'img'}};d={'reviewer':'synthetic','evidence':'SYNTHETIC','source_image_sha256':'img'}
  for defects,route in [(['crop'],'crop_candidate'),(['accessory','finger'],'local_edit'),(['action_target'],'rebuild_inputs'),(['accessory','prop_state'],'rebuild_inputs'),(['support','finger'],'rebuild_inputs')]:
   self.assertEqual(plan({**d,'defects':defects},row)['route'],route)
  self.assertEqual(plan({**d,'defects':['finger']},{**row,'round_id':2})['route'],'stop_diagnose')
  self.assertTrue(repair_decision_errors({**d,'defects':['crop']},row,require_image_call=True))
 def test_rebuild_requires_actual_changed_input_not_just_words(self):
  from codex_reference_contract import digest
  with tempfile.TemporaryDirectory() as t:
   root=Path(t)
   def write(n,v):p=root/n;p.write_text(json.dumps(v), encoding='utf-8', newline='\n');return {'path':n,'sha256':digest(p)}
   old=write('old.json',{'panels':[{'framing':{'body_crop':'full_body'}}]});new=write('new.json',{'panels':[{'framing':{'body_crop':'waist_up'}}]})
   state={'visual_basis':{'path':'basis'},'shot_manifest':{'path':'shot'}}
   d={'reviewer':'synthetic','evidence':'SYNTHETIC','source_image_sha256':'img','defects':['camera'],'input_resolution':{**state,'evidence':'SYNTHETIC已修镜头，后续完整门禁仍要批准'}}
   row={'round_id':1,'output':{'sha256':'img'},'package_manifest':old}
   self.assertTrue(repair_decision_errors(d,row,require_image_call=True))
   self.assertEqual(repair_decision_errors(d,row,require_image_call=True,state=state,root=root,new_package=new),[])
   self.assertTrue(repair_decision_errors(d,row,require_image_call=True,state=state,root=root,new_package=old))
 def test_lossless_crop_preserves_all_required_regions_and_never_approves(self):
  from PIL import Image
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);source=root/'source.png';Image.new('RGB',(120,160),(17,23,61)).save(source)
   d={'reviewer':'SYNTHETIC','evidence':'SYNTHETIC框选','source_image_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'crop':[15,20,105,140],'target_ratio':'3:4','min_short_edge':80,'required_visible':['手与杯'],'required_regions':{'手与杯':[20,40,50,90]}}
   r=export_crop(source,root/'crop.png',d);self.assertFalse(r['production_approved']);self.assertEqual(r['image_calls'],0)
   with Image.open(root/'crop.png') as im:self.assertEqual(im.size,(90,120));self.assertEqual(im.getpixel((0,0)),(17,23,61))
   for bad in [{**d,'required_regions':{'手与杯':[0,0,40,90]}},{**d,'min_short_edge':1024},{**d,'target_ratio':'1:1'}]:
    with self.assertRaises(ValueError):export_crop(source,root/'bad.png',bad)
 def test_metrics_do_not_equate_events_records_or_approved_images(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'00_输入审计').mkdir();state=root/'00_输入审计/state.json'
   state.write_text(json.dumps({'book_id':'T','episode_id':'E1','panels':[{'panel_id':'P001','attempt_id':'r2','round_id':2,'status':'VISUAL_PASS','attempt_history':[{'attempt_id':'r1','round_id':1,'status':'VISUAL_FAIL'}]}]}), encoding='utf-8', newline='\n')
   csv=root/'events.csv';csv.write_text('lane,id,status\na,x,completed\na,x,completed\na,y,completed\n', encoding='utf-8', newline='\n')
   r=build([state],native_events=csv);self.assertEqual(r['unique_attempt_records'],2);self.assertIsNone(r['user_accepted_panels']);self.assertEqual(r['first_round']['pass_rate_among_reviewed'],0)
   self.assertEqual(r['native_terminal_events']['unique_lane_event_ids'],2);self.assertIsNone(r['native_terminal_events']['successful_images']);self.assertIsNone(r['timing']['request_window_seconds_sum_not_wall_time'])
   with self.assertRaises(ValueError):build([state,state])

 def test_actual_scene_region_bounds_and_multiview_are_checked(self):
  from PIL import Image
  from codex_reference_contract import digest
  from input_quality import scene_reference_errors
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);path=root/'scene.png';Image.new('RGB',(120,80)).save(path)
   b,p=fx();p['reference_images']=[{'path':'scene.png','sha256':digest(path)}]
   view=p['visual_evidence_context']['scene_view'];view.update(reference_sha256=digest(path),multi_view=True)
   self.assertTrue(scene_reference_errors(p,root))
   view['source_region']=[0,0,60,80];self.assertEqual(scene_reference_errors(p,root),[])
   view['source_region']=[0,0,121,80];self.assertTrue(scene_reference_errors(p,root))
 def test_new_config_snapshot_propagates_policy_without_approvals(self):
  import subprocess
  from usage_config import read_config,memory_source
  from runtime_snapshot import create,verify
  base=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);config=json.loads(Path(config_path()).read_text(encoding='utf-8-sig'))
   config['execution_quality']={'policy':POLICY};cp=root/'config.json';cp.write_text(json.dumps(config), encoding='utf-8', newline='\n')
   parsed=read_config(cp);snapshot=create(root/'snapshot',memory_source=memory_source(parsed))
   self.assertTrue((Path(verify(snapshot)['scripts'])/'input_quality.py').exists())
   subprocess.run([sys.executable, '-X', 'utf8','-B',str(base/'scripts/init_preproduction.py'),'--config',str(cp),'--runtime-snapshot',snapshot['path'],'--book',config['production']['book'],'--episode',config['production']['episodes'][0],'--output',str(root/'rv')],check=True,capture_output=True)
   for rel in ['00_输入审计/生产流程.json','01_镜头改编_CANDIDATE/镜头改编表.json','04_B提示词包_CANDIDATE/全话提示词索引.json']:
    self.assertEqual(json.loads((root/'rv'/rel).read_text(encoding='utf-8-sig'))['input_quality_policy'],POLICY)
   state=json.loads((root/'rv/00_输入审计/生产流程.json').read_text(encoding='utf-8-sig'));self.assertEqual(state['gates'],{});self.assertEqual(state['panels'],[])
   config['execution_quality']={'policy':'unrecognized'};cp.write_text(json.dumps(config), encoding='utf-8', newline='\n')
   with self.assertRaises(ValueError):read_config(cp)
 def test_migrated_first_round_records_are_not_true_first_pass_rate(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'00_输入审计').mkdir();state=root/'00_输入审计/state.json'
   state.write_text(json.dumps({'book_id':'T','episode_id':'E1','panels':[{'panel_id':'P001','attempt_id':'new','round_id':1,'status':'VISUAL_PASS','attempt_history':[{'attempt_id':'old','round_id':1,'status':'VISUAL_FAIL'}]}]}), encoding='utf-8', newline='\n')
   r=build([state]);self.assertEqual(r['first_round']['attempts_recorded'],2);self.assertEqual(len(r['first_round']['ambiguous_first_round_panels']),1);self.assertIsNone(r['first_round']['unambiguous_panel_pass_rate'])

if __name__=='__main__':unittest.main()
