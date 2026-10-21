"""Displayed progress stays truthful, cached, scoped and independent of authority."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import production_progress as p


class ProgressTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.root = Path(t.name); self.display = self.root/'display'

    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value),encoding='utf-8')
        return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

    def state(self,eid='E001',count=3,unknown=False):
        root = self.root/eid; path = root/'00_输入审计/生产流程.json'
        script = self.write(root/'script.json',{'synthetic':True})
        order = ['P%03d'%i for i in range(1,count+1)]
        source = self.write(root/'source.json',{'panel_ids':order,'locked_scripts':{i:{} for i in order},'source_sha256':script['sha256']})
        state = {'book_id':'SYNTHETIC','episode_id':eid,'source_script':script,'source_snapshot':None if unknown else source,
                 'panels':[{'panel_id':i,'status':'PENDING'} for i in order], 'holds':[]}
        self.write(path,state); return path,state

    def test_unknown_total_is_not_guessed_or_dropped(self):
        a,_ = self.state(count=30); b,_ = self.state('E002',35,unknown=True)
        report=p.initialize(self.display,'production',[a,b])
        self.assertIsNone(report['total']);self.assertIsNone(report['percent'])
        self.assertIn('待核定',p.format_summary(report))
        self.assertEqual(len(report['episodes']),2)

    def test_source_weighting_scope_lock_and_resume_do_not_edit_states(self):
        a,_=self.state(count=30); b,_=self.state('E002',35)
        before={x:x.read_bytes() for x in (a,b)}
        result=p.initialize(self.display,'preparation',[a,b])
        self.assertEqual(result['total'],65);self.assertEqual(result['percent'],5)
        p.initialize(self.display,'preparation',[a,b])
        with self.assertRaises(ValueError):p.initialize(self.display,'production',[a,b])
        self.assertEqual(before,{x:x.read_bytes() for x in (a,b)})
        for weights in p.WEIGHTS.values():self.assertEqual(sum(weights.values()),100)

    def test_half_scope_uses_full_source_denominator_and_retries_do_not_add_panels(self):
        sp,state=self.state(count=35)
        image=self.write(self.root/'image.json',{'synthetic_image_receipt':True})
        for row in state['panels'][:18]:
            row.update(output=image,status='GENERATED',attempt_id='a1',attempt_history=[{'output':image,'attempt_id':'a0'}])
        self.write(sp,state)
        report=p.initialize(self.display,'production',[sp])
        self.assertEqual(report['episodes'][0]['counts']['images'],18)
        self.assertEqual(report['total'],35);self.assertEqual(report['percent'],23)
        self.assertEqual(report['episodes'][0]['counts']['INCOMPLETE'],35)

    def test_cadence_and_important_event_immediate_and_ack_only_after_send(self):
        sp,_=self.state();p.initialize(self.display,'production',[sp])
        self.assertEqual(p.show(self.display,now=0)['status'],'REPORT_DUE')
        self.assertFalse((self.display/'notification.json').exists())
        p.show(self.display,now=0,acknowledge=True)
        self.assertEqual(p.show(self.display,now=599)['status'],'NOT_DUE')
        self.assertEqual(p.show(self.display,now=600)['status'],'REPORT_DUE')
        p.refresh(self.display,wait_kind='SERVICE')
        p.show(self.display,now=601,acknowledge=True)
        self.assertEqual(p.show(self.display,now=1500)['status'],'NOT_DUE')
        self.assertEqual(p.show(self.display,now=1501)['status'],'REPORT_DUE')
        s=p.read(sp);s['holds']=[{'scope':'panels','panel_ids':['P001'],'reason':'missing reference'}];self.write(sp,s)
        p.refresh(self.display,wait_kind='SERVICE')
        self.assertEqual(p.show(self.display,now=602)['status'],'REPORT_DUE')
        p.refresh(self.display,wait_kind='HUMAN')
        self.assertEqual(p.show(self.display,now=9999)['status'],'NOT_DUE')
        p.refresh(self.display);self.assertEqual(p.show(self.display,now=9999)['status'],'REPORT_DUE')

    def test_tick_reads_only_snapshot_and_cursor_no_gates_images_or_metadata_scan(self):
        sp,_=self.state();p.initialize(self.display,'production',[sp])
        original=p.read;seen=[]
        def limited(path):
            seen.append(Path(path).name)
            if Path(path).parent!=self.display:raise AssertionError('timer read production payload')
            return original(path)
        with patch.object(p,'read',side_effect=limited),patch.object(p,'episode',side_effect=AssertionError('no refresh on tick')):
            self.assertEqual(p.show(self.display,now=0)['status'],'REPORT_DUE')
        self.assertEqual(seen,['task.json','snapshot.json'])

    def test_changed_deleted_evidence_invalidates_cache_and_progress_can_regress(self):
        sp,state=self.state()
        ref=self.write(self.root/'image.json',{'synthetic':True})
        state['panels'][0].update(output=ref,status='GENERATED');self.write(sp,state)
        old=p.initialize(self.display,'production',[sp])
        Path(ref['path']).unlink()
        self.assertEqual(p.show(self.display)['status'],'REFRESH_REQUIRED')
        new=p.refresh(self.display)
        self.assertLess(new['percent'],old['percent'])
        self.assertEqual(state,p.read(sp))

    def test_observer_reuses_existing_reception_and_does_not_reset_real_progress(self):
        sp,state=self.state();p.initialize(self.display,'production',[sp])
        result={'source_kind':'observed_frozen_gate_rehearsal','status':'RELEASE_CANDIDATE',
                'results':[{'episode_id':'E001','status':'REHEARSED'}]}
        p.observe_runtime(self.display,sp,'rehearsal',result)
        first=p.refresh(self.display);self.assertEqual(first['percent'],5)
        state['panels'][0]['status']='IN_FLIGHT';self.write(sp,state)
        second=p.refresh(self.display)
        self.assertEqual(second['stage_units']['receive'],3)
        self.assertEqual(first['last_real_progress_at'],second['last_real_progress_at'])
        p.show(self.display,acknowledge=True)
        self.assertEqual(state,p.read(sp))
        state['visual_basis']={'path':'new','sha256':'invalid'};self.write(sp,state)
        self.assertEqual(p.refresh(self.display)['stage_units']['receive'],0)

    def test_false_final_pass_or_unknown_never_means_delivery(self):
        sp,state=self.state();state['panels'][0]['status']='RESULT_UNKNOWN';self.write(sp,state)
        p.initialize(self.display,'production',[sp])
        p.observe_runtime(self.display,sp,'checkpoint',{'status':'PASS','next_action':'READY_FOR_EPISODE_PANEL'})
        result=p.refresh(self.display)
        self.assertEqual(result['stage_units']['continuity'],0)
        self.assertEqual(result['episodes'][0]['counts']['unknown'],1)
        self.assertLess(result['percent'],100)
        self.assertFalse((self.display/'delivered.json').exists())

    def test_real_qa_failure_and_manual_adoption_preserved_without_image_hashing(self):
        from test_first_batch_production import FirstBatchTests
        helper=FirstBatchTests();self.addCleanup(helper.doCleanups)
        h,state,row,_,_=helper.fixture()
        sp=h.root/'00_输入审计/生产流程.json';self.write(sp,state)
        report=p.initialize(self.display,'production',[sp])
        counts=report['episodes'][0]['counts']
        self.assertEqual(counts['images'],1);self.assertEqual(counts['reviewed'],1)
        self.assertEqual(counts['adopted'],1);self.assertEqual(counts['MANUAL_RETOUCH'],1)
        self.assertEqual(p.read(sp)['panels'][0]['status'],'VISUAL_FAIL')
        self.assertLess(report['percent'],100)

    def test_invalid_intervals_and_duplicate_episode_rejected(self):
        with self.assertRaises(ValueError):p.settings({'yield_seconds':61})
        with self.assertRaises(ValueError):p.settings({'active_seconds':True})
        sp,state=self.state();other=self.root/'other/00_输入审计/生产流程.json';self.write(other,state)
        with self.assertRaises(ValueError):p.initialize(self.display,'production',[sp,other])

    def test_current_stage_and_additional_blocker_do_not_change_percentage(self):
        sp,_=self.state();first=p.initialize(self.display,'production',[sp])
        block={'kind':'DEPENDENCY','scope':'E001','panel_ids':['P002'],'reason':'等待P001真实图片'}
        second=p.refresh(self.display,stage='images',activity='生产就绪格',blockers=[block])
        self.assertEqual(second['percent'],first['percent']);self.assertEqual(second['stage'],'images')
        self.assertIn('等待P001真实图片',p.format_summary(second))

    def test_display_initialization_failure_never_changes_production_result(self):
        from comic_start import start_display
        sp,_=self.state();before=sp.read_bytes()
        with patch.object(p,'initialize',side_effect=OSError('synthetic display failure')):
            result=start_display(self.display,'production',[sp])
        self.assertIn('progress_warning',result);self.assertEqual(sp.read_bytes(),before)

    def test_old_checker_result_cannot_be_bound_to_new_state(self):
        sp,state=self.state();p.initialize(self.display,'production',[sp]);old=copy.deepcopy(state)
        state['panels'][0]['status']='IN_FLIGHT';self.write(sp,state)
        with self.assertRaises(ValueError):p.observe_runtime(self.display,sp,'checkpoint',{'status':'PASS','next_action':'READY_TO_PACKAGE'},expected_state=old)


class ProgressHandoffIntegration(unittest.TestCase):
    def test_formal_zip_roundtrip_and_preparation_hundred_requires_actual_release(self):
        from test_direct_handoff import DirectHandoffTests
        helper=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        helper.setUp();self.addCleanup(helper.doCleanups)
        sp=helper.template/'00_输入审计/生产流程.json';display=helper.base/'progress'
        before=sp.read_bytes()
        prepared=p.initialize(display,'preparation',[sp])
        self.assertEqual(prepared['percent'],80,prepared)
        self.assertLess(prepared['percent'],100)
        helper.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        done=p.complete(display,helper.base/'正式交接包.zip')
        self.assertEqual(done['percent'],100,done)
        # Real handoff ZIP must pass the coordinated finish path too.
        import task_coordination as tc
        coordination=display.parent/'00_任务协调'
        tc.initialize(coordination,display)
        finished=tc.finish(coordination,0,helper.base/'正式交接包.zip')
        self.assertEqual(finished['status'],'READY_TO_DELIVER')
        self.assertEqual(finished['archive'],tc.reference(helper.base/'正式交接包.zip'))
        self.assertEqual(sp.read_bytes(),before)
        # Changing a dependency invalidates 100 even if the state file stayed unchanged.
        source=p.read(sp)['shot_manifest'];Path(helper.template/source['path']).write_text('{}',encoding='utf-8')
        self.assertEqual(p.show(display)['status'],'REFRESH_REQUIRED')
        self.assertLess(p.refresh(display)['percent'],100)

    def test_actual_complete_production_zip_and_changed_image_cannot_stay_hundred(self):
        import io
        import zipfile
        from contextlib import redirect_stdout
        from PIL import Image
        from test_first_batch_production import FirstBatchTests, decision
        from codex_reference_contract import checked_file, read_json, validate_panel, digest
        from make_generation_qa import _main as make_qa
        from panel_delivery import build, export
        from visual_evidence import continuity_targets
        helper=FirstBatchTests();self.addCleanup(helper.doCleanups)
        h,state,_,_,_=helper.fixture();write=h.h.f.write
        shots=read_json(checked_file(h.root,state['shot_manifest']))['panels']
        for row,shot in zip(state['panels'][1:],shots[1:]):
            pid=row['panel_id'];packet=read_json(checked_file(h.root,row['package_manifest']));panel=packet['panels'][0]
            errors,submission=validate_panel(panel,h.root);self.assertFalse(errors)
            idir=h.root/('return-'+pid);idir.mkdir();image=idir/(pid+'.png');Image.new('RGB',(90,160),'blue').save(image)
            output={'path':image.relative_to(h.root).as_posix(),'sha256':digest(image)}
            request={'attempt_id':row['attempt_id'],'backend_id':'codex_builtin_imagegen','panel_id':pid,**submission,
                     'source_kind':'observed_tool_call','source_locator':'synthetic://test-only'}
            response={'attempt_id':row['attempt_id'],'status':'COMPLETED','outputs':[output],
                      'source_kind':'observed_tool_result','source_locator':'synthetic://test-only'}
            panel['generation_execution']={'status':'COMPLETED','attempt_id':row['attempt_id'],
                'request_evidence':write(pid+'-req.json',request),'response_evidence':write(pid+'-res.json',response)}
            row.update(package_manifest=write(pid+'-returned.json',packet),status='VISUAL_PASS',output=output)
            qdir=h.root/('qa-'+pid)
            with redirect_stdout(io.StringIO()):
                code=make_qa(['--package',str(h.root),'--manifest',pid+'-returned.json','--images',str(idir),
                              '--output',str(qdir),'--skip-contact-sheet'])
            self.assertEqual(code,0)
            q=read_json(qdir/'生成图QA报告.json');item=q['panels'][0]
            for check in [*item['dimension_review'].values(),item['style_review']]:
                if check['status']=='UNREVIEWED':check.update(status='PASS',reviewer='SYNTHETIC',evidence='Synthetic only')
            for key in ('camera_match','shot_scale_match','background_view_match','body_crop_match',
                        'required_visible_information_preserved','no_extra_offscreen_characters'):item[key]=True
            item.setdefault('visual_evidence_review',{})['continuity_comparisons']=[
                {'panel_id':prior,'image':next(r for r in state['panels'] if r['panel_id']==prior)['output'],
                 'status':'PASS','observed':'SYNTHETIC actual files compared'} for prior in continuity_targets(shot)]
            row['qa_report']=write(pid+'-review.json',q)
            d=decision(row,item,[],action='complete');ref=write(pid+'-decision.json',d)
            row.update(production_decisions={row['attempt_id']:ref},adoption={'attempt_id':row['attempt_id'],'decision':ref,'reason':'Synthetic adopted'})
        continuity=read_json(checked_file(h.root,state['batch_reviews']['EPISODE']))
        continuity['outputs']=[r['output'] for r in state['panels']]
        state['batch_reviews']['EPISODE']=write('all-continuity.json',continuity)
        review=build(state,h.root);self.assertTrue(review['handoff_complete'],review)
        ref=write('complete-review.json',review);state['delivery_review']=ref
        state['gates']['final']={**h.h.approve([*review['artifacts'],ref]),'panel_ids':review['panel_ids']}
        out=h.root/'final-images';export(state,h.root,ref,out)
        archive=h.root/'final.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for file in out.rglob('*'):
                if file.is_file():z.write(file,'E000/'+file.relative_to(out).as_posix())
        sp=h.root/'00_输入审计/生产流程.json';sp.write_text(json.dumps(state),encoding='utf-8')
        display=h.root/'display';p.initialize(display,'production',[sp])
        self.assertEqual(p.complete(display,archive)['percent'],100)
        self.assertEqual(p.read(sp)['panels'][0]['status'],'VISUAL_FAIL')
        changed=checked_file(h.root,state['panels'][0]['output']);changed.write_bytes(b'changed')
        self.assertEqual(p.show(display)['status'],'REFRESH_REQUIRED')
        self.assertLess(p.refresh(display)['percent'],100)
