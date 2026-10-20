"""Already extracted formal handoffs; synthetic evidence, real frozen gates."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
import comic_start as start
import handoff_zip as h
import test_direct_handoff as fixture


class ExtractedHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        case=fixture.DirectHandoffTests('test_direct_bound_run_real_full_episode_gates_and_conditional_release')
        cls.addClassCleanup(case.doCleanups)
        case.setUp();case.scope_task()
        case.test_direct_bound_run_real_full_episode_gates_and_conditional_release()
        cls.original=Path(h.extract(case.base/'正式交接包.zip',case.base/'directory-only',reserve_bytes=0)['root'])
        # No source ZIP is left to consult or recompress during reception.
        for p in case.base.glob('*.zip'):p.unlink()
        cls.task=case.index['task_context']

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='dir-接包-');self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/'提前解压 改名后的包'
        shutil.copytree(self.original,self.root)
        self.output=self.base/'out'

    def rewrite_manifest(self):
        """Only synthetic negative fixtures: make payload hashes self-consistent."""
        data=h.read(self.root/h.INVENTORY);data['files']=h.files(self.root)
        (self.root/h.INVENTORY).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def rejected_before_run(self,pattern):
        with self.assertRaisesRegex(ValueError,pattern):start.receive(package_root=self.root,output=self.output)
        self.assertFalse(self.output.exists())

    def test_directory_without_zip_real_frozen_rehearsal_preserves_originals_and_scope(self):
        before={p.relative_to(self.root).as_posix():h.sha(p) for p in self.root.rglob('*') if p.is_file()}
        with patch.object(h.zipfile,'ZipFile',side_effect=AssertionError('must not access or rebuild ZIP')):
            result=start.receive(package_root=self.root,output=self.output)
        self.assertEqual(result['status'],'READY_FOR_PRODUCTION_ROUTING',result)
        self.assertEqual(result['image_calls'],0)
        self.assertEqual(result['reception']['archive_crc'],'NOT_AVAILABLE_EXTRACTED_DIRECTORY')
        run=Path(result['run_root']);report=h.read(run/'接包预检/演练报告.json')
        self.assertIsNone(report['candidate_zip_sha256'])
        self.assertTrue(report['originals_unchanged'])
        state=h.read(run/'本地运行/E000/00_输入审计/生产流程.json')
        self.assertEqual(state['task_context'],self.task)
        self.assertEqual(before,{p.relative_to(self.root).as_posix():h.sha(p) for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse(list(self.base.rglob('*.zip')))

    def test_cli_accepts_extracted_path_with_spaces_and_unicode(self):
        proc=subprocess.run([sys.executable,'-X','utf8','-B',str(Path(start.__file__)),
                             'receive','--package-root',str(self.root),'--output',str(self.output)],
                            capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['reception']['source_type'],'extracted_directory')

    def test_missing_changed_and_unlisted_files_fail_before_run(self):
        path=self.root/'交接说明.md';body=path.read_bytes()
        path.unlink();self.rejected_before_run('missing')
        path.write_bytes(body+b'changed');self.rejected_before_run('changed')
        path.write_bytes(body)
        (self.root/'unexpected.txt').write_text('unlisted',encoding='utf-8');self.rejected_before_run('unlisted')

    def test_missing_release_evidence_not_replaced_by_self_consistent_hashes(self):
        (self.root/'演练与导出确认/用户导出确认.json').unlink();self.rewrite_manifest()
        self.rejected_before_run('正式发布证据')

    def test_candidate_directory_is_not_a_formal_package(self):
        data=h.read(self.root/h.INVENTORY);data.pop('container_policy')
        (self.root/h.INVENTORY).write_text(json.dumps(data),encoding='utf-8')
        self.rejected_before_run('正式发布证据')

    def test_modified_conditional_approval_digest_is_rejected(self):
        p=self.root/'演练与导出确认/用户导出确认.json';data=h.read(p);data['approved_input_digest']='0'*64
        p.write_text(json.dumps(data),encoding='utf-8');self.rewrite_manifest()
        self.rejected_before_run('最终输入摘要失配')

    def test_exact_export_approval_can_be_checked_without_original_archive(self):
        p=self.root/'演练与导出确认/用户导出确认.json';data=h.read(p)
        data.pop('authorization_mode');data.pop('approved_input_digest')
        report=self.root/'演练与导出确认/演练报告.json'
        data.update(candidate_zip_sha256=h.read(report)['candidate_zip_sha256'],rehearsal_report_sha256=h.sha(report))
        p.write_text(json.dumps(data),encoding='utf-8');self.rewrite_manifest()
        self.assertEqual(h.check_delivery_directory(self.root)['payload_integrity'],'PASS')
        data['rehearsal_report_sha256']='0'*64;p.write_text(json.dumps(data),encoding='utf-8');self.rewrite_manifest()
        self.rejected_before_run('导出授权')

    def test_case_conflicting_or_escaping_manifest_rejected(self):
        p=self.root/h.INVENTORY;data=h.read(p)
        data['files'].append({**data['files'][0],'path':data['files'][0]['path'].upper()})
        p.write_text(json.dumps(data),encoding='utf-8');self.rejected_before_run('重复/大小写冲突')
        data['files'][-1]['path']='../outside';p.write_text(json.dumps(data),encoding='utf-8')
        self.rejected_before_run('path|路径|relative')

    def test_link_rejected_on_platforms_without_symlink_privileges(self):
        original=Path.is_symlink
        with patch.object(Path,'is_symlink',lambda p:p.name=='交接说明.md' or original(p)):
            self.rejected_before_run('符号链接')

    def test_output_inside_originals_rejected_without_mutation(self):
        with self.assertRaisesRegex(ValueError,'原件目录之外'):
            start.receive(package_root=self.root,output=self.root/'out')
        self.assertFalse((self.root/'out').exists())

    def test_os_metadata_is_not_treated_as_a_missing_production_file(self):
        (self.root/'.DS_Store').write_bytes(b'SYNTHETIC OS metadata')
        extra=self.root/'__MACOSX';extra.mkdir();(extra/'._data').write_bytes(b'SYNTHETIC resource fork')
        self.assertEqual(h.check_delivery_directory(self.root)['payload_integrity'],'PASS')

    def test_modern_frozen_template_still_requires_origin_evidence(self):
        index=h.read(self.root/h.INDEX);episode=index['episodes'][0]
        plan=h.read(self.root/episode['run_template']['path']);template=self.root/plan['root']
        (template/'00_输入审计/任务来源.json').unlink();self.rewrite_manifest()
        self.rejected_before_run('TASK_SCOPE_HOLD')

    def test_verified_pre_contract_snapshot_does_not_require_new_origin_marker(self):
        index=h.read(self.root/h.INDEX);episode=index['episodes'][0]
        manifest=self.root/episode['runtime_manifest']['path'];data=h.read(manifest)
        name='skills/vertical-comic-preproduction/scripts/task_context.py'
        # Synthetic pre-contract shape. No runtime source or real approval is changed.
        (manifest.parent/name).unlink();data['files']=[r for r in data['files'] if r['path']!=name]
        manifest.write_text(json.dumps(data),encoding='utf-8');episode['runtime_manifest']['sha256']=h.sha(manifest)
        plan=h.read(self.root/episode['run_template']['path']);template=self.root/plan['root']
        state=h.read(template/plan['state_file']);(template/'00_输入审计/任务来源.json').unlink()
        self.assertFalse(h.frozen_task_contract(self.root,episode))
        self.assertEqual(h.handoff_history_errors(self.root,episode,index['task_context'],state,template),[])
        state['panels'][0]['status']='RESULT_UNKNOWN'
        self.assertIn('真实调用',';'.join(h.handoff_history_errors(self.root,episode,index['task_context'],state,template)))
        # A changed frozen manifest cannot silently select the legacy path.
        manifest.write_text('{}',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'哈希失配'):h.frozen_task_contract(self.root,episode)


if __name__=='__main__':unittest.main()
