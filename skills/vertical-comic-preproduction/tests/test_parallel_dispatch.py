import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from parallel_dispatch import context_errors, receipt_errors, handoff_readiness


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.episode = self.root / "E021"
        (self.episode / "00_输入审计").mkdir(parents=True)
        self.control_path = self.root / "control.json"
        self.context = {"control_file": str(self.control_path), "job_id": "job21", "worker_id": "worker21", "epoch": 1}
        image_ref = self.write(self.root, "style.png", b"test frozen style bytes")
        self.style = {"reference_sha256": [image_ref["sha256"]], "traits": {"linework": "clean", "face_proportions": "fixed"}}
        style_ref = self.write(self.root, "basis.json", {"book_id": "book", "style": self.style})
        style_ref["role"] = "style_basis"
        registry_ref = self.write(self.root, "registry.json", {"existing_registry": "frozen, authoritative"})
        registry_ref["role"] = "state_registry"
        inputs = {"source_script": self.write(self.episode, "source.xlsx", b"source bytes"),
                  "source_snapshot": self.write(self.episode, "source.json", {"panel_ids": ["P001", "P002"]}),
                  "visual_basis": self.write(self.episode, "basis.json", {"book_id": "book", "episode_id": "E021", "style": self.style}),
                  "shot_manifest": self.write(self.episode, "shots.json", {"panels": []})}
        self.state = {"book_id": "book", "episode_id": "E021", "parallel_context": self.context,
                      "cancelled": False, "holds": [], "panels": [{"panel_id": "P001"}, {"panel_id": "P002"}], **inputs}
        self.state_path = self.episode / "00_输入审计/生产流程.json"
        self.control = {"policy": "parallel_episodes_v1", "version": 1, "book_id": "book", "epoch": 1,
                        "cancelled": False, "holds": [], "max_workers": 5, "max_inflight": 5,
                        "shared_files": [image_ref, style_ref, registry_ref],
                        "jobs": [{"job_id": "job21", "episode_id": "E021", "worker_id": "worker21", "root": str(self.episode), "status": "RUNNING", "frozen_inputs": copy.deepcopy(inputs)}],
                        "permits": [{"permit_id": "r1", "job_id": "job21", "worker_id": "worker21", "epoch": 1, "panel_id": "P001", "status": "RESERVED"}]}
        self.flush()

    def write(self, root, name, data):
        path = root / name
        content = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        path.write_bytes(content)
        return {"path": name, "sha256": hashlib.sha256(content).hexdigest()}

    def flush(self):
        self.control_path.write_text(json.dumps(self.control))
        self.state_path.write_text(json.dumps(self.state))

    def check(self, panel="P001"):
        self.flush()
        return context_errors(self.context, self.episode, "book", "E021", panel)

    def assertError(self, fragment, panel="P001"):
        self.assertTrue(any(fragment in e for e in self.check(panel)), self.check(panel))

    def test_valid_snapshot_read_only(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(self.check(), [])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_pause_blocks_only_new_dispatch_and_handoff_waits_for_inflight(self):
        self.control["jobs"][0]["dispatch_pause"] = True
        self.assertError("暂停新请求")
        self.assertEqual(self.check(panel=None), [])
        self.assertEqual(handoff_readiness(self.control, self.state, "job21", old_writer_stopped=True),
                         ["存在RESERVED或IN_FLIGHT许可；不得交接"])
        self.control["permits"][0]["status"] = "RELEASED"
        self.state["panels"][0]["status"] = "RESULT_UNKNOWN"
        self.assertTrue(any("结果未知" in e for e in handoff_readiness(self.control,self.state,"job21",old_writer_stopped=True)))
        self.state["panels"][0]["status"] = "VISUAL_PASS"
        self.assertEqual(handoff_readiness(self.control,self.state,"job21",old_writer_stopped=True),[])
        self.assertTrue(handoff_readiness(self.control,self.state,"job21",old_writer_stopped=False))

    def test_handoff_cli_reports_hold_without_mutating_control(self):
        script=Path(__file__).resolve().parents[1]/"scripts"/"parallel_dispatch.py"
        before=self.control_path.read_bytes()
        result=subprocess.run([sys.executable,str(script),"--state",str(self.state_path),
                               "--handoff-check","--old-writer-stopped"],capture_output=True,text=True)
        self.assertEqual(result.returncode,1)
        self.assertTrue(json.loads(result.stdout)["handoff_check_only"])
        self.assertEqual(self.control_path.read_bytes(),before)

    def test_duplicate_owner(self):
        other = copy.deepcopy(self.control["jobs"][0])
        other.update(job_id="job22", episode_id="E022", root=str(self.root / "E022"))
        self.control["jobs"].append(other)
        self.assertError("同一worker")

    def test_duplicate_episode_and_root(self):
        self.control["jobs"].append({**self.control["jobs"][0], "job_id": "job22", "worker_id": "worker22"})
        self.assertError("episode_id")
        self.assertError("根目录重复")

    def test_worker_capacity(self):
        self.control["max_workers"] = 0
        self.assertError("正整数")
        self.control["max_workers"] = 1
        self.control["jobs"].append({**self.control["jobs"][0], "job_id": "job22", "worker_id": "worker22", "episode_id": "E022", "root": str(self.root / "E022")})
        self.assertError("超过max_workers")

    def test_queued_jobs_do_not_consume_workers(self):
        self.control["max_workers"] = 1
        self.control["jobs"].append({**self.control["jobs"][0], "job_id": "job22", "worker_id": None,
                                     "episode_id": "E022", "root": str(self.root / "E022"), "status": "QUEUED"})
        self.assertEqual(self.check(), [])

    def test_boolean_epoch_rejected(self):
        self.context["epoch"] = True
        self.assertError("epoch已过期")

    def test_request_capacity(self):
        self.control["max_inflight"] = 1
        self.control["permits"].append({**self.control["permits"][0], "permit_id": "r2", "panel_id": "P002"})
        self.assertError("超过max_inflight")

    def test_cross_episode(self):
        self.control["jobs"][0]["episode_id"] = "E022"
        self.assertError("话号或根目录")

    def test_old_epoch(self):
        self.control["epoch"] = 2
        self.assertError("epoch已过期")
        self.assertError("活动permit")

    def test_shared_bytes_changed(self):
        (self.root / "style.png").write_bytes(b"new image")
        self.assertError("哈希不符")

    def test_missing_actual_style_bytes(self):
        self.control["shared_files"] = self.control["shared_files"][1:]
        self.assertError("样例实际文件")

    def test_missing_registry(self):
        self.control["shared_files"] = self.control["shared_files"][:-1]
        self.assertError("state_registry")

    def test_duplicate_permit(self):
        self.control["permits"].append({**self.control["permits"][0], "permit_id": "r2"})
        self.assertError("同话同格")

    def test_no_permit(self):
        self.control["permits"] = []
        self.assertError("唯一RESERVED")
        self.assertEqual(self.check(None), [])

    def test_inflight_cannot_resubmit(self):
        self.control["permits"][0]["status"] = "IN_FLIGHT"
        self.assertError("已IN_FLIGHT")
        self.assertEqual(self.check(None), [])

    def test_wrong_permit_owner(self):
        self.control["permits"][0]["worker_id"] = "another"
        self.assertError("活动permit")

    def test_global_hold_and_cancel(self):
        self.control["holds"] = ["style changed"]
        self.assertError("全局HOLD")
        self.control["holds"] = []
        self.control["cancelled"] = True
        self.assertError("批次取消")

    def test_episode_hold_and_wait(self):
        self.control["jobs"][0]["status"] = "HOLD"
        self.assertError("本话HOLD")
        self.control["jobs"][0]["status"] = "WAIT_REVIEW"
        self.assertError("尚待审查")

    def test_state_input_changed(self):
        self.state["shot_manifest"] = self.write(self.episode, "shots2.json", {"panels": ["changed"]})
        self.assertError("shot_manifest与任务冻结")

    def test_shared_style_mismatch(self):
        self.state["visual_basis"] = self.write(self.episode, "basis.json", {"book_id": "book", "episode_id": "E021", "style": {**self.style, "traits": {"linework": "different"}}})
        self.control["jobs"][0]["frozen_inputs"]["visual_basis"] = self.state["visual_basis"]
        self.assertError("未绑定共用")

    def test_foreign_panel(self):
        self.assertError("不属于本话", "P999")

    def test_relative_control_rejected(self):
        self.context["control_file"] = "control.json"
        self.assertError("绝对路径")

    def test_shared_path_escape(self):
        self.control["shared_files"][0]["path"] = "../style.png"
        self.assertError("根目录内相对路径")

    def test_state_context_mismatch(self):
        self.state["parallel_context"] = {**self.context, "worker_id": "foreign"}
        self.assertError("状态与调度上下文")

    def receipt(self, output_hash=None, receipt_override=None):
        self.flush()
        receipt = {**{k: self.context[k] for k in ("job_id", "worker_id", "epoch")}, "permit_id": "r1"}
        if receipt_override:
            receipt.update(receipt_override)
        return receipt_errors(self.context, self.episode, "book", "E021", "P001", receipt, output_hash)

    def completed_permit(self):
        output_hash = hashlib.sha256(b"actual output bytes").hexdigest()
        self.control["permits"][0].update(status="COMPLETED", output_sha256=output_hash)
        return output_hash

    def test_receipt_reserved(self):
        self.assertEqual(self.receipt(), [])

    def test_receipt_completed(self):
        output_hash = self.completed_permit()
        self.assertEqual(self.receipt(output_hash), [])

    def test_completed_job_still_reviewable(self):
        output_hash = self.completed_permit()
        self.control["jobs"][0]["status"] = "COMPLETED"
        self.assertEqual(self.check(None), [])
        self.assertEqual(self.receipt(output_hash), [])
        self.assertTrue(self.check("P001"))

    def test_cancelled_job_never_adopts(self):
        output_hash = self.completed_permit()
        self.control["jobs"][0]["status"] = "CANCELLED"
        self.assertTrue(self.receipt(output_hash))

    def test_receipt_old_epoch_after_state_upgrade(self):
        output_hash = self.completed_permit()
        self.context["epoch"] = 2
        self.control["epoch"] = 2
        # The terminal permit remains historical: do not rewrite its epoch.
        errors = self.receipt(output_hash, {"epoch": 1})
        self.assertTrue(any("epoch" in e for e in errors), errors)

    def test_receipt_old_owner_after_state_upgrade(self):
        output_hash = self.completed_permit()
        self.context["worker_id"] = "replacement"
        self.control["jobs"][0]["worker_id"] = "replacement"
        errors = self.receipt(output_hash, {"worker_id": "worker21"})
        self.assertTrue(any("worker_id" in e for e in errors), errors)

    def test_receipt_output_hash_missing_or_different(self):
        output_hash = self.completed_permit()
        del self.control["permits"][0]["output_sha256"]
        self.assertTrue(any("输出哈希" in e for e in self.receipt(output_hash)))
        self.control["permits"][0]["output_sha256"] = "0" * 64
        self.assertTrue(any("输出哈希" in e for e in self.receipt(output_hash)))

    def test_receipt_wrong_panel_and_permit(self):
        output_hash = self.completed_permit()
        self.control["permits"][0]["panel_id"] = "P002"
        self.assertTrue(any("其他格" in e for e in self.receipt(output_hash)))
        self.assertTrue(any("不存在" in e for e in self.receipt(output_hash, {"permit_id": "unknown"})))

    def test_receipt_cannot_adopt_reserved_output(self):
        output_hash = hashlib.sha256(b"candidate bytes").hexdigest()
        self.assertTrue(any("COMPLETED" in e for e in self.receipt(output_hash)))

    def make_carry_forward(self):
        output_hash = self.completed_permit()
        old_receipt = {"job_id": "job21", "worker_id": "worker21", "epoch": 1, "permit_id": "r1"}
        self.context["epoch"] = 2
        self.context["worker_id"] = "replacement"
        self.control["epoch"] = 2
        self.control["jobs"][0]["worker_id"] = "replacement"
        output = self.write(self.episode, "output.png", b"actual output bytes")
        package = self.write(self.episode, "package.json", {"dispatch_receipt": old_receipt})
        qa = self.write(self.episode, "qa.json", {"actual_visual_review": "test fixture"})
        self.state["panels"][0].update(package_manifest=package, qa_report=qa, output=output)
        report = {"policy": "dispatch_reuse_v1", "status": "PASS", "reviewer": "coordinator", "evidence": "Compared original image to current approved assets and shots.",
                  "worker_id": "replacement", "epoch": 2, "source_receipt": old_receipt,
                  "frozen_inputs": copy.deepcopy(self.control["jobs"][0]["frozen_inputs"]),
                  "package_manifest": package, "qa_report": qa, "output": output}
        self.save_carry_forward(report)
        return output_hash, old_receipt, report

    def save_carry_forward(self, report):
        self.control["permits"][0]["carry_forward"] = self.write(self.episode, "carry.json", report)

    def test_carry_forward_valid_old_epoch_owner(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        self.assertEqual(self.receipt(output_hash, old_receipt), [])
        self.assertEqual(self.control["permits"][0]["epoch"], 1)
        self.assertEqual(self.control["permits"][0]["worker_id"], "worker21")

    def test_carry_forward_wrong_output_ref(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        report["output"] = self.write(self.episode, "wrong.png", b"wrong image")
        self.save_carry_forward(report)
        self.assertTrue(any("output不是当前格" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_wrong_qa_ref(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        report["qa_report"] = self.write(self.episode, "wrongqa.json", {"different": "review"})
        self.save_carry_forward(report)
        self.assertTrue(any("qa_report不是当前格" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_stale_frozen_inputs(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        report["frozen_inputs"]["shot_manifest"] = self.write(self.episode, "oldshots.json", {"old": True})
        self.save_carry_forward(report)
        self.assertTrue(any("frozen_inputs" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_missing_actual_review(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        report["evidence"] = " "
        self.save_carry_forward(report)
        self.assertTrue(any("实际复核" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_changed_package_receipt(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        changed = self.write(self.episode, "package.json", {"dispatch_receipt": {**old_receipt, "epoch": 2}})
        report["package_manifest"] = changed
        self.state["panels"][0]["package_manifest"] = changed
        self.save_carry_forward(report)
        self.assertTrue(any("已更改原始" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_hash_tamper(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        (self.episode / "qa.json").write_text('{"changed": true}')
        self.assertTrue(any("哈希不符" in e for e in self.receipt(output_hash, old_receipt)))

    def test_carry_forward_never_authorizes_new_call(self):
        output_hash, old_receipt, report = self.make_carry_forward()
        self.control["permits"][0]["status"] = "RESERVED"
        self.assertTrue(self.receipt(None, old_receipt))

    def test_cli_read_only(self):
        script = Path(__file__).resolve().parents[1] / "scripts/parallel_dispatch.py"
        result = subprocess.run([sys.executable, str(script), "--state", str(self.state_path), "--panel", "P001"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["read_only"])


if __name__ == "__main__":
    unittest.main()
