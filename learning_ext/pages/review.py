from __future__ import annotations
import logging
from datetime import datetime
from learning_ext.presentation import project_display_name, project_choices
import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select
from learning_ext.db.models import LearningProject, KnowledgeNode, Card
from learning_ext.fsrs_review.service import (
    get_due_cards,
    get_review_stats,
    review_card,
    generate_cards_from_node,
)

logger = logging.getLogger(__name__)


class ReviewPage(BasePage):
    def __init__(self, app):
        super().__init__(app)
        self.current_card_id = gr.State(None)
        self.revealed = gr.State(False)

    def on_building_ui(self):
        gr.Markdown(
            "# 今日复习\n先回忆，再查看答案。根据回忆难度评分，安排下一次相遇。"
        )
        with gr.Column(elem_id="le-review-flow"):
            with gr.Row():
                self.project = gr.Dropdown(
                    label="学习项目", choices=[], interactive=True, scale=3
                )
                self.refresh = gr.Button("刷新项目", scale=1)
                self.btn_load = gr.Button("开始 / 下一张 →", variant="primary", scale=2)
            self.stats = gr.Markdown("")
            self.card_front = gr.Markdown(
                "选择项目，开始今天的复习。", elem_id="le-review-card"
            )
            self.card_back = gr.Markdown("", visible=False, elem_id="le-review-answer")
            self.reveal = gr.Button("显示答案", interactive=False)
            with gr.Row():
                self.ratings = [
                    gr.Button(
                        label,
                        interactive=False,
                        variant="primary" if n == 3 else "secondary",
                    )
                    for n, label in enumerate(
                        [
                            "重来 · 没有想起",
                            "困难 · 勉强想起",
                            "良好 · 正常回忆",
                            "简单 · 轻松掌握",
                        ],
                        1,
                    )
                ]
            self.status = gr.Markdown("")
            with gr.Accordion("添加复习卡片", open=False):
                gr.Markdown("从当前项目的知识点提炼卡片，也可以写下自己的问题和答案。")
                self.node = gr.Dropdown(label="知识点", choices=[], interactive=True)
                self.generate = gr.Button("AI 提炼 5 张卡片", variant="primary")
                self.front = gr.Textbox(label="问题", lines=2)
                self.back = gr.Textbox(label="答案", lines=3)
                self.add = gr.Button("保存自定义卡片")
                self.add_status = gr.Markdown("")

    def on_register_events(self):
        self._app.app.load(self._projects, outputs=self.project)
        self.refresh.click(self._projects, outputs=self.project)
        self.project.change(self._nodes, [self.project], [self.node]).then(
            self._load_next, [self.project], self._outputs()
        )
        self.btn_load.click(self._load_next, [self.project], self._outputs())
        self.reveal.click(
            lambda: (
                gr.update(visible=True),
                True,
                *[gr.update(interactive=True) for _ in range(4)],
            ),
            outputs=[self.card_back, self.revealed, *self.ratings],
        )
        for rating, button in enumerate(self.ratings, 1):
            button.click(
                lambda cid, shown, pid, rating=rating: self._rate(
                    cid, shown, pid, rating
                ),
                [self.current_card_id, self.revealed, self.project],
                self._outputs(),
                concurrency_id="review-rating",
                concurrency_limit=1,
            )
        self.generate.click(self._generate, [self.node], [self.add_status]).then(
            self._load_next, [self.project], self._outputs()
        )
        self.add.click(
            self._add, [self.node, self.front, self.back], [self.add_status]
        ).then(self._load_next, [self.project], self._outputs())

    def _outputs(self):
        return [
            self.card_front,
            self.card_back,
            self.current_card_id,
            self.revealed,
            self.stats,
            self.status,
            self.reveal,
            *self.ratings,
        ]

    def _projects(self):
        with Session(engine) as session:
            ps = session.exec(
                select(LearningProject)
                .where(LearningProject.user_id == "default")
                .order_by(LearningProject.updated_at.desc())
            ).all()
            return gr.update(
                choices=project_choices(ps),
                value=str(ps[0].id) if ps else None,
            )

    def _nodes(self, pid):
        with Session(engine) as session:
            ns = (
                session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.project_id == int(pid))
                ).all()
                if pid
                else []
            )
            return gr.update(
                choices=[(f"{n.code} · {n.title}", str(n.id)) for n in ns],
                value=str(ns[0].id) if ns else None,
            )

    def _load_next(self, pid=None, notice=""):
        with Session(engine) as session:
            stats = get_review_stats(session, project_id=int(pid) if pid else None)
            cards = get_due_cards(
                session, project_id=int(pid) if pid else None, limit=1
            )
            card = cards[0] if cards else None
            front = (
                card.front
                if card
                else (
                    "本轮复习完成。下次到期时再来回顾。"
                    if stats["total_cards"]
                    else "还没有复习卡片。在下方选择知识点，提炼或添加第一张卡片。"
                )
            )
            return (
                front,
                gr.update(value=card.back if card else "", visible=False),
                card.id if card else None,
                False,
                f"**待复习 {stats['due_count']}**　/　卡片总数 {stats['total_cards']}",
                notice,
                gr.update(interactive=bool(card)),
                *[gr.update(interactive=False) for _ in range(4)],
            )

    def _rate(self, cid, shown, pid, rating):
        if not cid or not shown:
            return self._load_next(pid, "请先显示答案，再根据回忆情况评分。")
        try:
            with Session(engine) as session:
                card = session.get(Card, int(cid))
                if not card or card.user_id != "default":
                    raise ValueError("卡片不可用")
                if pid and card.project_id != int(pid):
                    raise ValueError("卡片不属于当前项目")
                if card.suspended or card.next_review > datetime.utcnow():
                    return self._load_next(pid, "这张卡片已安排下次复习。")
                review_card(session, int(cid), rating, "default")
            return self._load_next(pid, "评分已保存，下次复习时间已更新。")
        except Exception:
            logger.exception("评分失败")
            return self._load_next(pid, "评分失败，请重试。")

    def _get_node(self, session, nid):
        if not nid:
            raise ValueError("请先选择知识点")
        node = session.get(KnowledgeNode, int(nid))
        project = session.get(LearningProject, node.project_id) if node else None
        if not project or project.user_id != "default":
            raise ValueError("知识点不可用")
        return node

    def _generate(self, nid):
        try:
            with Session(engine) as session:
                node = self._get_node(session, nid)
                cards = generate_cards_from_node(
                    session, node.id, "default", node.description, count=5
                )
                return (
                    f"已保存 {len(cards)} 张卡片。"
                    if cards
                    else "模型未返回有效卡片，可以重试或手动添加。"
                )
        except Exception:
            logger.exception("提炼卡片失败")
            return "请先选择知识点，并检查模型配置后重试。"

    def _add(self, nid, front, back):
        if not front.strip() or not back.strip():
            return "问题和答案都需要填写。"
        try:
            with Session(engine) as session:
                node = self._get_node(session, nid)
                session.add(
                    Card(
                        user_id="default",
                        project_id=node.project_id,
                        node_id=node.id,
                        front=front.strip(),
                        back=back.strip(),
                    )
                )
                session.commit()
            return "卡片已保存，可开始复习。"
        except Exception:
            logger.exception("保存卡片失败")
            return "保存失败，请先选择有效的知识点。"
