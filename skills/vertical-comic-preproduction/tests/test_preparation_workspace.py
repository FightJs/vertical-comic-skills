"""Workspace regressions: no invented rows, source/CAS/receipt boundaries."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from input_dependencies import file_hash
try:
    from preparation_workspace import Workspace
except ImportError:
    Workspace=None

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.ids=['P001','P002','P003'];self.source={'panel_ids':self.ids,'locked_scripts':{p:{'text':p} for p in self.ids}}
        self.ref=self.write('source.json',self.source)
        self.ratios=[{'panel_id':p,'frame_ratio':r,'frame_ratio_reason':'subject crop '+p} for p,r in zip(self.ids,['9:16','3:4','4:5'])]
        self.plan=self.write('ratios.json',{'policy':'content_balanced_ratios_v1','book_id':'B','episode_id':'E','source_snapshot':self.ref,'panel_ids':self.ids,'panels':self.ratios})
    def write(self,name,value):
        path=self.root/name;path.write_text(json.dumps(value),encoding='utf-8');return {'path':name,'sha256':file_hash(path)}
    def workspace(self):
        self.assertIsNotNone(Workspace,'workspace implementation missing')
        w=Workspace(self.root);w.initialize(self.ref,'B','E',{}, {'book_id':'B','episode_id':'E'},frame_ratio_plan=self.plan);return w
    def row(self,i):
        p=self.ids[i];return {'panel_id':p,'shot':{'panel_id':p,'locked_script':self.source['locked_scripts'][p],**self.ratios[i]},'execution':{},'packet_header':{'book_id':'B','episode_id':'E'},'render_mode':'structured_v2'}
    def fragment(self,op,i,**kw):
        return {'operation_id':op,'base_revision':0,'shared_version':0,'row_versions':{self.ids[i]:0},'consumed_rows':{},'panels':[self.row(i)],**kw}
    def test_pending_has_no_shot_and_scope_keeps_full_source(self):
        w=self.workspace();s=w.read();self.assertEqual(s['panels'],[]);self.assertEqual(s['pending_panel_ids'],self.ids)
        w.submit(self.fragment('one',0));scope=w.scope(['P001']);self.assertEqual(scope['panel_ids'],self.ids);self.assertEqual(scope['selected_panel_ids'],['P001']);self.assertEqual([r['panel_id'] for r in scope['panels']],['P001']);self.assertEqual(scope['source_snapshot'],self.ref)
        with self.assertRaises(ValueError):w.scope(['P002'])
        with self.assertRaises(ValueError):w.materialize(self.root/'full.json')
    def test_nonoverlap_stale_revision_merges_but_row_conflict_does_not(self):
        w=self.workspace();w.submit(self.fragment('a',0));w.submit(self.fragment('b',1))
        with self.assertRaises(ValueError):w.submit(self.fragment('c',0))
        with self.assertRaises(ValueError):w.submit(self.fragment('d',2,consumed_rows={'P001':0}))
        self.assertEqual(w.read()['revision'],2)
    def test_lost_response_receipt_survives_reopen_and_conflicting_duplicate_rejected(self):
        w=self.workspace();f=self.fragment('a',0);receipt=w.submit(f);self.assertEqual(Workspace(self.root).submit(f),receipt)
        self.assertEqual(Workspace(self.root).receipt('a'),receipt)
        changed=copy.deepcopy(f);changed['panels'][0]['execution']={'extra':'changed'}
        with self.assertRaises(ValueError):w.submit(changed)
        patch=Path(receipt['original_patch']['path']);self.assertEqual(json.loads(patch.read_text()),f)
    def test_complete_materialization_is_legacy_valid_and_canonical_order(self):
        from panel_source import validate
        w=self.workspace()
        for i in [2,0,1]:w.submit(self.fragment(str(i),i))
        path=self.root/'complete.json';value=w.materialize(path);validate(value)
        self.assertEqual([r['panel_id'] for r in value['panels']],self.ids);self.assertEqual(json.loads(path.read_text()),value)
        self.assertFalse(value['dispatch_authorized'])
    def test_bad_ratio_source_order_locked_text_shared_and_duplicate_rows_rejected(self):
        self.assertIsNotNone(Workspace,'workspace implementation missing')
        with self.assertRaises(ValueError):Workspace(self.root).initialize(self.ref,'B','E',{}, {'book_id':'B','episode_id':'E'})
        w=self.workspace();f=self.fragment('bad',0);f['panels'][0]['shot']['locked_script']={'text':'invented'}
        with self.assertRaises(ValueError):w.submit(f)
        f=self.fragment('bad-ratio',0);f['panels'][0]['shot']['frame_ratio']='1:1'
        with self.assertRaises(ValueError):w.submit(f)
        f=self.fragment('bad-shared',0,shared_version=99)
        with self.assertRaises(ValueError):w.submit(f)
        f=self.fragment('dupe',0);f['panels']*=2
        with self.assertRaises(ValueError):w.submit(f)
        self.assertEqual(w.read()['panels'],[])
    def test_shared_addition_is_versioned_and_stale_shared_is_rejected(self):
        w=self.workspace();w.submit(self.fragment('a',0,shared_updates={'new':{'tags':['a']}}))
        with self.assertRaises(ValueError):w.submit(self.fragment('b',1))
        w.submit(self.fragment('b2',1,shared_version=1));self.assertEqual(w.read()['shared_version'],1)
    def test_stale_shared_version_accepts_exact_unchanged_readset_only(self):
        w=self.workspace();w.submit(self.fragment('a',0,shared_updates={'unused':{'value':1}}))
        w.submit(self.fragment('b',1,consumed_shared={}))
        with self.assertRaises(ValueError):w.submit(self.fragment('c',2,consumed_shared={'unused':{'value':0}}))
        with self.assertRaises(ValueError):w.submit(self.fragment('d',2,consumed_shared={'missing':{}}))

    def test_imported_absolute_source_and_plan_references_preserve_their_identity(self):
        self.assertIsNotNone(Workspace,'workspace implementation missing')
        absolute={**self.ref,'path':str(self.root/self.ref['path'])}
        plan=json.loads((self.root/'ratios.json').read_text());plan['source_snapshot']=absolute
        plan_ref=self.write('absolute-plan.json',plan);plan_ref['path']=str(self.root/plan_ref['path'])
        w=Workspace(self.root);w.initialize(absolute,'B','E',{}, {'book_id':'B','episode_id':'E'},frame_ratio_plan=plan_ref)
        w.submit(self.fragment('a',0));self.assertEqual(w.scope(['P001'])['source_snapshot'],absolute)

    def test_source_race_at_short_writer_lock_is_rejected_without_commit(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        import preparation_workspace as module
        w=self.workspace();actual=module.file_lock
        @contextmanager
        def mutate_at_lock(path):
            (self.root/'source.json').write_text('{}')
            with actual(path):yield
        with patch.object(module,'file_lock',mutate_at_lock):
            with self.assertRaises(ValueError):w.submit(self.fragment('raced',0))
        self.assertEqual(w.read()['revision'],0)

    def test_source_and_ratio_plan_bytes_are_rechecked_before_submit(self):
        w=self.workspace();(self.root/'source.json').write_text('{}')
        with self.assertRaises(ValueError):w.submit(self.fragment('a',0))

if __name__=='__main__':unittest.main()
