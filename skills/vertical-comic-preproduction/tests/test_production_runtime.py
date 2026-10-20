"""Real isolated contracts and synthetic images; no image service or agents."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/"scripts"),str(Path(__file__).parent)]
import test_half_workflow as fixtures
from scoped_inputs import POLICY, build_plan, half_view
from codex_reference_contract import digest, file_session
from staged_workflow import evaluate, preflight_many
from production_runtime import DEFAULTS, compile_jobs, review_bundle, checkpoint, commit_updates, settings
from production_runtime import prepare_review
from production_runtime import dependency_plan_matches
from codex_reference_contract import validate_panel
from review_queue import build_queue
from batch_round import repair_route_errors


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.h=fixtures.ActualHalfGateTests("test_real_qa_round_report_and_first_half_approval")
        self.h.setUp();self.addCleanup(self.h.doCleanups);self.root=self.h.root
        self.r=self.h.returned();self.state=self.h.state

    def scoped(self):
        self.h.panel["generation_execution"]["status"]="NOT_RUN"
        self.h.h.manifest["optimization_policy"]=POLICY;self.h.sync()
        s=self.state;s.update(optimization_policy=POLICY,half_inputs={},half_gates={})
        original=json.loads((self.root/"shots.json").read_text(encoding='utf-8-sig'));original["optimization_policy"]=POLICY
        shot=self.h.h.f.write("scoped-shot.json",original)
        s["half_inputs"]={"H001":{"visual_basis":s["visual_basis"],"shot_manifest":shot}}
        s["half_gates"]={"H001":{"visual_basis":self.h.h.approve([s["source_script"],s["source_snapshot"],s["visual_basis"]]),
                               "shot_design":self.h.h.approve([s["visual_basis"],shot])}}
        source=json.loads((self.root/"snapshot.json").read_text(encoding='utf-8-sig'))
        s["batch_plan"]=self.h.h.f.write("scoped-plan.json",build_plan(s,source))
        self.r["status"]="PENDING"
        return s

    def enable_package(self,s):
        s["runtime"]=copy.deepcopy(DEFAULTS)
        compiled=compile_jobs(s,self.root,candidate=True)
        self.assertEqual(len(compiled["jobs"]),1,compiled)
        bundle=self.h.h.f.write("review-bundle.json",review_bundle(s,self.root,compiled))
        s["generation_packages"]={"H001":[bundle]}
        view=half_view(s,"H001")
        proof=self.h.h.f.write("literal-package-approval.json",
            self.h.h.approve([bundle,view["visual_basis"],view["shot_manifest"]]))
        s["approval_index"]=self.h.h.f.write("approval-index.json",{"policy":"approval_index_v1","entries":[{
            "phase":"generation_package","book_id":s["book_id"],"episode_ids":[s["episode_id"]],
            "panel_ids":["P001"],"approval":proof}]})
        return compiled

    def test_bulk_same_verdict_as_full_single_panel_gate_and_real_arguments(self):
        s=self.scoped();expected=evaluate(s,self.root,"generate","P001")
        bulk=preflight_many(s,self.root,["P001"])
        self.assertEqual(expected["status"],"PASS",expected)
        self.assertEqual(bulk["reports"][0]["status"],expected["status"])
        compiled=compile_jobs(s,self.root,["P001"])
        self.assertEqual(compiled["jobs"][0]["arguments"]["prompt"],self.h.panel["prompt"])
        self.assertEqual(len(compiled["jobs"][0]["arguments"]["referenced_image_paths"]),2)
        self.assertEqual(compiled["image_calls"],0)
        self.assertGreater(bulk["file_reuse_statistics"]["hash_hits"],0)

    def test_candidate_B_is_reviewable_but_cannot_dispatch(self):
        s=self.scoped();s["half_gates"]["H001"].pop("shot_design")
        compiled=compile_jobs(s,self.root,candidate=True)
        self.assertEqual(len(compiled["jobs"]),1,compiled)
        self.assertTrue(compiled["candidate_only"])
        self.assertFalse(compiled["preflight"]["dispatch_authorized"])
        self.assertEqual(evaluate(s,self.root,"generate","P001")["next_action"],"WAIT_HALF_SHOT_APPROVAL")

    def test_package_proof_is_required_and_exact_inputs_are_reused(self):
        s=self.scoped();s["runtime"]=copy.deepcopy(DEFAULTS)
        self.assertEqual(evaluate(s,self.root)["next_action"],"WAIT_GENERATION_PACKAGE_APPROVAL")
        self.assertEqual(preflight_many(s,self.root,["P001"])["status"],"HOLD")
        self.enable_package(s)
        self.assertEqual(preflight_many(s,self.root,["P001"])["status"],"READY")
        s["generation_packages"]={}
        self.assertEqual(preflight_many(s,self.root,["P001"])["status"],"HOLD")

    def test_incremental_review_omits_valid_unchanged_QA_but_detects_tamper(self):
        batch={"batch_id":"H001","panel_ids":["P001"]}
        self.assertEqual(build_queue(self.state,self.root,batch,incremental=True)["items"],[])
        (self.root/"synthetic-output.png").write_bytes(b"tampered")
        with self.assertRaises(ValueError):build_queue(self.state,self.root,batch,incremental=True)

    def test_review_cursor_only_deduplicates_same_attempt_not_new_image(self):
        self.r["status"]="GENERATED";batch={"batch_id":"H001","panel_ids":["P001"]}
        item=build_queue(self.state,self.root,batch,incremental=True)["items"][0]
        self.assertEqual(build_queue(self.state,self.root,batch,incremental=True,
            processed={"P001":item["review_token"]})["items"],[])
        self.r["attempt_id"]="P001-new"
        self.assertEqual(len(build_queue(self.state,self.root,batch,incremental=True,
            processed={"P001":item["review_token"]})["items"]),1)

    def test_QA_commit_is_atomic_rejects_stale_state_and_never_approves(self):
        self.r["status"]="GENERATED";path=self.root/"00_输入审计/生产流程.json"
        path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(self.state), encoding='utf-8', newline='\n')
        old=digest(path);updates=[{"panel_id":"P001","attempt_id":self.r["attempt_id"],"round_id":1,"status":"VISUAL_PASS"}]
        saved=commit_updates(path,old,updates)
        self.assertEqual(saved["status"],"UPDATES_SAVED")
        self.assertEqual(json.loads(path.read_text(encoding='utf-8-sig'))["panels"][0]["status"],"VISUAL_PASS")
        with self.assertRaisesRegex(ValueError,"STATE_CHANGED"):commit_updates(path,old,updates)
        self.assertEqual(saved["user_approval"],"NOT_GRANTED")

    def test_verified_QA_commit_records_watchdog_progress(self):
        self.r["status"]="GENERATED";self.state["runtime"]=copy.deepcopy(DEFAULTS)
        path=self.root/"00_输入审计/生产流程.json"
        path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(self.state), encoding='utf-8', newline='\n')
        update={"panel_id":"P001","attempt_id":self.r["attempt_id"],"round_id":1,"status":"VISUAL_PASS"}
        saved=commit_updates(path,digest(path),[update])
        self.assertEqual(saved["watchdog_progress"],["PROGRESS_RECORDED"])
        ledger=json.loads((path.parent/"worker_watchdog.json").read_text(encoding='utf-8-sig'))
        self.assertEqual(ledger["events"][-1]["kind"],"qa_saved")
        self.assertEqual(ledger["events"][-1]["stage"],"image_review")

    def test_commit_cannot_rewrite_gates_or_attempt_budget(self):
        self.r["status"]="GENERATED";path=self.root/"00_输入审计/生产流程.json"
        path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(self.state), encoding='utf-8', newline='\n');old=path.read_bytes()
        updates=[{"panel_id":"P001","attempt_id":self.r["attempt_id"],"round_id":1,"status":"VISUAL_PASS","gates":{}}]
        with self.assertRaises(ValueError):commit_updates(path,digest(path),updates)
        self.assertEqual(path.read_bytes(),old)

    def test_input_failure_cannot_be_routed_to_another_image_draw(self):
        s={"runtime":DEFAULTS}
        route={"repair_routes":{"P001":{"route":"targeted_image_repair","earliest_layer":"shot_design",
            "evidence":"SYNTHETIC conflicting crop","preserve_constraints":["identity"]}}}
        self.assertTrue(repair_route_errors(s,route,["P001"]))
        route["repair_routes"]["P001"]["earliest_layer"]="generation_execution"
        self.assertEqual(repair_route_errors(s,route,["P001"]),[])

    def test_read_transaction_reuses_hashes_and_rejects_mid_check_mutation(self):
        p=self.root/"small.json";p.write_text("{}", encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError,"CHECK_SNAPSHOT_CHANGED"):
            with file_session() as memo:
                first=digest(p);self.assertEqual(digest(p),first)
                self.assertEqual(memo["hash_reads"],1);self.assertEqual(memo["hash_hits"],1)
                p.write_text('{"changed":true}', encoding='utf-8', newline='\n')
                with self.assertRaisesRegex(ValueError,"CHECK_SNAPSHOT_CHANGED"):digest(p)
        self.assertNotEqual(digest(p),first)

    def test_runtime_settings_keep_half_review_as_ready(self):
        self.assertEqual(settings(copy.deepcopy(DEFAULTS))["half_review_dispatch"],"as_ready")
        bad={**DEFAULTS,"half_review_dispatch":"wait_for_all"}
        with self.assertRaises(ValueError):settings(bad)
        s=self.scoped();s["runtime"]=bad
        self.assertEqual(preflight_many(s,self.root,["P001"])["next_action"],"EXECUTION_CONTRACT_HOLD")

    def test_watchdog_settings_and_local_cross_episode_handoff(self):
        configured=copy.deepcopy(DEFAULTS)
        self.assertEqual(settings(configured)["watchdog"]["preparation_warning_seconds"],300)
        configured["watchdog"]["request_escalation_seconds"]=900
        with self.assertRaises(ValueError):settings(configured)
        with patch("staged_workflow.evaluate",return_value={"next_action":"WAIT_CROSS_EPISODE_REVIEW","status":"HOLD"}):
            result=checkpoint({"episode_id":"E021"},self.root)
        self.assertEqual(result["worker_lifecycle"],"LOCAL_DONE_HANDOFF_TO_COORDINATOR")
        self.assertFalse(result["ready_for_user_review"])

    def test_one_bad_selection_does_not_hide_ready_panel(self):
        s=self.scoped()
        report=preflight_many(s,self.root,["P001","P999"])
        self.assertEqual(report["status"],"PARTIAL_READY")
        self.assertEqual(report["ready_panel_ids"],["P001"])
        self.assertEqual(report["reports"][1]["status"],"HOLD")

    def test_duplicate_request_list_is_rejected_before_jobs_compile(self):
        s=self.scoped()
        self.assertEqual(compile_jobs(s,self.root,["P001","P001"])["jobs"],[])

    def test_incremental_materials_use_actual_nonstandard_return_name(self):
        self.r["status"]="GENERATED";self.r.pop("qa_report")
        batch={"batch_id":"H001","panel_ids":["P001"]}
        queue=prepare_review(self.state,self.root,build_queue(self.state,self.root,batch,incremental=True))
        item=queue["items"][0];qa=json.loads((self.root/item["qa_template"]["path"]).read_text(encoding='utf-8-sig'))
        self.assertEqual(qa["panels"][0]["image_sha256"],self.r["output"]["sha256"])
        self.assertEqual(qa["panels"][0]["style_review"]["status"],"UNREVIEWED")
        self.assertEqual(queue["contact_sheet"]["panel_ids"],["P001"])

    def test_preapproved_dependency_only_substitutes_exact_verified_image(self):
        s=self.scoped();view=half_view(s,"H001")
        shot=json.loads((self.root/view["shot_manifest"]["path"]).read_text(encoding='utf-8-sig'))
        shot["panels"][0]["generation_dependencies"]=["P000"]
        s["half_inputs"]["H002"]={**s["half_inputs"]["H001"],"shot_manifest":self.h.h.f.write("dependency-shot.json",shot)}
        source=json.loads((self.root/s["source_snapshot"]["path"]).read_text(encoding='utf-8-sig'))
        source["panel_ids"]=["P000","P001"]
        s["source_snapshot"]=self.h.h.f.write("dependency-source.json",source)
        s["panels"].insert(0,{"panel_id":"P000","status":"VISUAL_PASS","output":self.r["output"]})
        s["batch_plan"]=self.h.h.f.write("dependency-batch-plan.json",build_plan(s,source))
        packet=json.loads((self.root/self.r["package_manifest"]["path"]).read_text(encoding='utf-8-sig'));p=packet["panels"][0]
        p["reference_images"].append({**self.r["output"],"alias":"@prior","role":"previous approved frame"})
        p["reference_bindings"].append({"alias":"@prior","purpose":"pose_interaction","subject_ids":["A"]})
        errors,submission=validate_panel(p,self.root);self.assertEqual(errors,[])
        args=copy.deepcopy(submission["arguments"]);refs=[]
        for path in args["referenced_image_paths"]:refs.append({"path":path,"sha256":digest(Path(path))})
        args["referenced_image_paths"][-1]="@DEPENDENCY:P000"
        plan=self.h.h.f.write("dependency-plan.json",{"policy":"dependency_completion_plan_v1","book_id":s["book_id"],
            "episode_id":s["episode_id"],"batch_id":"H002","inputs":[{"panel_id":"P001","dependency_panel_ids":["P000"],
            "arguments":args,"reference_files":refs,"output_spec":p["output_spec"]}]})
        bundle={"dependency_completion_plan":plan};batch={"batch_id":"H002"}
        self.assertTrue(dependency_plan_matches(bundle,s,self.root,batch,self.r,packet,self.root))
        # Same exact approved request with fixed references relative to the new
        # run root; no front-computer path is needed after receiving the package.
        portable=json.loads((self.root/plan['path']).read_text(encoding='utf-8'))
        row=portable['inputs'][0];row['reference_path_basis']='run_root'
        for i,token in enumerate(row['arguments']['referenced_image_paths']):
            if token.startswith('@DEPENDENCY:'):
                row['reference_files'][i]={'path':token};continue
            relative=Path(token).resolve().relative_to(self.root.resolve()).as_posix()
            row['arguments']['referenced_image_paths'][i]=relative
            row['reference_files'][i]['path']=relative
        bundle={'dependency_completion_plan':self.h.h.f.write('portable-dependency-plan.json',portable)}
        self.assertTrue(dependency_plan_matches(bundle,s,self.root,batch,self.r,packet,self.root))
        p["prompt"]+="\nSYNTHETIC unauthorized composition change"
        (self.root/p.get("prompt_file","P001/prompt.txt")).write_text(p["prompt"], encoding='utf-8', newline='\n')
        self.assertFalse(dependency_plan_matches(bundle,s,self.root,batch,self.r,packet,self.root))


if __name__=="__main__":unittest.main()
