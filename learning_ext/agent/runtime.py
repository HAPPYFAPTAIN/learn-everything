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
from typing import Iterator

from learning_ext.agent.tools import (
    build_tool_specs,
    execute_tool,
    tool_needs_approval,
)

logger = logging.getLogger(__name__)

MAX_STEPS = 12

SYSTEM_PROMPT = """你是「动手学」的陪练教练，跑在用户自己的 Windows 电脑上，可以直接操作这台电脑：看当前窗口、读界面控件、点鼠标、敲键盘、启动程序、跑命令、读写文件。

你的价值不是替用户点完了事，而是「边做边教」：让用户看着你怎么做，知道下一步该点什么。

每轮都按这个顺序：
1. 先看。动手前调 observe_screen（必要时 read_ui / list_windows），别凭空猜用户屏幕上开着什么。
2. 先给步骤。用 update_plan 推一份 3~6 步的清单，每步一句话、是他能照着做的动作。
3. 逐步执行。每次只做一步：先用一句话说「我来做：…」，再调工具；做完看结果，用 update_plan 把 index 推到下一步。
4. 边做边讲。每步结尾告诉他这一步在界面上的哪里、为什么这么点，让他下次能自己做。
5. 用户自己动手时，你说清楚「点哪个位置、看到什么算成功」，等他说好了再继续。

硬性要求：
- 看不到画面像素。屏幕上的信息只能来自 observe_screen / read_ui / 命令输出，不要编造你没读到的东西。
- 点按钮前先 read_ui 拿坐标，别盲点。
- 删除、覆盖、改系统设置这类操作，先说清后果。
- 用户拒绝你的操作时，别硬来，改成口头教他点哪里。
- 中文，短句。每步不超过 3 行，命令放 ``` 里。不要说客套话，结尾直接给下一步。
"""

_FAIL_MARKS = ("已拒绝", "执行出错", "未知工具", "MCP 调用失败", "参数不匹配", "写入失败", "读取系统信息失败")


class Session:
    """一轮会话。单机单用户，页面自己持有一个实例即可。"""

    def __init__(self) -> None:
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.auto = False
        self.pending: list[dict] | None = None
        # 当前展示在界面上的步骤清单：{"steps": [...], "index": int}
        self.plan: dict | None = None

    # -- 便捷方法 -------------------------------------------------
    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.pending = None
        self.plan = None

    def compact(self, keep: int = 16) -> None:
        """历史太长时丢掉中间的工具往返，只保留 system 与最近若干条。"""
        if len(self.messages) <= keep + 1:
            return
        head, tail = self.messages[0], self.messages[-keep:]
        # 截断后首条不能是 tool（必须有对应的 assistant tool_calls）
        while tail and tail[0].get("role") == "tool":
            tail = tail[1:]
        self.messages = [head] + tail


def _client():
    from learning_ext.llm.client import _get_client

    return _get_client()


def _model_stream(session: Session) -> Iterator[dict]:
    """请求一次模型，流式产出 delta，返回 (text, calls)。

    代理/上游偶发抽风时，只要还没吐出任何字就整轮重来（最多 2 次）。
    """
    from learning_ext.llm.client import _load_config, _transient, friendly_error

    client, cfg = _client()
    text = ""
    slots: dict[int, dict] = {}
    attempt = 0
    while True:
        emitted = False
        try:
            stream = client.chat.completions.create(
                model=cfg["chat_model"],
                messages=session.messages,
                tools=build_tool_specs(),
                tool_choice="auto",
                temperature=0.3,
                stream=True,
            )
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
                parsed = {}
        except json.JSONDecodeError:
            parsed = {}
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
    session.messages.append(message)
    return text, calls


def _execute(session: Session, calls: list[dict]) -> Iterator[dict]:
    for call in calls:
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
        text, calls = yield from _model_stream(session)
        if not calls:
            return
        if not session.auto and any(tool_needs_approval(c["name"]) for c in calls):
            session.pending = calls
            yield {"kind": "need_approval", "calls": calls}
            return
        yield from _execute(session, calls)
    yield {"kind": "notice", "text": f"已连续执行 {MAX_STEPS} 步，先停一下。要继续就说一声。"}


def run(session: Session, text: str | None) -> Iterator[dict]:
    if text:
        session.messages.append({"role": "user", "content": text})
    session.compact()
    yield from _drive(session)


def approve(session: Session, allow: bool) -> Iterator[dict]:
    calls = session.pending or []
    session.pending = None
    if not calls:
        yield {"kind": "notice", "text": "没有待确认的操作。"}
        return
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
    yield from _drive(session)
