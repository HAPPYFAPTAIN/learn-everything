"""动手学：一个真的能操作这台电脑的对话式 Agent。

界面只有三块：
    #le-coach-scroll     转写区（有内容才出现）
    #le-coach-approve    待确认操作（有危险调用才出现）
    #le-coach-composer   胶囊输入框 + 发送键（一直存在）

没有内容时转写区收起，只剩居中的胶囊输入框。

当前阶段：功能还在做，页面先换成「开发中」说明（见 coach_soon.py）。
把 COMING_SOON 改成 False 就恢复原来的对话式 Agent。
"""

from __future__ import annotations

import html
import logging
import re
import time

import gradio as gr
from ktem.app import BasePage

from learning_ext.agent import runtime
from learning_ext.agent.tools import tool_titles
from learning_ext.pages.coach_soon import coming_soon_html

logger = logging.getLogger(__name__)

COMING_SOON = True   # 开发中：只渲染说明页，原实现保留

_PLACEHOLDER = "说说你卡在哪：我来接管电脑，一边做一边告诉你下一步点哪"

_KIND_TITLES = {
    "run_command": "执行命令",
    "list_dir": "列出目录",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "search_files": "搜索文件",
    "open_path": "打开文件",
    "open_url": "打开网址",
    "screenshot": "截屏",
    "system_info": "系统信息",
    "list_windows": "窗口列表",
    "clipboard_get": "读剪贴板",
    "clipboard_set": "写剪贴板",
    "observe_screen": "看当前屏幕",
    "read_ui": "读取界面控件",
    "click_ui": "点击控件",
    "click_at": "鼠标点击",
    "press_keys": "按键",
    "type_text": "输入文字",
    "launch_app": "启动程序",
}

_FENCE = re.compile(r"```([\w+#.-]*)[ \t]*\n(.*?)```", re.S)
_HEAD = re.compile(r"^(#{1,6})\s*(.+)$")
_BULLET = re.compile(r"^[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")


def _inline(text: str) -> str:
    """行内格式：先转义，再处理 `code` / **粗** / *斜* / 链接。"""
    text = html.escape(text, quote=False)
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
        if fence:
            close()
            lang, body = fences[int(fence.group(1))]
            label = f'<span class="le-code-lang">{html.escape(lang)}</span>' if lang else ""
            out.append(
                f'<div class="le-code">{label}<pre><code>{html.escape(body.strip(chr(10)))}</code></pre></div>'
            )
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
        self.items: list[dict] = []
        self.typing = False
        self._tool_index: dict[str, int] = {}
        self._last_push = 0.0
        self._outputs: list = []

    # ------------------------------------------------------------ 渲染
    def _render(self) -> str:
        parts: list[str] = []
        for item in self.items:
            kind = item["type"]
            if kind == "user":
                parts.append(
                    f'<div class="le-msg le-me"><div class="le-bubble">{_markdown(item["text"])}</div></div>'
                )
            elif kind == "ai":
                if not (item.get("text") or "").strip():
                    continue
                parts.append(
                    f'<div class="le-msg le-ai"><div class="le-avatar">助</div>'
                    f'<div class="le-body">{_markdown(item["text"])}</div></div>'
                )
            elif kind == "tool":
                status = item.get("status", "run")
                title = _KIND_TITLES.get(item["name"], item["name"])
                if item["name"].startswith("mcp__"):
                    title = item["name"].split("__")[-1]
                args = _args_preview(item.get("args") or {})
                arg_chip = f"<code>{html.escape(args)}</code>" if args else ""
                ms = item.get("ms")
                meta = ""
                if status == "run":
                    meta = '<span class="le-tool-dot le-run"></span>执行中'
                elif status == "denied":
                    meta = '<span class="le-tool-dot le-deny"></span>已拒绝'
                elif status == "err":
                    meta = '<span class="le-tool-dot le-err"></span>失败'
                else:
                    meta = f'<span class="le-tool-dot le-ok"></span>{ms if ms is not None else 0}ms'
                output = item.get("output") or ""
                detail = ""
                if output:
                    detail = (
                        "<details><summary>查看输出</summary>"
                        f'<pre class="le-tool-out">{html.escape(output)}</pre></details>'
                    )
                parts.append(
                    f'<div class="le-tool" data-status="{status}">'
                    f'<div class="le-tool-head"><b>{html.escape(title)}</b>'
                    f'{arg_chip}<span class="le-tool-meta">{meta}</span></div>'
                    f"{detail}</div>"
                )
            elif kind == "note":
                parts.append(f'<div class="le-note">{_markdown(item["text"])}</div>')
            elif kind == "error":
                parts.append(
                    f'<div class="le-note le-note-err">出错了：{html.escape(item["text"])}</div>'
                )

        if self.typing:
            parts.append(
                '<div class="le-msg le-ai le-pending"><div class="le-avatar">助</div>'
                '<div class="le-typing"><span></span><span></span><span></span></div></div>'
            )
        return '<div class="le-coach-feed">' + "".join(parts) + "</div>"

    def _approve_text(self, calls: list[dict]) -> str:
        lines = ["**这一步需要你点头**", ""]
        for call in calls:
            title = _KIND_TITLES.get(call["name"], call["name"])
            preview = _args_preview(call.get("args") or {})
            lines.append(f"- `{title}` {('· ' + preview) if preview else ''}")
        lines.append("")
        lines.append("允许后我会真的在这台电脑上动手，你看着屏幕就行。")
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
    def _push(self, force: bool = False):
        """把当前状态推给界面（流式时做一点节流）。"""
        now = time.time()
        if not force and now - self._last_push < 0.07:
            return None
        self._last_push = now
        return [
            self._plan_html(),
            self._render(),
            gr.update(visible=bool(self.session.pending)),
            self._approve_text(self.session.pending) if self.session.pending else "",
            "",
        ]

    def _consume(self, events):
        """把运行时事件流翻译成界面更新。"""
        for event in events:
            kind = event.get("kind")
            if kind == "step":
                self.typing = True
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
                self._tool_index[event["call_id"]] = len(self.items)
                self.items.append(
                    {
                        "type": "tool",
                        "name": event["name"],
                        "args": event.get("args") or {},
                        "status": "run",
                    }
                )
            elif kind == "tool_end":
                index = self._tool_index.get(event["call_id"])
                if index is not None and index < len(self.items):
                    item = self.items[index]
                    item["output"] = event.get("output") or ""
                    item["ms"] = event.get("ms")
                    item["status"] = (
                        "denied"
                        if event.get("denied")
                        else ("ok" if event.get("ok") else "err")
                    )
            elif kind == "need_approval":
                self.typing = False
                if self.items and self.items[-1]["type"] == "ai":
                    self.items[-1]["live"] = False
            elif kind == "notice":
                self.typing = False
                self.items.append({"type": "note", "text": event.get("text", "")})
            elif kind == "error":
                self.typing = False
                self.items.append({"type": "error", "text": event.get("message", "")})
            yield self._push(force=True)

        self.typing = False
        if self.items and self.items[-1]["type"] == "ai":
            self.items[-1]["live"] = False
        yield self._push(force=True)

    def _on_send(self, text: str):
        text = (text or "").strip()
        if not text:
            yield self._push(force=True)
            return
        if self.session.pending:
            self.items.append(
                {"type": "note", "text": "还有一步在等你确认，先点上面的「允许」或「拒绝」。"}
            )
            yield self._push(force=True)
            return
        self.items.append({"type": "user", "text": text})
        self.typing = True
        yield self._push(force=True)
        try:
            yield from self._consume(runtime.run(self.session, text))
        except Exception as exc:  # noqa: BLE001
            logger.exception("动手学对话失败")
            self.typing = False
            self.items.append({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
            yield self._push(force=True)

    def _approve(self, allow: bool):
        yield from self._consume(runtime.approve(self.session, allow))

    # Gradio 只把「生成器函数」当流式处理，lambda 会包成普通函数，所以各写一个
    def _on_allow(self):
        yield from self._approve(True)

    def _on_deny(self):
        yield from self._approve(False)

    def _on_allow_always(self):
        self.session.auto = True
        self.items.append({"type": "note", "text": "已开启自动执行：后面的操作不再逐条确认。"})
        yield from self._consume(runtime.approve(self.session, True))

    def _on_clear(self):
        self.session.reset()
        self.session.auto = False
        self.items = []
        self._tool_index = {}
        self.typing = False
        yield self._push(force=True)

    # ------------------------------------------------------------ UI
    def on_building_ui(self):
        if COMING_SOON:
            with gr.Column(elem_id="le-coach-soon-wrap"):
                gr.HTML(coming_soon_html(), elem_id="le-soon")
            self._outputs = []
            return
        with gr.Column(elem_id="le-coach-root"):
            self.plan_html = gr.HTML("", elem_id="le-coach-plan")
            with gr.Column(elem_id="le-coach-scroll"):
                self.transcript = gr.HTML(self._render(), elem_id="le-coach-transcript")
            with gr.Column(elem_id="le-coach-approve", visible=False) as self.approve_col:
                self.approve_md = gr.Markdown("", elem_id="le-coach-approve-text")
                with gr.Row(elem_id="le-coach-approve-actions"):
                    self.allow_btn = gr.Button("允许执行", elem_id="le-coach-allow", size="sm")
                    self.deny_btn = gr.Button("拒绝", elem_id="le-coach-deny", size="sm")
                    self.always_btn = gr.Button(
                        "这次对话都允许", elem_id="le-coach-always", size="sm"
                    )
            with gr.Row(elem_id="le-coach-composer"):
                self.input = gr.Textbox(
                    show_label=False,
                    container=False,
                    placeholder=_PLACEHOLDER,
                    lines=1,
                    max_lines=6,
                    elem_id="le-coach-input",
                    autofocus=True,
                )
                self.send_btn = gr.Button("发送", elem_id="le-coach-send", variant="primary")
                self.clear_btn = gr.Button("新对话", elem_id="le-coach-clear", size="sm")

        self._outputs = [
            self.plan_html,
            self.transcript,
            self.approve_col,
            self.approve_md,
            self.input,
        ]

    def on_register_events(self):
        if COMING_SOON:
            return
        outputs = self._outputs

        self.send_btn.click(self._on_send, inputs=[self.input], outputs=outputs)
        self.input.submit(self._on_send, inputs=[self.input], outputs=outputs)
        self.allow_btn.click(self._on_allow, outputs=outputs)
        self.deny_btn.click(self._on_deny, outputs=outputs)
        self.always_btn.click(self._on_allow_always, outputs=outputs)
        self.clear_btn.click(self._on_clear, outputs=outputs)

