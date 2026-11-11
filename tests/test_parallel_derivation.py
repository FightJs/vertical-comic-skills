"""Parallel draft derivation: synthetic local inputs, no image-service calls."""
import concurrent.futures
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/vertical-comic-preproduction/scripts'
sys.path.insert(0,str(SCRIPTS))
import panel_derivation as derivation
from input_dependencies import fingerprint,file_hash

class ParallelDerivationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.environment=patch.dict(os.environ,{'COMIC_RESOURCE_HOME':str(self.root/'resources')})
        self.environment.start();self.addCleanup(self.environment.stop)
        # Keep real admission/leases and locks; only machine telemetry is synthetic.
        from machine_resources import boot_id
        healthy=lambda disk:{'at':time.monotonic(),'boot':boot_id(),'cpus':8,'known':True,
            'total':32*1024**3,'available':24*1024**3,'compressed':0,'swapout':0,'pressure':1,'disk_free':20*1024**3}
        self.probe=patch('machine_resources.sample_system',healthy)
        self.probe.start();self.addCleanup(self.probe.stop)

    def fixture(self,count=3):
        ids=[f'P{i:03d}' for i in range(1,count+1)]
        snapshot=self.root/'snapshot.json'
        locked={pid:'Synthetic original '+pid for pid in ids}
        snapshot.write_text(json.dumps({'panel_ids':ids,'locked_scripts':locked}))
        rows=[]
        for pid in ids:
            shot={'panel_id':pid,'locked_script':locked[pid],'visual_focus':'original'}
            execution={'prompt':'Synthetic complete prompt '+pid}
            rows.append({'panel_id':pid,'shot':shot,'execution':execution,
                         'packet_header':{'book_id':'BOOK','episode_id':'E001'},
                         'render_mode':'preserved_import','import_panel_key':fingerprint({**shot,**execution})})
        source={'policy':'panel_authoring_source_v1','status':'WORKING_DRAFT','book_id':'BOOK','episode_id':'E001',
                'run_root':str(self.root),'source_snapshot':{'path':str(snapshot),'sha256':file_hash(snapshot)},
                'panel_ids':ids,'panels':rows,'shared':{},'shot_header':{'book_id':'BOOK','episode_id':'E001'}}
        path=self.root/'source.json';path.write_text(json.dumps(source));return path,source

    def test_facial_continuity_uses_only_visible_bound_identity_references(self):
        panel={'reference_images':[{'alias':'A'},{'alias':'B'}],
               'character_bindings':[{'on_screen':True,'character_id':'c1','identity_asset_alias':'A'},
                   {'on_screen':True,'character_id':'c2','identity_asset_alias':'B'},
                   {'on_screen':True,'character_id':'c3','identity_asset_alias':'MISSING'},
                   {'on_screen':False,'character_id':'c4','identity_asset_alias':'A'}],
               'subject_visibility':{'c2':{'face_visible':False}}}
        block=derivation.facial_continuity_block(panel)
        self.assertIn('c1：身份参考A',block)
        self.assertNotIn('c2',block);self.assertNotIn('c3',block);self.assertNotIn('c4',block)
        self.assertIn('表情、视线与透视',block);self.assertIn('不强行露出',block)
        panel['subject_visibility']['c1']={'face_visible':False}
        self.assertEqual(derivation.facial_continuity_block(panel),'')

    def test_fast_panel_publishes_before_slow_first_and_rows_stay_in_source_order(self):
        # A serial render loop or ordered future.result() would deadlock this barrier.
        path,source=self.fixture();slow_started=threading.Event();fast_published=threading.Event()
        real_render=derivation.render;active=0;peak=0;lock=threading.Lock();published=[]
        def render(*args):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            try:
                if args[1]['panel_id']=='P001':
                    slow_started.set();self.assertTrue(fast_published.wait(5),'fast sink was held behind first row')
                else:self.assertTrue(slow_started.wait(5))
                return real_render(*args)
            finally:
                with lock:active-=1
        def sink(row):
            self.assertTrue(all(file_hash(r['path'])==r['sha256'] for r in row['artifacts']))
            published.append(row['panel_id'])
            if row['panel_id']!='P001':fast_published.set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            pool.resource_admission='host_managed'
            with patch.object(derivation,'render',render):
                result=derivation.derive(path,self.root/'first',workers=3,sink=sink,executor=pool)
        self.assertGreaterEqual(peak,2)
        self.assertGreaterEqual(result['metrics']['peak_active_compiles'],2)
        self.assertLess(result['metrics']['first_ready_seconds'],result['metrics']['elapsed_seconds'])
        self.assertNotEqual(published[0],'P001')
        self.assertEqual([r['panel_id'] for r in result['panels']],source['panel_ids'])

    def test_scope_selects_real_rows_while_retaining_full_original_order(self):
        path,source=self.fixture()
        result=derivation.derive(path,self.root/'selected',panel_ids=['P003','P001'],workers=2)
        self.assertEqual(result['panel_ids'],['P001','P002','P003'])
        self.assertEqual([r['panel_id'] for r in result['panels']],['P001','P003'])
        self.assertEqual(result['metrics']['compiled_panels'],2)
        self.assertFalse((self.root/'selected'/'P002').exists())

    def test_dependency_failure_keeps_dependents_pending_and_unrelated_sink_ready(self):
        path,source=self.fixture(4);source['panels'][1]['dependencies']=['P001']
        source['panels'][2]['dependencies']=['P002']
        source['panels'][0]['import_panel_key']='invalid'
        path.write_text(json.dumps(source));published=[]
        result=derivation.derive(path,self.root/'failure',workers=4,sink=published.append)
        self.assertEqual(result['pending_panel_ids'],['P001','P002','P003'])
        self.assertEqual({r['panel_id'] for r in published if not r.get('pending')},{'P004'})
        self.assertEqual(set(result['errors']),{'P001'})

    def test_stream_rechecks_changed_shared_bytes_before_fast_panel_sink(self):
        path,source=self.fixture(2);dependency=self.root/'shared.txt';dependency.write_text('old')
        source['shot_header']['rule_reference']={'path':str(dependency),'sha256':file_hash(dependency)}
        path.write_text(json.dumps(source));published=[];fast_rendered=threading.Event();mutated=threading.Event()
        real_render=derivation.render
        def render(*args):
            panel=real_render(*args)
            if args[1]['panel_id']=='P001':
                self.assertTrue(fast_rendered.wait(5));dependency.write_text('new');mutated.set();time.sleep(.1)
            else:
                fast_rendered.set();self.assertTrue(mutated.wait(5))
            return panel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.resource_admission='host_managed'
            with patch.object(derivation,'render',render):
                with self.assertRaisesRegex(ValueError,'DRAFT_DEPENDENCY_CHANGED'):
                    derivation.derive(path,self.root/'stale-stream',sink=published.append,executor=pool)
        self.assertEqual(published,[],'stale fast row reached downstream before final transaction rejection')

    def test_stream_rechecks_source_identity_before_fast_panel_sink(self):
        path,source=self.fixture(2);published=[];fast_rendered=threading.Event();mutated=threading.Event()
        real_render=derivation.render
        def render(*args):
            panel=real_render(*args)
            if args[1]['panel_id']=='P001':
                self.assertTrue(fast_rendered.wait(5));path.write_text(path.read_text()+'\n');mutated.set();time.sleep(.1)
            else:
                fast_rendered.set();self.assertTrue(mutated.wait(5))
            return panel
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.resource_admission='host_managed'
            with patch.object(derivation,'render',render):
                with self.assertRaisesRegex(ValueError,'输入或工具变化'):
                    derivation.derive(path,self.root/'stale-source-stream',sink=published.append,executor=pool)
        self.assertEqual(published,[])

    def test_stale_source_is_rejected_after_worker_finishes(self):
        path,source=self.fixture();real_render=derivation.render
        def render(*args):
            panel=real_render(*args)
            if args[1]['panel_id']=='P001':path.write_text(path.read_text()+'\n')
            return panel
        with patch.object(derivation,'render',render):
            with self.assertRaisesRegex(ValueError,'输入或工具变化'):
                derivation.derive(path,self.root/'stale',workers=2)
        self.assertFalse((self.root/'stale'/'派生记录.json').exists())

    def test_shared_executor_survives_multiple_derivations(self):
        path,source=self.fixture()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.resource_admission='host_managed'
            a=derivation.derive(path,self.root/'a',executor=pool)
            b=derivation.derive(path,self.root/'b',executor=pool)
            self.assertEqual(pool.submit(lambda:17).result(),17)
        self.assertEqual(a['metrics']['compiled_panels'],3)
        self.assertEqual(b['metrics']['compiled_panels'],0)
        self.assertEqual(b['metrics']['reused_panels'],3)

    def scoped_fixture(self,complete_all=False,scope_ids=None,neighbor_ids=()):
        from preparation_workspace import Workspace
        path,source=self.fixture();ids=source['panel_ids']
        source['source_snapshot']['path']='snapshot.json'
        ratios=[{'panel_id':pid,'frame_ratio':ratio,'frame_ratio_reason':'subject '+pid}
                for pid,ratio in zip(ids,['9:16','3:4','4:5'])]
        plan=self.root/'ratios.json'
        plan.write_text(json.dumps({'policy':'content_balanced_ratios_v1','book_id':'BOOK','episode_id':'E001',
            'source_snapshot':source['source_snapshot'],'panel_ids':ids,'panels':ratios}))
        workspace=Workspace(self.root)
        workspace.initialize(source['source_snapshot'],'BOOK','E001',{},source['shot_header'],
            frame_ratio_plan={'path':'ratios.json','sha256':file_hash(plan)})
        rows=[row for row in source['panels'] if complete_all or row['panel_id'] in (scope_ids or ['P002'])]
        for row in rows:
            position=ids.index(row['panel_id']);row['shot'].update(ratios[position])
            row['import_panel_key']=fingerprint({**row['shot'],**row['execution']})
            if (complete_all and row['panel_id']=='P002') or row['panel_id'] in neighbor_ids:row['neighbor_context']=True
        workspace.submit({'operation_id':'one','base_revision':0,'shared_version':0,
            'row_versions':{row['panel_id']:0 for row in rows},'panels':rows})
        path=self.root/'scope.json';path.write_text(json.dumps(workspace.scope(ids if complete_all else scope_ids or ['P002'])))
        return path,plan

    def test_internal_scope_consumes_only_completed_rows_and_old_validator_remains_strict(self):
        from panel_source import validate,read
        path,plan=self.scoped_fixture()
        with self.assertRaises(ValueError):validate(read(path))
        with self.assertRaisesRegex(ValueError,'REQUIRES_PANEL_IDS'):
            derivation.derive(path,self.root/'implicit-scope')
        result=derivation.derive(path,self.root/'explicit-scope',panel_ids=['P002'],workers=2)
        self.assertEqual(result['panel_ids'],['P001','P002','P003'])
        self.assertEqual([r['panel_id'] for r in result['panels']],['P002'])
        self.assertEqual(result['metrics']['compiled_panels'],1)

    def test_scope_can_compile_exact_subset_while_retaining_completed_neighbor_context(self):
        path,plan=self.scoped_fixture(complete_all=True)
        result=derivation.derive(path,self.root/'subset-context',panel_ids=['P002'],workers=2)
        self.assertEqual(result['selected_panel_ids'],['P002'])
        self.assertEqual([r['panel_id'] for r in result['panels']],['P002'])
        self.assertEqual(result['metrics']['compiled_panels'],1)
        self.assertEqual(result['panels'][0]['depends_on'],['P001','P003'])

    def test_direct_subset_recompiles_when_nonselected_actual_neighbor_changes(self):
        path,source=self.fixture();source['panels'][1]['neighbor_context']=True
        path.write_text(json.dumps(source))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            pool.resource_admission='host_managed'
            first=derivation.derive(path,self.root/'neighbor-cold',panel_ids=['P002'],executor=pool)
            source['panels'][0]['shot']['visual_focus']='changed authored adjacent shot'
            row=source['panels'][0];row['import_panel_key']=fingerprint({**row['shot'],**row['execution']})
            path.write_text(json.dumps(source))
            second=derivation.derive(path,self.root/'neighbor-changed',panel_ids=['P002'],executor=pool)
        self.assertEqual(first['metrics']['compiled_panels'],1)
        self.assertEqual(second['metrics']['compiled_panels'],1)
        self.assertEqual(second['impact']['affected_panel_ids'],['P002'])

    def test_direct_subset_captures_nonselected_neighbor_reference_bytes(self):
        path,source=self.fixture();source['panels'][1]['neighbor_context']=True
        reference=self.root/'neighbor-ref.txt';reference.write_text('authored reference')
        row=source['panels'][0];row['shot']['context_reference']={'path':str(reference),'sha256':file_hash(reference)}
        row['import_panel_key']=fingerprint({**row['shot'],**row['execution']})
        path.write_text(json.dumps(source))
        first=derivation.derive(path,self.root/'neighbor-ref',panel_ids=['P002'],workers=2)
        self.assertIn(str(reference),[o['path'] for o in first['panels'][0]['observations']])
        reference.unlink()
        second=derivation.derive(path,self.root/'neighbor-ref-missing',panel_ids=['P002'],workers=2)
        self.assertEqual(second['pending_panel_ids'],['P002'])
        self.assertEqual(second['metrics']['compiled_panels'],0)

    def test_partial_scope_missing_global_neighbor_stays_pending_and_recovers_when_authored(self):
        from preparation_workspace import Workspace
        path,plan=self.scoped_fixture(scope_ids=['P001','P003'],neighbor_ids=['P003'])
        published=[]
        first=derivation.derive(path,self.root/'neighbor-pending',panel_ids=['P001','P003'],workers=2,sink=published.append)
        self.assertEqual(first['pending_panel_ids'],['P003'])
        self.assertIn('NEEDS_AUTHORING_NEIGHBOR:P002',first['errors']['P003'])
        self.assertEqual({row['panel_id'] for row in published if not row.get('pending')},{'P001'})
        workspace=Workspace(self.root);current=workspace.read();scope=json.loads(path.read_text())
        ratio=json.loads(plan.read_text())['panels'][1]
        shot={'panel_id':'P002','locked_script':'Synthetic original P002','visual_focus':'newly authored',**ratio}
        execution={'prompt':'actually authored neighbor'}
        row={'panel_id':'P002','shot':shot,'execution':execution,'packet_header':{'book_id':'BOOK','episode_id':'E001'},
            'render_mode':'preserved_import','import_panel_key':fingerprint({**shot,**execution})}
        workspace.submit({'operation_id':'complete-neighbor','base_revision':current['revision'],'shared_version':current['shared_version'],
            'row_versions':{'P002':0},'panels':[row]})
        path.write_text(json.dumps(workspace.scope(['P001','P002','P003'])))
        second=derivation.derive(path,self.root/'neighbor-recovered',previous=self.root/'neighbor-pending'/'派生记录.json',panel_ids=['P003'],workers=2)
        self.assertEqual(second['metrics']['compiled_panels'],1)
        self.assertEqual(second['pending_panel_ids'],[])
        self.assertEqual(second['panels'][0]['depends_on'],['P002'])

    def test_internal_scope_ratio_plan_readset_is_rechecked(self):
        path,plan=self.scoped_fixture();real_render=derivation.render
        def render(*args):
            panel=real_render(*args);plan.write_text(plan.read_text()+'\n');return panel
        with patch.object(derivation,'render',render):
            with self.assertRaisesRegex(ValueError,'DRAFT_DEPENDENCY_CHANGED'):
                derivation.derive(path,self.root/'stale-ratio',panel_ids=['P002'],workers=2)

    def test_unchanged_35_and_165_compile_zero_and_previous_artifacts_are_hashed_once(self):
        for count in (35,165):
            with self.subTest(count=count),concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                pool.resource_admission='host_managed'
                path,source=self.fixture(count)
                first=derivation.derive(path,self.root/f'cold-{count}',executor=pool)
                counts={}
                def tracked_hash(path):
                    key=str(path);counts[key]=counts.get(key,0)+1;return file_hash(path)
                with patch.object(derivation,'file_hash',tracked_hash):
                    second=derivation.derive(path,self.root/f'warm-{count}',executor=pool)
                self.assertEqual(first['metrics']['compiled_panels'],count)
                self.assertEqual(second['metrics']['compiled_panels'],0)
                self.assertEqual(second['metrics']['reused_panels'],count)
                self.assertTrue(all(counts[ref['path']]==1 for row in first['panels'] for ref in row['artifacts']))

    def test_single_edit_compiles_exact_dependency_closure_and_shared_change_is_conservative(self):
        path,source=self.fixture(4);source['panels'][2]['dependencies']=['P002']
        source['shared']['focus']='original'
        source['panels'][1]['shot']['visual_focus']={'$shared':'focus'}
        path.write_text(json.dumps(source))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pool.resource_admission='host_managed'
            derivation.derive(path,self.root/'cold',executor=pool)
            source['shared']['focus']='changed'
            row=source['panels'][1]
            row['import_panel_key']=fingerprint({**row['shot'],'visual_focus':'changed',**row['execution']})
            path.write_text(json.dumps(source))
            changed=derivation.derive(path,self.root/'changed',executor=pool)
            self.assertEqual(changed['impact']['affected_panel_ids'],['P002','P003'])
            self.assertEqual(changed['metrics']['compiled_panels'],2)
            source['shot_header']['shared_instruction']='changed common header'
            path.write_text(json.dumps(source))
            shared=derivation.derive(path,self.root/'shared',executor=pool)
        self.assertEqual(shared['metrics']['compiled_panels'],4)

    def test_subset_previous_full_receipt_does_not_treat_unselected_dependencies_as_removed(self):
        path,source=self.fixture();source['panels'][1]['dependencies']=['P001']
        path.write_text(json.dumps(source))
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            pool.resource_admission='host_managed'
            derivation.derive(path,self.root/'all',executor=pool)
            selected=derivation.derive(path,self.root/'only-two',panel_ids=['P002'],executor=pool)
        self.assertEqual(selected['metrics']['compiled_panels'],0)
        self.assertEqual(selected['impact']['removed_panel_ids'],[])

    def test_readset_mutation_is_rejected_even_when_source_bytes_are_unchanged(self):
        path,source=self.fixture();dependency=self.root/'dependency.txt';dependency.write_text('old')
        source['panels'][0]['dependency_queries']=[{'path':str(dependency)}]
        path.write_text(json.dumps(source));real_render=derivation.render
        def render(*args):
            panel=real_render(*args)
            if args[1]['panel_id']=='P001':dependency.write_text('new')
            return panel
        with patch.object(derivation,'render',render):
            with self.assertRaisesRegex(ValueError,'DRAFT_DEPENDENCY_CHANGED'):
                derivation.derive(path,self.root/'changed-readset',workers=2)
        self.assertFalse((self.root/'changed-readset'/'派生记录.json').exists())

    def test_owned_executor_keeps_pending_futures_within_admitted_capacity(self):
        path,source=self.fixture(12)
        result=derivation.derive(path,self.root/'bounded',workers=8)
        self.assertLessEqual(result['metrics']['peak_pending_compiles'],2)
        self.assertEqual(result['metrics']['compiled_panels'],12)

    def test_resource_wait_stops_at_shared_active_deadline_without_starting_work(self):
        import runtime_clock as clock
        from machine_resources import Coordinator
        path,source=self.fixture(1)
        stamp=lambda n:{'wall':1000+n,'mono':n,'host':'test','boot':'boot'}
        clock.initialize(self.root/'00_任务协调','preparation',1,hard_deadline=True,at=stamp(0))
        clock.event(self.root/'00_任务协调','start','start',at=stamp(0))
        coordinator=Coordinator();occupied=coordinator.acquire('host','occupied',disk=self.root)
        current=[0];real_acquire=coordinator.acquire;rendered=threading.Event();real_render=derivation.render
        def acquire(*args,**kwargs):
            result=real_acquire(*args,**kwargs)
            if result['status']=='RESOURCE_WAIT':current[0]=1
            return result
        def render(*args):rendered.set();return real_render(*args)
        with patch.object(clock,'instant',side_effect=lambda:stamp(current[0])),patch.object(coordinator,'acquire',acquire),patch.object(derivation,'render',render):
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as driver:
                pool=derivation.DerivationExecutor(2,coordinator=coordinator,disk=self.root)
                future=driver.submit(derivation.derive,path,self.root/'deadline-wait',executor=pool)
                # Release even on a broken implementation so the test cannot hang.
                time.sleep(.7);coordinator.release(occupied['token'])
                try:
                    with self.assertRaisesRegex(ValueError,'LIMIT_REACHED'):future.result(timeout=4)
                finally:pool.shutdown()
        self.assertFalse(rendered.is_set())

    def test_released_compile_slot_wakes_local_waiter_without_fixed_poll_gap(self):
        from machine_resources import Coordinator
        coordinator=Coordinator();telemetry=coordinator.probe
        coordinator.probe=lambda disk:{**telemetry(disk),'cpus':1}
        waiting=threading.Event();holding=threading.Event();real_acquire=coordinator.acquire;times={}
        def acquire(*args,**kwargs):
            result=real_acquire(*args,**kwargs)
            if args[0]=='compile' and result['status']=='RESOURCE_WAIT':waiting.set()
            return result
        def work(source,pid):
            if pid=='P001':
                holding.set()
                self.assertTrue(waiting.wait(5));times['released']=time.monotonic()
            else:times['next_started']=time.monotonic()
            return {'panel_id':pid}
        with patch.object(coordinator,'acquire',acquire):
            with derivation.DerivationExecutor(2,coordinator=coordinator,disk=self.root) as pool:
                first=pool.submit(work,{'run_root':str(self.root)},'P001')
                self.assertTrue(holding.wait(5),'first task must own the slot before testing waiter wakeup')
                second=pool.submit(work,{'run_root':str(self.root)},'P002')
                first.result(timeout=6);second.result(timeout=6)
        self.assertLess(times['next_started']-times['released'],.3)

    def test_coordinator_contention_waits_without_bypassing_host_lease(self):
        from machine_resources import Coordinator
        path,source=self.fixture();coordinator=Coordinator()
        occupied=coordinator.acquire('host','other-host',disk=self.root)
        self.assertEqual(occupied['status'],'RESOURCE_GRANTED')
        entered=threading.Event();real_render=derivation.render
        def render(*args):entered.set();return real_render(*args)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as driver:
            with patch.object(derivation,'render',render):
                future=driver.submit(derivation.derive,path,self.root/'contended',workers=2)
                self.assertFalse(entered.wait(.1))
                coordinator.release(occupied['token'])
                result=future.result(timeout=8)
        self.assertEqual(result['metrics']['compiled_panels'],3)
        self.assertEqual(coordinator.status()['active'],{'compile':0,'image':0,'host':0})

    def test_external_pool_requires_explicit_resource_admission(self):
        path,_=self.fixture()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            with self.assertRaisesRegex(ValueError,'ADMISSION'):
                derivation.derive(path,self.root/'unadmitted',executor=pool)

if __name__=='__main__':unittest.main()
