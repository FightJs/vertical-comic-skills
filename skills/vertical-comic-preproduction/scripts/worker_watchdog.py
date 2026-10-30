#!/usr/bin/env python3
"""Read-only, evidence-driven advice for slow comic episode workers.

The coordinator owns messages and dispatch. This module never grants approval,
retries a request, changes a permit, or changes an episode's owner.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from platform_io import file_lock, atomic_json
import hashlib
import json
import os
from pathlib import Path
import tempfile

POLICY = "worker_watchdog_v1"
DEFAULTS = {
    "policy": POLICY,
    "preparation_warning_seconds": 300,
    "preparation_escalation_seconds": 720,
    "review_warning_seconds": 300,
    "review_escalation_seconds": 720,
    "request_warning_seconds": 900,
    "request_escalation_seconds": 1800,
}
HUMAN_WAITS = {"HUMAN_A", "HUMAN_B", "HUMAN_PACKAGE", "HUMAN_C", "HUMAN_D", "HUMAN_STATE"}
CROSS_WAIT = "CROSS_EPISODE"
VALID_STAGES = {"input_audit", "visual_assets", "shot_design", "package", "generation", "image_review", "repair", "delivery"}
PREPARATION_STAGES = {"input_audit", "visual_assets", "shot_design", "package"}
PROGRESS_KINDS = {"stage_started", "audit_saved", "asset_saved", "shot_saved", "package_saved",
                  "request_submitted", "request_returned", "image_saved", "qa_saved", "diagnosis_saved", "episode_review_saved"}
PROGRESS_STAGE = {
    "audit_saved": {"input_audit"}, "asset_saved": {"visual_assets"},
    "shot_saved": {"shot_design"}, "package_saved": {"package"},
    "request_submitted": {"generation", "repair"}, "image_saved": {"generation", "repair"},
    "request_returned": {"generation", "repair"},
    "qa_saved": {"image_review"}, "diagnosis_saved": {"image_review", "repair"},
    "episode_review_saved": {"delivery"},
}


def settings(value):
    if not isinstance(value, dict) or value.get("policy") != POLICY:
        raise ValueError("watchdog.policy须为worker_watchdog_v1")
    if set(value) != set(DEFAULTS):
        raise ValueError("watchdog须完整填写六项阈值，不能静默省略")
    for prefix in ("preparation", "review", "request"):
        warning = value[f"{prefix}_warning_seconds"]
        escalation = value[f"{prefix}_escalation_seconds"]
        if type(warning) is not int or type(escalation) is not int or warning < 1 or escalation <= warning:
            raise ValueError(f"{prefix}阈值须为正整数且第二阈值大于第一阈值")
    return value


def _time(value):
    if not isinstance(value, str) or not value:
        raise ValueError("监控时间须为含时区的ISO时间")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("监控时间须含时区")
    return result.astimezone(timezone.utc)


def evaluate(snapshot, *, now=None, config=None):
    """Return only new T1/T2 alerts; caller persists emitted IDs after delivery."""
    config = settings(config or dict(DEFAULTS))
    if not isinstance(snapshot, dict) or snapshot.get("stage") not in VALID_STAGES:
        raise ValueError("监控快照须有真实当前阶段")
    current = _time(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    if current.tzinfo is None:
        raise ValueError("当前时间须含时区")
    current = current.astimezone(timezone.utc)
    wait_kind = snapshot.get("wait_kind", "NONE")
    if wait_kind not in HUMAN_WAITS | {"NONE", CROSS_WAIT, "SERVICE", "DEPENDENCY"}:
        raise ValueError("未知等待类型")
    requests = snapshot.get("requests", [])
    if not isinstance(requests, list):
        raise ValueError("requests须为清单")
    emitted = snapshot.get("emitted", [])
    if not isinstance(emitted, list) or any(not isinstance(v, str) for v in emitted):
        raise ValueError("emitted须为已实际送达的事件ID清单")
    emitted = set(emitted)
    alerts = dispatch_alerts(snapshot.get('pipeline_rows',[]),free_channels=snapshot.get('free_channels',0),
                             paused=snapshot.get('paused',False),now=current,emitted=emitted)
    lifecycle=snapshot.get('executor_lifecycle')
    if lifecycle is not None:
        if (not isinstance(lifecycle,dict) or lifecycle.get('state') not in {'ALIVE','TERMINATED','UNKNOWN'}
                or not lifecycle.get('executor_id') or not lifecycle.get('source_locator')):
            raise ValueError('EXECUTOR_LIFECYCLE_REQUIRES_HOST_RECEIPT')
        if lifecycle['state']=='TERMINATED':
            event_id='executor:'+str(lifecycle['executor_id'])+':terminated:'+str(lifecycle.get('event_id','terminal'))
            if event_id not in emitted:
                alerts.append({'event_id':event_id,'level':'T2','kind':'EXECUTOR_TERMINATED',
                    'action':'RECONCILE_CAPTURED_RETURNS_AND_REMOTE_OUTCOMES',
                    'source_locator':lifecycle['source_locator']})
            return {'policy':POLICY,'state':'EXECUTOR_TERMINATED','alerts':alerts,
                    'active_attempt_ids':[r.get('attempt_id') for r in requests if r.get('status') in {'IN_FLIGHT','RESULT_UNKNOWN'}],
                    'recommendation':'RECONCILE_ONCE_DO_NOT_ASSUME_NO_IMAGE'}
    active_requests = []
    for request in requests:
        if not isinstance(request, dict) or not request.get("attempt_id") or not request.get("panel_id"):
            raise ValueError("在途请求须有格号和attempt_id")
        if request.get("status") not in {"IN_FLIGHT", "RESULT_UNKNOWN", "RETURNED"}:
            raise ValueError("监控请求状态无效")
        if request["status"] != "IN_FLIGHT":
            continue
        start = _time(request.get("submitted_at"))
        if start > current:
            raise ValueError("请求时间不能晚于当前时间")
        active_requests.append(request["attempt_id"])
        age = (current - start).total_seconds()
        key = f"request:{request['panel_id']}:{request['attempt_id']}"
        for level, seconds in (("T1", config["request_warning_seconds"]), ("T2", config["request_escalation_seconds"])):
            event_id = f"{key}:{level}"
            if age >= seconds and event_id not in emitted:
                alerts.append({"event_id": event_id, "level": level, "kind": "REQUEST_IN_FLIGHT",
                               "age_seconds": int(age), "panel_id": request["panel_id"],
                               "action": "CHECK_STATUS_AND_PREPARE_OTHER_WORK" if level == "T1" else "HOLD_DUPLICATE_RETRY_AND_ESCALATE_SERVICE_DIAGNOSIS"})
    if wait_kind in HUMAN_WAITS:
        return {"policy": POLICY, "state": "WAIT_HUMAN", "alerts": alerts,
                "active_attempt_ids": active_requests, "recommendation": "WAIT_FOR_ACTUAL_APPROVAL"}
    if wait_kind == CROSS_WAIT:
        return {"policy": POLICY, "state": "LOCAL_HANDOFF_READY" if snapshot.get("local_episode_complete") is True else "WAIT_CROSS_EPISODE",
                "alerts": alerts, "active_attempt_ids": active_requests,
                "recommendation": "HAND_OFF_LOCAL_RESULT_TO_COORDINATOR" if snapshot.get("local_episode_complete") is True else "CONTINUE_INDEPENDENT_WORK"}
    progress = _time(snapshot.get("last_progress_at"))
    if progress > current:
        raise ValueError("进展时间不能晚于当前时间")
    blocker = snapshot.get("blocker_id")
    if not isinstance(blocker, str) or not blocker:
        raise ValueError("blocker_id须绑定具体阶段/问题，供跨恢复去重")
    age = (current - progress).total_seconds()
    group = "preparation" if snapshot["stage"] in PREPARATION_STAGES else "review"
    # In-flight image requests have their own clock. Other eligible work may proceed.
    if snapshot["stage"] == "generation" and active_requests and not snapshot.get("independent_work_pending"):
        return {"policy": POLICY, "state": "REQUESTS_IN_FLIGHT", "alerts": alerts,
                "active_attempt_ids": active_requests, "recommendation": "KEEP_ORIGINAL_REQUESTS_ALIVE"}
    for level, seconds in (("T1", config[f"{group}_warning_seconds"]), ("T2", config[f"{group}_escalation_seconds"])):
        event_id = f"stage:{snapshot['stage']}:{blocker}:{level}"
        if age >= seconds and event_id not in emitted:
            alerts.append({"event_id": event_id, "level": level, "kind": "WORKER_IDLE", "age_seconds": int(age),
                           "action": "PROMPT_NEXT_CONCRETE_STEP" if level == "T1" else "DIAGNOSE_AND_CONTINUE_ONLY_ELIGIBLE_WORK"})
    return {"policy": POLICY, "state": "ESCALATE" if any(a["level"] == "T2" for a in alerts) else "OBSERVE",
            "alerts": alerts, "active_attempt_ids": active_requests,
            "recommendation": "CHECK_REAL_GATES_BEFORE_DISPATCH_OR_HANDOFF"}



def dispatch_alerts(rows, *, free_channels=0, paused=False, now=None, emitted=()):
    """Observed pipeline delays, separate from the active production budget.

    This does not cancel calls, recover permits or infer an unknown outcome.
    Excluded waiting seconds must come from the run's clock, never estimates.
    """
    if paused:return []
    current=_time(now) if isinstance(now,str) else (now or datetime.now(timezone.utc))
    result=[]
    for row in rows:
        if row.get('saved_at') or not row.get('attempt_id'):continue
        if row.get('native_completed_at'):
            field,threshold,kind,action='native_completed_at',30,'RETURN_NOT_SAVED','COLLECT_AND_SAVE_EXISTING_RETURN'
        elif row.get('invocation_requested_at'):
            field,threshold,kind,action='invocation_requested_at',300,'LONG_INVOCATION','CHECK_ACTUAL_STATUS_AND_COLLECT_RETURNS'
        elif row.get('registered_at'):
            field,threshold,kind,action='registered_at',60,'REGISTERED_NOT_OBSERVED','RECONCILE_INVOCATION_WITHOUT_RETRY'
        elif row.get('ready_at') and free_channels>0:
            field,threshold,kind,action='ready_at',60,'READY_NOT_DISPATCHED','DISPATCH_ELIGIBLE_PANEL_OR_RECORD_BLOCKER'
        else:continue
        excluded=row.get('excluded_wait_seconds',{}).get(field,0)
        if not isinstance(excluded,(int,float)) or excluded<0:raise ValueError('Invalid excluded waiting interval')
        age=(current-_time(row[field])).total_seconds()-excluded
        level='T2' if kind=='LONG_INVOCATION' and age>=600 else 'T1'
        if level=='T2':action='ISOLATE_SLOW_CHANNEL_CONTINUE_AVAILABLE_CHANNELS'
        event_id=f"dispatch:{row.get('panel_id')}:{row['attempt_id']}:{kind}:{level}"
        if age>=threshold and event_id not in emitted:
            result.append({'event_id':event_id,'panel_id':row.get('panel_id'),'attempt_id':row['attempt_id'],
                'kind':kind,'level':level,'age_seconds':int(age),'action':action,'retry_allowed':False})
    return result

def _write_atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)


def record_progress(ledger_path, episode_root, event, *, now=None):
    """Persist one changed, hashed artifact; duplicate evidence cannot reset idle time."""
    ledger_path = Path(ledger_path).resolve()
    root = Path(episode_root).resolve()
    if not isinstance(event, dict) or event.get("stage") not in VALID_STAGES or event.get("kind") not in PROGRESS_KINDS:
        raise ValueError("进展事件须有有效阶段和实际事件类型")
    if event["kind"] in PROGRESS_STAGE and event["stage"] not in PROGRESS_STAGE[event["kind"]]:
        raise ValueError("进展事件类型不属于当前阶段")
    if not isinstance(event.get("blocker_id"), str) or not event["blocker_id"]:
        raise ValueError("进展事件须指定具体blocker_id")
    wait_kind = event.get("wait_kind", "NONE")
    if wait_kind not in HUMAN_WAITS | {"NONE", CROSS_WAIT, "SERVICE", "DEPENDENCY"}:
        raise ValueError("未知等待类型")
    evidence = event.get("evidence")
    if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str) or not isinstance(evidence.get("sha256"), str):
        raise ValueError("进展须绑定实际文件路径和哈希")
    relative = Path(evidence["path"])
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root) or not path.is_file():
        raise ValueError("进展证据须在本话目录内且真实存在")
    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != evidence["sha256"]:
        raise ValueError("进展证据哈希不符")
    current = _time(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    key = f"{event['stage']}:{event['kind']}:{relative}:{actual_hash}"
    with file_lock(ledger_path.with_suffix(".lock")) as lock:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {"policy": POLICY, "events": [], "emitted": []}
        if ledger.get("policy") != POLICY:
            raise ValueError("监控进度账本版本不一致")
        if key in {item["key"] for item in ledger["events"]}:
            return {"status": "DUPLICATE_EVIDENCE", "last_progress_at": ledger["events"][-1]["at"]}
        ledger["events"].append({"key": key, "stage": event["stage"], "kind": event["kind"],
                                 "blocker_id": event["blocker_id"], "wait_kind": wait_kind,
                                 "local_episode_complete": event.get("local_episode_complete") is True,
                                 "evidence": evidence, "at": current.isoformat()})
        _write_atomic(ledger_path, ledger)
        return {"status": "PROGRESS_RECORDED", "last_progress_at": ledger["events"][-1]["at"]}


def check_ledger(ledger_path, episode_state, *, now=None, config=None, independent_work_pending=False):
    ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    if ledger.get("policy") != POLICY or not ledger.get("events"):
        raise ValueError("先登记实际阶段起点或进展")
    latest = ledger["events"][-1]
    requests = [{"panel_id": row["panel_id"], "attempt_id": row["attempt_id"],
                 "submitted_at": row["submitted_at"], "status": "IN_FLIGHT"}
                for row in episode_state.get("panels", []) if row.get("status") == "IN_FLIGHT"]
    snapshot = {"stage": latest["stage"], "last_progress_at": latest["at"],
                "blocker_id": latest["blocker_id"], "wait_kind": latest["wait_kind"],
                "local_episode_complete": latest["local_episode_complete"],
                "requests": requests, "emitted": ledger.get("emitted", []),
                "pipeline_rows":[r for r in episode_state.get("panels",[]) if r.get("invocation_events")],
                "paused":latest["wait_kind"] in HUMAN_WAITS,
                "independent_work_pending": independent_work_pending}
    result = evaluate(snapshot, now=now, config=config)
    current = _time(now) if isinstance(now, str) else (now or datetime.now(timezone.utc))
    same_stage = []
    for event in reversed(ledger["events"]):
        if event["stage"] != latest["stage"]:
            break
        same_stage.append(event)
    result["stage_elapsed_seconds"] = int((current - _time(same_stage[-1]["at"])).total_seconds())
    result["idle_seconds"] = int((current - _time(latest["at"])).total_seconds())
    result["stage_elapsed_is_advisory"] = True
    return result


def acknowledge(ledger_path, episode_state, event_ids, *, now=None, config=None, independent_work_pending=False):
    """Call only after coordinator has delivered the listed actual alerts."""
    if not isinstance(event_ids, list) or not event_ids or len(event_ids) != len(set(event_ids)):
        raise ValueError("须确认不重复的已送达事件ID")
    ledger_path = Path(ledger_path).resolve()
    with file_lock(ledger_path.with_suffix(".lock")) as lock:
        current = check_ledger(ledger_path, episode_state, now=now, config=config,
                               independent_work_pending=independent_work_pending)
        allowed = {a["event_id"] for a in current["alerts"]}
        if not set(event_ids) <= allowed:
            raise ValueError("只能确认本次实际触发、尚未确认的提示")
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger["emitted"].extend(event_ids)
        _write_atomic(ledger_path, ledger)
    return {"status": "ALERTS_ACKNOWLEDGED", "event_ids": event_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--config", help="完整watchdog对象JSON；省略时用默认阈值")
    parser.add_argument("--now", help="仅用于离线回放与测试的ISO时间")
    args = parser.parse_args()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else None
    print(json.dumps(evaluate(snapshot, now=args.now, config=config), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    from platform_io import configure_stdio
    configure_stdio()
    main()
