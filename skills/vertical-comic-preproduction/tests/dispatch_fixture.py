"""Isolated real-gate dispatch inputs; all approval/image evidence is synthetic."""
import copy

import test_direct_handoff as handoff
from codex_reference_contract import checked_file, digest, read_json
from platform_io import atomic_json
from slot_leases import allocate, POLICY


class DispatchFixture:
    def __init__(self, slots=2):
        self.source = handoff.DirectHandoffTests()
        try:
            self.source.setUp()
            self.root = self.source.template.resolve()
            self.state = self.source.state
            self.state_path = self.root / '00_输入审计/生产流程.json'
            self.control_path = self.source.base / 'control.json'
            self.state['runtime']['dispatch_policy'] = POLICY
            self.state['parallel_context'] = {
                'control_file': str(self.control_path), 'job_id': 'synthetic-job',
                'worker_id': 'synthetic-worker', 'epoch': 1}
            basis = read_json(checked_file(self.root, self.state['visual_basis']))
            shared = [{**self.ref(checked_file(self.root, self.state['visual_basis'])), 'role': 'style_basis'}]
            shared.extend(self.ref(checked_file(self.root, ref)) for ref in basis['reference_files'])
            registry = self.source.base / 'registry.json'
            atomic_json(registry, {'synthetic': True})
            shared.append({**self.ref(registry), 'role': 'state_registry'})
            self.control = {
                'policy': 'parallel_episodes_v1', 'version': 1, 'book_id': self.state['book_id'],
                'epoch': 1, 'cancelled': False, 'holds': [], 'max_workers': 1, 'max_inflight': slots,
                'shared_files': shared, 'permits': [],
                'jobs': [{'job_id': 'synthetic-job', 'worker_id': 'synthetic-worker',
                          'episode_id': self.state['episode_id'], 'root': str(self.root),
                          'status': 'RUNNING', 'max_inflight': slots, 'active_batch_id': 'EPISODE',
                          'frozen_inputs': {k: copy.deepcopy(self.state[k]) for k in
                                            ('source_script', 'source_snapshot', 'visual_basis', 'shot_manifest')}}]}
            self.flush()
            allocate(self.control_path, digest(self.control_path), {'synthetic-job': slots})
            self.control = read_json(self.control_path)
        except BaseException:
            self.close()
            raise

    def ref(self, path):
        return {'path': path.resolve().relative_to(self.source.base.resolve()).as_posix(), 'sha256': digest(path)}

    def flush(self):
        atomic_json(self.state_path, self.state)
        atomic_json(self.control_path, self.control)

    def authorize_synthetic_repair(self, pid):
        """Real receipt, PNG/QA evidence and repair gates, with no image service.

        Used only to test mixed first/second-round ordering. All observations
        and returned pixels are explicitly synthetic fixture data.
        """
        from contextlib import redirect_stdout
        import io
        from PIL import Image
        from codex_reference_contract import validate_panel
        from episode_dispatch_queue import reserve_ready
        from batch_round import snapshot, attempt_errors
        from make_generation_qa import _main as make_qa
        from production_runtime import authorize_episode_repair
        from slot_leases import release_unsubmitted
        def write(name, value):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(path, value)
            return {'path': name, 'sha256': digest(path)}
        count = [r['panel_id'] for r in self.state['panels']].index(pid) + 1
        claimed = reserve_ready(self.state_path, digest(self.state_path), digest(self.control_path), count)
        assert len(claimed['reserved']) == count, claimed
        self.state = read_json(self.state_path)
        row = next(r for r in self.state['panels'] if r['panel_id'] == pid)
        packet = read_json(checked_file(self.root, row['package_manifest']))
        panel = packet['panels'][0]
        errors, plan = validate_panel(panel, self.root)
        assert not errors, errors
        image = self.root / f'synthetic-return-{pid}' / (pid + '.png')
        image.parent.mkdir()
        Image.new('RGB', (90, 160), 'white').save(image)
        output = {'path': image.relative_to(self.root).as_posix(), 'sha256': digest(image)}
        request = {'attempt_id': row['attempt_id'], 'backend_id': 'codex_builtin_imagegen',
                   'panel_id': pid, **plan, 'source_kind': 'observed_tool_call',
                   'source_locator': 'synthetic://fixture-not-a-real-call'}
        response = {'attempt_id': row['attempt_id'], 'status': 'COMPLETED', 'outputs': [output],
                    'source_kind': 'observed_tool_result', 'source_locator': 'synthetic://fixture-not-a-real-return'}
        panel['generation_execution'] = {'status': 'COMPLETED', 'attempt_id': row['attempt_id'],
            'request_evidence': write(pid + '-request.json', request),
            'response_evidence': write(pid + '-response.json', response)}
        row.update(package_manifest=write(pid + '-returned.json', packet), output=output, status='VISUAL_FAIL')
        qa_dir = self.root / (pid + '-synthetic-qa')
        with redirect_stdout(io.StringIO()):
            code = make_qa(['--package', str(self.root), '--manifest', row['package_manifest']['path'],
                           '--images', str(image.parent), '--output', str(qa_dir), '--skip-contact-sheet'])
        assert code == 0, code
        qa = read_json(qa_dir / '生成图QA报告.json')
        item = qa['panels'][0]
        for review in [*item['dimension_review'].values(), item['style_review']]:
            if review['status'] == 'UNREVIEWED':
                review.update(status='PASS', reviewer='SYNTHETIC', evidence='Fixture only')
        for key in ('camera_match', 'shot_scale_match', 'background_view_match', 'body_crop_match',
                    'required_visible_information_preserved', 'no_extra_offscreen_characters'):
            item[key] = True
        item['dimension_review']['action_interaction'].update(status='FAIL', reviewer='SYNTHETIC', evidence='Fixture hand gesture failure')
        row['qa_report'] = write(pid + '-reviewed.json', qa)
        row['failure_diagnosis'] = {'reviewer': 'SYNTHETIC', 'evidence': 'Fixture hand gesture failure', 'layer': 'generation_execution'}
        for permit in self.state['dispatch_ledger']:
            if permit['panel_id'] == pid:
                permit.update(status='COMPLETED', output_sha256=output['sha256'])
        self.flush()
        assert not attempt_errors(self.state, self.root, row)
        repair = copy.deepcopy(packet)
        repair.pop('dispatch_receipt')
        repair.pop('dispatch_source_package')
        attempt = pid + '-r2'
        repair['round_context'] = {'batch_id': 'EPISODE', 'round_id': 2, 'attempt_id': attempt}
        panel = repair['panels'][0]
        constraint = 'SYNTHETIC restore the approved hand gesture.'
        panel.update(operation='repair', generation_execution={'status': 'NOT_RUN'},
                     prompt=panel['prompt'] + '\n' + constraint,
                     prompt_file=pid + '/synthetic-repair-prompt.txt', panel_json_file=pid + '/synthetic-repair-panel.json')
        (self.root / panel['prompt_file']).write_text(panel['prompt'], encoding='utf-8', newline='\n')
        write(panel['panel_json_file'], panel)
        auth = {'policy': 'episode_repair_v1', 'panel_id': pid, 'failed_attempt': snapshot(row),
                'route': 'targeted_image_repair', 'reviewer': 'SYNTHETIC', 'evidence': 'Fixture hand gesture failure',
                'repair_constraints': [constraint], 'new_attempt_id': attempt,
                'new_package_manifest': write(pid + '-synthetic-repair.json', repair), 'new_shot_subset': row['shot_subset']}
        ref = write(pid + '-synthetic-repair-auth.json', auth)
        result = authorize_episode_repair(self.state_path, digest(self.state_path), ref['path'])
        assert result['status'] == 'REPAIR_AUTHORIZED', result
        others = [r['panel_id'] for r in claimed['reserved'] if r['panel_id'] != pid]
        if others:
            release_unsubmitted(self.state_path, digest(self.state_path), others)
        self.state = read_json(self.state_path)

    def close(self):
        self.source.doCleanups()
