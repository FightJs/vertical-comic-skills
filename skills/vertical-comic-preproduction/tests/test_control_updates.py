"""Coordinator updates participate in existing reservation/lease lock protocol."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parents[1]/'scripts'), str(Path(__file__).parent)]
from dispatch_fixture import DispatchFixture
from codex_reference_contract import digest, read_json
from episode_dispatch_queue import reserve_ready
import control_updates


class ControlUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.f = DispatchFixture(); self.addCleanup(self.f.close)

    def update(self, changes, **kwargs):
        return control_updates.update(self.f.control_path, kwargs.get('control_sha', digest(self.f.control_path)),
            kwargs.get('states', {'synthetic-job': digest(self.f.state_path)}), changes, reason='SYNTHETIC coordinator event')

    def test_pause_blocks_reservation_and_keeps_existing_ledger_unchanged(self):
        before = self.f.state_path.read_bytes(); control = read_json(self.f.control_path)
        result = self.update({'jobs': {'synthetic-job': {'dispatch_pause': True}}})
        self.assertEqual(result['status'], 'CONTROL_UPDATED')
        queued = reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)
        self.assertEqual(queued['status'], 'DISPATCH_PAUSED'); self.assertEqual(queued['reserved'], [])
        self.assertEqual(self.f.state_path.read_bytes(), before)
        after = read_json(self.f.control_path)
        self.assertEqual(control['jobs'][0]['slot_lease'], after['jobs'][0]['slot_lease'])
        self.assertEqual(control['permits'], after['permits'])
        self.update({'jobs': {'synthetic-job': {'dispatch_pause': False}}})
        self.assertEqual(reserve_ready(self.f.state_path, digest(self.f.state_path), digest(self.f.control_path), 1)['status'], 'RESERVED')

    def test_stale_control_or_owner_state_does_not_write(self):
        old = digest(self.f.control_path); self.update({'holds': []})
        before = self.f.control_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'CONTROL_CHANGED'): self.update({'holds': []}, control_sha=old)
        with self.assertRaisesRegex(ValueError, 'STATE_CHANGED'): self.update({'holds': []}, states={'synthetic-job': '0'*64})
        self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_cannot_change_capacity_owner_permits_or_references(self):
        for changes in ({'max_inflight': 9}, {'jobs': {'synthetic-job': {'worker_id': 'other'}}},
                        {'permits': []}, {'shared_files': []}, {'jobs': {'synthetic-job': {'frozen_inputs': {}}}}):
            before = self.f.control_path.read_bytes()
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.update(changes)
            self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_cancel_is_explicit_and_cannot_silently_resume(self):
        self.update({'cancelled': True})
        before = self.f.control_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'cancellation'): self.update({'cancelled': False})
        self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_old_toolchain_and_unknown_control_metadata_are_rejected(self):
        self.f.state['toolchain']['files'] = []; self.f.flush()
        before = self.f.control_path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'EXECUTION_CONTRACT_HOLD'): self.update({'holds': []})
        self.assertEqual(self.f.control_path.read_bytes(), before)

    def test_real_cli_uses_exact_owner_hashes(self):
        changes = self.f.root/'changes.json'; changes.write_text(json.dumps({'jobs': {'synthetic-job': {'dispatch_pause': True}}}))
        states = self.f.root/'states.json'; states.write_text(json.dumps({'synthetic-job': digest(self.f.state_path)}))
        result = subprocess.run([sys.executable, '-B', str(Path(control_updates.__file__)), '--control', str(self.f.control_path),
            '--expected-control-sha256', digest(self.f.control_path), '--expected-states', str(states), '--changes', str(changes),
            '--reason', 'SYNTHETIC pause'], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'CONTROL_UPDATED')


if __name__ == '__main__': unittest.main()
