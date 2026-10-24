from __future__ import annotations

import json
import logging
from learning_ext.presentation import project_display_name, project_choices
import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select
from learning_ext.db.models import (
    LearningProject,
    KnowledgeNode,
    Quiz,
    QuizQuestion,
    QuizAttempt,
)
from learning_ext.quiz.service import generate_quiz, grade_answer

logger = logging.getLogger(__name__)


_STATUS_CN = {
    "pending": "待学",
    "learning": "学习中",
    "reviewing": "复习中",
    "mastered": "已掌握",
    "weak": "薄弱",
    "skipped": "已跳过",
}


def _code_key(code: str):
    """'1.10' 要排在 '1.9' 后面，不能按字符串比。"""
    parts = []
    for seg in str(code or "").split("."):
        try:
            parts.append(int(seg))
        except ValueError:
            parts.append(0)
    return parts


def _chapter_of(code: str) -> str:
    return str(code or "").split(".")[0]


def _chapter_key(ch: str):
    return _code_key(ch)


class QuizPage(BasePage):
    def __init__(self, app):
        super().__init__(app)
        self.question_ids = gr.State([])
        self.question_index = gr.State(0)

    def on_building_ui(self):
        gr.Markdown(
            "# 检验你的理解\n选定项目，完成一组练习。逐题查看解析，找到需要回顾的知识点。"
        )
        with gr.Row(elem_id="le-quiz-flow"):
            with gr.Column(elem_id="le-quiz-settings", scale=1, min_width=280):
                gr.Markdown("### 测验设置\n选择学习范围，再决定练习方式。")
                self.project_id = gr.Dropdown(label="学习项目", choices=[], interactive=True)
                self.refresh = gr.Button("更新项目列表", size="sm", elem_id="le-quiz-refresh")
                # 测什么比测几道更重要：先定范围，再定题型。
                self.scope = gr.Radio(
                    label="测试范围",
                    choices=[
                        ("某一节", "section"),
                        ("某一章", "chapter"),
                        ("全部内容", "all"),
                        ("按学习进度", "progress"),
                    ],
                    value="all",
                    elem_id="le-quiz-scope",
                )
                self.node_pick = gr.Dropdown(
                    label="选哪一节", choices=[], visible=False, interactive=True
                )
                self.chapter_pick = gr.Dropdown(
                    label="选哪一章", choices=[], visible=False, interactive=True
                )
                self.progress_pick = gr.Dropdown(
                    label="测哪一批",
                    choices=[
                        ("只测已学过的", "learned"),
                        ("只测薄弱的", "weak"),
                        ("最近学的 10 节", "recent"),
                        ("只测还没学的", "pending"),
                    ],
                    value="learned",
                    visible=False,
                    interactive=True,
                )
                self.count = gr.Slider(label="题目数量", minimum=1, maximum=20, value=5, step=1)
                self.qtype = gr.Dropdown(label="题型", choices=[("混合", "mixed"), ("选择", "choice"), ("填空", "fill"), ("简答", "short"), ("实操", "practice")], value="mixed")
                self.btn_gen = gr.Button("开始测验 →", variant="primary")
                with gr.Accordion("继续上次测验", open=False):
                    gr.Markdown("载入当前项目上次未完成的测验。")
                    self.resume = gr.Button("继续作答")
            with gr.Column(elem_id="le-quiz-answer", scale=2, min_width=360):
                gr.Markdown("### 题目与作答")
                self.status = gr.Markdown("先在左侧选择学习项目，然后开始测验。")
                self.question = gr.Markdown("准备好后，题目将在这里显示。", elem_id="le-quiz-question")
                self.choices = gr.Radio(label="选择答案", choices=[], visible=False, interactive=True)
                self.answer = gr.Textbox(label="你的回答", placeholder="写下你的理解、推导过程或操作步骤…", lines=5)
                with gr.Row(elem_id="le-quiz-actions"):
                    self.submit = gr.Button("提交并查看解析", variant="primary", interactive=False)
                    self.next = gr.Button("下一题 →", interactive=False)
                self.feedback = gr.Markdown("")
                with gr.Accordion("作答记录", open=False):
                    self.history = gr.Markdown("完成测验后可在这里查看本轮记录。")

    def on_register_events(self):
        self.refresh.click(self._projects, outputs=self.project_id).then(
            self._on_project,
            [self.project_id],
            [self.node_pick, self.chapter_pick],
        )
        self._app.app.load(self._projects, outputs=self.project_id).then(
            self._on_project,
            [self.project_id],
            [self.node_pick, self.chapter_pick],
        )
        self.project_id.change(
            self._on_project,
            [self.project_id],
            [self.node_pick, self.chapter_pick],
        )
        # 选「某一节 / 某一章 / 按进度」时才显示对应的二级下拉
        self.scope.change(
            self._on_scope,
            [self.scope],
            [self.node_pick, self.chapter_pick, self.progress_pick],
        )
        self.btn_gen.click(
            self._generate,
            [
                self.project_id,
                self.scope,
                self.node_pick,
                self.chapter_pick,
                self.progress_pick,
                self.count,
                self.qtype,
            ],
            [self.question_ids, self.question_index, self.status],
        ).then(
            self._display, [self.question_ids, self.question_index], self._outputs()
        ).then(
            lambda: "尚未作答。", outputs=[self.history]
        )
        self.resume.click(
            self._resume,
            [self.project_id],
            [self.question_ids, self.question_index, self.status, self.history],
        ).then(self._display, [self.question_ids, self.question_index], self._outputs())
        self.submit.click(
            self._submit,
            [self.question_ids, self.question_index, self.choices, self.answer],
            [self.feedback, self.submit, self.next, self.history],
            concurrency_limit=1,
        )
        self.next.click(
            lambda i: i + 1, [self.question_index], [self.question_index]
        ).then(self._display, [self.question_ids, self.question_index], self._outputs())

    def _outputs(self):
        return [
            self.question,
            self.choices,
            self.answer,
            self.feedback,
            self.submit,
            self.next,
        ]

    def _projects(self):
        with Session(engine) as session:
            projects = session.exec(
                select(LearningProject)
                .where(LearningProject.user_id == "default")
                .order_by(LearningProject.updated_at.desc())
            ).all()
            return gr.update(
                choices=project_choices(projects),
                value=str(projects[0].id) if projects else None,
            )

    def _on_project(self, pid):
        """换了项目就重建「节」和「章」两个下拉。"""
        if not pid:
            return (
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
            )
        try:
            with Session(engine) as session:
                nodes = session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.project_id == int(pid))
                ).all()
        except Exception:
            logger.exception("读取测验范围失败")
            return (
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
            )
        ordered = sorted(nodes, key=lambda n: _code_key(n.code))
        node_choices = [
            (f"{n.code} · {n.title} · {_STATUS_CN.get(n.status, n.status)}", n.code)
            for n in ordered
        ]
        chapters: dict[str, list[KnowledgeNode]] = {}
        for n in ordered:
            chapters.setdefault(_chapter_of(n.code), []).append(n)
        chapter_choices = [
            (f"第 {ch} 章 · {chapters[ch][0].title[:14]} · {len(chapters[ch])} 节", ch)
            for ch in sorted(chapters, key=_chapter_key)
        ]
        return (
            gr.update(
                choices=node_choices,
                value=node_choices[0][1] if node_choices else None,
            ),
            gr.update(
                choices=chapter_choices,
                value=chapter_choices[0][1] if chapter_choices else None,
            ),
        )

    def _on_scope(self, scope):
        return (
            gr.update(visible=scope == "section"),
            gr.update(visible=scope == "chapter"),
            gr.update(visible=scope == "progress"),
        )

    def _pick_nodes(self, nodes, scope, node_code, chapter, progress_mode):
        """按选定范围挑出要出题的节点。"""
        learned = ("mastered", "learning", "reviewing")
        if scope == "section":
            return [n for n in nodes if n.code == node_code]
        if scope == "chapter":
            return [n for n in nodes if _chapter_of(n.code) == str(chapter)]
        if scope == "progress":
            if progress_mode == "learned":
                return [n for n in nodes if n.status in learned]
            if progress_mode == "weak":
                return [
                    n
                    for n in nodes
                    if n.status == "weak"
                    or (
                        n.status in ("learning", "reviewing", "mastered")
                        and (n.mastery or 0) < 0.5
                    )
                ]
            if progress_mode == "pending":
                return [n for n in nodes if n.status == "pending"]
            if progress_mode == "recent":
                done = [n for n in nodes if n.status in learned]
                return sorted(done, key=lambda n: n.id or 0, reverse=True)[:10]
            return nodes
        return nodes

    def _generate(
        self, project_id, scope, node_code, chapter, progress_mode, count, qtype
    ):
        if not project_id:
            return [], 0, "请先创建并保存一条学习路线，再刷新项目。"
        scope = scope or "all"
        try:
            with Session(engine) as session:
                p = session.get(LearningProject, int(project_id))
                if not p or p.user_id != "default":
                    raise ValueError("学习项目不可用")
                all_nodes = session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.project_id == p.id)
                ).all()
                if not all_nodes:
                    raise ValueError("这个项目还没有知识点，请先保存学习路线")

                ordered = sorted(all_nodes, key=lambda n: _code_key(n.code))
                picked = self._pick_nodes(
                    ordered, scope, node_code, chapter, progress_mode
                )
                if not picked:
                    hint = {
                        "section": "这一节还没有内容，换一节试试。",
                        "chapter": "这一章还没有内容，换一章试试。",
                        "progress": {
                            "learned": "还没有学过的章节，先学一节再来。",
                            "weak": "暂时没有薄弱的章节，说明学得挺稳。",
                            "recent": "还没有学过的章节，先学一节再来。",
                            "pending": "没有待学的章节了，这个项目已经全部过完。",
                        }.get(progress_mode, "这个范围里没有可出题的章节。"),
                    }.get(scope, "这个范围里没有可出题的章节。")
                    raise ValueError(hint)

                # 一章十几节全塞给出题模型，题只会浮在表面。按题数限制节点数，
                # 多出来的按掌握度升序优先——查漏就该先考最不熟的那几节。
                limit = max(3, min(int(count), 6))
                if len(picked) > limit:
                    picked = sorted(
                        picked, key=lambda n: (n.mastery or 0, _code_key(n.code))
                    )[:limit]
                picked = sorted(picked, key=lambda n: _code_key(n.code))

                quiz = generate_quiz(
                    session,
                    "default",
                    [n.id for n in picked],
                    project_id=p.id,
                    count=int(count),
                    qtype=qtype,
                )
                ids = [
                    q.id
                    for q in session.exec(
                        select(QuizQuestion)
                        .where(QuizQuestion.quiz_id == quiz.id)
                        .order_by(QuizQuestion.id)
                    ).all()
                ]
                covered = "、".join(n.code for n in picked)
                label = {
                    "section": "本节",
                    "chapter": f"第 {chapter} 章",
                    "all": "全部内容",
                    "progress": {
                        "learned": "已学过的",
                        "weak": "薄弱的",
                        "recent": "最近学的",
                        "pending": "还没学的",
                    }.get(progress_mode, "按进度"),
                }.get(scope, "全部内容")
                return (
                    ids,
                    0,
                    f"已按「{label}」出 {len(ids)} 道题，覆盖 {covered}。"
                    f"逐题作答后查看解析。",
                )
        except ValueError as e:
            logger.info("生成测验跳过: %s", e)
            return [], 0, f"⚠️ {e}"
        except Exception:
            logger.exception("生成测验失败")
            return [], 0, "生成失败。请检查模型配置与连接后重试；原有学习记录不受影响。"

    def _resume(self, pid):
        if not pid:
            return [], 0, "请先选择学习项目。", ""
        with Session(engine) as session:
            quiz = session.exec(
                select(Quiz)
                .where(Quiz.project_id == int(pid), Quiz.user_id == "default")
                .order_by(Quiz.id.desc())
            ).first()
            if not quiz:
                return [], 0, "这个项目还没有测验，请先生成。", ""
            ids = [
                q.id
                for q in session.exec(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_id == quiz.id)
                    .order_by(QuizQuestion.id)
                ).all()
            ]
            attempts = session.exec(
                select(QuizAttempt).where(
                    QuizAttempt.question_id.in_(ids), QuizAttempt.user_id == "default"
                )
            ).all()
            done = {a.question_id for a in attempts}
            index = next((i for i, qid in enumerate(ids) if qid not in done), len(ids))
            history = self._history(session, ids, attempts)
            return ids, index, "已载入最近的测验与作答记录。", history

    @staticmethod
    def _history(session, ids, attempts):
        score = sum(1 for a in attempts if a.is_correct)
        rows = [f"**已完成 {len(attempts)} / {len(ids)} · 正确 {score} 题**"]
        by_question = {a.question_id: a for a in attempts}
        for i, qid in enumerate(ids):
            if qid not in by_question:
                continue
            a = by_question[qid]
            q = session.get(QuizQuestion, qid)
            rows.append(
                f"### {i+1}. {q.stem}\n\n{'回答正确' if a.is_correct else '待巩固'} · 我的回答：{a.user_answer}\n\n{a.feedback}\n\n**参考答案**：{q.answer}\n\n{q.explanation}"
            )
        return "\n\n".join(rows)

    def _display(self, ids, index):
        if not ids or index < 0 or index >= len(ids):
            return (
                (
                    "本轮已完成。你可以回顾解析，或开始新的测验。"
                    if ids
                    else "生成测验后，题目将在这里显示。"
                ),
                gr.update(visible=False, value=None),
                gr.update(value="", visible=False),
                "",
                gr.update(interactive=False),
                gr.update(interactive=False),
            )
        with Session(engine) as session:
            q = session.get(QuizQuestion, ids[index])
            if not q:
                raise gr.Error("题目已不存在，请重新生成测验。")
            options = json.loads(q.options or "[]")
            choices = [(str(text), chr(65 + i)) for i, text in enumerate(options)]
            return (
                f"**{index+1:02d} / {len(ids):02d}**\n\n### {q.stem}",
                gr.update(visible=q.qtype == "choice", choices=choices, value=None),
                gr.update(visible=q.qtype != "choice", value=""),
                "",
                gr.update(interactive=True),
                gr.update(interactive=False),
            )

    def _submit(self, ids, index, choice, answer):
        if not ids or index < 0 or index >= len(ids):
            return (
                "请先生成测验。",
                gr.update(interactive=False),
                gr.update(interactive=False),
                gr.skip(),
            )
        try:
            with Session(engine) as session:
                q = session.get(QuizQuestion, ids[index])
                if not q:
                    raise ValueError("题目不存在")
                value = choice if q.qtype == "choice" else answer
                if not value or not value.strip():
                    return (
                        "请先填写答案。",
                        gr.update(interactive=True),
                        gr.update(interactive=False),
                        gr.skip(),
                    )
                attempt = grade_answer(session, q.id, value.strip())
                feedback = f"### {'回答正确' if attempt.is_correct else '还有需要巩固的地方'}\n\n{attempt.feedback}\n\n**参考答案**：{q.answer}\n\n{q.explanation}"
                attempts = session.exec(
                    select(QuizAttempt)
                    .where(
                        QuizAttempt.question_id.in_(ids),
                        QuizAttempt.user_id == "default",
                    )
                    .order_by(QuizAttempt.id)
                ).all()
                history = self._history(session, ids, attempts)
                return (
                    feedback,
                    gr.update(interactive=False),
                    gr.update(interactive=True),
                    history,
                )
        except Exception:
            logger.exception("批改失败")
            return (
                "暂时无法批改，请检查模型连接后重试。",
                gr.update(interactive=True),
                gr.update(interactive=False),
                gr.skip(),
            )
