"""动手学：观察实际环境，逐步指导，并确认每一次操作。"""

from __future__ import annotations

import html
import json
import logging
import re
from functools import partial
from threading import Lock
import time

import gradio as gr
from ktem.app import BasePage

from learning_ext.agent import runtime
from learning_ext.agent.tools import tool_titles
from learning_ext.rich_text import render_rich_text

logger = logging.getLogger(__name__)

_PLACEHOLDER = "你想学会什么，或卡在哪一步？"
_SUGGESTIONS = {
    "env": "请结合我的学习目标，检查这台电脑已有的环境和工具；如果目标还不明确，先问清我要学什么。告诉我哪些可以直接使用、哪些还缺少，不安装或修改。",
    "files": "帮我寻找这台电脑上可用的软件或文件。先问清我想找什么，再搜索并说明结果，不自动打开或修改。",
    "window": "我在当前窗口遇到了问题。请先确认要看的窗口和我的目标，再观察界面、指出下一步的位置；先指导，操作前逐步让我确认。",
}

_KIND_TITLES = tool_titles()

_FENCE = re.compile(r"```([\w+#.-]*)[ \t]*\n(.*?)```", re.S)
_HEAD = re.compile(r"^(#{1,6})\s*(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")


def _inline(text: str) -> str:
    """行内格式：先转义，再处理 `code` / **粗** / *斜* / 链接。"""
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<i>\1</i>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" target="_blank" rel="noreferrer">\1</a>',
        text,
    )
    return text


def _table(rows: list[str]) -> str:
    """把 | a | b | 形式的表格行转成 HTML。"""

    def cells(row: str) -> list[str]:
        body = row.strip()
        if body.startswith("|"):
            body = body[1:]
        if body.endswith("|"):
            body = body[:-1]
        return [c.strip() for c in body.split("|")]

    if len(rows) < 2:
        return "<p>" + "<br>".join(_inline(r) for r in rows) + "</p>"
    header = cells(rows[0])
    separator = re.fullmatch(r"\|?[\s:|-]+\|?", rows[1] or "")
    body_rows = rows[2:] if separator else rows[1:]
    head_html = "".join(f"<th>{_inline(c)}</th>" for c in header)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells(r)) + "</tr>"
        for r in body_rows
    )
    return (
        '<div class="le-table-wrap"><table class="le-md-table">'
        f"<thead><tr>{head_html}</tr></thead><tbody>{body_html}</tbody></table></div>"
    )


def _markdown(src: str) -> str:
    """够用的迷你 markdown：代码块、标题、列表、引用、粗斜体、行内代码、链接。"""
    src = (src or "").replace("\r\n", "\n")
    fences: list[tuple[str, str]] = []

    def take(match: re.Match) -> str:
        fences.append((match.group(1), match.group(2)))
        return f"\n\u00a7{len(fences) - 1}\u00a7\n"

    src = _FENCE.sub(take, src)

    out: list[str] = []
    mode: str | None = None

    def close() -> None:
        nonlocal mode
        if mode:
            out.append(f"</{mode}>")
            mode = None

    lines = src.split("\n")
    index = 0
    while index < len(lines):
        raw = lines[index]
        index += 1
        line = raw.rstrip()
        if not line.strip():
            close()
            continue

        # 表格：连续的 | 开头行，第二行是 |---| 分隔
        if line.strip().startswith("|"):
            block = [line.strip()]
            while index < len(lines) and lines[index].strip().startswith("|"):
                block.append(lines[index].strip())
                index += 1
            close()
            out.append(_table(block))
            continue

        fence = re.fullmatch(r"\u00a7(\d+)\u00a7", line.strip())
        if fence and int(fence.group(1)) < len(fences):
            close()
            lang, body = fences[int(fence.group(1))]
            out.append(render_rich_text(f"```{lang}\n{body}\n```"))
            continue

        head = _HEAD.match(line)
        if head:
            close()
            size = {1: "h3", 2: "h3", 3: "h4"}.get(len(head.group(1)), "h5")
            out.append(f"<{size}>{_inline(head.group(2))}</{size}>")
            continue

        bullet = _BULLET.match(line)
        ordered = _ORDERED.match(line)
        if bullet or ordered:
            want = "ul" if bullet else "ol"
            if mode != want:
                close()
                out.append(f"<{want}>")
                mode = want
            out.append(f"<li>{_inline((bullet or ordered).group(1))}</li>")
            continue

        quote = _QUOTE.match(line)
        if quote:
            close()
            out.append(f"<blockquote>{_inline(quote.group(1))}</blockquote>")
            continue

        if line.strip() in ("---", "***"):
            close()
            out.append("<hr>")
            continue

        close()
        out.append(f"<p>{_inline(line)}</p>")

    close()
    return "\n".join(out)


def _args_preview(args: dict) -> str:
    """工具参数压成一行，方便一眼看出在干什么。"""
    if not args:
        return ""
    if "command" in args:
        text = str(args["command"])
    elif "path" in args:
        text = str(args["path"])
    elif "url" in args:
        text = str(args["url"])
    elif "root" in args:
        text = f'{args.get("root")} · {args.get("pattern", "")}'
    elif "text" in args:
        text = str(args["text"])[:80]
    else:
        text = " · ".join(f"{k}={v}" for k, v in list(args.items())[:3])
    text = " ".join(text.split())
    return text if len(text) <= 120 else text[:117] + "…"


class CoachPage(BasePage):
    def __init__(self, app):
        super().__init__(app)
        self.session = runtime.Session()
        from learning_ext.chat_connections import default_model_token
        self.session.model_selection = default_model_token()
        self.items: list[dict] = []
        self.typing = False
        self._tool_index: dict[str, int] = {}
        self._last_push = 0.0
        self._outputs: list = []
        self._busy = False
        self._turn_lock = Lock()
        self._render_cache: dict[str, tuple[tuple, str]] = {}
        self._sent_controls: dict[int, object] = {}
        self._frame_seq = 0
        self._question_selection = None
        self._selection_question = None

    # ------------------------------------------------------------ 渲染
    def _render_items(self) -> dict[str, str]:
        """Cache settled messages; only parse Markdown for content that changed."""
        parts: dict[str, str] = {}
        for index, item in enumerate(self.items):
            key = f"{self.session.id}-{index}"
            signature = (item.get("type"), item.get("text"), item.get("name"),
                         item.get("status"), item.get("output"), item.get("ms"),
                         item.get("call_id"), json.dumps(item.get("args"), ensure_ascii=False))
            cached = self._render_cache.get(key)
            if cached and cached[0] == signature:
                if cached[1]:
                    parts[key] = cached[1]
                continue
            chunk = []
            kind = item["type"]
            if kind == "user":
                chunk.append(
                    f'<div data-message-id="{key}" class="le-msg le-me"><div class="le-bubble">{_markdown(item["text"])}</div></div>'
                )
            elif kind == "ai":
                if not (item.get("text") or "").strip():
                    continue
                chunk.append(
                    f'<div data-message-id="{key}" class="le-msg le-ai"><div class="le-avatar">助</div>'
                    f'<div class="le-body">{_markdown(item["text"])}</div></div>'
                )
            elif kind == "reasoning":
                chunk.append(f'<details class="le-tool le-coach-reasoning" data-message-id="{key}"><summary>思考过程</summary><div class="le-tool-detail">{_markdown(item["text"])}</div></details>')
            elif kind == "tool":
                status = item.get("status", "run")
                title = _KIND_TITLES.get(item["name"], item["name"])
                if item["name"].startswith("mcp__"):
                    title = item["name"].split("__")[-1]
                args = json.dumps(item.get("args") or {}, ensure_ascii=False, indent=2)
                ms = item.get("ms")
                meta = ""
                if status == "pending":
                    meta = '<span class="le-tool-dot le-wait"></span>等待确认'
                elif status == "run":
                    meta = '<span class="le-tool-dot le-run"></span>执行中'
                elif status == "denied":
                    meta = '<span class="le-tool-dot le-deny"></span>未执行'
                elif status == "err":
                    meta = '<span class="le-tool-dot le-err"></span>失败'
                else:
                    duration = f' · {ms / 1000:.1f}s' if ms is not None and ms >= 1000 else ""
                    meta = f'<span class="le-tool-dot le-ok"></span>已完成{duration}'
                output = item.get("output") or ""
                call_id = html.escape(str(item.get("call_id", "")))
                result = output or {"pending": "等待你确认后执行。", "run": "正在检查，结果会显示在这里。"}.get(status, "操作已结束。")
                chunk.append(
                    f'<details class="le-tool" data-message-id="{key}" data-status="{status}" data-call-id="{call_id}">'
                    '<summary class="le-tool-head"><span class="le-tool-icon" aria-hidden="true">'
                    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2.5" y="3" width="15" height="14" rx="3"/><path d="m6 7 3 3-3 3m5 0h3"/></svg></span>'
                    f'<b>{html.escape(title)}</b><span class="le-tool-chevron" aria-hidden="true">'
                    '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="m6 4 4 4-4 4"/></svg></span>'
                    f'<span class="le-tool-meta">{meta}</span></summary>'
                    '<div class="le-tool-detail"><section><h4>输入</h4>'
                    f'<pre class="le-tool-args">{html.escape(args)}</pre></section>'
                    f'<section><h4>结果</h4><pre class="le-tool-out">{html.escape(result)}</pre></section></div></details>'
                )
            elif kind == "note":
                chunk.append(f'<div data-message-id="{key}" class="le-note">{_markdown(item["text"])}</div>')
            elif kind == "error":
                chunk.append(
                    f'<div data-message-id="{key}" class="le-note le-note-err">出错了：{html.escape(item["text"])}</div>'
                )
            rendered = "".join(chunk)
            self._render_cache[key] = (signature, rendered)
            if rendered:
                parts[key] = rendered

        if self.typing:
            parts["pending"] = (
                '<div data-message-id="pending" class="le-msg le-ai le-pending"><div class="le-avatar">助</div>'
                '<div class="le-thinking" role="status"><span class="le-typing" aria-hidden="true"><i></i><i></i><i></i></span>'
                '<span>正在思考如何指点…</span></div></div>'
            )
        return parts

    def _render(self) -> str:
        return (
            f'<div class="le-coach-feed" aria-live="polite" aria-relevant="additions text" '
            f'aria-busy="{str(self._busy).lower()}">' + "".join(self._render_items().values()) + "</div>"
        )

    def _frame(self, snapshot=False) -> str:
        """Self-contained frames survive Gradio coalescing; JS patches changed nodes only."""
        parts = self._render_items()
        self._frame_seq += 1
        payload = html.escape(json.dumps(parts, ensure_ascii=False))
        return (f'<div data-coach-frame data-session="{self.session.id}" data-seq="{self._frame_seq}" '
                f'data-busy="{str(self._busy).lower()}">{payload}</div>')

    def _approve_text(self, calls: list[dict]) -> str:
        lines = ['<strong>这一步需要你点头</strong>']
        for call in calls:
            title = _KIND_TITLES.get(call["name"], call["name"])
            preview = _args_preview(call.get("args") or {})
            arguments = json.dumps(call.get("args") or {}, ensure_ascii=False, indent=2)
            lines.append(f'<p>{html.escape(title)} · {html.escape(preview)}</p>')
            lines.append('<details class="le-approval-parameters"><summary>查看完整操作内容</summary>'
                         f'<pre>{html.escape(arguments)}</pre></details>')
        lines.append('<p>仅允许本次操作，后续步骤会再次确认。</p>')
        return "\n".join(lines)

    def _plan_html(self) -> str:
        """步骤清单：做完的打勾，当前这步高亮，后面的等着。"""
        plan = self.session.plan
        if not plan or not plan.get("steps"):
            return ""
        steps = plan["steps"]
        index = plan.get("index", 0)
        rows = []
        for i, text in enumerate(steps):
            if i < index:
                state, mark = "done", "✓"
            elif i == index:
                state, mark = "now", str(i + 1)
            else:
                state, mark = "todo", str(i + 1)
            rows.append(
                f'<li class="{state}"><span class="le-step-no">{mark}</span>'
                f'<span class="le-step-txt">{html.escape(text)}</span></li>'
            )
        done = min(index, len(steps))
        pct = round(done / len(steps) * 100)
        return (
            '<div class="le-plan"><div class="le-plan-head">'
            f'<span>接下来怎么做</span><b>{done}/{len(steps)}</b></div>'
            f'<ol class="le-plan-list">{"".join(rows)}</ol>'
            f'<div class="le-plan-bar"><i style="width:{pct}%"></i></div></div>'
        )

    # ------------------------------------------------------------ 事件
    def _push(self, force: bool = False, clear_input: bool = False, snapshot: bool = False):
        """把当前状态推给界面（流式时做一点节流）。"""
        now = time.monotonic()
        if not force and now - self._last_push < 0.10:
            return None
        self._last_push = now
        pending = bool(self.session.pending)
        input_update = gr.update(interactive=not self._busy, placeholder=(
            "写下你的回答，或补充具体情况…" if self.session.question else
            "告诉我你的进展，或接着问…" if self.items else _PLACEHOLDER))
        if clear_input:
            input_update["value"] = ""
        question = self.session.question
        options = question["options"][:3] if question else []
        question_id = question["id"] if question else None
        fresh_question = self._selection_question != question_id
        if fresh_question:
            self._selection_question = question_id
            self._question_selection = None
        selected = self._question_selection
        question_copy = ('<div class="le-question-heading"><span>先确认一件事</span>'
                         f'<h3>{html.escape(question["question"])}</h3></div>') if question else ""
        updates = [
            self._plan_html(),
            self._frame(snapshot=snapshot),
            gr.update(visible=pending),
            self._approve_text(self.session.pending) if self.session.pending else "",
            input_update,
            gr.update(interactive=not self._busy and not pending),
            gr.update(interactive=not self._busy),
            gr.update(interactive=not self._busy and pending),
            gr.update(interactive=not self._busy and pending),
            gr.update(interactive=not self._busy and pending),
            gr.update(visible=not self.items),
            gr.update(visible=not self.items),
            gr.update(visible=bool(question)),
            question_copy,
            *[gr.update(visible=bool(question) and (i < len(options) or i == 3), interactive=not self._busy,
                        variant="primary" if selected == i else "secondary",
                        value=(options[i]["label"] + ("\n" + options[i]["description"] if options[i].get("description") else ""))
                        if i < len(options) else "自己填写") for i in range(4)],
            question["id"] if question else "",
            gr.update(visible=bool(question) and selected == 3, interactive=not self._busy,
                      **({"value": ""} if fresh_question else {})),
            gr.update(interactive=bool(question) and selected is not None and not self._busy),
        ]
        for index, value in enumerate(updates):
            if index == 1:
                continue
            if not snapshot and not (index == 4 and clear_input) and self._sent_controls.get(index) == value:
                updates[index] = gr.skip()
            else:
                self._sent_controls[index] = value.copy() if isinstance(value, dict) else value
        return updates

    def _tool_item(self, call: dict, status: str) -> dict:
        call_id = call["call_id"] if "call_id" in call else call["id"]
        index = self._tool_index.get(call_id)
        if index is None or index >= len(self.items):
            index = len(self.items)
            self._tool_index[call_id] = index
            self.items.append({"type": "tool", "call_id": call_id, "name": call.get("name", "操作"), "args": call.get("args") or {}})
        item = self.items[index]
        item["status"] = status
        return item

    def _consume(self, events):
        """把运行时事件流翻译成界面更新。"""
        for event in events:
            kind = event.get("kind")
            if kind == "step":
                self.typing = True
            elif kind == "reasoning":
                if self.items and self.items[-1]["type"] == "reasoning":
                    self.items[-1]["text"] = event["text"]
                else:
                    self.items.append({"type": "reasoning", "text": event["text"]})
                payload = self._push()
                if payload:
                    yield payload
                continue
            elif kind == "delta":
                self.typing = False
                if self.items and self.items[-1]["type"] == "ai" and self.items[-1].get("live"):
                    self.items[-1]["text"] = event["text"]
                else:
                    self.items.append({"type": "ai", "text": event["text"], "live": True})
                payload = self._push()
                if payload:
                    yield payload
                continue
            elif kind == "plan":
                self.typing = False
                yield self._push(force=True)
                continue
            elif kind == "tool_start":
                self.typing = False
                if self.items and self.items[-1]["type"] == "ai":
                    self.items[-1]["live"] = False
                self._tool_item(event, "run")
            elif kind == "tool_end":
                status = "denied" if event.get("denied") else ("ok" if event.get("ok") else "err")
                item = self._tool_item(event, status)
                item["output"] = str(event.get("output") or "")
                item["ms"] = event.get("ms")
            elif kind == "need_approval":
                self.typing = False
                if self.items and self.items[-1]["type"] == "ai":
                    self.items[-1]["live"] = False
                for call in event.get("calls") or self.session.pending or []:
                    self._tool_item(call, "pending")
            elif kind == "question":
                self.typing = False
                if self.items and self.items[-1]["type"] == "ai":
                    self.items[-1]["live"] = False
            elif kind == "notice":
                self.typing = False
                self.items.append({"type": "note", "text": event.get("text", "")})
            elif kind == "error":
                self.typing = False
                for item in self.items:
                    if item["type"] == "tool" and item.get("status") in {"run", "pending"}:
                        item.update(status="err", output="操作已中断，请先核实当前状态。")
                self.items.append({"type": "error", "text": event.get("message", "")})
            yield self._push(force=True)

        self.typing = False
        if self.items and self.items[-1]["type"] == "ai":
            self.items[-1]["live"] = False
        yield self._push(force=True)

    def _on_send(self, text: str):
        yield from self._send(text)

    def _select_option(self, index: int, question_id: str):
        if not self._turn_lock.acquire(blocking=False):
            return self._push(force=True)
        try:
            question = self.session.question
            if question and question["id"] == question_id and (index == 3 or 0 <= index < min(3, len(question["options"]))):
                self._selection_question = question_id
                self._question_selection = index
        finally:
            self._turn_lock.release()
        return self._push(force=True)

    def _confirm_question(self, text: str, question_id: str):
        index = self._question_selection
        if self._selection_question != question_id or index is None:
            yield self._push(force=True)
            return
        if index == 3:
            if not (text or "").strip():
                gr.Warning("写下你的想法后再继续。")
                yield self._push(force=True)
                return
            yield from self._send(text, question_id=question_id)
        else:
            yield from self._send("", question_id=question_id, option_index=index)

    def _on_option(self, index: int, question_id: str):
        yield from self._send("", question_id=question_id, option_index=index)

    def _send(self, text: str, *, question_id=None, option_index=None):
        text = (text or "").strip()
        if (not text and option_index is None) or not self._turn_lock.acquire(blocking=False):
            yield self._push(force=True, snapshot=True)
            return
        if question_id is not None and (not self.session.question or self.session.question["id"] != question_id):
            self._turn_lock.release()
            yield self._push(force=True, snapshot=True)
            return
        if option_index is not None:
            question = self.session.question
            if (not question or question["id"] != question_id or
                    not 0 <= option_index < len(question["options"])):
                self._turn_lock.release()
                yield self._push(force=True, snapshot=True)
                return
            text = question["options"][option_index]["label"]
        self._busy = True
        try:
            if self.session.pending:
                self.items.append({"type": "note", "text": "还有一步在等你确认，先选择「允许这一步」或「暂不执行」。"})
                yield self._push(force=True)
            else:
                if self.session.question:
                    self.items.append({"type": "ai", "text": self.session.question["question"]})
                self.items.append({"type": "user", "text": text})
                self.typing = True
                yield self._push(force=True, clear_input=True, snapshot=True)
                yield from self._consume(runtime.run(self.session, text))
        except Exception as exc:  # noqa: BLE001
            logger.exception("动手学对话失败")
            self.session.question = None
            self.items.append({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            self.typing = False
            self._busy = False
            self._turn_lock.release()
        yield self._push(force=True, snapshot=True)

    def _approve(self, allow: bool):
        if not self._turn_lock.acquire(blocking=False):
            yield self._push(force=True, snapshot=True)
            return
        self._busy = True
        self.session.auto = False
        try:
            yield self._push(force=True)
            yield from self._consume(runtime.approve(self.session, allow))
        except Exception as exc:  # noqa: BLE001
            logger.exception("动手学确认失败")
            self.items.append({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            self.typing = False
            self._busy = False
            self._turn_lock.release()
        yield self._push(force=True, snapshot=True)

    # Gradio 只把「生成器函数」当流式处理，lambda 会包成普通函数，所以各写一个
    def _on_allow(self):
        yield from self._approve(True)

    def _on_deny(self):
        yield from self._approve(False)

    def _on_allow_always(self):
        yield from self._approve(True)

    def _on_clear(self):
        if not self._turn_lock.acquire(blocking=False):
            yield self._push(force=True)
            return
        try:
            selection = self.session.model_selection
            self.session.reset()
            self.session = runtime.Session()
            self.session.model_selection = selection
            self.items = []
            self._tool_index = {}
            self._render_cache.clear()
            self.typing = False
        finally:
            self._turn_lock.release()
        yield self._push(force=True, clear_input=True, snapshot=True)

    def _fill_suggestion(self, name: str):
        if self._busy or self.session.pending:
            return gr.update()
        return gr.update(value=_SUGGESTIONS[name])

    def _model_choices(self, connection):
        from learning_ext import connection_store
        from learning_ext.llm.client import _load_config
        from learning_ext.model_platforms import PLATFORMS
        if connection == "(default)":
            return [_load_config()["chat_model"]]
        record = connection_store.find_connection(record_id=connection)
        if not record:
            raise gr.Error("连接已被删除，请刷新列表。")
        return list(dict.fromkeys([record["chat_model"], *PLATFORMS[record["provider"]]["models"]]))

    def _configure_model(self, connection, model, effort, show):
        from learning_ext import chat_connections, chat_thinking
        if not self._turn_lock.acquire(blocking=False):
            raise gr.Error("回答完成后再切换模型。")
        try:
            if self.session.pending:
                raise gr.Error("请先处理待确认的操作。")
            choices = self._model_choices(connection)
            if model not in choices:
                raise gr.Error("请选择此连接的模型。")
            token = chat_connections.model_token("" if connection == "(default)" else connection,
                "" if connection == "(default)" else model,
                {"effort": effort, "show_thinking": show})
            self.session.model_selection = token
            self.session.record("agent_model_settings", connection=connection, model=model,
                                effort=effort, show_thinking=show)
            return gr.update(label=model), gr.update(visible=chat_thinking.supports_effort(model))
        finally:
            self._turn_lock.release()

    def _load_model_settings(self):
        from learning_ext import chat_connections, chat_thinking
        connection, model, prefs = chat_connections.parse_selection(self.session.model_selection or chat_connections.default_model_token())
        connection = connection or "(default)"
        try:
            choices = self._model_choices(connection)
        except gr.Error:
            connection = "(default)"
            choices = self._model_choices(connection)
            self.session.model_selection = chat_connections.default_model_token(prefs)
        model = model if model in choices else choices[0]
        return (gr.update(choices=chat_connections.saved_choices(), value=connection),
                gr.update(choices=choices, value=model),
                gr.update(value=prefs["effort"], visible=chat_thinking.supports_effort(model)),
                gr.update(value=prefs["show_thinking"]), gr.update(label=model))

    def _connection_models(self, connection):
        choices = self._model_choices(connection)
        return gr.update(choices=choices, value=choices[0])

    # ------------------------------------------------------------ UI
    def on_building_ui(self):
        with gr.Column(elem_id="le-coach-root"):
            self.welcome = gr.HTML(
                '<div class="le-coach-welcome-copy"><h1>想做什么，一起动手。</h1>'
                '<p>先看看你的电脑，再把目标拆成一步步行动。</p></div>',
                elem_id="le-coach-welcome",
            )
            with gr.Row(elem_id="le-coach-suggestions") as self.suggestions:
                self.suggest_env = gr.Button("检查学习环境", elem_id="le-coach-suggest-env", size="sm")
                self.suggest_files = gr.Button("寻找软件或文件", elem_id="le-coach-suggest-files", size="sm")
                self.suggest_window = gr.Button("指导当前窗口", elem_id="le-coach-suggest-window", size="sm")
            with gr.Row(elem_id="le-coach-toolbar"):
                from learning_ext import chat_connections, chat_thinking
                from learning_ext.llm.client import _load_config
                from learning_ext.model_platforms import detect_platform, platform_icon_url
                initial_model = self._model_choices("(default)")[0]
                default_icon = platform_icon_url(detect_platform(_load_config()["base_url"]))
                with gr.Accordion(initial_model, open=False, elem_id="le-coach-model-menu") as self.model_menu:
                    gr.HTML(f'<span data-default-icon="{html.escape(default_icon, quote=True)}"></span>', elem_id="le-coach-model-brand")
                    self.connection = gr.Dropdown(choices=chat_connections.saved_choices(), value="(default)", show_label=False, container=False, elem_id="le-coach-connection")
                    self.model = gr.Radio(choices=[initial_model], value=initial_model, show_label=False, container=False, elem_id="le-coach-model-list")
                    self.effort = gr.Radio(choices=[("轻快", "low"), ("深入", "high"), ("尽全力", "max")], value="low", label="思考强度", visible=chat_thinking.supports_effort(initial_model), elem_id="le-coach-effort")
                    self.show_thinking = gr.Checkbox(False, label="显示思考过程", elem_id="le-coach-show-thinking")
                    self.model_refresh = gr.Button("刷新连接", size="sm", elem_id="le-coach-model-refresh")
                self.clear_btn = gr.Button("开启新任务", elem_id="le-coach-clear", size="sm")
            self.plan_html = gr.HTML("", elem_id="le-coach-plan")
            with gr.Column(elem_id="le-coach-scroll"):
                self.transcript = gr.HTML(self._render(), elem_id="le-coach-transcript")
            self.stream = gr.HTML("", elem_id="le-coach-stream")
            with gr.Column(elem_id="le-coach-approve", visible=False) as self.approve_col:
                self.approve_md = gr.HTML("", elem_id="le-coach-approve-text")
                with gr.Row(elem_id="le-coach-approve-actions"):
                    self.allow_btn = gr.Button("允许这一步", elem_id="le-coach-allow", size="sm", variant="primary")
                    self.deny_btn = gr.Button("暂不执行", elem_id="le-coach-deny", size="sm")
                    self.always_btn = gr.Button(
                        "仅允许本次", elem_id="le-coach-always", size="sm", visible=False
                    )
            # A queued click must carry the ID that was displayed when clicked.
            self.question_id = gr.Textbox("", visible=False, elem_id="le-coach-question-id")
            with gr.Column(elem_id="le-coach-question", visible=False) as self.question_col:
                self.question_copy = gr.HTML("", elem_id="le-coach-question-copy")
                with gr.Row(elem_id="le-coach-question-options"):
                    self.option_buttons = [gr.Button("", elem_id=f"le-coach-option-{i}", visible=False) for i in range(4)]
                self.custom_answer = gr.Textbox(show_label=False, placeholder="写下你的想法…", lines=2, max_lines=4,
                                               visible=False, elem_id="le-coach-custom-answer")
                self.confirm_question = gr.Button("继续 →", interactive=False, variant="primary", elem_id="le-coach-question-confirm")
            with gr.Row(elem_id="le-coach-composer"):
                self.input = gr.Textbox(
                    show_label=False,
                    container=False,
                    placeholder=_PLACEHOLDER,
                    lines=1,
                    max_lines=6,
                    elem_id="le-coach-input",
                    autofocus=False,
                )
                self.send_btn = gr.Button("发送", elem_id="le-coach-send", variant="primary")

        self._outputs = [
            self.plan_html,
            self.stream,
            self.approve_col,
            self.approve_md,
            self.input,
            self.send_btn,
            self.clear_btn,
            self.allow_btn,
            self.deny_btn,
            self.always_btn,
            self.welcome,
            self.suggestions,
            self.question_col,
            self.question_copy,
            *self.option_buttons,
            self.question_id,
            self.custom_answer,
            self.confirm_question,
        ]

    def on_register_events(self):
        from learning_ext import chat_connections
        self.connection.input(self._connection_models, inputs=[self.connection], outputs=[self.model], show_progress="hidden").then(self._configure_model, inputs=[self.connection, self.model, self.effort, self.show_thinking], outputs=[self.model_menu, self.effort], show_progress="hidden")
        for control in (self.model, self.effort, self.show_thinking):
            control.input(self._configure_model, inputs=[self.connection, self.model, self.effort, self.show_thinking],
                           outputs=[self.model_menu, self.effort], show_progress="hidden")
        self.model_refresh.click(lambda: gr.update(choices=chat_connections.saved_choices()), outputs=[self.connection], show_progress="hidden")
        outputs = self._outputs
        events = {"outputs": outputs, "concurrency_id": "desktop-coach", "concurrency_limit": 1,
                  "show_progress": "hidden", "trigger_mode": "once"}
        self.send_btn.click(self._on_send, inputs=[self.input], **events)
        self.input.submit(self._on_send, inputs=[self.input], **events)
        self.allow_btn.click(self._on_allow, **events)
        self.deny_btn.click(self._on_deny, **events)
        self.always_btn.click(self._on_allow_always, **events)
        self.clear_btn.click(self._on_clear, outputs=outputs, queue=False, show_progress="hidden")
        for index, button in enumerate(self.option_buttons):
            button.click(partial(self._select_option, index), inputs=[self.question_id], **events)
        self.confirm_question.click(self._confirm_question, inputs=[self.custom_answer, self.question_id], **events)
        self.custom_answer.submit(self._confirm_question, inputs=[self.custom_answer, self.question_id], **events)
        app = getattr(self._app, "app", None)
        if app is not None:
            app.load(self._load_model_settings, outputs=[self.connection, self.model, self.effort, self.show_thinking, self.model_menu], show_progress="hidden")
            app.load(lambda: self._push(force=True, snapshot=True), outputs=outputs, queue=False, show_progress="hidden")
        for name, button in (("env", self.suggest_env), ("files", self.suggest_files), ("window", self.suggest_window)):
            button.click(partial(self._fill_suggestion, name), outputs=[self.input], queue=False, show_progress="hidden")
