# Adapted from Z.ai ZCode, Apache-2.0. See third_party/zcode/NOTICE.md.
from __future__ import annotations

from dataclasses import dataclass
import time
import uuid


TRANSITIONS = {
    "idle": {"processing_input"},
    "processing_input": {"awaiting_model_response", "completing"},
    "awaiting_model_response": {"streaming", "completing", "error"},
    "streaming": {"scheduling_tools", "aggregating_results", "completing", "error"},
    "scheduling_tools": {"executing_tools", "awaiting_permission", "error"},
    "executing_tools": {"aggregating_results", "awaiting_permission", "error"},
    "aggregating_results": {"awaiting_model_response", "scheduling_tools", "completing", "error"},
    "awaiting_permission": {"executing_tools", "error"},
    "completing": {"idle"},
    "error": {"idle"},
}


@dataclass(frozen=True)
class Capability:
    read_only: bool = False
    destructive: bool = False
    scope: str = "system"
    needs_approval: bool = True


def permission(capability, *, plan=True):
    if capability is None:
        return "deny", "tool.unknown"
    if plan:
        if capability.read_only and not capability.destructive and capability.scope == "none" and not capability.needs_approval:
            return "allow", "mode.plan.readOnly"
        return "deny", "mode.plan.nonReadOnly"
    if capability.read_only and not capability.destructive and not capability.needs_approval:
        return "allow", "mode.build.readOnly"
    return "ask", "mode.build.sideEffect"


class TurnMachine:
    def __init__(self, session_id, emit):
        self.trace_id = uuid.uuid4().hex
        self.turn_id = uuid.uuid4().hex
        self.session_id = session_id
        self.phase = "idle"
        self.calls = {}
        self.emit = emit

    def event(self, name, **details):
        self.emit(name, trace_id=self.trace_id, turn_id=self.turn_id, phase=self.phase, **details)

    def transition(self, phase):
        if phase not in TRANSITIONS[self.phase]:
            raise ValueError(f"Invalid ZCode turn transition: {self.phase} -> {phase}")
        previous = self.phase
        self.phase = phase
        self.event("agent_phase", previous=previous)

    def schedule(self, calls):
        self.transition("scheduling_tools")
        self.calls = {uuid.uuid4().hex: dict(name=c["tool"], args=c["args"], status="scheduled") for c in calls}

    def execute(self, registry):
        self.transition("executing_tools")
        results = []
        for call_id, call in self.calls.items():
            entry = registry.get(call["name"])
            decision, rule = permission(entry[0] if entry else None)
            self.event("agent_permission", call_id=call_id, tool=call["name"], decision=decision, rule=rule)
            started = time.monotonic()
            if decision != "allow":
                result = {"ok": False, "error": "tool_not_permitted"}
                call["status"] = "permission_denied"
            else:
                call["status"] = "running"
                self.event("agent_tool_started", call_id=call_id, tool=call["name"], arguments=call["args"])
                try:
                    result = {"ok": True, "data": entry[1](**call["args"])}
                    call["status"] = "completed"
                except (ValueError, TypeError, OSError) as exc:
                    result = {"ok": False, "error": type(exc).__name__}
                    call["status"] = "failed"
            self.event("agent_tool_completed", call_id=call_id, tool=call["name"], result=result,
                       elapsed_ms=round((time.monotonic()-started)*1000))
            results.append({"call_id": call_id, "tool": call["name"], **result})
        self.transition("aggregating_results")
        return results

    def fail(self, reason):
        self.phase = "error"
        self.event("agent_failed", reason=reason)
