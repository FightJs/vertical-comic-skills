"""Observable deadline/publishing behavior; synthetic artifacts, no image calls."""
from pathlib import Path
import hashlib,json,sys,tempfile,unittest,zipfile
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'),str(Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/tests')]
import runtime_clock as c
import deadline_delivery as d
import delivery_contract as dc
from test_hard_deadline import stamp

class WallClockTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.clock=self.root/'00_任务协调'
        c.initialize(self.clock,'production',at=stamp(0),hard_deadline=True,delivery_deadline=True)
        c.event(self.clock,'start','s',at=stamp(0))
    def test_wait_counts_and_drain_reserves_packaging(self):
        c.event(self.clock,'wait_user','w',at=stamp(10));c.event(self.clock,'resume','r',at=stamp(12000))
        v=c.status(self.clock,at=stamp(12600))
        self.assertEqual(v['remaining_seconds'],1800);self.assertEqual(v['schedule_stage'],'DRAIN')
        self.assertEqual(v['active_seconds'],610);self.assertFalse(v['new_calls_allowed'])
        with patch.object(c,'instant',return_value=stamp(12600)):
            with self.assertRaisesRegex(ValueError,'DELIVERY_DRAIN'):c.require_dispatch(self.root)
            self.assertIsNotNone(c.require_step(self.root,'qa-save'))
    def test_new_context_needs_no_optional_hook_receipt(self):
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        with patch.object(c,'instant',return_value=stamp(1)):
            self.assertTrue(c.require_dispatch(self.root)['new_calls_allowed'])
    def test_schedule_cannot_be_removed_or_budget_restarted(self):
        c.initialize_context(self.root,'production',14400,hard_deadline=True)
        with self.assertRaisesRegex(ValueError,'SCOPE_CONFLICT'):
            c.initialize(self.clock,'production',hard_deadline=True)
        p=self.clock/'runtime-clock.json';v=dc.read(p);v.pop('delivery_schedule');p.write_text(json.dumps(v))
        with patch.object(c,'instant',return_value=stamp(1)),self.assertRaisesRegex(ValueError,'SCOPE_MISMATCH'):
            c.require_dispatch(self.root)

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.ep=self.root/'E001';self.state=self.ep/'00_输入审计/生产流程.json';self.state.parent.mkdir(parents=True)
        def ref(name,data):
            p=self.ep/name;p.write_bytes(data);return {'path':name,'sha256':hashlib.sha256(data).hexdigest()}
        self.source=ref('source.json',json.dumps({'panel_ids':['E001-P001','E001-P002']}).encode())
        self.image=ref('image.png',b'synthetic bytes preserved')
        self.value={'book_id':'Test','episode_id':'E001','source_snapshot':self.source,'panels':[
            {'panel_id':'E001-P001','attempt_id':'a1','status':'GENERATED','output':self.image,'round_id':1},
            {'panel_id':'E001-P002','attempt_id':'a2','status':'RESULT_UNKNOWN','round_id':2,'attempt_history':[{'status':'CALL_FAILED'}]}]}
        self.state.write_text(json.dumps(self.value));self.identity=dc.initialize(self.root,'production',[self.state])['path']
        clock=self.root/'00_任务协调';c.initialize(clock,'production',hard_deadline=True,delivery_deadline=True);c.event(clock,'start','s')
    def test_unknown_missing_and_unreviewed_deliver_without_state_changes(self):
        before=self.state.read_bytes();report=d.export(self.identity)
        self.assertEqual(report['source_panel_count'],2);self.assertEqual(report['image_count'],1)
        self.assertEqual(report['counts'],{'INCOMPLETE':2});self.assertFalse(report['all_usable'])
        self.assertEqual(before,self.state.read_bytes())
        with zipfile.ZipFile(report['archive']['path']) as z:
            self.assertIsNone(z.testzip())
            rows=json.loads(z.read('E001/交付索引.json'))['panels']
            self.assertEqual(rows[1]['current_status'],'RESULT_UNKNOWN')
            self.assertEqual(z.read('E001/'+rows[0]['delivered_image']['path']),b'synthetic bytes preserved')
            self.assertIn('问题明细.csv',z.namelist())
    def test_changed_image_rejects_without_overwriting_prior_zip(self):
        first=d.export(self.identity);before=Path(first['archive']['path']).read_bytes()
        (self.ep/'image.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'SNAPSHOT_CHANGED'):d.export(self.identity)
        self.assertEqual(Path(first['archive']['path']).read_bytes(),before)
        self.assertEqual(dc.read(Path(self.identity).parent/d.POINTER)['archive'],first['archive'])
    def test_deadline_does_not_block_packaging_or_create_completion(self):
        clock=c.status(Path(self.identity).parent)
        with patch.object(d,'schedule',return_value={**clock,'state':'RUNNING','remaining_seconds':0,'delivery_due_wall':0}):
            report=d.export(self.identity)
        self.assertFalse(report['published_before_deadline']);self.assertFalse(report['full_quality_guaranteed'])
    def test_adoption_failure_never_silently_uses_newest(self):
        self.value['panels'][0]['adoption']={'attempt_id':'old','reason':'older is better'}
        self.state.write_text(json.dumps(self.value))
        report=d.export(self.identity);self.assertEqual(report['image_count'],0)
    def test_preparation_candidate_retains_inputs_without_fake_executability(self):
        task=self.root/'prep';identity=dc.initialize(task,'preparation',[self.state])['path']
        c.initialize(task/'00_任务协调','preparation',hard_deadline=True,delivery_deadline=True);c.event(task/'00_任务协调','start','s')
        report=d.export(identity)
        self.assertFalse(report['preparation_executable']);self.assertFalse(report['production_state_changed'])
        with zipfile.ZipFile(report['archive']['path']) as z:
            self.assertIn('依据/'+self.source['sha256']+'/source.json',z.namelist())
    def test_real_packager_process_publishes_before_short_deadline(self):
        import subprocess
        task=self.root/'watch-short';identity=dc.initialize(task,'production',[self.state])['path']
        c.initialize(task/'00_任务协调','production',4,hard_deadline=True,delivery_deadline=True);c.event(task/'00_任务协调','start','s')
        run=subprocess.run([sys.executable,'-B',str(Path(d.__file__)),'watch','--contract',identity],capture_output=True,text=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        report=dc.read(Path(identity).parent/d.POINTER)
        self.assertTrue(report['published_before_deadline']);self.assertTrue(Path(report['archive']['path']).is_file())
        self.assertEqual(report['status'],'INCOMPLETE_CHECKPOINT');self.assertFalse(report['task_completed'])

    def test_real_adopted_qa_bound_and_no_final_gate(self):
        from test_delivery_publish import complete_fixture
        helper,state,sp=complete_fixture(self)
        task=self.root/'complete';identity=dc.initialize(task,'production',[sp])['path']
        c.initialize(task/'00_任务协调','production',hard_deadline=True,delivery_deadline=True);c.event(task/'00_任务协调','start','s')
        state['gates'].pop('final');sp.write_text(json.dumps(state));before=sp.read_bytes()
        report=d.export(identity)
        self.assertEqual(report['image_count'],len(state['panels']));self.assertEqual(before,sp.read_bytes())
        with zipfile.ZipFile(report['archive']['path']) as z:
            rows=json.loads(z.read(state['episode_id']+'/交付索引.json'))['panels']
            self.assertEqual(rows[0]['image'],state['panels'][0]['output'])
            self.assertEqual(rows[0]['qa_report'],state['panels'][0]['qa_report'])


class CompleteDeliveryTests(unittest.TestCase):
    def fixture(self):
        from test_delivery_publish import complete_fixture
        h,state,sp=complete_fixture(self)
        task=h.root.parent.parent/'new-full-task'
        identity=dc.initialize(task,'production',[sp])['path']
        c.initialize(task/'00_任务协调','production',hard_deadline=True,delivery_deadline=True);c.event(task/'00_任务协调','start','s')
        return h,state,sp,task,identity
    def test_full_on_time_result_finishes_without_final_D_or_repeat_review(self):
        h,state,sp,task,identity=self.fixture();state['gates'].pop('final');sp.write_text(json.dumps(state))
        import production_progress as progress,task_coordination as tc
        progress.initialize(task/'00_显示进度','production',[sp]);tc.initialize(task/'00_任务协调',task/'00_显示进度')
        report=d.export(identity);self.assertEqual(report['status'],'FULL_RESULT_READY')
        self.assertTrue(report['task_completed']);receipt=Path(identity).parent/d.POINTER
        result=tc.finish(task/'00_任务协调',0,report['archive']['path'],delivery_report=receipt)
        self.assertEqual(result['status'],'READY_TO_DELIVER');self.assertEqual(progress.refresh(task/'00_显示进度')['percent'],100)
    def test_missing_panel_or_unknown_blocks_success(self):
        h,state,sp,task,identity=self.fixture();state['panels'][0]['status']='RESULT_UNKNOWN';sp.write_text(json.dumps(state))
        report=d.export(identity);self.assertEqual(report['status'],'INCOMPLETE_CHECKPOINT')
        self.assertFalse(report['task_completed'])
        with self.assertRaisesRegex(ValueError,'FULL_RESULT_REQUIRED'):d.complete(identity,Path(identity).parent/d.POINTER,report['archive']['path'])
    def test_adopted_old_version_and_major_issue_remain_bound(self):
        import copy
        h,state,sp,task,identity=self.fixture();row=state['panels'][0]
        decision_path=h.root/row['production_decisions'][row['attempt_id']]['path'];decision=dc.read(decision_path)
        decision['issues'][0].update(category=1,kind='action_target',problem='wrong action target',target='approved action target')
        decision_path.write_text(json.dumps(decision));ref={'path':decision_path.relative_to(h.root).as_posix(),'sha256':dc.digest(decision_path)}
        row['production_decisions'][row['attempt_id']]=ref;row['adoption']['decision']=ref
        old=copy.deepcopy(row);old_image=row['output']
        row.update(attempt_id='new-failed',status='CALL_FAILED',round_id=2,attempt_history=[old])
        sp.write_text(json.dumps(state));report=d.export(identity)
        self.assertTrue(report['complete_scope']);self.assertFalse(report['all_usable'])
        with zipfile.ZipFile(report['archive']['path']) as z:
            item=json.loads(z.read(state['episode_id']+'/交付索引.json'))['panels'][0]
            self.assertEqual(item['image'],old_image);self.assertEqual(item['attempt_id'],old['attempt_id'])
            self.assertEqual(item['outcome'],'MANUAL_PRIORITY');self.assertEqual(item['issues'][0]['problem'],'wrong action target')
    def test_light_review_does_not_reintroduce_six_dimension_gate(self):
        import test_light_review
        helper=test_light_review.LightReviewTests();self.addCleanup(helper.doCleanups)
        h,sp,row,proposal=helper.fixture();test_light_review.save(sp,dc.digest(sp),proposal)
        task=h.root.parent.parent/'light-time-task';identity=dc.initialize(task,'production',[sp])['path']
        c.initialize(task/'00_任务协调','production',hard_deadline=True,delivery_deadline=True);c.event(task/'00_任务协调','start','s')
        report=d.export(identity)
        with zipfile.ZipFile(report['archive']['path']) as z:
            index=json.loads(z.read('E000/交付索引.json'))
            self.assertEqual(index['panels'][0]['outcome'],'DELIVERABLE')
            self.assertEqual(index['panels'][0]['image_review_profile'],'light_story_review_v1')
        self.assertFalse(report['task_completed'])  # remaining source panels genuinely absent

if __name__=='__main__':unittest.main()
