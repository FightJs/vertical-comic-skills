"""Real-gate approval revocation; shared/state lock ordering without image calls."""
from contextlib import contextmanager
import copy
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
import authority_updates as authority
from codex_reference_contract import checked_file, digest, file_session, read_json
from episode_dispatch_queue import reserve_ready
from platform_io import atomic_json
from staged_workflow import approval_errors
from _historical_fixture import evaluate


def writer_process(kind, state_path, token, changes, entered, proceed, attempted, results):
    """Real writer, events around lock acquisition only; do not replace gates."""
    import production_runtime
    actual_locks = authority.state_write_lock
    actual_file_lock = authority.file_lock
    @contextmanager
    def observed_file_lock(path, **kwargs):
        if path.name.endswith('.dispatch.lock'): attempted.set()
        with actual_file_lock(path, **kwargs) as stream: yield stream
    @contextmanager
    def held(*args, **kwargs):
        with actual_locks(*args, **kwargs):
            entered.set()
            if not proceed.wait(15): raise ValueError('SYNC_TIMEOUT')
            yield
    try:
        with patch.object(authority, 'file_lock', side_effect=observed_file_lock):
            if kind == 'revoke':
                with patch.object(authority, 'state_write_lock', side_effect=held):
                    value = authority.update_approvals(state_path, token, revoke=changes)
            else:
                with patch.object(production_runtime, 'state_write_lock', side_effect=held):
                    value = production_runtime.commit_updates(state_path, token, changes)
        results.put((kind, value['status']))
    except (OSError, ValueError) as exc: results.put((kind, str(exc)))


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(); self.addCleanup(self.f.close)
        self.root = self.f.root
        self.proof = copy.deepcopy(self.f.state['gates']['shot_design'])
        self.proof_ref = self.write('original-user-proof.json', self.proof)
        self.ids = [r['panel_id'] for r in self.f.state['panels']]
        self.registration = {'approval': self.proof_ref, 'phase': 'shot_design', 'panel_ids': self.ids}
        self.revocation = {'approval': self.proof_ref, 'message': {'source_kind': 'user_message',
            'source_locator': 'SYNTHETIC_TEST_NOT_REAL_USER', 'quote': 'SYNTHETIC withdraw this exact approval'}}

    def write(self, name, value):
        path = self.root/name; atomic_json(path, value)
        return {'path': name, 'sha256': digest(path)}

    def update(self, **kwargs):
        return authority.update_approvals(self.f.state_path, digest(self.f.state_path), **kwargs)

    def reserve(self):
        return reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)

    def current(self): return read_json(self.f.state_path)

    def test_registration_preserves_proof_bytes_and_publishes_new_index_only(self):
        original = (self.root/self.proof_ref['path']).read_bytes()
        old = self.f.state.get('approval_index')
        old_bytes = checked_file(self.root, old).read_bytes() if old else None
        result = self.update(register=[self.registration])
        state = self.current(); self.assertEqual(result['authority_revision'], 1)
        self.assertFalse(result['short_lock_enabled'])
        index = read_json(checked_file(self.root, state['approval_index']))
        proof = checked_file(self.root, index['entries'][-1]['approval'])
        self.assertEqual(proof.read_bytes(), original)
        self.assertEqual((self.root/self.proof_ref['path']).read_bytes(), original)
        if old: self.assertEqual(checked_file(self.root, old).read_bytes(), old_bytes)
        self.assertEqual(self.reserve()['status'], 'RESERVED')

    def test_revocation_blocks_embedded_proof_and_index_fallback_without_rewriting_them(self):
        self.update(register=[self.registration]); before = self.current()
        old_index = checked_file(self.root, before['approval_index']).read_bytes()
        self.update(revoke=[self.revocation]); after = self.current()
        self.assertEqual(before['gates'], after['gates'])
        self.assertEqual(checked_file(self.root, before['approval_index']).read_bytes(), old_index)
        result = self.reserve()
        self.assertEqual(result['reserved'], [], result)
        self.assertFalse(list(self.root.glob('*.dispatch-*.json')))
        self.assertEqual(after['authority_revision'], 2)

    def test_same_proof_cannot_be_re_registered_after_revocation(self):
        self.update(revoke=[self.revocation]); before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REVOKED'):
            self.update(register=[self.registration])
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_new_real_proof_can_authorize_same_artifacts_after_old_proof_revoked(self):
        self.update(revoke=[self.revocation])
        fresh = {**self.proof, 'source_locator': 'SYNTHETIC_NEW_USER_DECISION', 'quote': 'SYNTHETIC reapprove these exact inputs'}
        ref = self.write('new-user-proof.json', fresh)
        self.update(register=[{**self.registration, 'approval': ref}])
        self.assertEqual(self.reserve()['status'], 'RESERVED')

    def test_stale_cas_and_invalid_scope_do_not_write(self):
        old = digest(self.f.state_path); self.update(register=[self.registration])
        before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'STATE_CHANGED'):
            authority.update_approvals(self.f.state_path, old, revoke=[self.revocation])
        with self.assertRaisesRegex(ValueError, 'exact phase'):
            self.update(register=[{**self.registration, 'panel_ids': ['P999']}])
        with self.assertRaisesRegex(ValueError, 'user revocation'):
            self.update(revoke=[{**self.revocation, 'message': {'source_kind': 'agent', 'quote': 'not human'}}])
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_read_transaction_ends_before_any_published_file_or_state_write(self):
        from codex_reference_contract import _FILE_SESSION
        real = authority._write_once
        def observe(*args, **kwargs):
            self.assertIsNone(_FILE_SESSION.get()); return real(*args, **kwargs)
        with patch.object(authority, '_write_once', side_effect=observe):
            self.update(register=[self.registration])
        with file_session(), self.assertRaisesRegex(ValueError, 'REQUIRES_OWN_TRANSACTION'):
            self.update(revoke=[self.revocation])

    def test_changed_proof_during_validation_discards_every_write(self):
        actual = approval_errors
        def changed(*args, **kwargs):
            result = actual(*args, **kwargs)
            atomic_json(self.root/self.proof_ref['path'], self.proof)
            return result
        before = self.f.state_path.read_bytes()
        with patch('staged_workflow.approval_errors', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'CHECK_SNAPSHOT_CHANGED'):
                self.update(register=[self.registration])
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertFalse((self.root/'00_输入审计/authority_versions').exists())

    def test_revocation_not_bypassed_by_transaction_local_approval_cache(self):
        self.update(revoke=[self.revocation]); revoked = self.current()
        initial = copy.deepcopy(revoked); initial['approval_revocations'] = []
        with file_session():
            with authority.authority_context(initial, self.root):
                self.assertEqual(approval_errors(self.proof, self.root, self.proof['artifacts'],
                    initial['book_id'], initial['episode_id'], phase='shot_design', panel_ids=self.ids), [])
            with authority.authority_context(revoked, self.root):
                errors = approval_errors(self.proof, self.root, self.proof['artifacts'],
                    revoked['book_id'], revoked['episode_id'], phase='shot_design', panel_ids=self.ids)
                self.assertIn('APPROVAL_REVOKED', ';'.join(errors))

    def test_authority_context_is_isolated_and_historical_evidence_is_not_rewritten(self):
        self.update(revoke=[self.revocation]); state = self.current()
        with authority.authority_context(state, self.root, enforce=False):
            self.assertEqual(authority.revocation_errors(self.proof, state['book_id'], state['episode_id']), [])
        with authority.authority_context(state, self.root):
            self.assertTrue(authority.revocation_errors(self.proof, state['book_id'], state['episode_id']))
            self.assertEqual(authority.revocation_errors(self.proof, state['book_id'], 'OTHER'), [])
        self.assertIsNone(authority.revocation_token())

    def test_lookup_metadata_and_cached_coverage_cannot_hide_withdrawal(self):
        from panel_readiness import artifacts_covered
        self.update(revoke=[self.revocation]); revoked = self.current()
        initial = copy.deepcopy(revoked); initial['approval_revocations'] = []
        indexed = {**self.proof, '_lookup_panel_ids': self.ids}
        with file_session():
            with authority.authority_context(initial, self.root):
                self.assertTrue(artifacts_covered(initial, self.root, indexed, self.proof['artifacts'], self.ids, 'shot_design'))
            with authority.authority_context(revoked, self.root):
                self.assertFalse(artifacts_covered(revoked, self.root, indexed, self.proof['artifacts'], self.ids, 'shot_design'))

    def test_withdrawn_delegation_blocks_existing_agent_decision(self):
        from review_policy import proposal, delegated_decisions
        grant = {'policy': 'user_delegation_v1', 'status': 'AUTHORIZED', 'source_kind': 'user_message',
                 'quote': 'SYNTHETIC delegate exact B', 'source_locator': 'SYNTHETIC_GRANT',
                 'constraints': ['SYNTHETIC preserve exact approved input scope'], 'book_id': self.f.state['book_id'],
                 'episode_ids': ['E000'], 'panel_ids': {'E000': self.ids}, 'phases': ['shot_design']}
        grant_ref = self.write('delegation.json', grant)
        review = proposal(self.f.state['book_id'], 'E000', [{'item_id': 'B', 'phase': 'shot_design',
            'panel_ids': self.ids, 'artifacts': self.proof['artifacts'], 'summary': 'SYNTHETIC exact B'}], self.root)
        proof = delegated_decisions(review, ['B'], grant_ref, 'SYNTHETIC reviewer', 'SYNTHETIC observation', self.root)[0]
        ref = self.write('agent-decision.json', proof)
        row = {**self.registration, 'approval': ref}
        self.update(register=[row])
        self.update(revoke=[{**self.revocation, 'approval': grant_ref}])
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REVOKED'):
            self.update(register=[row])
        # A real script run must share the named module's authority ContextVar
        # with imported validators, rather than creating a separate __main__ one.
        changes = self.write('withdrawn-delegation-changes.json', {'register': [row]})
        before = self.f.state_path.read_bytes()
        cli = subprocess.run([sys.executable, '-B', str(Path(authority.__file__)), '--state', str(self.f.state_path),
            '--expected-state-sha256', digest(self.f.state_path), '--changes', str(self.root/changes['path'])],
            capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(cli.returncode, 1, cli.stdout+cli.stderr)
        self.assertIn('APPROVAL_REVOKED', ';'.join(json.loads(cli.stdout)['errors']))
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_batch_cannot_register_and_revoke_same_proof_or_expand_scope(self):
        before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'APPROVAL_REVOKED'):
            self.update(register=[self.registration], revoke=[self.revocation])
        ref = self.write('narrow-proof.json', {**self.proof, 'panel_ids': ['P001']})
        with self.assertRaisesRegex(ValueError, 'expand'):
            self.update(register=[{**self.registration, 'approval': ref}])
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_evidence_publication_failure_does_not_commit_authority_state(self):
        before = self.f.state_path.read_bytes()
        with patch.object(authority.os, 'link', side_effect=PermissionError('synthetic filesystem interruption')):
            with self.assertRaises(PermissionError): self.update(register=[self.registration])
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_invalid_authority_metadata_is_global_hold_not_legacy_fallback(self):
        self.f.state.update(authority_policy='future', authority_revision=1, approval_revocations=[])
        self.f.flush()
        before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'AUTHORITY_HOLD'): self.reserve()
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_new_entry_cannot_install_authority_on_an_older_toolchain(self):
        self.f.state['toolchain']['files'] = [r for r in self.f.state['toolchain']['files'] if r['path'] != 'authority_updates.py']
        self.f.flush(); before = self.f.state_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'EXECUTION_CONTRACT_HOLD'):
            self.update(register=[self.registration])
        self.assertEqual(self.f.state_path.read_bytes(), before)
        self.assertFalse((self.root/'00_输入审计/authority_versions').exists())

    def test_actual_cli_registers_and_rejects_a_stale_retry_without_writes(self):
        token = digest(self.f.state_path)
        changes = self.write('register-changes.json', {'register': [self.registration]})
        script = Path(__file__).resolve().parents[1]/'scripts/authority_updates.py'
        args = [sys.executable, '-B', str(script), '--state', str(self.f.state_path),
                '--expected-state-sha256', token, '--changes', str(self.root/changes['path'])]
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'AUTHORITY_UPDATED')
        before = self.f.state_path.read_bytes()
        stale = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(stale.returncode, 1, stale.stdout+stale.stderr)
        self.assertEqual(json.loads(stale.stdout)['status'], 'HOLD')
        self.assertEqual(self.f.state_path.read_bytes(), before)

    def test_policy_installed_after_old_prelock_read_requires_fresh_cas(self):
        actual = authority.file_lock
        @contextmanager
        def changed(path, **kwargs):
            with actual(path, **kwargs) as stream:
                new = self.current()
                new.update(authority_policy=authority.POLICY, authority_revision=1, approval_revocations=[])
                atomic_json(self.f.state_path, new)
                yield stream
        with patch.object(authority, 'file_lock', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'AUTHORITY_PROTOCOL_CHANGED'):
                with authority.state_write_lock(self.f.state_path): self.fail('must not enter old writer')

    def test_registered_owner_writes_take_the_same_two_locks_in_reservation_order(self):
        self.update(register=[self.registration])
        actual = authority.file_lock; paths = []
        @contextmanager
        def observed(path, **kwargs):
            paths.append(path)
            with actual(path, **kwargs) as stream: yield stream
        with patch.object(authority, 'file_lock', side_effect=observed):
            with authority.state_write_lock(self.f.state_path): pass
        self.assertEqual(paths, sorted([self.f.state_path.with_suffix('.runtime.lock'), self.f.control_path.resolve().with_suffix('.dispatch.lock')]))

    def test_legacy_owner_writes_still_take_only_episode_state_lock(self):
        actual = authority.file_lock; paths = []
        @contextmanager
        def observed(path, **kwargs):
            paths.append(path)
            with actual(path, **kwargs) as stream: yield stream
        with patch.object(authority, 'file_lock', side_effect=observed):
            with authority.state_write_lock(self.f.state_path): pass
        self.assertEqual(paths, [self.f.state_path.with_suffix('.runtime.lock')])

    def race(self, first):
        self.update(register=[self.registration]); self.assertEqual(self.reserve()['status'], 'RESERVED')
        token = digest(self.f.state_path)
        updates = [{'panel_id': 'P001', 'round_id': 1, 'attempt_id': 'P001-r1', 'status': 'IN_FLIGHT'}]
        ctx = multiprocessing.get_context('spawn'); results = ctx.Queue()
        entered = {k: ctx.Event() for k in ('revoke', 'submit')}
        proceed = {k: ctx.Event() for k in entered}; attempted = {k: ctx.Event() for k in entered}
        processes = {k: ctx.Process(target=writer_process, args=(k, self.f.state_path, token,
            [self.revocation] if k=='revoke' else updates, entered[k], proceed[k], attempted[k], results)) for k in entered}
        second = 'submit' if first=='revoke' else 'revoke'
        try:
            processes[first].start(); self.assertTrue(entered[first].wait(15))
            processes[second].start(); self.assertTrue(attempted[second].wait(15))
            self.assertFalse(entered[second].is_set())
            proceed[second].set(); proceed[first].set()
            outcomes = dict([results.get(timeout=20), results.get(timeout=20)])
            self.assertEqual(outcomes[first], 'AUTHORITY_UPDATED' if first=='revoke' else 'UPDATES_SAVED', outcomes)
            self.assertIn('STATE_CHANGED', outcomes[second], outcomes)
            for process in processes.values(): process.join(15); self.assertEqual(process.exitcode, 0)
        finally:
            for process in processes.values():
                if process.pid and process.is_alive(): process.terminate(); process.join(5)
            results.close(); results.join_thread()
        return updates

    def test_revocation_wins_before_inflight_and_old_submission_must_reread(self):
        updates = self.race('revoke')
        from production_runtime import commit_updates
        state = self.current(); self.assertEqual(state['panels'][0]['status'], 'PENDING')
        with self.assertRaisesRegex(ValueError, '完整门禁'):
            commit_updates(self.f.state_path, digest(self.f.state_path), updates)
        self.assertEqual(self.current()['dispatch_ledger'][0]['status'], 'RESERVED')

    def test_inflight_wins_first_and_later_revocation_preserves_its_attempt_and_slot(self):
        self.race('submit'); self.update(revoke=[self.revocation])
        state = self.current()
        self.assertEqual(state['panels'][0]['status'], 'IN_FLIGHT')
        self.assertEqual(state['panels'][0]['attempt_id'], 'P001-r1')
        self.assertEqual(state['dispatch_ledger'][0]['status'], 'IN_FLIGHT')
        self.assertEqual(self.reserve()['reserved'], [])


if __name__ == '__main__': unittest.main()
