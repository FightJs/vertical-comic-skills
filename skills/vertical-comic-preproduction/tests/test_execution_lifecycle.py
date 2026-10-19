"""Independent execution-v2 lifecycle regressions. Synthetic artifacts, no tool calls or gate mocks."""
import sys, json, copy, tempfile, shutil, subprocess, unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'scripts'),str(BASE/'tests')]
from PIL import Image
import test_staged_workflow as fixtures
from codex_reference_contract import digest,validate_panel
from staged_workflow import evaluate
from scoped_inputs import POLICY,build_plan,half_view
from execution_contract import POLICY as EXEC,toolchain,CHECKS
from source_adapter import adapted
from continuity_context import load_context,contextual_tags,binding_errors
from continuity_contract import validate_manifest as continuity_validate,reference_usage_block
from batch_round import snapshot,attempt_errors,template

def observe(name,actual,expected=None):
    if expected is not None and actual!=expected:
        raise AssertionError(f'{name}: actual={actual!r}; expected={expected!r}')

def write(root,name,value):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    return {'path':name,'sha256':digest(path)}
def read(root,ref):return json.loads((root/ref['path']).read_text())
def cli(*args):return subprocess.run([sys.executable,*map(str,args)],capture_output=True,text=True)
def approve(refs):return {'status':'APPROVED','source_kind':'user_message','source_locator':'synthetic://NOT-REAL-USER','quote':'SYNTHETIC TEST ONLY','book_id':'UNIT','episode_id':'E000','artifacts':refs}

def build_calibration(root):
  h=fixtures.StagedTests();h.setUp();h.real_input();shutil.copytree(h.root,root);h.doCleanups()
  m=json.loads((root/'全话提示词索引.json').read_text());p=m['panels'][0]
  p.update(generation_dependencies=[],requires_state_review=False,calibration_anchor=True,state_review_policy='merge_into_C',source_panel_id='E000-P001')
  m.update(execution_mode='half_episode_async_v1',optimization_policy=POLICY,execution_contract=EXEC,round_context={'batch_id':'H001','round_id':1,'attempt_id':'P001-r1'})
  source=write(root,'source.json',{'SYNTHETIC':'locked source'});ids=['P001','P002','P003','P004']
  def expand_scope(obj):
    if isinstance(obj,dict):
      if 'confirmation' in obj:obj['confirmation']['scope']['panel_ids']=ids
      for value in obj.values():expand_scope(value)
    elif isinstance(obj,list):
      for value in obj:expand_scope(value)
  expand_scope(m['identity_registry'])
  raw={'source_sha256':source['sha256'],'panel_ids':['E000-'+pid for pid in ids],'locked_scripts':{'E000-'+pid:copy.deepcopy(p['locked_script']) for pid in ids}}
  raw_ref=write(root,'raw-snapshot.json',raw);snap=write(root,'snapshot.json',adapted(raw,'E000',raw_ref))
  original_basis=json.loads((root/'basis.json').read_text());basis=write(root,'H001-basis.json',original_basis)
  p2=copy.deepcopy(p);p2.update(panel_id='P002',source_panel_id='E000-P002',calibration_anchor=False,camera_view_id='CAM2',adjacent_face_comparison={'A':{'face_comparable':True,'evidence':'synthetic visible faces'}})
  p2['continuity_contract']['scene'].update(mode='same_scene_new_view',previous_panel_id='P001')
  p2['continuity_contract']['qa_requirements']['framing']['subject_ids']=['P002']
  p2.update(camera_angle_family='three_quarter_right',camera_position={'x':3,'y':2,'z':1.6},camera_view_signature='TEST right camera chest-up')
  for binding in p2['reference_bindings']:
    if binding['subject_ids']==['P001']:binding['subject_ids']=['P002']
  for binding in p2['character_bindings']:binding['asset_exemption']['panel_ids']=['P002']
  p2['scene_binding']['asset_exemption']['panel_ids']=['P002']
  from repair_prompt_package import camera_block,content_block
  from identity_confirmation import execution_block
  p2['camera_execution_block']=camera_block(p2,p2,None,None);p2['content_execution_block']=content_block(p2,p2);p2['identity_execution_block']=execution_block(p2,m['identity_registry'])
  p2['reference_usage_block']=reference_usage_block(p2['reference_bindings'],p2['reference_images'])
  p2['prompt']='\n\n'.join(p2[k] for k in ('camera_execution_block','content_execution_block','identity_execution_block','reference_usage_block','style_execution_block','negative_prompt'))
  shots={**copy.deepcopy(m),'panels':[copy.deepcopy(p),p2]};shot_ref=write(root,'H001-shots.json',shots)
  s={'policy':'staged_comic_v1','book_id':'UNIT','episode_id':'E000','episode_order':['E000'],'execution_mode':'half_episode_async_v1','optimization_policy':POLICY,'execution_contract':EXEC,'toolchain':toolchain(),'source_script':source,'source_snapshot':snap,'review_policy':{'systemic_failure_count_gt':5,'max_auto_correction_rounds':1},'half_inputs':{'H001':{'visual_basis':basis,'shot_manifest':shot_ref}},'half_gates':{'H001':{'visual_basis':approve([source,snap,basis])}},'gates':{},'state_reviews':{},'round_reviews':{},'batch_reviews':{},'calibration_reviews':{},'holds':[],'cancelled':False,'production_authorization':{**approve([source]),'panel_ids':ids},'panels':[]}
  audit={'policy':'semantic_audit_v1','book_id':'UNIT','episode_id':'E000','source_snapshot':snap,'visual_basis':basis,'shot_manifest':shot_ref,'panel_ids':['P001','P002'],'panels':[{'panel_id':pid,'status':'REVIEWED','reviewer':'SYNTHETIC','evidence':'test semantic assertions','checks':{k:{'status':'PASS','evidence':'synthetic checked'} for k in CHECKS}} for pid in ids[:2]]}
  audit_ref=write(root,'semantic.json',audit);s['half_inputs']['H001']['semantic_audit']=audit_ref
  s['half_gates']['H001']['shot_design']=approve([basis,shot_ref,audit_ref])
  for pid in ids:s['panels'].append({'panel_id':pid,'source_panel_id':'E000-'+pid,'status':'PENDING','round_id':1,'attempt_id':pid+'-r1'})
  s['panels'][0].update(package_manifest=write(root,'全话提示词索引.json',m),shot_subset=write(root,'shot-subset.json',{**m,'panels':[copy.deepcopy(p)]}))
  s['batch_plan']=write(root,'plan.json',build_plan(s,read(root,snap)));write(root,'00_输入审计/生产流程.json',s)
  return s,m,p,shots

def create_return(root,s,m,p,status,round_id):
  pid=p['panel_id'];attempt=f'{pid}-r{round_id}';m['round_context']={'batch_id':'H001','round_id':round_id,'attempt_id':attempt}
  errors,plan=validate_panel(p,root);assert not errors,errors
  image_dir=root/f'images-r{round_id}';image_dir.mkdir();out=image_dir/(pid+'.png');Image.new('RGB',(90,160),'white' if round_id==1 else 'yellow').save(out);out_ref={'path':str(out.relative_to(root)),'sha256':digest(out)}
  req={'attempt_id':attempt,'backend_id':'codex_builtin_imagegen','panel_id':pid,**plan,'source_kind':'observed_tool_call','source_locator':'synthetic://fake-call'}
  res={'attempt_id':attempt,'status':'COMPLETED','outputs':[out_ref],'source_kind':'observed_tool_result','source_locator':'synthetic://fake-result'}
  p['generation_execution']={'status':'COMPLETED','attempt_id':attempt,'request_evidence':write(root,f'request-r{round_id}.json',req),'response_evidence':write(root,f'response-r{round_id}.json',res)}
  mr=write(root,f'round{round_id}-manifest.json',m)
  # CLI package uses conventional filename; copy the exact manifest as a stable version.
  write(root,'全话提示词索引.json',m)
  qdir=root/f'qa-r{round_id}';r=cli(BASE/'scripts/make_generation_qa.py','--package',root,'--images',image_dir,'--output',qdir);assert r.returncode==0,r.stdout+r.stderr
  q=json.loads((qdir/'生成图QA报告.json').read_text());q['source_manifest_sha256']=mr['sha256'];it=q['panels'][0]
  for rv in [*it['dimension_review'].values(),it['style_review']]:
    if rv['status']=='UNREVIEWED':rv.update(status='PASS',reviewer='SYNTHETIC',evidence='synthetic QA only')
  for k in ('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters'):it[k]=True
  if status=='VISUAL_FAIL':it['dimension_review']['action_interaction'].update(status='FAIL',reviewer='SYNTHETIC',evidence='Synthetic missing hand gesture')
  record=next(x for x in s['panels'] if x['panel_id']==pid);record.update(status=status,round_id=round_id,attempt_id=attempt,package_manifest=mr,output=out_ref,qa_report=write(root,f'qa-reviewed-r{round_id}.json',q))
  if status=='VISUAL_FAIL':record['failure_diagnosis']={'reviewer':'SYNTHETIC','evidence':'synthetic missing gesture','layer':'action_interaction'}
  return record

def tests_calibration(root):
  s,m,p,shots=build_calibration(root);r=s['panels'][0]
  result=evaluate(s,root,'generate','P001');observe('complete new-contract first calibration preflight',result['next_action'],'READY_FOR_HALF_PANEL');assert result['status']=='PASS',result
  wrong=copy.deepcopy(s);wrong['panels'][0]['source_panel_id']='P001';observe('record source ID mismatch blocks',evaluate(wrong,root,'generate','P001')['status'],'HOLD')
  create_return(root,s,m,p,'VISUAL_FAIL',1);observe('first fail actual six-dimension attempt check',attempt_errors(half_view(s,'H001'),root,r),[])
  before=evaluate(s,root);observe('first fail before calibration report',before['next_action'])
  write(root,'00_输入审计/生产流程.json',s);qpath=root/'calibration-review.json';cmd=cli(BASE/'scripts/calibration_repair.py','--state',root/'00_输入审计/生产流程.json','--panel','P001','--write',qpath);observe('CLI creates only unreviewed calibration candidate',cmd.returncode,0);assert cmd.returncode==0,cmd.stdout+cmd.stderr
  cal=json.loads(qpath.read_text());cal.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='Synthetic review only',diagnosis={'reviewer':'SYNTHETIC','evidence':'Only missing hand gesture; preserve all else','earliest_layer':'action_interaction','requires_basis_change':False,'repair_constraints':{'P001':['仅恢复原稿抬手动作；保留身份、衣装、画风、空间和镜头。']}})
  cref=write(root,'calibration-review.json',cal);s['calibration_reviews']['P001']=cref
  observe('calibration report unlocks prepare while P002 stays pending',evaluate(s,root)['next_action'],'PREPARE_CALIBRATION_CORRECTION')
  r['attempt_history']=[snapshot(r)];r.update(status='REPAIR_AUTHORIZED',round_id=2,attempt_id='P001-r2')
  target=r['attempt_history'][0]['output'];m.update(calibration_repair={'policy':'state_calibration_repair_v1','panel_id':'P001','source_review_sha256':cref['sha256'],'source_attempt_id':'P001-r1'},repair_source_output=target,round_context={'batch_id':'H001','round_id':2,'attempt_id':'P001-r2'})
  p.update(operation='repair',generation_execution={'status':'NOT_RUN'})
  p['reference_images'].append({**target,'alias':'@FAILED_P001','role':'repair_target','version':'SYNTHETIC-r1','subject_ids':['A']})
  p['reference_bindings'].append({'alias':'@FAILED_P001','purpose':'pose_interaction','subject_ids':['A'],'allowed_transfer':['pose'],'forbidden_transfer':['identity','clothing','style']})
  old_usage=p['reference_usage_block'];p['reference_usage_block']=reference_usage_block(p['reference_bindings'],p['reference_images']);p['prompt']=p['prompt'].replace(old_usage,p['reference_usage_block'])+'\n'+cal['diagnosis']['repair_constraints']['P001'][0]
  stage=root.parent/'repair-stage';shutil.copytree(root,stage);repair_root=root/'attempt2';stage.rename(repair_root)
  (repair_root/'P001/prompt.txt').write_text(p['prompt']);write(repair_root,'P001/提示词.json',p);ref=write(repair_root,'repair-manifest.json',m);r['package_manifest']={**ref,'path':'attempt2/'+ref['path']}
  gen=evaluate(s,root,'generate','P001');observe('full second-round repair preflight while followers unsubmitted',gen['next_action'],'READY_FOR_HALF_PANEL');observe('second-round preflight errors',gen['errors'],[])
  s_bad=copy.deepcopy(s);s_bad['panels'][0]['round_id']=3;observe('third round rejected',evaluate(s_bad,root,'generate','P001')['status'],'HOLD')
  # Validate report/package binding remains strict after source-target mutation.
  m_bad=copy.deepcopy(m);m_bad['repair_source_output']['sha256']='0'*64;s_bad=copy.deepcopy(s);s_bad['panels'][0]['package_manifest']=write(root,'bad-target-manifest.json',m_bad)
  observe('wrong repair target rejected',evaluate(s_bad,root,'generate','P001')['status'],'HOLD')
  create_return(repair_root,s,m,p,'VISUAL_FAIL',2)
  for k in ('package_manifest','qa_report','output'):r[k]={**r[k],'path':'attempt2/'+r[k]['path']}
  observe('second-round failed calibration stops',evaluate(s,root)['next_action'],'STOP_DIAGNOSE')
  # Turn this actual synthetic round-2 QA into passed evidence, without invoking anything.
  qa=read(root,r['qa_report']);qa['panels'][0]['dimension_review']['action_interaction']['status']='PASS';r.update(status='VISUAL_PASS',qa_report=write(root,'qa-r2-pass.json',qa));r.pop('failure_diagnosis',None)
  result=evaluate(s,root);observe('passed correction resumes untouched follower',result['eligible_panel_ids'],['P002']);observe('second-round snapshot retained',r['attempt_history'][0]['status'],'VISUAL_FAIL')
  wrong_completed=copy.deepcopy(s);wrong_completed['panels'][0]['source_panel_id']='E999-P999'
  result=evaluate(wrong_completed,root)
  observe('completed progress source ID remains immutable',result['next_action'],'EXECUTION_CONTRACT_HOLD')
  observe('completed progress source ID error is explicit',any('SOURCE_ID_HOLD' in x for x in result['errors']),True)
  # Round one cannot be written until untouched followers actually terminate.
  try:template(half_view(s,'H001'),read(root,s['batch_plan'])['batches'][0],{x['panel_id']:x for x in s['panels']},1);actual='UNEXPECTED_TEMPLATE'
  except ValueError:actual='WAIT_FOLLOWERS'
  observe('round-one aggregate waits untouched follower',actual,'WAIT_FOLLOWERS')
  write(root,'00_输入审计/生产流程.json',s)
  return s,m,p,shots

def tests_context(root,s,m,shots):
  # Bind P002's one-panel execution to the actually frozen H001 prior shots.
  current=copy.deepcopy(shots['panels'][1]);packet={**copy.deepcopy(m),'panels':[current]};packet.pop('calibration_repair',None);packet.pop('repair_source_output',None)
  source={'root':str(root),'episode_id':'E000','source_script':s['source_script'],'source_snapshot':s['source_snapshot'],'visual_basis':s['half_inputs']['H001']['visual_basis'],'shot_manifest':s['half_inputs']['H001']['shot_manifest'],'visual_approval':s['half_gates']['H001']['visual_basis'],'shot_approval':s['half_gates']['H001']['shot_design']}
  ctx={'policy':'approved_shot_context_v1','book_id':'UNIT','current':{'episode_id':'E000','panel_id':'P002'},'episode_order':['E000'],'sources':[source],'entries':[{'source':0,'panel_id':'P001'}]}
  packet['continuity_context']=write(root,'context-P002.json',ctx)
  previous,errors=load_context(packet,root);observe('real frozen prior-shot context',errors,[])
  observe('same-scene single panel continuity check',continuity_validate(packet,prompt=False,root=root)[0],[])
  observe('source-frozen context binding',binding_errors(s,root,packet,root),[])
  observe('adjacent face and panel tags',contextual_tags(packet,root,current),['adjacent_panel_pair','same_character_adjacent_expression'])
  noctx=copy.deepcopy(packet);noctx.pop('continuity_context');observe('same-scene single without predecessor rejected',bool(continuity_validate(noctx,prompt=False,root=root)[0]),True)
  altered=copy.deepcopy(ctx);altered['entries']=[{'source':0,'panel_id':'P002'}];bad={**packet,'continuity_context':write(root,'future-context.json',altered)};observe('current/future predecessor rejected',bool(load_context(bad,root)[1]),True)
  altered=copy.deepcopy(ctx);altered['sources'][0]['shot_approval']={**source['shot_approval'],'panel_ids':['P002']};bad={**packet,'continuity_context':write(root,'unapproved-prior.json',altered)};observe('out-of-scope prior approval rejected',bool(load_context(bad,root)[1]),True)
  observe('new contract missing context binding rejected',bool(binding_errors(s,root,noctx,root)),True)
  skip=copy.deepcopy(packet);skip['panels'][0]['panel_id']='P003';skip_ctx=copy.deepcopy(ctx);skip_ctx['current']['panel_id']='P003'
  skip['continuity_context']=write(root,'skipped-adjacent-context.json',skip_ctx)
  observe('new contract skipped actual adjacent source rejected',bool(binding_errors(s,root,skip,root)),True)
  # Probe whether a matching metadata/hash arbitrary future context source can pass.
  altered=copy.deepcopy(ctx);altered['sources'][0]['root']=str(root.parent);bad={**packet,'continuity_context':write(root,'wrong-root.json',altered)};observe('changed source root rejected',bool(binding_errors(s,root,bad,root)),True)

def tests_successor(root,s,m,shots):
  current=copy.deepcopy(shots['panels'][1]);packet={**copy.deepcopy(m),'panels':[current]};packet.pop('calibration_repair',None);packet.pop('repair_source_output',None)
  source={'root':str(root),'episode_id':'E000','source_script':s['source_script'],'source_snapshot':s['source_snapshot'],'visual_basis':s['half_inputs']['H001']['visual_basis'],'shot_manifest':s['half_inputs']['H001']['shot_manifest'],'visual_approval':s['half_gates']['H001']['visual_basis'],'shot_approval':s['half_gates']['H001']['shot_design']}
  ctx={'policy':'approved_shot_context_v1','book_id':'UNIT','current':{'episode_id':'E000','panel_id':'P002'},'episode_order':['E000'],'sources':[source],'entries':[{'source':0,'panel_id':'P001'}]}
  package_root=root/'attempt-P002';package_root.mkdir()
  shutil.copytree(root/'P001',package_root/'P001')
  for name in ('identity-proof.json','style_approval.json','capability.json'):shutil.copy2(root/name,package_root/name)
  current['generation_execution']={'status':'NOT_RUN'};packet['round_context']={'batch_id':'H001','round_id':1,'attempt_id':'P002-r1'}
  packet['continuity_context']=write(package_root,'context-P002.json',ctx)
  (package_root/'P002').mkdir();(package_root/'P002/prompt.txt').write_text(current['prompt']);write(package_root,'P002/提示词.json',current)
  record=s['panels'][1];ref=write(package_root,'全话提示词索引.json',packet);record['package_manifest']={**ref,'path':'attempt-P002/'+ref['path']}
  subset={**packet,'panels':[copy.deepcopy(current)]}
  subset['continuity_context']=write(root,'context-P002-subset.json',ctx);record['shot_subset']=write(root,'P002-shot-subset.json',subset)
  result=evaluate(s,root,'generate','P002');observe('full successor gate with frozen context',result['next_action'],'READY_FOR_HALF_PANEL');observe('full successor gate errors',result['errors'],[])
  original_manifest=record['package_manifest']
  missing=copy.deepcopy(packet);missing.pop('continuity_context')
  ref=write(package_root,'missing-context-manifest.json',missing);record['package_manifest']={**ref,'path':'attempt-P002/'+ref['path']}
  result=evaluate(s,root,'generate','P002')
  observe('full successor gate missing context rejected',result['status'],'HOLD')
  observe('full successor gate names missing adjacency',any('真实相邻' in x for x in result['errors']),True)
  record['package_manifest']=original_manifest
  create_return(package_root,s,packet,current,'VISUAL_PASS',1)
  for key in ('package_manifest','qa_report','output'):record[key]={**record[key],'path':'attempt-P002/'+record[key]['path']}
  batch=read(root,s['batch_plan'])['batches'][0];view=half_view(s,'H001');records={x['panel_id']:x for x in s['panels']}
  first=template(view,batch,records,1);first.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='synthetic aggregate',diagnosis=read(root,s['calibration_reviews']['P001'])['diagnosis']);s['round_reviews']['H001']={'1':write(root,'H001-round1.json',first)}
  observe('aggregate keeps original calibration fail and follower first pass',[x['status'] for x in first['attempts']],['VISUAL_FAIL','VISUAL_PASS'])
  observe('aggregate with missing round2 requests corrected verification',evaluate(s,root)['next_action'],'REVIEW_CORRECTION')
  second=template(view,batch,records,2);second.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='synthetic all-half recheck');s['round_reviews']['H001']['2']=write(root,'H001-round2.json',second)
  observe('all-half round2 accepts preserved follower round1',[x['round_id'] for x in second['attempts']],[2,1])
  observe('after all-half round2 next actual continuity gate',evaluate(s,root)['next_action'],'REVIEW_HALF_CONTINUITY')
  continuity={'policy':'batch_review_v1','book_id':'UNIT','episode_id':'E000',**batch,'status':'PASS','reviewer':'SYNTHETIC','evidence':'synthetic actual all-half compare','visual_basis':view['visual_basis'],'shot_manifest':view['shot_manifest'],'outputs':[x['output'] for x in s['panels'][:2]],'previous_outputs':[]}
  s['batch_reviews']['H001']=write(root,'H001-continuity.json',continuity)
  observe('complete first half still requires actual user C',evaluate(s,root)['next_action'],'WAIT_FIRST_HALF_APPROVAL')
  write(root,'00_输入审计/production-final-test-state.json',s)

def tests_adjacent_context(root):
  s,m,p,shots=build_calibration(root)
  current=shots['panels'][1]
  current.update(camera_angle_family=p['camera_angle_family'],camera_position=copy.deepcopy(p['camera_position']),camera_view_signature='RENAMED_SAME_REAL_COMPOSITION',adjacent_change_reason='Synthetic naming-only camera change')
  from repair_prompt_package import camera_block
  current['camera_execution_block']=camera_block(current,current,None,None)
  current['prompt']='\n\n'.join(current[k] for k in ('camera_execution_block','content_execution_block','identity_execution_block','reference_usage_block','style_execution_block','negative_prompt'))
  shot_ref=write(root,'H001-shots.json',shots);s['half_inputs']['H001']['shot_manifest']=shot_ref
  audit=read(root,s['half_inputs']['H001']['semantic_audit']);audit['shot_manifest']=shot_ref;audit_ref=write(root,'semantic.json',audit);s['half_inputs']['H001']['semantic_audit']=audit_ref
  s['half_gates']['H001']['shot_design']=approve([s['half_inputs']['H001']['visual_basis'],shot_ref,audit_ref])
  create_return(root,s,m,p,'VISUAL_PASS',1)
  source={'root':str(root),'episode_id':'E000','source_script':s['source_script'],'source_snapshot':s['source_snapshot'],'visual_basis':s['half_inputs']['H001']['visual_basis'],'shot_manifest':shot_ref,'visual_approval':s['half_gates']['H001']['visual_basis'],'shot_approval':s['half_gates']['H001']['shot_design']}
  ctx={'policy':'approved_shot_context_v1','book_id':'UNIT','current':{'episode_id':'E000','panel_id':'P002'},'episode_order':['E000'],'sources':[source],'entries':[{'source':0,'panel_id':'P001'}]}
  packet={**copy.deepcopy(m),'panels':[current],'round_context':{'batch_id':'H001','round_id':1,'attempt_id':'P002-r1'}}
  packet['continuity_context']=write(root,'context-P002.json',ctx)
  current['generation_execution']={'status':'NOT_RUN'}
  (root/'P002').mkdir();(root/'P002/prompt.txt').write_text(current['prompt']);write(root,'P002/提示词.json',current)
  s['panels'][1].update(package_manifest=write(root,'P002-manifest.json',packet),shot_subset=write(root,'P002-subset.json',packet))
  from validate_preproduction import Gate
  gate=Gate(root);gate.check_adjacent(p,current)
  observe('direct full-pair camera gate rejects signature-only rename',bool(gate.errors),True)
  observe('same naming-only camera through single-panel frozen context full generate',evaluate(s,root,'generate','P002')['status'],'HOLD')

class ExecutionLifecycleTests(unittest.TestCase):
    def test_technical_pass_cannot_waive_failed_mem010_check(self):
        from rule_memory import select
        from validate_preproduction import Gate
        from batch_workflow import input_errors
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'episode';s,m,p,shots=build_calibration(root)
            library=root/'rules';library.mkdir();body=library/'rule.md'
            body.write_text('SYNTHETIC adjacent rule: camera_view_distinct and shot_scale_distinct.\n')
            rule={'id':'MEM-010','title':'Synthetic adjacent rule','version':'1','status':'active','scope':'cross_work',
                'primary_stage':'shot_design','stages':['shot_design','generation','image_review'],
                'admission':{'portable':True,'contains_story_facts':False,'rationale':'SYNTHETIC method only'},
                'trigger':{'any_tags':['adjacent_panel_pair'],'any_visual_terms':[]},
                'requirements':{stage:{'checks':['camera_view_distinct','shot_scale_distinct'],'artifacts':[],'prompt_constraints':False} for stage in ['shot_design','generation','image_review']},
                'file':{'path':'rule.md','sha256':digest(body)}}
            (library/'记忆索引.json').write_text(json.dumps({'policy':'triggered_rules_v1','rules':[rule]}))
            source={'policy':'triggered_rules_v1','root':str(library),'index':'记忆索引.json'}
            s['memory_source']=source;m['memory_source']=source;shots['memory_source']=source;current=shots['panels'][1];current['memory_tags']=[]
            for stage in ('shot_design','generation'):
                match=select(source,stage,current,['adjacent_panel_pair'])[0]
                app={'memory_id':rule['id'],'rule_version':rule['version'],'rule_signature':match['rule_signature'],'rule_sha256':rule['file']['sha256'],
                    'decision':'APPLIED','reviewer':'SYNTHETIC','evidence':'Synthetic distinct view but unchanged scale',
                    'checks':{'camera_view_distinct':{'status':'PASS','evidence':'Synthetic changed camera'},
                              'shot_scale_distinct':{'status':'FAIL','evidence':'Synthetic source scale remains the same'}},'artifacts':[],'prompt_constraints':[]}
                current.setdefault('memory_applications',{})[stage]=[app]
            shot_ref=write(root,'rule-shots.json',shots);s['half_inputs']['H001']['shot_manifest']=shot_ref
            basis=s['half_inputs']['H001']['visual_basis'];s['half_gates']['H001']['shot_design']=approve([basis,shot_ref])
            approved_source={'root':str(root),'episode_id':'E000','source_script':s['source_script'],'source_snapshot':s['source_snapshot'],
                'visual_basis':basis,'shot_manifest':shot_ref,'visual_approval':s['half_gates']['H001']['visual_basis'],'shot_approval':s['half_gates']['H001']['shot_design']}
            context={'policy':'approved_shot_context_v1','book_id':'UNIT','current':{'episode_id':'E000','panel_id':'P002'},
                'episode_order':['E000'],'sources':[approved_source],'entries':[{'source':0,'panel_id':'P001'}]}
            context_ref=write(root,'rule-context.json',context)
            packet={**m,'panels':[current],'continuity_context':context_ref,'dependency_outputs':{},
                'round_context':{'batch_id':'H001','round_id':1,'attempt_id':'P002-r1'}}
            (root/'P002').mkdir();(root/'P002/prompt.txt').write_text(current['prompt']);write(root,'P002/提示词.json',current)
            subset={**shots,'panels':[current],'continuity_context':context_ref}
            record=s['panels'][1];record.update(package_manifest=write(root,'rule-packet.json',packet),shot_subset=write(root,'rule-subset.json',subset))
            technical=Gate(root,expected_panel_ids=['P002']).run(root/record['shot_subset']['path'],root/record['package_manifest']['path'])
            self.assertEqual(technical['errors'],[]);self.assertEqual(technical['scope'],'STRUCTURAL_AND_INPUT_CONSISTENCY_ONLY')
            view=half_view(s,'H001');errors=input_errors(view,root,record,current,read(root,basis),{r['panel_id']:r for r in s['panels']})
            self.assertTrue(errors);self.assertTrue(all('MEMORY_HOLD:MEM-010:shot_scale_distinct' in e for e in errors),errors)

    def test_full_calibration_failure_repair_context_successor_and_half_aggregate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'calibration'
            s,m,p,shots=tests_calibration(root)
            tests_context(root,s,m,shots)
            tests_successor(root,s,m,shots)

    def test_real_adjacent_context_enforces_observable_camera_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tests_adjacent_context(Path(tmp)/'adjacent')

if __name__=='__main__':unittest.main(verbosity=2)
