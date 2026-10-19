"""Independent synthetic lifecycle; no production files or real image calls."""
import sys, tempfile, shutil, json, copy, subprocess, unittest
from pathlib import Path
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'scripts'),str(BASE/'tests')]
import test_staged_workflow as staged_fixtures
from staged_workflow import evaluate,qa_errors
from scoped_inputs import POLICY,build_plan,half_view
from batch_round import template
from batch_workflow import cross_episode_errors
from codex_reference_contract import digest,validate_panel
from PIL import Image
SCRIPT=BASE/'scripts'
def run():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);fixtures=[]; packets=[];bases=[]
  def write(base,name,data):
   path=base/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,ensure_ascii=False), encoding='utf-8', newline='\n');return {'path':name,'sha256':digest(path)}
  def ep_ref(base,ref):return {**ref,'path':(base/ref['path']).relative_to(root).as_posix()}
  def approve(artifacts):return {'status':'APPROVED','source_kind':'user_message','source_locator':'synthetic://not-real','quote':'SYNTHETIC APPROVAL ONLY','book_id':'UNIT','episode_id':'E000','artifacts':artifacts}
  try:
   for i in (1,2):
    h=staged_fixtures.StagedTests();h.setUp();fixtures.append(h);old=h.real_input();dest=root/f'packet{i}';shutil.copytree(h.root,dest)
    shutil.copy2(dest/'identity-proof.json',root/'identity-proof.json')
    pid=f'P{i:03d}';bid=f'H{i:03d}';manifest=json.loads(json.dumps(h.manifest).replace('P001',pid));panel=manifest['panels'][0]
    if i==2:(dest/'P001').rename(dest/'P002')
    panel.update(generation_dependencies=[],requires_state_review=False)
    manifest.update(execution_mode='half_episode_async_v1',optimization_policy=POLICY,round_context={'batch_id':bid,'round_id':1,'attempt_id':pid+'-r1'})
    (dest/pid/'prompt.txt').write_text(panel['prompt'], encoding='utf-8', newline='\n');write(dest,f'{pid}/提示词.json',panel);write(dest,'全话提示词索引.json',manifest)
    basis=json.loads((h.root/old['visual_basis']['path']).read_text(encoding='utf-8-sig').replace('P001',pid));basis['reference_files']=[ep_ref(dest,r) for r in basis['reference_files']]
    packets.append((dest,pid,bid,manifest));bases.append(basis)
   source=write(root,'source.json',{'SYNTHETIC':'2-panel-source'})
   snap=write(root,'snapshot.json',{'source_sha256':source['sha256'],'panel_ids':['P001','P002'],'locked_scripts':{pid:m['panels'][0]['locked_script'] for d,pid,b,m in packets}})
   s={'policy':'staged_comic_v1','execution_mode':'half_episode_async_v1','optimization_policy':POLICY,'book_id':'UNIT','episode_id':'E000','source_script':source,'source_snapshot':snap,'review_policy':{'systemic_failure_count_gt':5,'max_auto_correction_rounds':1},'half_inputs':{},'half_gates':{},'gates':{},'state_reviews':{},'round_reviews':{},'batch_reviews':{},'holds':[],'cancelled':False,'panels':[],'production_authorization':{**approve([source]),'panel_ids':['P001','P002']}}
   for (dest,pid,bid,m),basis in zip(packets,bases):
    br=write(root,bid+'-basis.json',basis);shots=copy.deepcopy(m);sr=write(root,bid+'-shots.json',shots)
    s['half_inputs'][bid]={'visual_basis':br,'shot_manifest':sr};s['half_gates'][bid]={'visual_basis':approve([source,snap,br]),'shot_design':approve([br,sr])}
    s['panels'].append({'panel_id':pid,'status':'PENDING','round_id':1,'attempt_id':pid+'-r1','package_manifest':ep_ref(dest,{'path':'全话提示词索引.json','sha256':digest(dest/'全话提示词索引.json')}),'shot_subset':write(root,bid+'-subset.json',shots)})
   plan=build_plan(s,json.loads((root/'snapshot.json').read_text(encoding='utf-8-sig')));s['batch_plan']=write(root,'plan.json',plan)
   for i,(dest,pid,bid,m) in enumerate(packets):
    pre=evaluate(s,root,'generate',pid);assert pre['status']=='PASS'
    panel=m['panels'][0];errs,submission=validate_panel(panel,dest);assert not errs;images=dest/'images';images.mkdir();out=images/(pid+'.png');Image.new('RGB',(90,160),'white').save(out)
    req={'attempt_id':pid+'-r1','backend_id':'codex_builtin_imagegen','panel_id':pid,**submission,'source_kind':'observed_tool_call','source_locator':'synthetic://not-real'}
    res={'attempt_id':pid+'-r1','status':'COMPLETED','outputs':[{'path':out.relative_to(dest).as_posix(),'sha256':digest(out)}],'source_kind':'observed_tool_result','source_locator':'synthetic://not-real'}
    panel['generation_execution']={'status':'COMPLETED','attempt_id':pid+'-r1','request_evidence':write(dest,'request.json',req),'response_evidence':write(dest,'response.json',res)};mr=write(dest,'全话提示词索引.json',m)
    qdir=dest/'qa';p=subprocess.run([sys.executable, '-X', 'utf8',str(SCRIPT/'make_generation_qa.py'),'--package',str(dest),'--images',str(images),'--output',str(qdir)],capture_output=True,text=True, encoding='utf-8');assert p.returncode==0,p.stderr
    qa=json.loads((qdir/'生成图QA报告.json').read_text(encoding='utf-8-sig'));item=qa['panels'][0]
    for rv in [*item['dimension_review'].values(),item['style_review']]:rv.update(status='PASS',reviewer='SYNTHETIC',evidence='TEST ONLY')
    for k in ('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters'):item[k]=True
    r=s['panels'][i];r.update(status='VISUAL_PASS',package_manifest=ep_ref(dest,mr),output=ep_ref(dest,{'path':out.relative_to(dest).as_posix(),'sha256':digest(out)}),qa_report=ep_ref(dest,write(dest,'reviewed-qa.json',qa)))
    assert not qa_errors(root,r)
    from review_reuse import fingerprint
    fingerprint(root,r)
    view=half_view(s,bid);batch=plan['batches'][i]
    rep=template(view,batch,{x['panel_id']:x for x in s['panels']},1);rep.update(status='REVIEWED',reviewer='SYNTHETIC',evidence='TEST ONLY');s['round_reviews'][bid]={'1':write(root,bid+'-round.json',rep)}
    cont={'policy':'batch_review_v1','book_id':'UNIT','episode_id':'E000',**batch,'status':'PASS','reviewer':'SYNTHETIC','evidence':'TEST ONLY','visual_basis':view['visual_basis'],'shot_manifest':view['shot_manifest'],'outputs':[r['output']],'previous_outputs':[s['panels'][0]['output']] if i else []};s['batch_reviews'][bid]=write(root,bid+'-continuity.json',cont)
    x=evaluate(s,root);assert x['qa_reuse_statistics']['hits']>=1,x
    if i==0:
     assert x['next_action']=='WAIT_FIRST_HALF_APPROVAL';s['gates']['pilot']=approve([view['visual_basis'],view['shot_manifest'],r['output']])
    else:assert x['next_action']=='WAIT_FINAL_APPROVAL'
   refs=[s['source_script'],s['source_snapshot']]
   for pair in s['half_inputs'].values():refs.extend(pair.values())
   refs.extend(r['output'] for r in s['panels']);s['gates']['final']=approve(refs);assert evaluate(s,root,'deliver')['next_action']=='READY_TO_PACKAGE'
   write(root,'00_输入审计/生产流程.json',s)
   # Cross-episode verifier: use two synthetic job records referring to the same
   # fully checked fixture, isolating frozen input/report scope from orchestration.
   jobs=[{'job_id':j,'episode_id':'E000','root':str(root),'frozen_inputs':{'source_script':s['source_script'],'source_snapshot':s['source_snapshot']},'frozen_halves':copy.deepcopy(s['half_inputs'])} for j in ['J1','J2']]
   control={'book_id':'UNIT','epoch':1,'shared_files':[],'jobs':jobs};cross={'policy':'cross_episode_review_v1','book_id':'UNIT','epoch':1,'shared_files':[],'status':'PASS','reviewer':'SYNTHETIC','evidence':'TEST ONLY','episodes':[{'job_id':j['job_id'],'episode_id':'E000','half_inputs':s['half_inputs'],'outputs':[r['output'] for r in s['panels']],'qa_reports':[r['qa_report'] for r in s['panels']]} for j in jobs]}
   control['cross_episode_review']=write(root,'cross.json',cross);write(root,'control.json',control);ctx={'control_file':str(root/'control.json')};errors=cross_episode_errors(ctx);assert not errors
   control['jobs'][0]['frozen_halves']['H002']['shot_manifest']=s['half_inputs']['H001']['shot_manifest'];write(root,'control.json',control);assert any('冻结' in e for e in cross_episode_errors(ctx))
  finally:
   for h in fixtures:h.doCleanups()

class ScopedLifecycleTests(unittest.TestCase):
 def test_real_two_package_half_C_D_and_cross_frozen_binding(self):
  run()

if __name__=='__main__':unittest.main()
