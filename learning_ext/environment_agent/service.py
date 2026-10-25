from __future__ import annotations

import json
import time
import re

from learning_ext.agent.zcode_core import TurnMachine
from learning_ext.llm import chat_json
from learning_ext.practice.environment import inspect_environment, TOOLS
from .discovery import Discovery, system_info
from .prompts import EXPLORE


def explore_environment(context, *, planner=None, emit=None, session_id="", discovery=None):
    planner = planner or chat_json
    emit = emit or (lambda *args, **kwargs: None)
    text = "\n".join(str(context.get(key, "")) for key in ("course", "topic", "goal", "background", "lesson", "practice")) if isinstance(context, dict) else str(context)
    report = inspect_environment(text)
    report.update(system=system_info(), engine="zcode-core-python", complete=False, summary="", scope="本机只读检查")
    machine = TurnMachine(session_id, emit)
    report["trace_id"] = machine.trace_id
    machine.transition("processing_input")
    discovery = discovery or Discovery()
    history, seen = [], set()
    started = time.monotonic()
    try:
        for round_number in range(4):
            if time.monotonic() - started > 90:
                report["stop_reason"] = "time_budget"
                break
            machine.transition("awaiting_model_response")
            prompt = {"task": text[:18000], "system": report["system"], "evidence": report["items"],
                      "tools": discovery.descriptions(), "history": history, "remaining_rounds": 4-round_number}
            result = planner(json.dumps(prompt, ensure_ascii=False), system=EXPLORE)
            machine.transition("streaming")
            if not isinstance(result, dict) or not isinstance(result.get("calls"), list):
                raise ValueError("invalid_exploration_response")
            calls = result["calls"]
            if not calls:
                report["complete"] = True
                report["summary"] = str(result.get("summary", ""))[:300]
                machine.transition("completing")
                break
            if len(calls) > 3:
                raise ValueError("too_many_tool_calls")
            batch = []
            for call in calls:
                if not isinstance(call, dict) or not isinstance(call.get("tool"), str) or not isinstance(call.get("args"), dict):
                    raise ValueError("invalid_tool_request")
                if len(json.dumps(call, ensure_ascii=False)) > 1500:
                    raise ValueError("tool_request_too_large")
                signature = json.dumps(call, sort_keys=True, ensure_ascii=False)
                if signature not in seen:
                    seen.add(signature)
                    batch.append(call)
            if not batch:
                report["stop_reason"] = "repeated_queries"
                machine.transition("completing")
                break
            machine.schedule(batch)
            results = machine.execute(discovery.registry())
            history.append({"calls": batch, "results": results})
            if any(not item["ok"] for item in results):
                report["stop_reason"] = "tool_failed_or_denied"
                machine.transition("completing")
                break
        else:
            report["stop_reason"] = "round_budget"
        if machine.phase not in {"completing", "error"}:
            machine.transition("completing")
    except Exception as exc:
        report["stop_reason"] = type(exc).__name__
        machine.fail(type(exc).__name__)
    by_key = {item["key"]: item for item in report["items"]}
    for item in discovery.evidence:
        alias = next((key for key, (_, pattern, _) in TOOLS.items() if key in by_key and re.search(pattern, item["name"], re.I)), None)
        if alias and item["key"].startswith("candidate:"):
            old = by_key[alias]
            if not old.get("spec") and old["status"] in {"unknown", "missing"} and item["status"] == "present":
                by_key[alias] = {**old, **item, "key": alias, "name": old["name"]}
            continue
        if item["key"] not in by_key or not by_key[item["key"]].get("spec"):
            by_key[item["key"]] = item
    report["items"] = list(by_key.values())
    if not report["complete"]:
        report["summary"] = "已保留本次确认的环境信息，其余条件仍需在对应步骤确认。"
    emit("environment_exploration_completed", trace_id=machine.trace_id, report=report)
    return report


def audited_exploration(context, *, planner=None):
    from learning_ext.action_learning.service import Journal
    import uuid
    state = {"id": uuid.uuid4().hex, "node": None, "index": -1}
    journal = Journal()
    return explore_environment(context, planner=planner, session_id=state["id"],
                               emit=lambda event, **details: journal.record(state, event, **details))
