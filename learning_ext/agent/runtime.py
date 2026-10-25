"""动手学的对话运行时：流式输出 + 工具调用循环 + 审批暂停。

对外只暴露三样东西：
    Session()          一轮会话的状态（messages / auto / pending）
    run(session, text) 发起一轮，产出事件流
    approve(session, allow) 对暂停中的调用做决定，继续产出事件流

事件（dict，kind 字段区分）：
    step          新的一次模型请求开始
    delta         助手文本增量（text 为累计文本）
    tool_start    开始执行某个工具
    tool_end      某个工具结束（output / ms / ok / denied）
    need_approval 有工具需要用户确认（calls 列表），本轮暂停
    notice        提示信息
    error         出错
"""

from __future__ import annotations

import json
import logging
import time
import hashlib
import uuid
from typing import Iterator

from learning_ext.agent.tools import (
    build_tool_specs,
    execute_tool,
    tool_needs_approval,
)
from learning_ext.agent.prompts import DESKTOP_COACH
from learning_ext.agent.zcode_core import TurnMachine

logger = logging.getLogger(__name__)

MAX_STEPS = 12

SYSTEM_PROMPT = DESKTOP_COACH

_FAIL_MARKS = ("已拒绝", "执行出错", "未知工具", "MCP 调用失败", "参数不匹配", "写入失败", "读取系统信息失败")


class Session:
    """一轮会话。单机单用户，页面自己持有一个实例即可。"""

    def __init__(self) -> None:
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.auto = False
        self.pending: list[dict] | None = None
        # 当前展示在界面上的步骤清单：{"steps": [...], "index": int}
        self.plan: dict | None = None
        self.id = uuid.uuid4().hex
        self.machine = None
        self.pending_digest = None
        self.pending_payload = ""
        self.pending_at = 0
        self.task = None

    def record(self, event, **details):
        from learning_ext.action_learning.service import Journal
        if self.machine:
            details.setdefault("trace_id", self.machine.trace_id)
            details.setdefault("turn_id", self.machine.turn_id)
        Journal().record({"id": self.id, "node": None, "index": (self.plan or {}).get("index", 0)}, event, **details)

    def begin(self):
        self.machine = TurnMachine(self.id, self.record)
        self.machine.transition("processing_input")

    # -- 便捷方法 -------------------------------------------------
    def reset(self) -> None:
        self.record("agent_reset")
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.pending = None
        self.plan = None
        self.machine = None
        self.pending_digest = None
        self.pending_payload = ""
        self.task = None
        self.auto = False

    def compact(self, keep: int = 16) -> None:
        """历史太长时丢掉中间的工具往返，只保留 system 与最近若干条。"""
        if len(self.messages) <= keep + 1:
            return
        head, tail = self.messages[0], self.messages[-keep:]
        # 截断后首条不能是 tool（必须有对应的 assistant tool_calls）
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        self.messages = [head] + ([self.task] if self.task and self.task not in tail else []) + tail


def _model_stream(session: Session) -> Iterator[dict]:
    """请求一次模型，流式产出 delta，返回 (text, calls)。

    代理/上游偶发抽风时，只要还没吐出任何字就整轮重来（最多 2 次）。
    """
    from learning_ext.llm.client import _transient, friendly_error

    from learning_ext.llm.client import stream_tool_response
    text = ""
    slots: dict[int, dict] = {}
    attempt = 0
    while True:
        emitted = False
        try:
            stream = stream_tool_response(session.messages, build_tool_specs())
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue
                piece = getattr(delta, "content", None)
                if piece:
                    text += piece
                    emitted = True
                    yield {"kind": "delta", "text": text}
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = slots.setdefault(
                        getattr(tc, "index", 0) or 0, {"id": "", "name": "", "arguments": ""}
                    )
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        slot["name"] += getattr(fn, "name", None) or ""
                        slot["arguments"] += getattr(fn, "arguments", None) or ""
            break
        except Exception as exc:  # noqa: BLE001
            if emitted or attempt >= 2 or not _transient(exc):
                logger.exception("模型调用失败")
                if session.machine:
                    session.machine.fail(type(exc).__name__)
                yield {"kind": "error", "message": friendly_error(exc)}
                return "", []
            wait = 1.2 * (attempt + 1)
            logger.warning("模型流式失败(%s)，%.1fs 后重试：%s", type(exc).__name__, wait, exc)
            time.sleep(wait)
            attempt += 1
            text = ""
            slots = {}

    calls: list[dict] = []
    for index in sorted(slots):
        slot = slots[index]
        raw = slot["arguments"].strip() or "{}"
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Tool arguments must be an object")
        except json.JSONDecodeError:
            session.record("agent_invalid_arguments", tool=slot["name"])
            yield {"kind": "error", "message": "工具参数不完整，本轮没有执行操作。请重试。"}
            return "", []
        except ValueError:
            session.record("agent_invalid_arguments", tool=slot["name"])
            yield {"kind": "error", "message": "工具参数格式无效，本轮没有执行操作。"}
            return "", []
        calls.append(
            {
                "id": slot["id"] or f"call_{index}",
                "name": slot["name"],
                "args": parsed,
                "raw": raw,
            }
        )

    message: dict = {"role": "assistant", "content": text}
    if calls:
        message["tool_calls"] = [
            {
                "id": c["id"],
                "type": "function",
                "function": {"name": c["name"], "arguments": c["raw"]},
            }
            for c in calls
        ]
    if text or calls:
        session.messages.append(message)
    return text, calls


def _execute(session: Session, calls: list[dict]) -> Iterator[dict]:
    for call in calls:
        session.record("agent_tool_started", call_id=call["id"], tool=call["name"], arguments=call["args"])
        # 步骤清单不走工具执行器，直接改成界面事件
        if call["name"] == "update_plan":
            steps = [str(s) for s in (call["args"].get("steps") or []) if str(s).strip()]
            try:
                index = int(call["args"].get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            index = max(0, min(index, len(steps)))
            if steps:
                session.plan = {"steps": steps, "index": index}
            session.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": f"步骤清单已显示给用户（共 {len(steps)} 步，当前第 {index + 1} 步）。",
                }
            )
            yield {"kind": "plan", "steps": steps, "index": index}
            session.record("agent_plan_updated", count=len(steps), index=index)
            continue

        yield {
            "kind": "tool_start",
            "call_id": call["id"],
            "name": call["name"],
            "args": call["args"],
        }
        started = time.time()
        output = execute_tool(call["name"], call["args"])
        output = output or "（无输出）"
        spent = int((time.time() - started) * 1000)
        session.record("agent_tool_completed", call_id=call["id"], tool=call["name"], elapsed_ms=spent,
                       ok=not output.startswith(_FAIL_MARKS), output=output[:8000])
        session.messages.append(
            {"role": "tool", "tool_call_id": call["id"], "content": output[:8000]}
        )
        yield {
            "kind": "tool_end",
            "call_id": call["id"],
            "name": call["name"],
            "args": call["args"],
            "output": output,
            "ms": spent,
            "ok": not output.startswith(_FAIL_MARKS),
        }


def _drive(session: Session) -> Iterator[dict]:
    for _ in range(MAX_STEPS):
        if session.pending:
            yield {"kind": "need_approval", "calls": session.pending}
            return
        yield {"kind": "step"}
        session.machine.transition("awaiting_model_response")
        text, calls = yield from _model_stream(session)
        if session.machine.phase == "error":
            return
        session.machine.transition("streaming")
        if not calls:
            session.machine.transition("completing")
            return
        session.machine.transition("scheduling_tools")
        if sum(tool_needs_approval(c["name"]) for c in calls) > 1:
            session.record("agent_batch_denied", reason="one_action_at_a_time", count=len(calls))
            for call in calls:
                session.messages.append({"role": "tool", "tool_call_id": call["id"], "content": "未执行：每次只请求一个需要授权的动作。"})
            session.machine.transition("executing_tools")
            session.machine.transition("aggregating_results")
            session.machine.transition("completing")
            yield {"kind": "notice", "text": "这次包含多个操作，尚未执行。请先确认当前的一步。"}
            return
        if any(tool_needs_approval(c["name"]) for c in calls):
            session.pending = calls
            session.pending_at = time.monotonic()
            session.pending_digest = _digest(calls)
            session.pending_payload = json.dumps(calls, ensure_ascii=False)
            session.machine.transition("awaiting_permission")
            session.record("agent_approval_requested", calls=calls)
            yield {"kind": "need_approval", "calls": calls}
            return
        session.machine.transition("executing_tools")
        yield from _execute(session, calls)
        session.machine.transition("aggregating_results")
    session.machine.transition("completing")
    yield {"kind": "notice", "text": f"已连续执行 {MAX_STEPS} 步，先停一下。要继续就说一声。"}


def run(session: Session, text: str | None) -> Iterator[dict]:
    if session.pending:
        yield {"kind": "notice", "text": "还有操作等待确认，请先允许或拒绝。"}
        return
    if text:
        message = {"role": "user", "content": text}
        session.messages.append(message)
        if session.task is None:
            session.task = message
    session.compact()
    session.begin()
    yield from _drive(session)


def _digest(calls):
    return hashlib.sha256(json.dumps(calls, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def approve(session: Session, allow: bool) -> Iterator[dict]:
    calls = session.pending or []
    session.pending = None
    if not calls:
        yield {"kind": "notice", "text": "没有待确认的操作。"}
        return
    valid = session.pending_digest == _digest(calls) and time.monotonic() - session.pending_at <= 90
    if not valid and session.pending_payload:
        calls = json.loads(session.pending_payload)
    session.pending_payload = ""
    session.pending_digest = None
    allow = bool(allow and valid)
    session.record("agent_approval_resolved", allowed=allow, valid=valid)
    session.machine.transition("executing_tools")
    if allow:
        yield from _execute(session, calls)
    else:
        for call in calls:
            session.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": "用户拒绝了这次操作，未执行。请换一种不需要该权限的方式，或先问清楚。",
                }
            )
            yield {
                "kind": "tool_end",
                "call_id": call["id"],
                "name": call["name"],
                "args": call["args"],
                "output": "你拒绝了这次操作，未执行。",
                "ms": 0,
                "ok": False,
                "denied": True,
            }
    session.machine.transition("aggregating_results")
    if not allow:
        session.machine.transition("completing")
        yield {"kind": "notice", "text": "本次操作未执行。你可以继续提问或亲自完成这一步。"}
        return
    yield from _drive(session)
