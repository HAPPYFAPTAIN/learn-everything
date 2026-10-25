from __future__ import annotations

from functools import partial
import html
from urllib.parse import urlparse

import gradio as gr
from sqlmodel import Session, select
from ktem.db.engine import engine

from learning_ext.action_learning.service import ActionLearning
from learning_ext.agent import guided_desktop as desktop
from learning_ext.db.models import KnowledgeNode, LearningProject
from learning_ext.progress.study import get_practice_task, sort_nodes_by_code
from learning_ext.llm.client import friendly_error, _load_config
from learning_ext.rich_text import render_rich_text
from learning_ext.environment_agent.view import environment_card


def escape(value):
    return html.escape(str(value or ""))


def action_card(state):
    index = state["index"]
    if index < 0:
        return environment_card(state)
    step = state["steps"][index]
    done = index in state["done"]
    return (
        f'<article class="le-action-card" data-le-step-active="true" data-le-focus="step" data-step="{index}">'
        f'<div class="le-action-kicker"><span>第 {index+1:02} 步</span><span>{"已自行完成" if done else "现在，做这一件事"}</span></div>'
        f'<h2>{escape(step["title"])}</h2><div class="le-action-instruction">{render_rich_text(step["action"], legacy_commands=True)}</div>'
        f'<div class="le-action-check"><span>做到什么算完成</span>{render_rich_text(step["check"])}</div>'
        f'<details class="le-action-source"><summary>对应原文</summary><blockquote>{render_rich_text(step["source"])}</blockquote></details>'
        '</article>'
    )


class ActionLearningPanel:
    def __init__(self, page):
        self.page = page
        self.service = ActionLearning()

    def build(self):
        self.state = gr.State(None)
        with gr.Row(elem_id="le-learning-mode"):
            gr.HTML('<div class="le-mode-intro"><span class="le-mode-icon" aria-hidden="true">↳</span><strong>一次，专心做一件事</strong></div>')
            self.entry = gr.Button("拆解步骤 →", elem_id="le-step-entry", scale=0)
        self.notice = gr.Markdown("", elem_id="le-step-notice")
        with gr.Column(visible=False, elem_id="le-action-learning") as self.panel:
            with gr.Row(elem_id="le-action-topbar"):
                self.meta = gr.HTML("")
                self.close = gr.Button("返回全文", size="sm", scale=0, elem_id="le-action-close")
            self.previous = gr.Button("已经是第一步", elem_id="le-action-previous")
            self.card = gr.HTML("")
            with gr.Row(elem_id="le-action-tools") as self.action_tools:
                self.hint = gr.Button("给我一点提示", size="sm")
                self.assist = gr.Button("问问 AI", size="sm")
                self.screen = gr.Button("屏幕引导", size="sm")
                self.done = gr.Button("这一步我做完了 ✓", variant="primary", size="sm")
            self.recheck = gr.Button("重新检查环境", size="sm", visible=False, elem_id="le-environment-recheck")
            self.help = gr.HTML("", elem_id="le-action-help")
            with gr.Column(visible=False, elem_id="le-action-assistant") as self.assistant:
                gr.HTML('<div class="le-action-assistant-title">动手学 <span>只协助当前这一步</span></div>')
                with gr.Row():
                    self.question = gr.Textbox(placeholder="卡在哪里？", show_label=False, scale=4, lines=1)
                    self.ask = gr.Button("问 AI", scale=0)
                with gr.Column(visible=False, elem_id="le-action-screen") as self.screen_panel:
                    with gr.Row():
                        self.window = gr.Dropdown(label="选择要引导的窗口", choices=[], interactive=True, scale=4)
                        self.refresh = gr.Button("刷新窗口", scale=0)
                    self.observe = gr.Button("读取这个窗口的控件", size="sm")
                    with gr.Column(visible=False) as self.targets:
                        self.control = gr.Dropdown(label="要找的控件", choices=[], interactive=True)
                        with gr.Row():
                            self.highlight = gr.Button("在屏幕上圈出来", size="sm")
                            self.locate = gr.Button("让 AI 帮我定位", size="sm")
                        self.share = gr.Checkbox(label="本次允许把这个窗口的控件名称发给当前模型定位（不含截图或输入内容）", value=False)
                    with gr.Column(visible=False) as self.authorization:
                        self.approve = gr.Checkbox(label="先圈出位置，再授权本次操作", value=False, interactive=False)
                        self.execute = gr.Button("仅操作这一次", interactive=False, variant="primary", size="sm")
                    self.revoke = gr.Button("停止辅助 / 撤回授权", size="sm")
            self.next = gr.Button("下一步 ↓", elem_id="le-action-next")
        return self

    def register(self):
        self.outputs = [self.state, self.panel, self.notice, self.meta, self.previous, self.card,
                        self.next, self.help, self.assistant, self.window, self.control,
                        self.approve, self.execute, self.share, self.screen_panel, self.targets, self.authorization,
                        self.action_tools, self.recheck]
        inputs = [self.state, self.page.current_node_id, self.page.current_project_id, self.page._app.user_id,
                  self.window, self.control, self.question, self.approve, self.share]
        commands = [(self.entry,"start"),(self.close,"close"),(self.previous,"previous"),(self.next,"next"),
                    (self.hint,"hint"),(self.assist,"assist"),(self.done,"done"),(self.ask,"ask"),
                    (self.refresh,"windows"),(self.observe,"observe"),(self.highlight,"highlight"),
                    (self.locate,"locate"),(self.execute,"execute"),(self.revoke,"revoke"),(self.screen,"screen"), (self.recheck,"recheck_environment")]
        for button, command in commands:
            button.click(partial(self.dispatch, command), inputs=inputs, outputs=self.outputs,
                         concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        self.question.submit(partial(self.dispatch, "ask"), inputs=inputs, outputs=self.outputs,
                             concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        self.window.input(partial(self.handle, "window_changed"), inputs=inputs, outputs=self.outputs,
                          concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        self.control.input(partial(self.handle, "control_changed"), inputs=inputs, outputs=self.outputs,
                           concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        self.page.course_drop.change(partial(self.handle, "close"), inputs=inputs, outputs=self.outputs,
                                     concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        self.page.project_id.input(partial(self.handle, "close"), inputs=inputs, outputs=self.outputs,
                                  concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")
        for tab_id, tab in self.page._app._tabs.items():
            if tab_id != "learning-workbench-tab":
                tab.select(partial(self.handle, "close"), inputs=inputs, outputs=self.outputs,
                           concurrency_id="action-learning", concurrency_limit=1, show_progress="hidden")

    def dispatch(self, command, state, *args):
        if command in {"start", "recheck_environment"}:
            yield self.render({"loading": True}, "")
        elif command == "ask" and state and state.get("active"):
            yield self.render({**state, "help": "正在想怎么帮你完成这一步…"}, "")
        yield self.handle(command, state, *args)

    @staticmethod
    def context(node_id, project_id, owner):
        with Session(engine) as session:
            node = session.get(KnowledgeNode, int(node_id)) if node_id else None
            project = session.get(LearningProject, node.project_id) if node else None
            if not node or not project or project.user_id != owner or str(project.id) != str(project_id):
                raise ValueError("请先打开自己的课程。")
            if len(node.description or "") < 120:
                raise ValueError("本节内容还在准备，正文就绪后再拆解。")
            practice = get_practice_task(session, node.id)
            nodes = sort_nodes_by_code(list(session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == project.id)).all()))
            return dict(course=node.title, goal=project.goal, topic=project.topic, background=project.background,
                        route=[dict(code=n.code,title=n.title,status=n.status) for n in nodes],
                        lesson=node.description, practice=practice.description if practice else "")

    def handle(self, command, state, node, project, owner, window, control, question, approved, sharing):
        owner = str(owner or "default")
        state = state or {}
        notice = ""
        try:
            if command == "close":
                if state.get("id"):
                    self.service.revoke(state, "focus_closed")
                state.update(active=False, loading=False)
                return self.render(state, "")
            if command == "start":
                if state.get("id"):
                    self.service.revoke(state, "session_switched")
                context = self.context(node, project, owner)
                state = self.service.start(owner, int(node), context)
                state.update(active=True, assist=False, screen=False, help="", windows=[], window=None, control=None)
            else:
                self.service.require(state, int(node) if node else None, owner)
                if not state.get("active"):
                    raise ValueError("请重新进入逐步行动。")
                if state["index"] < 0 and command not in {"next", "previous", "recheck_environment", "hint", "ask", "revoke"}:
                    raise ValueError("先确认本机环境，进入具体行动后再使用辅助。")
                if command in {"next", "previous"}:
                    self.service.revoke(state, "step_authorization_cleared")
                    self.service.move(state, 1 if command == "next" else -1)
                    state.update(help="", control=None, assist=False, screen=False)
                elif command == "recheck_environment":
                    self.service.recheck_environment(state)
                    state.update(help="", assist=False, screen=False, control=None)
                elif command == "done":
                    self.service.complete(state)
                    notice = "已记录为自行完成。" if len(state["done"]) < len(state["steps"]) else "本节行动已全部自行完成。返回全文后可做过关检查。"
                elif command == "hint":
                    state["help"] = self.service.hint(state)
                elif command == "assist":
                    state["assist"] = not state.get("assist", False)
                    if not state["assist"]:
                        self.service.revoke(state)
                    self.service.journal.record(state, "assistant_toggled", open=state["assist"])
                elif command == "ask":
                    state["help"] = self.service.help(state, question)
                elif command in {"windows", "window_changed", "screen"}:
                    self.service.revoke(state, command)
                    if command in {"windows", "screen"}:
                        state["windows"] = desktop.windows()
                    state.update(window=window if command == "window_changed" else None, control=None, screen=True, assist=True)
                elif command == "observe":
                    self.service.revoke(state, "observe_requested")
                    chosen = next((item for item in state.get("windows", []) if str(item["hwnd"]) == window), None)
                    if not chosen:
                        raise ValueError("刷新并选择你正在操作的窗口。")
                    state["observation"] = desktop.observe(chosen)
                    state.update(window=window, control=None)
                    count = len(state["observation"]["items"])
                    self.service.journal.record(state, "window_observed", window=chosen["title"], count=count)
                    notice = f"已识别 {count} 个控件。选择一个圈出位置，或让 AI 帮你找。"
                elif command == "control_changed":
                    state["pending"] = None
                    state["control"] = control
                    desktop.stop_highlight(state["id"])
                    self.service.journal.record(state, "control_selected", key=control)
                elif command in {"highlight", "locate"}:
                    state["pending"] = None
                    if command == "locate":
                        if not sharing:
                            raise ValueError("先勾选本次允许发送控件名称，或直接手动选择控件。")
                        item = self.service.locate(state)
                    else:
                        item = next((item for item in (state.get("observation") or {}).get("items", []) if item["key"] == control), None)
                        if not item:
                            raise ValueError("先读取窗口并选择一个控件。")
                    state["control"] = item["key"]
                    self.service.prepare_operation(state, item)
                    notice = "已开启 6 秒圈选指引，请查看目标窗口。" + ("" if state.get("pending") else "这个控件请亲自操作。")
                elif command == "execute":
                    notice = self.service.execute(state, approved)
                elif command == "revoke":
                    self.service.revoke(state)
                    state.update(assist=False, control=None)
                    notice = "已停止辅助，授权已撤回。"
        except Exception as exc:
            state["pending"] = None
            if state.get("id"):
                self.service.journal.record(state, "request_failed", command=command, error=type(exc).__name__)
            notice = str(exc) if isinstance(exc, ValueError) else friendly_error(exc)
        return self.render(state, notice)

    @staticmethod
    def render(state, notice):
        active = state.get("active", False) and bool(state.get("steps"))
        loading = state.get("loading", False)
        index = state.get("index", 0)
        steps = state.get("steps", [])
        previous_index = ActionLearning.next_index(state, -1) if active else index
        next_index = ActionLearning.next_index(state, 1) if active else index
        prev = ("↑ 查看本机环境" if previous_index < 0 else "↑ 上一条 · " + steps[previous_index]["title"]) if active and previous_index != index else "从这里开始"
        next_text = ("开始行动 · " if index < 0 else "下一条 · ") + steps[next_index]["title"] + " ↓" if active and next_index >= 0 and next_index != index else "准备已确认" if index < 0 else "已经是最后一步"
        pending = state.get("pending")
        verb = {"toggle":"切换开关","select":"选中","expand":"展开","invoke":"点击"}.get(pending["item"]["action"], "操作") if pending else "操作"
        label = (f'允许本次在「{pending["window"]["title"]}」{verb}「{pending["item"]["name"]}」' if pending else "先圈出位置，再授权本次操作")
        items = (state.get("observation") or {}).get("items", [])
        cfg = _load_config()
        destination = f'{cfg.get("chat_model", "当前模型")} · {urlparse(cfg.get("base_url", "")).hostname or "已配置平台"}'
        position = "学习前检查" if index < 0 else f"{index+1} / {len(steps)}"
        meta = (f'<div class="le-action-progress"><strong>{escape(state["context"]["course"])}</strong>'
                f'<span>{position} · 自行完成 {len(state["done"])} 步</span>'
                f'<progress value="{len(state["done"])}" max="{len(steps)}"></progress></div>') if active else ""
        card = action_card(state) if active else ""
        if loading:
            card = ('<section class="le-action-loading" data-le-focus="loading" role="status" aria-live="polite" aria-busy="true">'
                    '<span class="le-action-loader" aria-hidden="true"></span><h2>把这一节，变成可做的小步</h2>'
                    '<p>正在检查本机环境，整理行动与完成标准</p><div class="le-action-skeleton" aria-hidden="true"><i></i><i></i><i></i></div></section>')
        return (state, gr.update(visible=active or loading), notice, meta,
                gr.update(value=prev, interactive=active and previous_index!=index), card,
                gr.update(value=next_text, interactive=active and next_index!=index), render_rich_text(state["help"], legacy_commands=True) if state.get("help") else "",
                gr.update(visible=active and state.get("assist", False)),
                gr.update(choices=[(f'{item["title"]} · {item["process"]}', str(item["hwnd"])) for item in state.get("windows", [])], value=state.get("window")),
                gr.update(choices=[(item["name"], item["key"]) for item in items], value=state.get("control") if any(item["key"] == state.get("control") for item in items) else None),
                gr.update(value=False, label=label, interactive=bool(pending)), gr.update(interactive=bool(pending)),
                gr.update(value=False, label=f"本次允许发送控件名称给 {destination} 定位（不含截图或输入内容）"),
                gr.update(visible=active and state.get("screen", False)), gr.update(visible=bool(items)), gr.update(visible=bool(pending)),
                gr.update(visible=active and index>=0), gr.update(visible=active and bool(state.get("environment", {}).get("items"))))
