"""Actual packaging/gates with synthetic images and approvals; no image-service calls."""
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import delivery_contract as dc
import delivery_publish as pub
import production_progress as progress
from codex_reference_contract import read_json,digest


def complete_fixture(test):
    import io
    import zipfile
    from contextlib import redirect_stdout
    from PIL import Image
    from test_first_batch_production import FirstBatchTests, decision
    from codex_reference_contract import checked_file, read_json, validate_panel, digest
    from make_generation_qa import _main as make_qa
    from panel_delivery import build, export
    from visual_evidence import continuity_targets
    helper=FirstBatchTests();test.addCleanup(helper.doCleanups)
    h,state,_,_,_=helper.fixture();write=h.h.f.write
    shots=read_json(checked_file(h.root,state['shot_manifest']))['panels']
    for row,shot in zip(state['panels'][1:],shots[1:]):
        pid=row['panel_id'];packet=read_json(checked_file(h.root,row['package_manifest']));panel=packet['panels'][0]
        errors,submission=validate_panel(panel,h.root);test.assertFalse(errors)
        idir=h.root/('return-'+pid);idir.mkdir();image=idir/(pid+'.png');Image.frombytes('RGB',(90,160),os.urandom(90*160*3)).save(image)
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
        test.assertEqual(code,0)
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
    review=build(state,h.root);test.assertTrue(review['handoff_complete'],review)
    ref=write('complete-review.json',review);state['delivery_review']=ref
    state['gates']['final']={**h.h.approve([*review['artifacts'],ref]),'panel_ids':review['panel_ids']}
    sp=h.root/'00_输入审计/生产流程.json'
    sp.write_text(json.dumps(state),encoding='utf-8')
    return h,state,sp


class ProductionPublishTests(unittest.TestCase):
    def prepare(self,mode=None,limit=None):
        h,state,sp=complete_fixture(self)
        # Use a task outside the production episode, matching actual receive().
        task=h.root.parent.parent/'delivery-task'
        ref=dc.initialize(task,'production',[sp])
        if limit is not None:
            # Existing bounded v1 task fixture: never create this via new startup.
            identity=Path(ref['path']);marker=dc.read(identity);reqpath=Path(marker['requirements']['path'])
            old=dc.read(reqpath);old.pop('csv_policy');old.update(max_file_bytes=limit,package_mode=mode or 'allow_parts')
            reqpath.write_text(json.dumps(old));marker['requirements']=dc.reference(reqpath)
            identity.write_text(json.dumps(marker));ref=dc.reference(identity)
        return h,state,sp,task,ref

    def test_publish_cli_hold_is_nonzero_json(self):
        import subprocess
        script=Path(__file__).resolve().parents[1]/'scripts/panel_delivery.py'
        result=subprocess.run([sys.executable,'-B',str(script),'--publish','unused',
                               '--contract','missing-contract.json'],capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['status'],'DELIVERY_HOLD')
        self.assertNotIn('Traceback',result.stderr)

    def test_actual_ordinary_zip_exact_images_and_coordinated_completion(self):
        h,state,sp,task,ref=self.prepare()
        before=sp.read_bytes();image_hashes={r['output']['path']:digest(h.root/r['output']['path']) for r in state['panels']}
        output=task/'发送';report=pub.publish_production(ref['path'],output)
        self.assertEqual(report['status'],'DELIVERY_READY');self.assertEqual(len(report['artifacts']),1)
        self.assertEqual(report['image_calls'],0);self.assertFalse(report['images_reencoded'])
        value=dc.load_identity(ref['path']);dc.assert_completion(value,output/pub.REPORT,report['artifacts'][0]['path'])
        with zipfile.ZipFile(report['artifacts'][0]['path']) as z:
            names=z.namelist();self.assertFalse(any(n.endswith('.zip') for n in names))
            import csv,io
            overview=list(csv.DictReader(io.StringIO(z.read('图片问题总览.csv').decode('utf-8-sig'))))
            self.assertEqual([r['格号'] for r in overview],[r['panel_id'] for r in state['panels']])
            self.assertTrue(all(r['图片路径'] in names for r in overview))
            self.assertIn('问题明细.csv',names)
            self.assertIsNone(value['max_file_bytes'])
            for name in names:
                if '/图片/' in name:
                    data=z.read(name);self.assertIn(hashlib.sha256(data).hexdigest(),image_hashes.values())
        self.assertEqual(sp.read_bytes(),before)
        display=task/'00_显示进度';progress.initialize(display,'production',[sp])
        import task_coordination as tc
        coord=task/'00_任务协调';tc.initialize(coord,display)
        with self.assertRaisesRegex(ValueError,'必须提供'):tc.finish(coord,0,report['artifacts'][0]['path'])
        self.assertNotIn('finish',tc.read(coord/'coordination.json'))
        result=tc.finish(coord,0,report['artifacts'][0]['path'],delivery_report=output/pub.REPORT)
        self.assertEqual(result['status'],'READY_TO_DELIVER')
        self.assertEqual(progress.refresh(display)['percent'],100)
        self.assertEqual(len(result['artifacts']),1)
        # A changed ZIP invalidates the fast display and explicit final validator.
        Path(report['artifacts'][0]['path']).write_bytes(b'changed')
        self.assertEqual(progress.show(display)['status'],'REFRESH_REQUIRED')
        self.assertLess(progress.refresh(display)['percent'],100)
        with self.assertRaises(ValueError):dc.assert_completion(value,output/pub.REPORT,report['artifacts'][0]['path'])

    def test_strict_overlimit_stays_hold_and_same_failure_is_not_replayed(self):
        h,state,sp,task,ref=self.prepare(mode='single_zip',limit=65536)
        before=sp.read_bytes();output=task/'发送'
        with self.assertRaisesRegex(ValueError,'SIZE_HOLD'):pub.publish_production(ref['path'],output)
        self.assertFalse(output.exists());self.assertEqual(sp.read_bytes(),before)
        with self.assertRaisesRegex(ValueError,'相同输入'):pub.publish_production(ref['path'],task/'另一个名字')
        log=dc.read(Path(ref['path']).parent/'打包尝试.json')
        self.assertEqual(len(log['attempts']),1);self.assertEqual(log['attempts'][0]['status'],'FAILED')

    def test_authorized_parts_are_ordinary_zip_complete_and_bounded(self):
        h,state,sp,task,ref=self.prepare(limit=65536)
        output=task/'发送';report=pub.publish_production(ref['path'],output)
        self.assertGreater(len(report['artifacts']),1)
        self.assertTrue(all(x['bytes']<=65536 for x in report['artifacts']))
        value=dc.load_identity(ref['path']);dc.assert_completion(value,output/pub.REPORT,report['artifacts'][0]['path'])
        found=[]
        for a in report['artifacts']:
            with zipfile.ZipFile(a['path']) as z:found.extend(n for n in z.namelist() if '/图片/' in n)
        self.assertEqual(len(found),len(state['panels']));self.assertEqual(len(found),len(set(found)))
        Path(report['artifacts'][-1]['path']).unlink()
        with self.assertRaises(ValueError):dc.assert_completion(value,output/pub.REPORT,report['artifacts'][0]['path'])

    def test_foreign_files_and_unfinished_scope_do_not_become_delivery(self):
        h,state,sp,task,ref=self.prepare();value=dc.load_identity(ref['path'])
        expected,_=pub.production_expected(value)
        with self.assertRaisesRegex(ValueError,'夹带'):
            pub.verify_production_files(value,[],{**expected,'旧候选.png':'unused'})
        state['panels'][-1].pop('adoption');sp.write_text(json.dumps(state))
        with self.assertRaises(ValueError):pub.publish_production(ref['path'],task/'发送')

    def test_csv_missing_or_forged_stays_hold(self):
        h,state,sp,task,ref=self.prepare();output=task/'发送'
        report=pub.publish_production(ref['path'],output);value=dc.load_identity(ref['path'])
        source=Path(report['artifacts'][0]['path'])
        with zipfile.ZipFile(source) as z:data={n:z.read(n) for n in z.namelist()}
        missing=task/'missing.zip'
        with zipfile.ZipFile(missing,'w') as z:
            for n,v in data.items():
                if n!='图片问题总览.csv':z.writestr(n,v)
        with self.assertRaisesRegex(ValueError,'缺'):
            pub.verify_production_files(value,[pub.artifact(missing)],report['members'])
        forged={**report['members'],'图片问题总览.csv':hashlib.sha256(b'fake clean').hexdigest()}
        with self.assertRaisesRegex(ValueError,'哈希不符'):
            pub.verify_production_files(value,report['artifacts'],forged)

    def test_content_and_state_mutation_make_receipt_stale(self):
        h,state,sp,task,ref=self.prepare();output=task/'发送'
        report=pub.publish_production(ref['path'],output);value=dc.load_identity(ref['path'])
        state['holds']=[{'reason':'synthetic new actual issue'}];sp.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError,'状态'):dc.validate_receipt(value,output/pub.REPORT)

    def test_successful_same_output_is_reused_without_repacking(self):
        h,state,sp,task,ref=self.prepare();output=task/'发送'
        report=pub.publish_production(ref['path'],output)
        with patch.object(pub,'pack_panels',side_effect=AssertionError('no repeated packing')):
            self.assertEqual(pub.publish_production(ref['path'],output),report)


class PreparationPublishTests(unittest.TestCase):
    def test_real_formal_release_transport_receive_and_complete_gate(self):
        from test_direct_handoff import DirectHandoffTests
        import handoff_zip as hz
        helper=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        helper.setUp();self.addCleanup(helper.doCleanups)
        sp=helper.template/'00_输入审计/生产流程.json'
        task=helper.base/'delivery-task';ref=dc.initialize(task,'preparation',[sp],max_file_bytes=65536)
        before=sp.read_bytes();display=task/'00_显示进度';progress.initialize(display,'preparation',[sp])
        helper.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        source=helper.base/'正式交接包.zip'
        self.assertTrue(source.exists())
        with self.assertRaisesRegex(ValueError,'必须提供'):progress.complete(display,source)
        self.assertFalse((display/'delivered.json').exists())
        output=task/'发送';report=hz.publish(source,ref['path'],output)
        self.assertEqual(report['status'],'DELIVERY_READY');self.assertGreater(len(report['artifacts']),1)
        self.assertTrue(all(a['bytes']<=65536 for a in report['artifacts']))
        self.assertEqual(report['image_calls'],0)
        self.assertEqual(report['content_validation']['kind'],'full_source_recovery_v1')
        with self.assertRaisesRegex(ValueError,'内部原包'):
            progress.complete(display,source,delivery_report=output/pub.REPORT)
        done=progress.complete(display,report['artifacts'][0]['path'],delivery_report=output/pub.REPORT)
        self.assertEqual(done['percent'],100)
        self.assertEqual(sp.read_bytes(),before)
        receipt=dc.read(output/'运输验证.json')
        self.assertEqual(receipt['max_file_bytes'],65536)
        self.assertEqual(receipt['package_mode'],'allow_parts')
        self.assertEqual(receipt['recovery']['file_count'],receipt['original_files'])
        import comic_start
        first=Path(report['artifacts'][0]['path']);self.assertIn('第001卷',first.name)
        received=comic_start.receive(first,runtime_limit_seconds=None,output=task/'receiver')
        self.assertEqual(received['status'],'READY_FOR_PRODUCTION_ROUTING')
        received_contract=dc.load_identity(received['delivery_identity']['path'])
        self.assertIsNone(received_contract['max_file_bytes'])
        self.assertEqual(received_contract['csv_policy'],dc.CSV_POLICY)

    def test_transport_single_limit_does_not_autosplit(self):
        import handoff_transport as transport
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=root/'source.zip'
            data=os.urandom(100000)
            with zipfile.ZipFile(source,'w') as z:z.writestr('包/image.png',data)
            # Unit capacity branch only; real package gates are tested above.
            with patch('handoff_zip.check_delivery_archive',return_value={}):
                with self.assertRaisesRegex(ValueError,'严格单ZIP'):
                    transport.export(source,root/'out',65536,package_mode='single_zip')
            self.assertFalse((root/'out').exists());self.assertTrue(source.exists())

    def test_explicit_assembly_preserves_all_gates_and_only_builds_candidate(self):
        from test_direct_handoff import DirectHandoffTests
        from handoff_delivery import copy_assembly_plan
        import handoff_zip as hz
        f=DirectHandoffTests();f.setUp();self.addCleanup(f.doCleanups)
        rows=[{**x,'reason':'traceability','evidence':'SYNTHETIC reviewed full candidate'} for x in hz.files(f.package)]
        plan={'policy':'explicit_handoff_assembly_v1','files':rows,'required_paths':[hz.INDEX],
              'dependencies':{},'unresolved_paths':[],'reviewer':'SYNTHETIC','evidence':'SYNTHETIC exact fixture'}
        result=copy_assembly_plan(f.package,f.base/'assembled',plan)
        self.assertEqual(result['status'],'ASSEMBLED_CANDIDATE_NOT_APPROVED')
        self.assertEqual(hz.files(f.package),hz.files(f.base/'assembled'))
        bad=copy.deepcopy(plan);bad['files']=[r for r in rows if r['path']!=hz.INDEX]
        with self.assertRaisesRegex(ValueError,'必要材料'):copy_assembly_plan(f.package,f.base/'bad',bad)
        self.assertFalse((f.base/'bad').exists())
        bad=copy.deepcopy(plan);bad['unresolved_paths']=['unknown source']
        with self.assertRaisesRegex(ValueError,'未知依赖'):copy_assembly_plan(f.package,f.base/'unknown',bad)


if __name__=='__main__':unittest.main()
