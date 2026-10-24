"""间隔复习页。

流程按「先选复习哪一节 → 再开始」来排：
    项目 → 复习哪一节 → 开始复习 → 看题 → 显示答案 → 评分 → 下一张

以前是把「选知识点 + AI 提炼卡片」塞在页面最底下的折叠面板里，
复习进度却在顶部，用户得在两头来回跑。现在选范围、生成卡片、开始复习
都在同一块区域，卡片区只负责出题和评分。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import Card, KnowledgeNode, LearningProject
from learning_ext.fsrs_review.service import (
    cards_per_node,
    generate_cards_from_node,
    get_due_cards,
    get_review_stats,
    review_card,
)
from learning_ext.presentation import project_choices

logger = logging.getLogger(__name__)

ALL_NODES = "__all__"   # 「全部章节」这个选项的值


def _md_safe(text: str) -> str:
    """Markdown 里连续下划线会被当成粗体/斜体，填空题的挖空就消失了。

    展示前把下划线转义掉，存储保持原样（导出、其他视图都不受影响）。
    """
    return re.sub(r"_{2,}", lambda m: "\\_" * min(len(m.group()), 12), text or "")


def _local_date(dt) -> str:
    """UTC 时间转成本地「几月几日」；取不到就说「之后」。"""
    if not dt:
        return "之后"
    try:
        return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%m 月 %d 日")
    except Exception:
        return "之后"


class ReviewPage(BasePage):
    def __init__(self, app):
        super().__init__(app)
        self.current_card_id = gr.State(None)
        self.revealed = gr.State(False)

    # ==================== UI ====================

    def on_building_ui(self):
        gr.Markdown(
            "# 今日复习\n先选要复习的那一节，再开始。先回忆，再看答案，最后按难度评分。"
        )
        with gr.Column(elem_id="le-review-flow"):
            with gr.Row(elem_id="le-review-scope"):
                self.project = gr.Dropdown(
                    label="学习项目",
                    choices=[],
                    interactive=True,
                    scale=3.6,
                    # 两个下拉都带一行说明，标签和输入框才能在一条线上对齐；
                    # 只有一个带 info 时，它的标签会被自己的说明顶高一截。
                    info="先选项目，下一栏才有可复习的章节。",
                )
                self.node = gr.Dropdown(
                    label="复习哪一节",
                    choices=[],
                    value=None,
                    interactive=True,
                    scale=4,
                    info="选一节只复习这一节；也可以选「全部章节」一次刷完。",
                )
                self.btn_start = gr.Button(
                    "开始复习 →", variant="primary", scale=1.5, elem_id="le-review-start"
                )
            self.stats = gr.Markdown("", elem_id="le-review-stats")
            self.card_front = gr.Markdown(
                "选好项目与章节，点「开始复习」。", elem_id="le-review-card"
            )
            self.card_back = gr.Markdown("", visible=False, elem_id="le-review-answer")
            with gr.Row(elem_id="le-review-actions"):
                self.reveal = gr.Button("显示答案", interactive=False)
                self.gen_cards = gr.Button(
                    "为这一节生成 5 张卡", variant="secondary", visible=False
                )
            with gr.Row(elem_id="le-review-ratings"):
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
            self.status = gr.Markdown("", elem_id="le-review-status")
            with gr.Accordion("手动写一张卡片", open=False):
                gr.Markdown("给当前选中的这一节加一张自己的问答卡。")
                self.front = gr.Textbox(label="问题", lines=2)
                self.back = gr.Textbox(label="答案", lines=3)
                self.add = gr.Button("保存这张卡", size="sm")
                self.add_status = gr.Markdown("")

    # ==================== 事件 ====================

    def on_register_events(self):
        self._app.app.load(self._bootstrap, outputs=[self.project, self.node])
        self.project.change(
            self._on_project_change,
            [self.project],
            [self.node, *self._outputs()],
        )
        self.node.change(
            self._preview,
            [self.project, self.node],
            self._outputs(),
        )
        self.btn_start.click(
            self._start,
            [self.project, self.node],
            self._outputs(),
        )
        self.reveal.click(
            self._reveal_answer,
            [self.card_back],
            [self.card_back, self.revealed, *self.ratings],
        )
        for rating, button in enumerate(self.ratings, 1):
            button.click(
                lambda cid, shown, pid, nid, rating=rating: self._rate(
                    cid, shown, pid, nid, rating
                ),
                [self.current_card_id, self.revealed, self.project, self.node],
                self._outputs(),
                concurrency_id="review-rating",
                concurrency_limit=1,
            )
        self.gen_cards.click(
            self._generate,
            [self.project, self.node],
            self._outputs(),
        )
        self.add.click(self._add, [self.node, self.front, self.back], [self.add_status])

    def _outputs(self):
        return [
            self.card_front,
            self.card_back,
            self.current_card_id,
            self.revealed,
            self.stats,
            self.status,
            self.reveal,
            self.gen_cards,
            *self.ratings,
        ]

    # ==================== 数据 ====================

    def _bootstrap(self):
        """页面加载：填项目，并按第一个项目填好章节列表。"""
        with Session(engine) as session:
            ps = session.exec(
                select(LearningProject)
                .where(LearningProject.user_id == "default")
                .order_by(LearningProject.updated_at.desc())
            ).all()
        if not ps:
            return (
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
            )
        pid = ps[0].id
        return (
            gr.update(choices=project_choices(ps), value=str(pid)),
            self._node_choices(pid),
        )

    def _node_choices(self, pid):
        """章节下拉：每项后面标这一节有几张卡，一眼看出哪节能复习。"""
        if not pid:
            return gr.update(choices=[], value=None)
        with Session(engine) as session:
            ns = session.exec(
                select(KnowledgeNode)
                .where(KnowledgeNode.project_id == int(pid))
                .order_by(KnowledgeNode.code)
            ).all()
            counts = cards_per_node(session, int(pid))
        choices = [("全部章节", ALL_NODES)]
        for n in ns:
            cnt = counts.get(n.id, 0)
            tail = f"{cnt} 张" if cnt else "还没卡片"
            choices.append((f"{n.code} · {n.title}　·　{tail}", str(n.id)))
        # 默认落到「全部章节」，想按节复习自己选
        return gr.update(choices=choices, value=ALL_NODES)

    def _on_project_change(self, pid):
        node_update = self._node_choices(pid)
        return (node_update, *self._render(pid, ALL_NODES, peek=True))

    # ==================== 取卡 ====================

    @staticmethod
    def _scope(pid, nid):
        """把下拉值翻译成过滤条件：(project_id, node_id)。"""
        pid_i = int(pid) if pid else None
        nid_i = int(nid) if nid and nid != ALL_NODES else None
        return pid_i, nid_i

    def _load_next(self, pid, nid, notice=""):
        pid_i, nid_i = self._scope(pid, nid)
        with Session(engine) as session:
            stats = get_review_stats(session, project_id=pid_i, node_id=nid_i)
            cards = get_due_cards(session, project_id=pid_i, node_id=nid_i, limit=1)
            card = cards[0] if cards else None
        return self._render(
            pid, nid, notice=notice, stats=stats, card=card, peek=False
        )

    def _preview(self, pid, nid):
        """选章节时只更新统计与提示，不直接出卡（用户点「开始」才开始）。"""
        pid_i, nid_i = self._scope(pid, nid)
        with Session(engine) as session:
            stats = get_review_stats(session, project_id=pid_i, node_id=nid_i)
        return self._render(pid, nid, stats=stats, peek=True)

    def _start(self, pid, nid):
        if not pid:
            return self._render(pid, nid, notice="先选一个学习项目。", peek=True)
        if not nid:
            return self._render(pid, nid, notice="先选要复习哪一节。", peek=True)
        return self._load_next(pid, nid)

    def _render(self, pid, nid, *, notice="", stats=None, card=None, peek=False):
        pid_i, nid_i = self._scope(pid, nid)
        if stats is None:
            with Session(engine) as session:
                stats = get_review_stats(session, project_id=pid_i, node_id=nid_i)

        due = stats["due_count"]
        total = stats["total_cards"]
        scope_txt = "这一节" if nid_i else "本项目"
        stats_md = f"**待复习 {due}**　·　{scope_txt}共 {total} 张卡"

        # 空状态分三种：没有卡 / 卡都排好了 / 回到「请开始」
        need_cards = total == 0 and pid_i is not None
        if card is not None:
            front = _md_safe(card.front)
            back = gr.update(value=_md_safe(card.back), visible=False)
            reveal_btn = gr.update(interactive=True, visible=True)
        elif peek:
            if need_cards:
                front = (
                    "这一节还没有复习卡片，点下方「为这一节生成 5 张卡」。"
                    if nid_i
                    else "这个项目还没有复习卡片，先在上方选一节。"
                )
            elif due == 0:
                front = f"这一节暂时没有到期卡片，下次到期：{_local_date(stats.get('next_due'))}。"
            else:
                front = f"有 {due} 张卡等着复习，点右上角「开始复习 →」。"
            back = gr.update(value="", visible=False)
            reveal_btn = gr.update(interactive=False)
        else:
            if due == 0:
                front = (
                    "这一节暂时没有到期的卡片了。"
                    if total
                    else "这一节还没有复习卡片，点下方「为这一节生成 5 张卡」。"
                )
            else:
                front = "没有取到卡片，可以再点一次「开始复习」。"
            back = gr.update(value="", visible=False)
            reveal_btn = gr.update(interactive=False)

        # 「生成卡片」只在没有卡、且选定具体某一节时露出来
        gen_btn = gr.update(visible=bool(need_cards and nid_i))
        # 没卡可复习时，收起「显示答案」和评分，避免空页面上摆一排灰按钮。
        # 注意：不要再动态改「开始复习」这个按钮——Gradio 会把它的更新错位到
        # 后面第一个按钮（评分第一颗）上，实测过。文案引导交给卡片区。
        has_card = card is not None
        reveal_btn = gr.update(interactive=has_card, visible=has_card)

        return (
            front,
            back,
            card.id if card else None,
            False,
            stats_md,
            notice,
            reveal_btn,
            gen_btn,
            *[gr.update(interactive=False, visible=has_card) for _ in range(4)],
        )

    def _reveal_answer(self, back):
        return (
            gr.update(visible=True),
            True,
            *[gr.update(interactive=True) for _ in range(4)],
        )

    # ==================== 评分 ====================

    def _rate(self, cid, shown, pid, nid, rating):
        if not cid or not shown:
            return self._load_next(pid, nid, "请先点「显示答案」，再按回忆难度评分。")
        try:
            with Session(engine) as session:
                card = session.get(Card, int(cid))
                if not card or card.user_id != "default":
                    raise ValueError("卡片不可用")
                if card.suspended or card.next_review > datetime.utcnow():
                    return self._load_next(pid, nid, "这张卡已安排好下次复习。")
                review_card(session, int(cid), rating, "default")
            return self._load_next(pid, nid, "评分已保存，下次复习时间已更新。")
        except Exception:
            logger.exception("评分失败")
            return self._load_next(pid, nid, "评分失败，请重试。")

    # ==================== 生成 / 手写 ====================

    def _get_node(self, session, nid):
        if not nid or nid == ALL_NODES:
            raise ValueError("请先选具体的某一节")
        node = session.get(KnowledgeNode, int(nid))
        project = session.get(LearningProject, node.project_id) if node else None
        if not project or project.user_id != "default":
            raise ValueError("知识点不可用")
        return node

    def _generate(self, pid, nid):
        """按当前选中的这一节提炼卡片，生成完直接出第一张。"""
        try:
            with Session(engine) as session:
                node = self._get_node(session, nid)
                cards = generate_cards_from_node(
                    session, node.id, "default", node.description, count=5
                )
                made = len(cards)
        except Exception:
            logger.exception("提炼卡片失败")
            return self._render(
                pid, nid, notice="生成失败：请先选具体某一节，并检查模型配置。", peek=True
            )
        notice = f"已为「{node.title}」生成 {made} 张卡。" if made else "模型没有返回有效卡片，可以重试或手写一张。"
        return self._load_next(pid, nid, notice) if made else self._render(
            pid, nid, notice=notice, peek=True
        )

    def _add(self, nid, front, back):
        if not front.strip() or not back.strip():
            return "问题和答案都要填。"
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
            return "已保存。点「开始复习」就能看到它。"
        except Exception:
            logger.exception("保存卡片失败")
            return "保存失败：请先在右上角选中具体的某一节。"
