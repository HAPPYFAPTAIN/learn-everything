import html
import uuid

import gradio as gr

from learning_ext.home_content import HERO, DIRECTIONS_HEADING, direction_art


def flow_target(tab, stage=""):
    return (
        f'<span data-le-flow-target="{html.escape(tab, quote=True)}" '
        f'data-le-flow-stage="{html.escape(stage, quote=True)}" '
        f'data-le-flow-id="{uuid.uuid4().hex}"></span>'
    )


def connection_configured():
    from learning_ext.llm.client import _load_config

    cfg = _load_config()
    return bool(cfg.get("api_key") and cfg.get("base_url") and cfg.get("chat_model"))


def goal_summary(topic, background, hours):
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("写下你想学会的事，或选择上方的学习方向。")
    return (
        '<div class="le-onboarding-summary"><span class="le-eyebrow">你的学习目标</span>'
        f'<h2>{html.escape(topic)}</h2><p>起点：{html.escape((background or "").strip() or "从基础开始")}'
        f' · 每周 {float(hours):g} 小时</p></div>'
    )


SAMPLE = """<details class="le-sample"><summary><span class="le-sample-play" aria-hidden="true">▶</span><span><strong>60 秒体验课</strong><small>认识表格 · 不调用模型</small></span><span>试试看 →</span></summary>
<div class="le-sample-body"><h2>从一个你熟悉的例子开始。</h2><p>一张订单表中，每一行是一笔订单，日期、商品和金额分别占一列。</p>
<div class="le-sample-table"><table><caption>示例订单表</caption><thead><tr><th>日期</th><th>商品</th><th>金额</th></tr></thead>
<tbody><tr><td>10 月 1 日</td><td>笔记本</td><td>20 元</td></tr><tr><td>10 月 2 日</td><td>铅笔</td><td>5 元</td></tr></tbody></table></div>
<p><strong>要找出 10 月 1 日的订单，先看哪一列？</strong></p>
<div class="le-sample-options"><button type="button" data-le-sample="date">日期</button><button type="button" data-le-sample="item">商品</button><button type="button" data-le-sample="amount">金额</button></div>
<p data-le-sample-result role="status" aria-live="polite">选一个答案试试，不会计入正式学习记录。</p></div></details>"""


class GuidedHomePage:
    def __init__(self, app):
        self._app = app

    def on_building_ui(self):
        with gr.Column(elem_id="le-guided-home"):
            self.resume_id = gr.State(None)
            with gr.Row(visible=False, elem_id="le-resume-row") as self.resume_row:
                self.resume = gr.HTML("")
                self.resume_btn = gr.Button("继续学习 →", variant="primary", size="sm", min_width=110)
            gr.HTML(HERO)
            with gr.Column(elem_id="le-home-journey"):
                self.steps = gr.HTML(self._steps(1))
                with gr.Column(visible=True, elem_id="le-home-goal-panel") as self.goal_panel:
                    gr.HTML(DIRECTIONS_HEADING, elem_id="le-discovery-heading")
                    with gr.Row(elem_id="le-discovery-cards"):
                        with gr.Column(elem_classes=["le-direction-card"]):
                            gr.HTML(direction_art("python"))
                            self.example_python = gr.Button("做出第一个小工具\n用 Python 整理一张表格", elem_classes=["le-direction-button"])
                        with gr.Column(elem_classes=["le-direction-card"]):
                            gr.HTML(direction_art("ai"))
                            self.example_ai = gr.Button("看懂 AI 如何工作\n从零认识一个 Agent", elem_classes=["le-direction-button"])
                        with gr.Column(elem_classes=["le-direction-card"]):
                            gr.HTML(direction_art("writing"))
                            self.example_writing = gr.Button("把想法表达清楚\n写一份让人看懂的工作汇报", elem_classes=["le-direction-button"])
                    with gr.Column(elem_id="le-onboarding-card"):
                        gr.HTML('<div class="le-custom-heading"><h3>或者直接写下目标</h3></div>')
                        self.topic = gr.Textbox(label="写下你想学会的事", placeholder="我想学会……，这样就能……", lines=2, max_lines=4, elem_id="le-onboarding-topic")
                        with gr.Accordion("我的学习节奏", open=False, elem_id="le-learning-preferences"):
                            with gr.Row():
                                with gr.Column(scale=3):
                                    self.background = gr.Textbox(label="从哪里开始", placeholder="零基础，或写下你已经会的…", lines=2)
                                with gr.Column(scale=2, elem_id="le-time-preference"):
                                    self.hours = gr.Slider(minimum=1, maximum=20, value=3, step=1, label="每周留给学习的时间 · 小时")
                        with gr.Row(elem_id="le-home-goal-action"):
                            self.next_btn = gr.Button("为我安排第一步 →", variant="primary")
                with gr.Column(visible=False, elem_id="le-home-confirm") as self.confirm_panel:
                    self.summary = gr.HTML("")
                    self.connection = gr.Markdown("")
                    self.begin_btn = gr.Button("生成学习路线 →", variant="primary")
                    self.back_btn = gr.Button("返回修改目标", variant="secondary", elem_id="le-home-back")
                    gr.HTML('<p class="le-reassurance">生成时会把学习目标与背景发送给你配置的模型服务。路线先供你预览，确认之后才会保存和备课。</p>')
                self.feedback = gr.Markdown("", elem_id="le-onboarding-feedback")
            gr.HTML(SAMPLE)
            gr.HTML('<div class="le-guided-footer"><button type="button" data-le-tour-start="learning">需要逐步操作提示？</button></div>')
            self.marker = gr.HTML("", elem_id="le-onboarding-marker")
            with gr.Row(elem_id="le-home-bridge"):
                self.refresh = gr.Button("刷新首页", elem_id="le-home-refresh")

    @staticmethod
    def _steps(active):
        labels = ["选一个方向", "确认学习安排", "预览路线并开始"]
        return f'<nav class="le-onboarding-steps" data-home-step="{active}" aria-label="开始学习的步骤">' + "".join(
            f'<span {"aria-current=step" if i == active else ""}><b>{i:02}</b> {label}</span>'
            for i, label in enumerate(labels, 1)
        ) + "</nav>"

    def _confirm(self, topic, background, hours):
        try:
            summary = goal_summary(topic, background, hours)
        except ValueError as exc:
            return gr.update(), gr.update(), "", "", gr.update(), str(exc), gr.update()
        configured = connection_configured()
        message = "已找到保存的模型配置。下一步可以生成路线，实际连接结果以请求为准。" if configured else "还差一次连接设置。先连接 AI，完成后回来继续，刚才填写的目标会保留在当前页面。"
        return gr.update(visible=False), gr.update(visible=True), summary, message, gr.update(value="生成学习路线 →" if configured else "先连接 AI →"), "", self._steps(2)

    def _handoff(self, topic, background, hours):
        goal_summary(topic, background, hours)
        if not connection_configured():
            return *[gr.update() for _ in range(10)], flow_target("quick-setup-tab", "connect")
        return (
            topic.strip(), (background or "").strip(), topic.strip(), float(hours), "{}",
            "",
            "", None, {}, gr.update(active=False), flow_target("learning-path-tab", "preview"),
        )

    @staticmethod
    def _resume_info():
        from ktem.db.engine import engine
        from sqlmodel import Session, select
        from learning_ext.db.models import KnowledgeNode, LearningProject
        from learning_ext.fsrs_review.service import get_review_stats
        from learning_ext.progress.study import get_next_learnable_nodes, get_project_progress

        with Session(engine) as session:
            project = session.exec(select(LearningProject).join(KnowledgeNode).where(LearningProject.user_id == "default", LearningProject.status == "active").order_by(LearningProject.id.desc())).first()
            if not project:
                return gr.update(visible=False), "", None
            project_id = project.id
            title = html.escape(project.topic or project.title or f"未命名学习项目 · {project_id}")
            progress = get_project_progress(session, project_id)
            next_nodes = get_next_learnable_nodes(session, project_id, limit=1)
            review = get_review_stats(session, project_id=project_id)

        total = int(progress.get("total") or 0)
        done = int(progress.get("done") or 0)
        pct = max(0.0, min(100.0, float(progress.get("pct") or 0)))
        due = int(review.get("due_count") or 0)
        progress_label = f"已掌握 {done} / {total} 节" if total else "课程小节待补充"
        if next_nodes:
            node = next_nodes[0]
            next_markup = (
                '<div class="le-resume-next"><small>下一节</small><strong>'
                f'<span>{html.escape(node.code)}</span>{html.escape(node.title)}</strong></div>'
            )
        elif total and done == total:
            next_markup = '<div class="le-resume-next"><small>下一步</small><strong>全部小节已掌握，可继续复习巩固</strong></div>'
        else:
            next_markup = '<div class="le-resume-next"><small>下一步</small><strong>打开工作台查看可学小节</strong></div>'
        markup = (
            '<section class="le-resume-strip" aria-label="继续当前课程">'
            '<div class="le-resume-summary">'
            '<div class="le-resume-heading"><span class="le-resume-icon" aria-hidden="true">↗</span>'
            f'<div><small>当前课程</small><strong>{title}</strong></div></div>'
            '<div class="le-resume-progress">'
            f'<div><span>{progress_label}</span><strong>{pct:g}%</strong></div>'
            f'<div class="le-resume-progress-track" role="progressbar" aria-label="课程掌握进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct:g}"><i style="width:{pct:g}%"></i></div></div></div>'
            '<div class="le-resume-details">'
            f'{next_markup}<div class="le-resume-review"><small>待复习</small><strong>{due} <span>张</span></strong></div>'
            '</div></section>'
        )
        return gr.update(visible=True), markup, project_id

    def on_register_events(self):
        page = self._app.learning_path_page
        wb = self._app.learning_workbench_page
        self.next_btn.click(self._confirm, [self.topic, self.background, self.hours], [self.goal_panel, self.confirm_panel, self.summary, self.connection, self.begin_btn, self.feedback, self.steps])
        self.back_btn.click(lambda: (gr.update(visible=True), gr.update(visible=False), self._steps(1), ""), outputs=[self.goal_panel, self.confirm_panel, self.steps, self.feedback])
        self.example_python.click(lambda: "用 Python 整理一张 Excel 表", outputs=self.topic)
        self.example_writing.click(lambda: "写一份清楚的工作汇报", outputs=self.topic)
        self.example_ai.click(lambda: "从零理解 AI Agent 的工作原理，并做一个简单的 Agent", outputs=self.topic)
        self.begin_btn.click(self._handoff, [self.topic, self.background, self.hours], [page.topic_input, page.background_input, page.goal_input, page.hours_input, page.roadmap_json, page.roadmap_output, page.save_progress, page.current_project_id, page.prep_context, page.prep_timer, self.marker], show_progress="hidden").then(
            lambda: page._begin_generation() if connection_configured() else tuple(gr.update() for _ in range(8)),
            outputs=[page.current_project_id, page.save_progress, page.status, page.roadmap_json, page.roadmap_output, page.generating, self.begin_btn, page.regenerate_btn], show_progress="hidden",
        ).then(
            lambda topic, background, hours: page._generate_preview(topic, background, topic, hours) if connection_configured() else tuple(gr.update() for _ in range(6)),
            inputs=[self.topic, self.background, self.hours], outputs=[page.roadmap_output, page.roadmap_json, page.status, page.generating, self.begin_btn, page.regenerate_btn], show_progress="full",
        )
        def refresh_home():
            ready = connection_configured()
            return *self._resume_info(), ("已找到保存的模型配置。可以继续生成路线。" if ready else "先连接 AI，再回来继续，当前页面里的目标会保留。"), gr.update(value="生成学习路线 →" if ready else "先连接 AI →")
        self.refresh.click(refresh_home, outputs=[self.resume_row, self.resume, self.resume_id, self.connection, self.begin_btn], show_progress="hidden")
        self._app.app.load(self._resume_info, outputs=[self.resume_row, self.resume, self.resume_id], show_progress="hidden")
        self.resume_btn.click(wb._auto_init, [self.resume_id], wb.load_outputs).then(lambda: flow_target("learning-workbench-tab", "study"), outputs=self.marker)
        page.open_course.click(wb._auto_init, [page.current_project_id], wb.load_outputs).then(lambda: flow_target("learning-workbench-tab", "study"), outputs=self.marker)
