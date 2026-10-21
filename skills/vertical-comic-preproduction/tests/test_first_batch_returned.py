"""A completed repair may add return evidence, never change authorized inputs."""
import sys, json, io, unittest
from pathlib import Path
from contextlib import redirect_stdout
BASE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(BASE/'scripts'),str(BASE/'tests')]
import test_first_batch_production as fixtures
from codex_reference_contract import checked_file,read_json,validate_panel,digest
from make_generation_qa import _main as make_qa
from panel_delivery import build
from PIL import Image

def run_case(tamper=False):
 harness=fixtures.FirstBatchTests('test_old_adoption_uses_its_own_issues_and_qa')
 try:
  h,s,row,item,d=harness.fixture();row=harness.second_attempt(h,s,row,item,call_failed=False)
  packet=read_json(checked_file(h.root,row['package_manifest']));panel=packet['panels'][0]
  errors,submission=validate_panel(panel,h.root);assert not errors,errors
  image_dir=h.root/'second-real-return';image_dir.mkdir();image=image_dir/'P001.png';Image.new('RGB',(90,160),'yellow').save(image)
  out={'path':str(image.relative_to(h.root)),'sha256':digest(image)}
  req={'attempt_id':row['attempt_id'],'backend_id':'codex_builtin_imagegen','panel_id':'P001',**submission,'source_kind':'observed_tool_call','source_locator':'synthetic://fixture'}
  res={'attempt_id':row['attempt_id'],'status':'COMPLETED','outputs':[out],'source_kind':'observed_tool_result','source_locator':'synthetic://fixture'}
  panel['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],'request_evidence':h.h.f.write('second-request.json',req),'response_evidence':h.h.f.write('second-response.json',res)}
  row.update(package_manifest=h.h.f.write('second-returned.json',packet),status='VISUAL_FAIL',output=out)
  qdir=h.root/'second-qa'
  with redirect_stdout(io.StringIO()):code=make_qa(['--package',str(h.root),'--manifest','second-returned.json','--images',str(image_dir),'--output',str(qdir),'--skip-contact-sheet'])
  assert code==0
  qa=read_json(qdir/'生成图QA报告.json');it=qa['panels'][0]
  for rv in [*it['dimension_review'].values(),it['style_review']]:
   if rv['status']=='UNREVIEWED':rv.update(status='PASS',reviewer='SYNTHETIC',evidence='Fixture only')
  for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match','required_visible_information_preserved','no_extra_offscreen_characters'):it[key]=True
  it['style_review'].update(status='FAIL',reviewer='SYNTHETIC',evidence='Synthetic later candidate has worse style')
  row.update(qa_report=h.h.f.write('second-reviewed.json',qa),failure_diagnosis={'reviewer':'SYNTHETIC','evidence':'later style regression','layer':'generation_execution'})
  if tamper:
   packet['panels'][0]['prompt']+='\nunauthorized creative change'
   row['package_manifest']=h.h.f.write('tampered-return.json',packet)
  result=build(s,h.root)
  assert result['panels'][0]['attempt_id']=='P001-r1',result
  assert result['panels'][0]['issues'][0]['kind']=='finger'
  return result
 finally:harness.doCleanups()

class ReturnedAdoptionTests(unittest.TestCase):
 def test_worse_return_keeps_both_true_qa_and_adopts_first_image(self):
  report=run_case()
  self.assertEqual(report['panels'][0]['attempt_id'],'P001-r1')
 def test_return_evidence_cannot_authorize_changed_prompt(self):
  with self.assertRaises(ValueError):run_case(tamper=True)

if __name__=='__main__':unittest.main()
