import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import production_activation as a
from platform_io import atomic_json
import test_light_review as fixtures
class ActivationTests(unittest.TestCase):
    def test_transaction_recovers_after_one_write(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();x=root/'x.json';y=root/'y.json';atomic_json(x,{'n':0});atomic_json(y,{'n':0})
            original=a.atomic_json;seen=[]
            def fail(p,v):
                if Path(p)==y and not seen:seen.append(1);raise OSError('injected exit')
                return original(p,v)
            with patch.object(a,'atomic_json',side_effect=fail):
                with self.assertRaises(OSError):a.transact(root,{str(x):{'n':1},str(y):{'n':1}},{str(x):a.sha(x),str(y):a.sha(y)})
            self.assertEqual(a.read(x)['n'],1);a.recover(root)
            self.assertEqual(a.read(y)['n'],1);self.assertEqual(a.recover(root)['status'],'COMMITTED')
    def test_changed_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();x=root/'x.json';atomic_json(x,{'n':0})
            with self.assertRaisesRegex(ValueError,'VERSION_CHANGED'):a.transact(root,{str(x):{'n':1}},{str(x):'stale'})
            self.assertEqual(a.read(x)['n'],0)
    def fixture(self):
        f=fixtures.LightReviewTests();self.addCleanup(f.doCleanups);h,p,r,proposal=f.fixture()
        state=a.read(p);state.pop('parallel_context',None);state.pop('dispatch_consistency',None)
        atomic_json(p,state);run=h.root.parent
        manifest=run/'整批执行清单.json';atomic_json(manifest,{'book_id':state['book_id'],'max_inflight':len(state['panels']),
            'episodes':[{'episode_id':state['episode_id'],'state':str(p),'panel_count':len(state['panels'])}]})
        return h,p,state,manifest
    def test_missing_authority_does_not_activate(self):
        h,p,state,m=self.fixture();state.pop('production_authorization',None);atomic_json(p,state);before=p.read_bytes()
        value=a.activate(m,{},a.sha(m));self.assertEqual(value['status'],'PARTIAL_HOLD');self.assertEqual(before,p.read_bytes())
    def test_actual_authority_wires_owner_and_capacity(self):
        h,p,state,m=self.fixture()
        proof={'status':'APPROVED','source_kind':'user_message','quote':'SYNTHETIC production request',
            'source_locator':'fixture://request','book_id':state['book_id'],'episode_id':state['episode_id'],
            'panel_ids':[r['panel_id'] for r in state['panels']],'artifacts':[state['source_script']]}
        result=a.activate(m,{state['episode_id']:proof},a.sha(m));self.assertEqual(result['status'],'ACTIVATED',result)
        from parallel_dispatch import context_errors
        state=a.read(p);self.assertEqual(context_errors(state['parallel_context'],h.root,state['book_id'],state['episode_id']),[])

    def test_view_switch_updates_all_routes_and_blocks_old_dispatch(self):
        import shutil
        from delivery_contract import initialize,load_identity
        h,p,state,m=self.fixture();run=m.parent
        dest=run/'execution-view';shutil.copytree(h.root,dest)
        new=(dest/'00_输入审计/生产流程.json').resolve()
        identity=initialize(run,'production',[p],completion_profile='minimal_panel_delivery_v1')
        task=run/'00_显示进度/task.json';task.parent.mkdir(exist_ok=True)
        atomic_json(task,{'states':[str(p)],'delivery_identity':identity})
        coordinator=run/'00_任务协调/coordination.json';atomic_json(coordinator,{'delivery_identity':identity,'states':[str(p)]})
        a.switch_view(run,p,new,a.sha(identity['path']))
        self.assertEqual(load_identity(identity['path'])['states'],[str(new)])
        self.assertEqual(a.read(task)['delivery_identity']['sha256'],a.sha(identity['path']))
        self.assertEqual(a.read(coordinator)['states'],[str(new)])
        with self.assertRaisesRegex(ValueError,'RELOCATED'):a.require_active(p)
        a.require_active(new)

    def test_readonly_old_state_guard_rejects_racing_dispatch(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();old=root/'old/00_输入审计/生产流程.json';old.parent.mkdir(parents=True)
            target=root/'route.json';atomic_json(old,{'status':'PENDING'});atomic_json(target,{'route':'old'})
            version=a.sha(old);atomic_json(old,{'status':'IN_FLIGHT'})
            with self.assertRaisesRegex(ValueError,'VERSION_CHANGED'):
                a.transact(root,{str(target):{'route':'new'}},{str(target):a.sha(target),str(old):version})
            self.assertEqual(a.read(target)['route'],'old')

    def test_bound_owner_relocation_deduplicates_shared_lock(self):
        import shutil
        from delivery_contract import initialize
        h,p,state,m=self.fixture();run=m.parent
        proof={'status':'APPROVED','source_kind':'user_message','quote':'SYNTHETIC production',
            'source_locator':'fixture://request','book_id':state['book_id'],'episode_id':state['episode_id'],
            'panel_ids':[r['panel_id'] for r in state['panels']],'artifacts':[state['source_script']]}
        a.activate(m,{state['episode_id']:proof},a.sha(m))
        dest=run/'bound-view';shutil.copytree(h.root,dest);new=(dest/'00_输入审计/生产流程.json').resolve()
        identity=initialize(run,'production',[p],completion_profile='minimal_panel_delivery_v1')
        a.switch_view(run,p,new,a.sha(identity['path']))
        from parallel_dispatch import context_errors
        current=a.read(new)
        self.assertEqual(context_errors(current['parallel_context'],dest,current['book_id'],current['episode_id']),[])
        with self.assertRaisesRegex(ValueError,'RELOCATED'):a.require_active(p)
