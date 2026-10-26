"""全局 AI 助教：一份对话，跨页面共用。

面板挂在应用根级（Tabs 之外），由前端脚本以固定浮层呈现，
因此切换标签时对话和内容都不会丢；上下文按当前所在页面自动切换：
学习工作台=当前知识点、间隔复习=当前卡片、查漏测验=当前题目。
"""

from __future__ import annotations

import logging

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session

from learning_ext.db.models import (
    Card,
    KnowledgeNode,
    LearningProject,
    QuizQuestion,
)

logger = logging.getLogger(__name__)

HEADING_HTML = (
    '<div class="le-assistant-heading">'
    '<div class="le-assistant-identity"><span class="le-assistant-avatar" aria-hidden="true"></span>'
    '<div><span class="le-kicker">STUDY COMPANION</span><h3>以太小助</h3></div></div>'
    '<button data-le-assistant-close aria-label="关闭以太小助">×</button>'
    "</div>"
)

EMPTY_HTML = (
    '<div class="le-assistant-empty-inner">'
    '<div class="le-assistant-context">'
    '<span data-le-assistant-context-label>以太小助 · 学习助手</span>'
    '<strong data-le-assistant-context-title>学习规划、理解与复习</strong>'
    '<p data-le-assistant-context-detail hidden></p>'
    "</div>"
    '<div class="le-assistant-quick-list">'
    '<button type="button" data-le-assistant-suggestion>帮我拆解一个学习目标</button>'
    '<button type="button" data-le-assistant-suggestion>怎样安排今天的学习？</button>'
    '<button type="button" data-le-assistant-suggestion>帮我检查自己的理解</button>'
    "</div></div>"
)

SYSTEM_PROMPT = (
    "你是耐心的学习助教。基于学习者当前正在看的知识点、复习卡片或测验题目，"
    "解答疑问、纠正误解、补充知识。"
)

WORKBENCH_TAB = "learning-workbench-tab"


class GlobalAssistant(BasePage):
    """跨页面共用的 AI 助教面板与事件。"""

    def __init__(self, app):
        super().__init__(app)
        self.history = gr.State([])
        self.active_tab = gr.State(WORKBENCH_TAB)

    # ---------------- UI ----------------
    def on_building_ui(self):
        with gr.Column(elem_id="le-global-assistant") as self.panel:
            gr.HTML(HEADING_HTML)
            gr.Markdown(
                "围绕你正在看的内容提问。", elem_classes=["le-caption"]
            )
            self.empty_state = gr.HTML(EMPTY_HTML, elem_id="le-assistant-empty")
            self.chatbot = gr.Chatbot(
                label="",
                height=340,
                show_label=False,
                type="messages",
                elem_id="le-assistant-chat",
            )
            with gr.Row(elem_id="le-chat-compose"):
                self.chat_input = gr.Textbox(
                    label="向助教提问",
                    placeholder="回车发送 · Shift 换行",
                    show_label=False,
                    lines=2,
                    scale=4,
                    elem_id="le-chat-input",
                )
                self.chat_send_btn = gr.Button(
                    "发送",
                    variant="primary",
                    size="sm",
                    scale=0,
                    min_width=64,
                    elem_id="le-chat-send",
                )
            with gr.Accordion("对话操作", open=False, elem_id="le-assistant-ops"):
                self.append_btn = gr.Button("将最近回复加入课程", size="sm")
                self.clear_btn = gr.Button("清空对话", size="sm")
                self.status = gr.Markdown("")

    # ---------------- 事件 ----------------
    def on_register_events(self):
        tabs = getattr(self._app, "tabs", None)
        if tabs is not None:
            tabs.select(self._on_tab_select, outputs=self.active_tab)

        chat_io = [self.chatbot, self.history, self.chat_input]
        inputs = [self.chat_input, self.history, *self._context_inputs()]
        self.chat_send_btn.click(self._send, inputs, chat_io)
        self.chat_input.submit(self._send, inputs, chat_io)
        self.clear_btn.click(lambda: ([], [], ""), outputs=chat_io)

        # 「加入课程」仍由工作台实现（它要写回节点正文），这里只换绑输入
        wb = getattr(self._app, "learning_workbench_page", None)
        if wb is not None and hasattr(wb, "current_node_id"):
            self.append_btn.click(
                wb._append_last_assistant_to_node,
                [wb.current_node_id, self.history],
                [wb.node_guide, self.status],
            )

    def _context_inputs(self):
        """各页面用于提供上下文的组件（顺序与 _send 形参一致）。"""
        app = self._app
        wb = getattr(app, "learning_workbench_page", None)
        rv = getattr(app, "learning_review_page", None)
        qz = getattr(app, "learning_quiz_page", None)
        return [
            self.active_tab,
            getattr(wb, "current_node_id", None),
            getattr(rv, "current_card_id", None),
            getattr(qz, "question_ids", None),
            getattr(qz, "question_index", None),
        ]

    @staticmethod
    def _on_tab_select(evt: gr.SelectData):
        value = getattr(evt, "value", None)
        return str(value) if value else WORKBENCH_TAB

    # ---------------- 对话 ----------------
    def _send(self, message, history, active_tab, wb_node, rv_card, qz_ids, qz_index):
        if not message or not message.strip():
            yield history, history, ""
            return
        user_msg = message.strip()
        new_history = (history or []) + [{"role": "user", "content": user_msg}]
        yield new_history, new_history, ""
        try:
            from learning_ext.llm import chat

            ctx = self._resolve_context(active_tab, wb_node, rv_card, qz_ids, qz_index)
            ctx += "【对话历史】\n"
            for h in (history or [])[-6:]:
                role = "学习者" if h.get("role") == "user" else "助教"
                ctx += f"{role}: {(h.get('content') or '')[:300]}\n"
            ctx += (
                f"\n【学习者最新消息】{user_msg}\n\n"
                "请基于上面的内容回答。如材料有误或需补充，明确指出。Markdown，500 字内。"
            )
            reply = chat(ctx, system=SYSTEM_PROMPT, temperature=0.4, purpose="qa")
            final = new_history + [{"role": "assistant", "content": reply}]
            yield final, final, ""
        except Exception as e:
            logger.exception("助教回复失败")
            err = new_history + [{"role": "assistant", "content": f"❌ 出错了: {e}"}]
            yield err, err, ""

    def _resolve_context(self, active_tab, wb_node, rv_card, qz_ids, qz_index) -> str:
        """按当前页面取上下文；识别不出来或该页暂无内容时，按可用顺序兜底。"""
        tab = str(active_tab or "")

        def kind_of(value: str):
            if "workbench" in value or "工作台" in value:
                return "workbench"
            if "review" in value or "复习" in value:
                return "review"
            if "quiz" in value or "测验" in value:
                return "quiz"
            return None

        active = kind_of(tab)
        order = [k for k in (active,) if k] + [
            k for k in ("workbench", "review", "quiz") if k != active
        ]

        for kind in order:
            try:
                text = self._context_for(kind, wb_node, rv_card, qz_ids, qz_index)
            except Exception:
                logger.exception("解析助教上下文失败 (%s)", kind)
                text = None
            if text:
                return text
        return "【当前页面】通用\n"

    def _context_for(self, kind, wb_node, rv_card, qz_ids, qz_index):
        if kind == "workbench" and wb_node:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(wb_node))
                proj = s.get(LearningProject, node.project_id) if node else None
            if node:
                return (
                    "【当前页面】学习工作台\n"
                    f"【学习主题】{proj.topic if proj else ''}\n"
                    f"【当前知识点】{node.title} ({node.code})\n"
                    f"【教学内容摘要】\n{(node.description or '')[:2000]}\n\n"
                )
        elif kind == "review" and rv_card:
            with Session(engine) as s:
                card = s.get(Card, int(rv_card))
            if card:
                return (
                    "【当前页面】间隔复习\n"
                    f"【正在复习的卡片】\n问题：{card.front}\n答案：{card.back}\n\n"
                )
        elif kind == "quiz" and qz_ids:
            idx = int(qz_index or 0)
            if 0 <= idx < len(qz_ids):
                with Session(engine) as s:
                    q = s.get(QuizQuestion, qz_ids[idx])
                if q:
                    return (
                        f"【当前页面】查漏测验（第 {idx + 1} 题）\n"
                        f"【题目】{q.stem}\n"
                        f"【参考答案】{q.answer}\n"
                        f"【解析】{q.explanation}\n\n"
                    )
        return None
