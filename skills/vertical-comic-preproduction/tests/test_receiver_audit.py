"""Combined read-only receiver scopes retain independent gate decisions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
import test_direct_handoff as fixtures
import production_runtime as runtime
import production_evidence as batch_workflow
from codex_reference_contract import file_session

METRICS = {'file_reuse_statistics', 'audit_reuse_statistics', 'preflight_elapsed_seconds',
           'elapsed_seconds', 'cpu_seconds'}


def decisions(value):
    if isinstance(value, dict):return {k:decisions(v) for k,v in value.items() if k not in METRICS}
    if isinstance(value, list):return [decisions(v) for v in value]
    return value


class ReceiverAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.DirectHandoffTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.state, self.root = self.fixture.state, self.fixture.template
        self.ids = ['P001', 'P002', 'P003', 'P004']

    def combined(self):return runtime.receiver_audit(self.state,self.root,self.ids[:2],self.ids)

    def test_three_scopes_equal_separate_runs_and_reuse_exact_inputs(self):
        first = runtime.compile_jobs(self.state,self.root,self.ids[:2],input_audit=True)
        with file_session():prepared = runtime.preparation_report(self.state,self.root)
        full = runtime.compile_jobs(self.state,self.root,self.ids,input_audit=True)
        with patch.object(batch_workflow,'input_errors',wraps=batch_workflow.input_errors) as checks:
            combined = self.combined()
        self.assertEqual(checks.call_count,4)
        for name, expected in [('h001',first),('preparation',prepared),('all_inputs',full)]:
            self.assertEqual(decisions(combined[name]),decisions(expected),name)
        stats=combined['audit_reuse_statistics']
        self.assertEqual(stats['receiver_panel_inputs'],{'runs':4,'hits':2})
        self.assertGreater(stats['preparation_report']['hits'],0)

    def test_input_audit_cannot_grant_capacity_or_change_normal_compile(self):
        self.state['runtime']['dispatch_policy']='episode_slot_lease_v1'
        before=copy.deepcopy(self.state)
        normal=runtime.compile_jobs(self.state,self.root,self.ids[:2])
        self.assertEqual(normal['jobs'],[])
        self.assertIn('WAIT_CAPACITY_ASSIGNMENT',json.dumps(normal))
        result=self.combined()
        self.assertEqual(result['image_calls'],0)
        self.assertIs(result['dispatch_authorized'],False)
        for scope in ('h001','all_inputs'):
            self.assertIs(result[scope]['dispatch_authorized'],False)
            self.assertIs(result[scope]['preflight']['dispatch_authorized'],False)
            self.assertEqual(len(result[scope]['jobs']),2 if scope=='h001' else 4)
            for job in result[scope]['jobs']:
                self.assertIs(job['dispatch_authorized'],False)
                self.assertEqual(job['status'],'INPUT_AUDITED_NOT_DISPATCHABLE')
        self.assertEqual(self.state,before)
        self.assertEqual(decisions(runtime.compile_jobs(self.state,self.root,self.ids[:2])),decisions(normal))

    def test_invalid_scope_candidate_and_live_context_rejected(self):
        for first,full in [([],self.ids),(self.ids[1:2],self.ids),(self.ids[:2],list(reversed(self.ids)))]:
            with self.assertRaises(ValueError):runtime.receiver_audit(self.state,self.root,first,full)
        with self.assertRaises(ValueError):runtime.compile_jobs(self.state,self.root,self.ids,input_audit=True,candidate=True)
        self.state['parallel_context']={'job_id':'LIVE'}
        with self.assertRaises(ValueError):self.combined()
        with self.assertRaises(ValueError):runtime.compile_jobs(self.state,self.root,self.ids,input_audit=True)

    def test_later_input_failure_is_not_hidden_by_h001(self):
        self.state['production_authorization']['panel_ids'].remove('P004')
        result=self.combined()
        self.assertEqual([j['panel_id'] for j in result['h001']['jobs']],self.ids[:2])
        self.assertNotIn('P004',[j['panel_id'] for j in result['all_inputs']['jobs']])
        self.assertIn('当前格不在已授权生产范围',json.dumps(result['all_inputs'],ensure_ascii=False))

    def test_inline_revocation_between_phases_cannot_reuse_pass(self):
        original=runtime.preparation_report
        def revoke(state,root):
            result=original(state,root)
            state['production_authorization']['panel_ids'].remove('P001')
            return result
        with patch.object(runtime,'preparation_report',side_effect=revoke):result=self.combined()
        self.assertIn('P001',[j['panel_id'] for j in result['h001']['jobs']])
        self.assertNotIn('P001',[j['panel_id'] for j in result['all_inputs']['jobs']])

    def set_capability(self,value):
        # Only the synthetic fixture snapshot is modified, then freshly manifested.
        h=fixtures.h
        snapshot=self.fixture.package/'runtime'
        cap=snapshot/'skills/vertical-comic-preproduction/scripts/runtime_capabilities.json'
        if value is None:cap.unlink()
        else:cap.write_text(json.dumps(value),encoding='utf-8')
        manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
        manifest['files']=[{'path':p.relative_to(snapshot).as_posix(),'sha256':h.sha(p)}
                           for p in sorted(snapshot.rglob('*')) if p.is_file() and p!=snapshot/'manifest.json']
        (snapshot/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        # Capability bytes are now part of the executing toolchain. Rebuild
        # this synthetic template binding as well; production bind stays strict.
        from execution_contract import toolchain
        self.fixture.state['toolchain']['files']=toolchain(cap.parent)['files']
        self.fixture.refresh_template()
        self.fixture.index['episodes'][0]['runtime_manifest']=self.fixture.ref('runtime/manifest.json')
        self.fixture.save()

    def test_absent_capability_requires_import_without_fallback(self):
        self.set_capability(None)
        _,_,_,report=self.fixture.pipeline()
        self.assertEqual(report['status'],'HOLD',report)
        self.assertIn('IMPORT_REQUIRED',str(report))
        self.assertTrue(all(r.get('argv') is None for r in report['results']))

    def test_unknown_capability_holds_without_fallback(self):
        self.set_capability({'policy':'unsupported'})
        _,_,_,report=self.fixture.pipeline()
        self.assertEqual(report['status'],'HOLD',report)
        self.assertIn('未知冻结接包审计能力',str(report))

    def test_malformed_capability_produces_hold_report(self):
        self.set_capability([])
        _,_,_,report=self.fixture.pipeline()
        self.assertEqual(report['status'],'HOLD',report)
        self.assertIn('未知冻结接包审计能力',str(report))

    def test_rehearsal_timeout_retains_evidence_and_holds(self):
        h,d=fixtures.h,fixtures.d
        z=self.fixture.base/'candidate.zip';h.pack(self.fixture.package,z)
        received=Path(h.extract(z,self.fixture.base/'extracted',reserve_bytes=0)['root'])
        bound=d.bind(received,self.fixture.base/'local-run')
        dest=self.fixture.base/'rehearsal'
        report=h.rehearse(z,received,bound['run_root'],bound['run_index'],dest,timeout=.001)
        self.assertEqual(report['status'],'HOLD',report)
        timeout=json.loads((dest/'E000_receiver_audit_timeout.json').read_text(encoding='utf-8'))
        self.assertEqual(timeout['status'],'HOLD')
        self.assertTrue((dest/timeout['stdout']).is_file())
        self.assertTrue((dest/timeout['stderr']).is_file())

    def test_changed_file_between_phases_rejects_warm_snapshot(self):
        original=runtime.preparation_report
        def change(state,root):
            result=original(state,root)
            path=root/state['shot_manifest']['path']
            path.write_text(path.read_text(encoding='utf-8')+' ',encoding='utf-8')
            return result
        with patch.object(runtime,'preparation_report',side_effect=change):
            with self.assertRaisesRegex(ValueError,'CHECK_SNAPSHOT_CHANGED'):self.combined()

    def test_cli_keeps_stdout_json_and_stderr_stage_progress(self):
        command=[sys.executable,'-B',str(Path(runtime.__file__)),
                 '--state',str(self.root/'00_输入审计/生产流程.json'),
                 '--action','receiver-audit','--progress','--h001-panels',*self.ids[:2],
                 '--panels',*self.ids]
        proc=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['policy'],'receiver_audit_bundle_v1')
        events=[json.loads(line) for line in proc.stderr.splitlines()]
        self.assertTrue({'H001','preparation','all_inputs','snapshot_verification'} <= {e['stage'] for e in events})
        self.assertTrue(all(e['not_approval_evidence'] for e in events))
        self.assertEqual(events[-1]['status'],'FINISHED_NOT_AUTHORIZATION')


if __name__=='__main__':unittest.main()
