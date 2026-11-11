"""Automatic closure assembly with real frozen receive; synthetic evidence only."""
import copy,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
try:
    from preparation_handoff import build_package
except ImportError:
    build_package=None
import handoff_zip as h
import handoff_delivery as d

class PreparationHandoffTests(unittest.TestCase):
    def setUp(self):
        from test_direct_handoff import DirectHandoffTests
        self.f=DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.scope_task();self.state_path=self.f.template/self.f.state_ref['path']
        self.config={'package_id':'SYNTHETIC_AUTOMATIC','assembly_destination':str(self.f.base/'automatic-package'),
            'runtime_manifest':{'path':str(self.f.package/'runtime/manifest.json'),'sha256':h.sha(self.f.package/'runtime/manifest.json')}}
    def build(self,config=None):
        self.assertIsNotNone(build_package,'automatic handoff implementation missing')
        return build_package(self.f.base,[str(self.state_path)],self.config if config is None else config)
    def test_automatic_transitive_closure_preserves_original_bytes_excludes_scheduler_and_receives(self):
        for relative in ['.preparation-scheduler/owner.json','.preparation-workspace/patches/obsolete.json','unrelated/history/unused.json']:
            p=self.f.template/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{"not_consumed":true}')
        from runtime_clock import initialize_context
        self.f.state['runtime_execution_context']=initialize_context(self.f.base,'preparation',None)
        self.state_path.write_text(json.dumps(self.f.state))
        original=self.state_path.read_bytes();result=self.build();self.assertEqual(result['status'],'ASSEMBLED_CANDIDATE_NOT_APPROVED',result)
        replay=self.build();self.assertEqual(replay['package_root'],result['package_root']);self.assertTrue(replay['assembly_reused'])
        package=Path(result['package_root']);index=h.audit_index(package);self.assertEqual(index['policy'],'rehearsed_zip_handoff_v2');self.assertEqual(index['production_window_policy'],'full_episode_v1')
        episode=index['episodes'][0];self.assertNotIn('halves',episode);self.assertEqual([r['classification'] for r in episode['panels']],['READY']*4)
        template=h.read(h.reference(package,episode['run_template']));base=h.inside(package,template['root']);self.assertEqual(h.inside(base,template['state_file']).read_bytes(),original)
        self.assertEqual(self.state_path.read_bytes(),original);self.assertFalse(any('/owner.json' in r['path'] or 'obsolete.json' in r['path'] or 'unused.json' in r['path'] for r in h.files(package)))
        self.assertEqual(h.reference(package,episode['approval_evidence']).read_bytes(),(self.f.template/self.f.state['approval_index']['path']).read_bytes())
        self.assertFalse(result['approval_created']);self.assertIn('export_authorization',result['authorization_requirements'])
        candidate=self.f.base/'auto-candidate.zip';h.pack(package,candidate)
        bound=d.bind(package,self.f.base/'auto-bound');report=h.rehearse(candidate,package,bound['run_root'],bound['run_index'],self.f.base/'auto-rehearsal',timeout=25)
        self.assertEqual(report['status'],'RELEASE_CANDIDATE',report)
        # Only this fixture creates synthetic user evidence; assembly never does.
        approval=self.f.base/'synthetic-export.json';approval.write_text(json.dumps({'status':'APPROVED','source_kind':'user_message','source_locator':'SYNTHETIC_NOT_REAL','quote':'Synthetic conditional export fixture','authorization_mode':'approved_inputs_auto_export_v1','package_id':index['package_id'],'approved_input_digest':d.input_review(package,index)['approved_input_digest'],'after_successful_rehearsal':True}))
        formal=self.f.base/'auto-formal.zip';h.release(candidate,self.f.base/'auto-rehearsal/演练报告.json',approval,formal)
        # Receive must work after all original source/runtime/template roots vanish.
        self.f.package.rename(self.f.base/'original-source-unavailable')
        (self.f.base/'00_任务协调').rename(self.f.base/'original-clock-unavailable')
        recovered=self.build();self.assertEqual(recovered['package_root'],str(package));self.assertTrue(recovered['assembly_reused'])
        import comic_start
        with patch.object(h.shutil,'disk_usage',return_value=SimpleNamespace(free=10*1024**3)):
            received=comic_start.receive(formal,runtime_limit_seconds=None,output=self.f.base/'auto-received')
        self.assertEqual(received['status'],'READY_FOR_PRODUCTION_ROUTING',received);self.assertEqual(received['image_calls'],0)
        self.assertTrue(all(r['history']['remaining_auto_corrections']==1 for r in episode['panels']))
    def test_scope_history_and_specialized_source_evidence_close_without_copying_unrelated_history(self):
        import shutil
        state=copy.deepcopy(self.f.state);root=self.f.template
        history=root/'.preparation-pipeline/scopes/retained-scope.json';history.parent.mkdir(parents=True,exist_ok=True)
        original_audit=root/state['semantic_audit']['path']
        nested=root/'.preparation-pipeline/scopes/original-capability-proof.json';nested.write_text(json.dumps({'capability':{'path':str(original_audit.resolve()),'sha256':h.sha(original_audit)}}))
        history.write_text(json.dumps({'policy':'preparation_scope_history_v1','original_audit_ref':state['semantic_audit'],
            'scopes':{'P001':{'inputs':{'input_semantics_policy':'final_input_semantics_v2','book_id':state['book_id'],'episode_id':'E000','panel_id':'P001','shot_signature':'a'*64,'visual_basis_sha256':state['visual_basis']['sha256'],'prompt':'synthetic retained actual input','references':[],'tool_files':state['toolchain']['files'],'skill_entries':[r['sha256'] for r in state['toolchain']['skill_entries']], '_preparation_scope':{'files':[{'path':str(original_audit.resolve()),'sha256':h.sha(original_audit)},{'path':str(nested.resolve()),'sha256':h.sha(nested)}], 'consumed_facts':{'panel':{'panel_id':'PENDING_OLD_SCOPE','prompt':'historical input facts only','reference_images':[]}}}},'review':{'review_performed':False}}}}))
        state['preparation_scope_history']={'path':str(history.relative_to(root)),'sha256':h.sha(history)}
        extra=root/'only-transitive/source.png';extra.parent.mkdir();image=next(root.rglob('scene.png'));shutil.copyfile(image,extra)
        evidence=root/'special-evidence.json';evidence.write_text(json.dumps({'source_file':'only-transitive/source.png','source_sha256':h.sha(extra)}))
        state['original_evidence']={'path':evidence.name,'sha256':h.sha(evidence)}
        self.state_path.write_text(json.dumps(state));result=self.build();self.assertEqual(result['status'],'ASSEMBLED_CANDIDATE_NOT_APPROVED',result)
        package=Path(result['package_root']);episode=h.audit_index(package)['episodes'][0];plan=h.read(h.reference(package,episode['run_template']));base=h.inside(package,plan['root'])
        self.assertEqual((base/state['preparation_scope_history']['path']).read_bytes(),history.read_bytes());self.assertEqual((base/'only-transitive/source.png').read_bytes(),extra.read_bytes())
        state['live_dependency']={'path':str(nested.relative_to(root)),'sha256':h.sha(nested)};self.state_path.write_text(json.dumps(state))
        live=self.build({**self.config,'assembly_destination':str(self.f.base/'live-dependency')});self.assertEqual(live['status'],'MISSING_INPUTS');self.assertIn('portable binding',live['missing'][0]['reason'])
        state.pop('live_dependency')
        retained=json.loads(history.read_text());inputs=retained['scopes']['P001']['inputs']
        inputs['tool_files'][0]['sha256']='0'*64;history.write_text(json.dumps(retained));state['preparation_scope_history']['sha256']=h.sha(history);self.state_path.write_text(json.dumps(state))
        bad=self.build({**self.config,'assembly_destination':str(self.f.base/'bad-tools')});self.assertEqual(bad['status'],'MISSING_INPUTS');self.assertIn('tool_files',bad['missing'][0]['reason'])
        inputs['tool_files']=copy.deepcopy(state['toolchain']['files']);inputs.pop('input_semantics_policy');history.write_text(json.dumps(retained));state['preparation_scope_history']['sha256']=h.sha(history);self.state_path.write_text(json.dumps(state))
        unknown=self.build({**self.config,'assembly_destination':str(self.f.base/'unknown-tools')});self.assertEqual(unknown['status'],'MISSING_INPUTS');self.assertIn('agent_capacity.py',unknown['missing'][0]['reason'])

    def test_single_episode_run_root_uses_canonical_template_root(self):
        self.assertIsNotNone(build_package,'automatic handoff implementation missing')
        result=build_package(self.f.template,[str(self.state_path)],self.config)
        self.assertEqual(result['status'],'ASSEMBLED_CANDIDATE_NOT_APPROVED',result)
        package=Path(result['package_root']);episode=h.audit_index(package)['episodes'][0]
        self.assertEqual(h.read(h.reference(package,episode['run_template']))['root'],'template')

    def test_missing_adoption_or_task_origin_returns_exact_hold_without_fake_approval(self):
        value=copy.deepcopy(self.f.state);value.pop('approval_index');self.state_path.write_text(json.dumps(value))
        result=self.build();self.assertEqual(result['status'],'MISSING_INPUTS');self.assertIn('E000.approval_index',result['missing_keys']);self.assertFalse(Path(self.config['assembly_destination']).exists())
        self.state_path.write_text(json.dumps(self.f.state));(self.f.template/'00_输入审计/任务来源.json').unlink()
        result=self.build();self.assertIn('E000.task_origin',result['missing_keys']);self.assertFalse(result['approval_created'])
    def test_unknown_call_and_changed_reference_cannot_be_packaged_as_ready(self):
        value=copy.deepcopy(self.f.state);value['panels'][0]['status']='RESULT_UNKNOWN';self.state_path.write_text(json.dumps(value))
        result=self.build();self.assertEqual(result['status'],'MISSING_INPUTS');self.assertIn('E000.P001.history',result['missing_keys'])
        self.state_path.write_text(json.dumps(self.f.state));source=self.f.template/self.f.state['source_snapshot']['path'];source.write_text('{}')
        result=self.build();self.assertEqual(result['status'],'MISSING_INPUTS');self.assertTrue(result['missing'])

if __name__=='__main__':unittest.main()
