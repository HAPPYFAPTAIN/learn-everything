"""学习工作台：顶部选课、章节导航、阅读内容与独立助教侧窗。"""

from __future__ import annotations

import html
import json
import logging
import re
from learning_ext.presentation import project_display_name, project_choices, clean_heading_icons

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import (
    KnowledgeEdge,
    KnowledgeNode,
    LearningProject,
    NodeResource,
    Task,
)
from learning_ext.notes import (
    explain_term,
    fetch_preview,
    generate_resources,
    get_note,
    get_resources,
    save_note,
    save_resources_to_db,
)
from learning_ext.progress.study import (
    STATUS_LEARNING,
    STATUS_MASTERED,
    STATUS_PENDING,
    STATUS_SKIPPED,
    generate_node_summary_to_db,
    generate_practice_lesson_to_db,
    generate_summaries_background,
    get_practice_task,
    get_next_learnable_nodes,
    get_nodes_without_content,
    get_project_progress,
    is_content_valid,
    sort_nodes_by_code,
    regenerate_all_content,
    set_node_status,
)
from learning_ext.progress.audit import audit_node_content

logger = logging.getLogger(__name__)

STATUS_LABEL = {
    STATUS_PENDING: "待学",
    STATUS_LEARNING: "学习中",
    STATUS_MASTERED: "已掌握",
    "weak": "薄弱",
    STATUS_SKIPPED: "已跳过",
}
STAGE_NAMES = {"base": "基础", "strengthen": "强化", "sprint": "冲刺"}

RESOURCE_ICON = {
    "doc": "📄",
    "html": "🌐",
    "pdf": "📕",
    "video": "🎬",
    "book": "📖",
    "article": "📰",
    "tool": "🔧",
    "search": "🔍",
    "summary": "🧠",
}

RESOURCE_EMPTY_MD = "*点「拉取参考资料」自动抓取本节正文引用来源*"

# 划词解释主脚本由 custom_app.py 内联到 Gradio 初始模板。这里保留 Gradio
# 事件侧的轻量兜底: 如果事件 JS 可用, 重新确认监听器已安装。
WORD_LOOKUP_JS = """
function(...args){
  if (window.__leInstallWordLookup) window.__leInstallWordLookup();
  return args;
}
"""

WORKBENCH_CSS = """
<style>
#le-selected-term {position:absolute!important;width:1px!important;height:1px!important;opacity:0!important;overflow:hidden!important;pointer-events:none!important;}
#le-term-result {display:none!important;}
#le-guide-md {overflow-wrap:anywhere;word-break:break-word;}
</style>
"""


class StudyWorkbenchPage(BasePage):
    """学习工作台"""

    def __init__(self, app):
        super().__init__(app)
        # 仅声明 gr.State, 业务函数都是普通函数
        self.current_node_id = gr.State(None)
        self.current_project_id = gr.State(None)
        # 正在等备课结果的节点 -> 占位内容
        self._pending_nodes: dict[int, str] = {}
        # 界面当前显示占位的那一节（定时器据此判断要不要替换）
        self._pending_node: int | None = None
        # 已经为哪个项目排过整项目备课（避免反复扫描）
        self._prep_kicked: set[int] = set()

    # ==================== UI 构建 ====================

    def on_building_ui(self):
        gr.HTML(WORKBENCH_CSS)
        gr.HTML(
            '<div class="le-page-heading"><div><h1>学习工作台</h1><p>一次专注一个知识点。阅读、实践，再用自己的话理解它。</p></div></div>'
        )
        with gr.Row(elem_id="le-workbench-row"):
            with gr.Column(scale=1, min_width=200, elem_id="le-left-col"):
                gr.HTML('<div class="le-course-strip-heading"><strong>当前学习</strong><span>选择项目和课程，继续你的进度</span></div>')
                self.project_id = gr.Dropdown(
                    label="学习项目", choices=[], value=None, interactive=True, elem_id="le-project-picker"
                )
                self.progress_display = gr.Markdown("", elem_classes=["le-progress"], elem_id="le-course-progress")
                self.course_drop = gr.Dropdown(
                    label="当前课程", choices=[], value=None, interactive=True, elem_id="le-course-picker"
                )
                gr.Markdown(
                    "选择课程后自动打开。完成阅读后，可在正文下方标记掌握情况。",
                    elem_classes=["le-caption"], elem_id="le-course-hint",
                )
                with gr.Accordion("项目与课程管理", open=False, elem_id="le-course-admin"):
                    with gr.Row():
                        self.refresh_btn = gr.Button("刷新项目", size="sm")
                        self.load_list_btn = gr.Button("刷新课程", size="sm")
                    self.view_btn = gr.Button("重新载入当前课程", size="sm")
                    with gr.Accordion("环境配置", open=False, elem_id="le-env-setup"):
                        self.env_status = gr.Markdown("")
                        self.auto_setup_plan = gr.State(value=None)
                        self.auto_setup_btn = gr.Button("生成配置方案", size="sm")
                        self.execute_setup_btn = gr.Button("执行这份配置方案", size="sm", visible=False)
                        self.apply_env_btn = gr.Button("已完成配置", size="sm")
                        self.auto_setup_output = gr.Code(
                            label="配置方案与执行记录",
                            language="shell",
                            visible=False,
                            interactive=False,
                        )
                    with gr.Accordion("内容维护", open=False):
                        self.regen_all_btn = gr.Button("补全缺失内容", size="sm")
                        self.regen_all_force_btn = gr.Button(
                            "重新生成全部内容", size="sm", variant="stop"
                        )
                        self.regen_all_status = gr.Markdown("")
                    with gr.Accordion("添加课程", open=False):
                        self.add_title = gr.Textbox(
                            label="课程标题", placeholder="例如：分布式训练进阶"
                        )
                        self.add_stage = gr.Dropdown(
                            label="阶段",
                            choices=[
                                ("基础", "base"),
                                ("强化", "strengthen"),
                                ("冲刺", "sprint"),
                            ],
                            value="base",
                        )
                        self.add_code = gr.Textbox(
                            label="编号 · 可选", placeholder="例如：1.6"
                        )
                        self.add_difficulty = gr.Slider(
                            label="难度", minimum=1, maximum=5, value=3, step=1
                        )
                        self.add_hours = gr.Number(
                            label="预估学时", value=2, precision=0
                        )
                        self.add_desc = gr.Textbox(label="课程说明", lines=2)
                        self.add_ai_btn = gr.Button("AI 生成并添加", size="sm")
                        self.add_btn = gr.Button("添加课程", size="sm")
                        self.add_status = gr.Markdown("")
            with gr.Column(scale=4, min_width=320, elem_id="le-center-col"):
                self.selected_term = gr.Textbox(
                    elem_id="le-selected-term",
                    visible=True,
                    interactive=True,
                    show_label=False,
                )
                with gr.Tabs(elem_id="le-content-tabs"):
                    with gr.TabItem("阅读", elem_id="le-lookup-zone"):
                        self.node_guide = gr.Markdown(
                            "", elem_id="le-guide-md", elem_classes=["le-lookup-zone"]
                        )
                        with gr.Accordion("课程内容工具", open=False):
                            with gr.Row():
                                self.regen_node_btn = gr.Button(
                                    "重新生成本节", size="sm"
                                )
                                self.audit_node_btn = gr.Button(
                                    "检查内容完整性", size="sm"
                                )
                            self.regen_node_status = gr.Markdown("")
                            self.audit_node_output = gr.Markdown(
                                "检查本节内容的完整性、深度与结构。"
                            )
                    with gr.TabItem("实践", elem_id="le-practice-zone"):
                        self.practice_md = gr.Markdown(
                            "本节暂无实践内容，可生成操作步骤、代码与验收清单。"
                        )
                        self.gen_practice_btn = gr.Button("准备实践内容", size="sm")
                        self.gen_practice_status = gr.Markdown("")
                    with gr.TabItem("笔记", elem_id="le-note-zone"):
                        self.note_input = gr.Textbox(
                            label="我的理解",
                            placeholder="用自己的话，记下这一节最重要的内容…",
                            lines=12,
                        )
                        self.save_note_btn = gr.Button(
                            "保存笔记", variant="primary", size="sm"
                        )
                        self.note_status = gr.Markdown("")
                    with gr.TabItem("参考", elem_id="le-resource-zone"):
                        self.resources_md = gr.Markdown(RESOURCE_EMPTY_MD)
                        self.gen_resources_btn = gr.Button(
                            "整理本节参考资料", size="sm"
                        )
                        self.gen_resources_status = gr.Markdown("")
                        with gr.Accordion("添加参考链接", open=False):
                            self.resource_preview_url = gr.Textbox(
                                label="网址", placeholder="https://..."
                            )
                            self.preview_btn = gr.Button("读取正文", size="sm")
                            self.resource_preview = gr.Markdown("")
                # 标题放在标签栏之下：标签栏吸顶后，标题与正文一起从下方穿过
                self.node_header = gr.Markdown(
                    "选择上方课程，开始阅读。", elem_id="le-center-content"
                )
                with gr.Accordion("划词解释结果", open=False, elem_id="le-term-result"):
                    self.term_explain_btn = gr.Button("解释选中词汇", size="sm")
                    self.term_explain_output = gr.Markdown("", elem_id="le-term-output")
                with gr.Row(elem_id="le-lesson-actions"):
                    with gr.Accordion("调整学习状态", open=False):
                        self.start_btn = gr.Button("标记为学习中", size="sm")
                        self.skip_btn = gr.Button("跳过本节", size="sm")
                    self.master_btn = gr.Button(
                        "已掌握本节 ✓", variant="primary", size="sm"
                    )
                self.action_status = gr.Markdown("")
        # 选段改写的桥：前端把「选中了哪句话、要怎么改」写进这个隐藏输入框，
        # 再点一下隐藏按钮触发事件。Gradio 4.44 没有 visible="hidden"，
        # 所以用 CSS 把这一行挪出可视区（元素仍在 DOM 里，脚本才够得着）。
        with gr.Row(elem_id="le-rewrite-bridge"):
            self.rewrite_payload = gr.Textbox(
                value="", show_label=False, container=False, elem_id="le-rewrite-payload"
            )
            self.rewrite_trigger = gr.Button("改写", elem_id="le-rewrite-trigger")
        # 提示条必须放在隐藏行外面：那行是 opacity:0，放里面会跟着一起透明
        self.rewrite_note = gr.HTML("", elem_id="le-rewrite-note")
        # 备课轮询：正文还在写时，写好了自动替换，用户不用点任何按钮
        self.prep_timer = gr.Timer(3.0, active=True)

    # ==================== 事件绑定 ====================

    def on_register_events(self):
        # 项目变化: 刷新进度 + 课程下拉框 + 环境状态
        project_outputs = [
            self.progress_display,
            self.course_drop,
            self.current_project_id,
            self.env_status,
        ]
        self.project_id.input(
            fn=self._on_project_change,
            inputs=[self.project_id],
            outputs=project_outputs,
        )
        self.refresh_btn.click(
            fn=self._refresh_projects,
            outputs=[self.project_id],
        ).then(
            fn=self._on_project_change,
            inputs=[self.project_id],
            outputs=project_outputs,
        )
        self.load_list_btn.click(
            fn=self._on_project_change,
            inputs=[self.current_project_id],
            outputs=project_outputs,
        )

        # 课程选择: Dropdown 选课后点「查看课程」按钮加载内容 (解耦: 项目变更不清空内容)
        view_outputs = [
            self.current_node_id,
            self.node_header,
            self.node_guide,
            self.practice_md,
            self.note_input,
            self.resources_md,
        ]
        self.view_btn.click(
            fn=self._on_node_select,
            inputs=[self.course_drop],
            outputs=view_outputs,
        )
        self.course_drop.change(
            fn=self._on_course_change,
            inputs=[self.course_drop],
            outputs=view_outputs,
        )

        # 备课轮询：正文还在写 → 写好了自动替换（无需用户点按钮）
        # 注意：gr.Timer 的 tick 不会给事件传输入，所以这里不留 inputs，
        # 由页面自己记住「当前在等哪一节」。
        self.prep_timer.tick(
            fn=self._poll_writing,
            outputs=[self.node_guide, self.practice_md],
        )

        # 选段改写：前端把请求写进隐藏输入框后点这个按钮
        self.rewrite_trigger.click(
            fn=self._on_rewrite,
            inputs=[self.current_node_id, self.rewrite_payload],
            outputs=[self.node_guide, self.rewrite_note],
        )

        # 环境配置
        self.auto_setup_btn.click(
            fn=self._prepare_setup,
            inputs=[self.current_project_id],
            outputs=[self.auto_setup_output, self.env_status, self.auto_setup_plan, self.execute_setup_btn],
        )
        self.execute_setup_btn.click(
            fn=self._execute_setup,
            inputs=[self.current_project_id, self.auto_setup_plan],
            outputs=[self.auto_setup_output, self.env_status, self.auto_setup_plan, self.execute_setup_btn],
        )
        self.apply_env_btn.click(
            fn=self._apply_env,
            inputs=[self.current_project_id],
            outputs=[self.env_status],
        )

        # 重新生成
        self.regen_node_btn.click(
            fn=self._regen_current_node,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.regen_node_status, self.node_header, self.node_guide],
        )
        self.audit_node_btn.click(
            fn=self._audit_current_node,
            inputs=[self.current_node_id],
            outputs=[self.audit_node_output],
        )
        self.regen_all_btn.click(
            fn=lambda pid: self._regen_all(pid, False),
            inputs=[self.current_project_id],
            outputs=[self.regen_all_status],
        )
        self.regen_all_force_btn.click(
            fn=lambda pid: self._regen_all(pid, True),
            inputs=[self.current_project_id],
            outputs=[self.regen_all_status],
        )

        # 笔记
        self.save_note_btn.click(
            fn=self._save_note,
            inputs=[self.current_node_id, self.current_project_id, self.note_input],
            outputs=[self.note_status],
        )

        # 实操课程
        self.gen_practice_btn.click(
            fn=self._gen_practice_lesson,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.practice_md, self.gen_practice_status],
        )

        # 参考资料
        self.gen_resources_btn.click(
            fn=self._gen_resources,
            inputs=[self.current_node_id, self.current_project_id],
            outputs=[self.resources_md, self.gen_resources_status],
        )
        self.preview_btn.click(
            fn=self._preview_resource,
            inputs=[self.resource_preview_url],
            outputs=[self.resource_preview],
        )

        # 划词解释
        self.selected_term.change(
            fn=self._on_term_selected,
            inputs=[self.selected_term, self.current_node_id],
            outputs=[self.term_explain_output],
        )
        self.term_explain_btn.click(
            fn=self._on_term_selected_manual,
            inputs=[self.selected_term, self.current_node_id],
            outputs=[self.term_explain_output],
        )

        # 添加课程
        add_outputs = [self.add_status, self.course_drop, self.progress_display]
        self.add_btn.click(
            fn=self._add_node,
            inputs=[
                self.current_project_id,
                self.add_title,
                self.add_desc,
                self.add_stage,
                self.add_code,
                self.add_difficulty,
                self.add_hours,
            ],
            outputs=add_outputs,
        )
        # AI 生成教学内容后直接添加
        self.add_ai_btn.click(
            fn=self._add_node_with_ai,
            inputs=[
                self.current_project_id,
                self.add_title,
                self.add_desc,
                self.add_stage,
                self.add_code,
                self.add_difficulty,
                self.add_hours,
            ],
            outputs=add_outputs,
        )

        # 状态操作: 刷新进度 + 3个课程下拉框
        status_outputs = [
            self.action_status,
            self.progress_display,
            self.course_drop,
        ]
        self.start_btn.click(
            fn=lambda nid: self._set_status(nid, STATUS_LEARNING),
            inputs=[self.current_node_id],
            outputs=status_outputs,
        ).then(self._refresh_node_header, inputs=[self.current_node_id], outputs=[self.node_header])
        self.master_btn.click(
            fn=lambda nid: self._set_status(nid, STATUS_MASTERED),
            inputs=[self.current_node_id],
            outputs=status_outputs,
        ).then(self._refresh_node_header, inputs=[self.current_node_id], outputs=[self.node_header])
        self.skip_btn.click(
            fn=lambda nid: self._set_status(nid, STATUS_SKIPPED),
            inputs=[self.current_node_id],
            outputs=status_outputs,
        ).then(self._refresh_node_header, inputs=[self.current_node_id], outputs=[self.node_header])

        # 页面加载后自动初始化: 填充项目+课程+预加载第一节内容
        load_outputs = [
            self.project_id,  # 0: 项目下拉框
            self.progress_display,  # 1: 进度
            self.course_drop,  # 2: 课程下拉框
            self.current_project_id,  # 3
            self.env_status,  # 4
            self.current_node_id,  # 5: 预加载的节点 id
            self.node_header,  # 6: 节点标题
            self.node_guide,  # 7: 教学内容
            self.practice_md,  # 8: 实操课程
            self.note_input,  # 9: 笔记
            self.resources_md,  # 10: 参考资料
        ]
        try:
            self._app.app.load(
                fn=self._auto_init,
                outputs=load_outputs,
                js=WORD_LOOKUP_JS,
            )
        except Exception as e:
            logger.warning(f"demo.load 注册失败: {e}")

    # ==================== 业务函数 ====================

    def _build_node_header(self, node, proj):
        return (
            f"### [{node.code}] {node.title}\n\n"
            f"`{node.est_hours}h` `难度{node.difficulty}/5` "
            f"`{STATUS_LABEL.get(node.status, node.status)}`"
        )

    def _build_progress_md(self, prog):
        return (
            f"**进度**: {prog['done']}/{prog['total']} ({prog['pct']}%)\n\n"
            f"已掌握 {prog['done']} · 学习中 {prog['learning']} · 待学 {prog['pending']}"
        )

    def _build_nodes_data(self, session, pid):
        nodes = session.exec(
            select(KnowledgeNode).where(KnowledgeNode.project_id == pid)
        ).all()
        learnable_ids = {n.id for n in get_next_learnable_nodes(session, pid, limit=50)}
        done_statuses = {STATUS_MASTERED, STATUS_SKIPPED}
        result = []
        for n in sort_nodes_by_code(list(nodes)):
            result.append(
                {
                    "id": n.id,
                    "code": n.code,
                    "title": n.title,
                    "stage": n.stage,
                    "status": n.status,
                    "has_content": is_content_valid(n.description),
                    "learnable": n.id in learnable_ids or n.status in done_statuses,
                }
            )
        return result

    def _build_drop_choices(self, nodes_data):
        """构建单个 Dropdown 的全部选项列表 (按阶段分组, 带状态图标)。"""
        choices = []
        stages_order = ["base", "strengthen", "sprint"]
        grouped: dict[str, list] = {}
        for n in nodes_data:
            grouped.setdefault(n.get("stage", "base"), []).append(n)
        for stage_key in stages_order:
            ns = grouped.get(stage_key, [])
            if not ns:
                continue
            # 添加阶段分隔标题 (作为不可选项, value 留空)
            choices.append(
                (f"──── {STAGE_NAMES.get(stage_key, stage_key)} ────", "__stage__")
            )
            for n in ns:
                status = n.get("status", STATUS_PENDING)
                has_content = n.get("has_content", False)
                learnable = n.get("learnable", False)
                state = STATUS_LABEL.get(status, "待学")
                if status == STATUS_PENDING and not learnable:
                    state = "待解锁"
                elif not has_content and status == STATUS_PENDING:
                    state = "待生成"
                label = f"{n.get('code', '')} {n.get('title', '')} · {state}"
                choices.append((label, str(n.get("id", 0))))
        return choices

    def _load_env(self, session, pid):
        env_task = session.exec(
            select(Task).where(Task.project_id == pid).where(Task.task_type == "env")
        ).first()
        if env_task:
            return env_task.description or "", (
                "✅ 环境已配置" if env_task.status == "done" else "⚠️ 环境待配置"
            )
        return "", ""

    def _render_resources_md(self, resources):
        lines = []
        for r in resources:
            if r.rtype == "summary":
                continue
            icon = RESOURCE_ICON.get(r.rtype, "📄")
            lines.append(f"### {r.title}")
            lines.append(f"\n类型：`{(r.rtype or 'html').upper()}`")
            if r.description:
                lines.append(f"\n{r.description}")
            if r.preview:
                lines.append("\n已拉取正文内容，后台已保存用于审计与后续引用。")
            else:
                lines.append("\n*未能抓取到可读正文。*")
            if r.url:
                lines.append(f"\n来源：`{r.url}`")
            lines.append("\n---")
        return "\n".join(lines) if lines else "*暂无可展示参考资料。*"

    def _render_practice_md(self, task):
        if not task or not task.description:
            return "*本节暂无实操课程。高难/实操内容会自动生成，也可以点击「🧪 生成实操课程」。*"
        return task.description

    # ---- 自动初始化 (页面加载时执行, 预加载第一节内容) ----
    def _auto_init(self):
        """页面加载后: 填充项目/课程下拉框 + 预加载第一个可学节点的教学内容。"""
        try:
            with Session(engine) as s:
                projs = s.exec(
                    select(LearningProject).order_by(LearningProject.id.desc())
                ).all()
                if not projs:
                    return [
                        gr.update(),
                        "",
                        gr.update(),
                        None,
                        "",
                        None,
                        "*请先创建学习路线*",
                        "",
                        "*本节暂无实操课程。*",
                        "",
                        RESOURCE_EMPTY_MD,
                    ]
                pid = projs[0].id
                dd_update = gr.update(
                    choices=project_choices(projs),
                    value=str(pid),
                )
                prog = get_project_progress(s, pid)
                progress_md = self._build_progress_md(prog)
                env_md, env_status = self._load_env(s, pid)
                nodes_data = self._build_nodes_data(s, pid)
                course_c = self._build_drop_choices(nodes_data)

                # 没备课的章节直接丢后台，用户什么都不用点
                proj0 = s.get(LearningProject, pid)
                self._kick_project_prep(pid, proj0.topic if proj0 else "")
                first_node_id = None
                header = "*选择课程开始学习*"
                guide = ""
                practice_md = "*本节暂无实操课程。*"
                note_content = ""
                res_md = RESOURCE_EMPTY_MD
                if nodes_data:
                    first = nodes_data[0]
                    first_node_id = first["id"]
                    node = s.get(KnowledgeNode, first_node_id)
                    if node:
                        proj = s.get(LearningProject, pid)
                        header = self._build_node_header(node, proj)
                        guide = self._ensure_course_content(
                            first_node_id, proj.topic if proj else "", node.description
                        )
                        guide = self._truncate_guide(guide)
                        practice_md = self._render_practice_md(
                            get_practice_task(s, first_node_id)
                        )
                        note = get_note(s, first_node_id)
                        note_content = note.content if note else ""
                        resources = get_resources(s, first_node_id)
                        if resources:
                            res_md = self._render_resources_md(resources)
                        else:
                            res_md = self._ensure_resources_background(
                                first_node_id, pid
                            )
                # 选中第一个节点
                course_update = gr.update(
                    choices=course_c,
                    value=str(first_node_id) if first_node_id else None,
                )

                logger.info(
                    f"[工作台] _auto_init 完成: 项目#{pid}, 预加载节点#{first_node_id}, guide长度={len(guide)}"
                )

                return [
                    dd_update,  # 0: 项目下拉框
                    progress_md,  # 1: 进度
                    course_update,  # 2: 课程下拉框
                    pid,  # 3: current_project_id
                    env_status,  # 4: 环境状态
                    first_node_id,  # 5: current_node_id
                    header,  # 6: 节点标题
                    guide,  # 7: 教学内容
                    practice_md,  # 8: 实操课程
                    note_content,  # 9: 笔记
                    res_md,  # 10: 参考资料
                ]
        except Exception as e:
            logger.exception("_auto_init 失败")
            return [
                gr.update(),
                "",
                gr.update(),
                None,
                "",
                None,
                "*加载失败*",
                "",
                "*本节暂无实操课程。*",
                "",
                RESOURCE_EMPTY_MD,
            ]

    # ---- 项目相关 ----
    def _refresh_projects(self):
        try:
            with Session(engine) as session:
                projects = session.exec(
                    select(LearningProject).order_by(LearningProject.id.desc())
                ).all()
                choices = project_choices(projects)
                cur = str(projects[0].id) if projects else None
                return gr.update(choices=choices, value=cur)
        except Exception:
            return gr.update()

    def _on_project_change(self, project_id):
        if not project_id:
            return "*请先选择项目*", gr.update(), None, ""
        try:
            pid = int(project_id)
        except (ValueError, TypeError):
            return "*ID无效*", gr.update(), None, ""
        with Session(engine) as session:
            prog = get_project_progress(session, pid)
            progress_md = self._build_progress_md(prog)
            env_md, env_status = self._load_env(session, pid)
            nodes_data = self._build_nodes_data(session, pid)
            proj = session.get(LearningProject, pid)
            topic = proj.topic if proj else ""
        self._kick_project_prep(pid, topic)
        course_c = self._build_drop_choices(nodes_data)
        return (
            progress_md,
            gr.update(
                choices=course_c, value=str(nodes_data[0]["id"]) if nodes_data else None
            ),
            pid,
            env_status,
        )

    # ---- 添加课程 ----
    def _add_node(self, project_id, title, desc, stage, code, difficulty, hours):
        """添加课程 (不含 AI 教学内容, 后续可在工作台生成)。"""
        if not project_id:
            return "⚠️ 请先选择项目", gr.update(), gr.update()
        if not title or not title.strip():
            return "⚠️ 请输入课程标题", gr.update(), gr.update()
        try:
            from learning_ext.progress.study import add_node

            with Session(engine) as s:
                node = add_node(
                    s,
                    int(project_id),
                    title.strip(),
                    description=desc or "",
                    stage=stage or "base",
                    code=code or "",
                    difficulty=difficulty or 3,
                    est_hours=hours or 2,
                )
                pid = int(project_id)
                nodes_data = self._build_nodes_data(s, pid)
                course_c = self._build_drop_choices(nodes_data)
                prog = get_project_progress(s, pid)
                progress_md = self._build_progress_md(prog)
            return (
                f"✅ 已添加课程 [{node.code}] {node.title}。选中它后，"
                "在「阅读」页底部展开「课程内容工具」，点「重新生成本节」即可让 AI 生成教学内容。",
                gr.update(choices=course_c, value=str(node.id)),
                progress_md,
            )
        except Exception as e:
            return f"❌ 添加失败: {e}", gr.update(), gr.update()

    def _add_node_with_ai(
        self, project_id, title, desc, stage, code, difficulty, hours
    ):
        """添加课程并立即用 AI 生成教学内容 (同步等待约 30-60 秒)。"""
        if not project_id:
            return "⚠️ 请先选择项目", gr.update(), gr.update()
        if not title or not title.strip():
            return "⚠️ 请输入课程标题", gr.update(), gr.update()
        try:
            from learning_ext.progress.study import (
                add_node,
                generate_node_summary_to_db,
            )

            with Session(engine) as s:
                node = add_node(
                    s,
                    int(project_id),
                    title.strip(),
                    description=desc or "",
                    stage=stage or "base",
                    code=code or "",
                    difficulty=difficulty or 3,
                    est_hours=hours or 2,
                )
                nid = node.id
                pid = int(project_id)
                proj = s.get(LearningProject, pid)
                topic = proj.topic if proj else ""
            # AI 生成教学内容
            ok = generate_node_summary_to_db(nid, topic)
            with Session(engine) as s:
                nodes_data = self._build_nodes_data(s, pid)
                course_c = self._build_drop_choices(nodes_data)
                prog = get_project_progress(s, pid)
                progress_md = self._build_progress_md(prog)
            if ok:
                msg = f"✅ 已添加课程 [{node.code}] {node.title} 并生成完整教学内容！"
            else:
                msg = f"✅ 已添加课程 [{node.code}] {node.title}，教学内容生成失败，可后续重试。"
            return msg, gr.update(choices=course_c, value=str(nid)), progress_md
        except Exception as e:
            return f"❌ 失败: {e}", gr.update(), gr.update()

    # ---- 课程加载 (按钮触发, 普通函数) ----
    def _on_node_select(self, node_id):
        """「查看课程」按钮触发: 读取 Dropdown 选中的节点 ID, 加载教学内容。"""
        logger.info(f"[工作台] _on_node_select 被调用, node_id={node_id!r}")
        if not node_id or node_id == "__stage__":
            return (
                None,
                "*请先在下拉框中选择一节课，再点「查看课程」*",
                "",
                "*本节暂无实操课程。*",
                "",
                RESOURCE_EMPTY_MD,
                [],
                [],
            )
        try:
            nid = int(node_id)
        except (ValueError, TypeError):
            return (
                None,
                "*ID无效*",
                "",
                "*本节暂无实操课程。*",
                "",
                RESOURCE_EMPTY_MD,
                [],
                [],
            )

        with Session(engine) as session:
            node = session.get(KnowledgeNode, nid)
            if not node:
                return (
                    None,
                    "*知识点不存在*",
                    "",
                    "*本节暂无实操课程。*",
                    "",
                    RESOURCE_EMPTY_MD,
                )
            proj = session.get(LearningProject, node.project_id)
            header = self._build_node_header(node, proj)
            guide = node.description or ""
            practice = get_practice_task(session, nid)
            practice_md = self._render_practice_md(practice)
            note = get_note(session, nid)
            note_content = note.content if note else ""
            resources = get_resources(session, nid)
            res_md = (
                self._render_resources_md(resources)
                if resources
                else self._ensure_resources_background(nid, node.project_id)
            )
            topic = proj.topic if proj else ""

        logger.info(
            f"[工作台] 加载节点 [{node.code}] {node.title}, guide长度={len(guide)}"
        )

        guide = self._ensure_course_content(nid, topic, guide)
        guide = self._truncate_guide(guide)
        logger.info(f"[工作台] 返回内容, guide长度={len(guide)}")

        return nid, header, guide, practice_md, note_content, res_md

    def _on_course_change(self, node_id):
        if not node_id or node_id == "__stage__":
            return tuple(gr.update() for _ in range(6))
        return self._on_node_select(node_id)

    def _ensure_course_content(self, node_id: int, topic: str, guide: str | None) -> str:
        """有内容就直接给；没有就排进后台备课，先显示「正在写这一节」。

        以前这里是同步生成，用户点进来会卡住几十秒，失败还给一段「去点按钮」的提示；
        现在一律不阻塞，写完由定时器自动替换。
        """
        current = guide or ""
        if is_content_valid(current):
            return current
        try:
            nid = int(node_id)
        except (TypeError, ValueError):
            return self._writing_placeholder()
        self._queue_single(nid)
        return self._writing_placeholder()

    def _writing_placeholder(self) -> str:
        return (
            "⏳ **正在写这一节…**\n\n"
            "通常 30–60 秒。写完会自动出现在这里，你可以先去读别的章节，不用点任何按钮。\n\n"
            "> 等不及的话，点右下角「助教」，它现在就能按这个知识点回答你。"
        )

    def _queue_single(self, node_id: int) -> None:
        """把某一节排进后台备课，并记下它正在等。"""
        from learning_ext.progress import prep

        try:
            nid = int(node_id)
        except (TypeError, ValueError):
            return
        if nid in self._pending_nodes:
            return
        with Session(engine) as session:
            node = session.get(KnowledgeNode, nid)
            if not node:
                return
            proj = session.get(LearningProject, node.project_id)
            pid = node.project_id
            topic = proj.topic if proj else ""
        self._pending_nodes[nid] = self._writing_placeholder()
        self._pending_node = nid
        prep.start(pid, [nid], topic)

    def _kick_project_prep(self, pid, topic: str) -> None:
        """打开某个项目时，把还没备课的章节全部丢后台，不用用户操心。"""
        from learning_ext.progress import prep

        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return
        if pid in self._prep_kicked:
            return
        self._prep_kicked.add(pid)
        try:
            with Session(engine) as session:
                nodes = session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.project_id == pid)
                ).all()
                missing = [n.id for n in nodes if not is_content_valid(n.description)]
        except Exception:
            logger.exception("扫描缺失教学内容失败")
            return
        if missing:
            prep.start(pid, missing, topic)
            logger.info("[工作台] 项目#%s 后台补备 %d 节", pid, len(missing))

    def _poll_writing(self):
        """定时检查：正在写的这一节写好了没，好了就替换正文。

        gr.Timer 不会传输入，所以用 self._pending_node 记住当前在等哪一节；
        替换成功后清掉，避免每 3 秒重复推同一份内容。
        """
        nid = self._pending_node
        if not nid:
            return gr.update(), gr.update()
        try:
            with Session(engine) as session:
                node = session.get(KnowledgeNode, int(nid))
                if not node or not is_content_valid(node.description):
                    return gr.update(), gr.update()
                practice_md = self._render_practice_md(get_practice_task(session, int(nid)))
                body = node.description or ""
        except Exception:
            logger.exception("读取备课结果失败")
            return gr.update(), gr.update()
        self._pending_node = None
        self._pending_nodes.pop(int(nid), None)
        logger.info("[工作台] node#%s 备课完成，自动替换正文", nid)
        return self._truncate_guide(body), practice_md

    # ---- 选段改写 ----
    @staticmethod
    def _toast(message: str, ok: bool | None = None, undo: bool = False) -> str:
        """正文下方那条小提示条（绝对定位，不占版面）。"""
        kind = "busy" if ok is None else ("ok" if ok else "err")
        mark = '<span class="le-toast-dot"></span>' if ok is None else ""
        undo_btn = (
            '<button type="button" class="le-toast-act" data-rewrite-act="undo">撤销</button>'
            if undo
            else ""
        )
        return (
            f'<div class="le-toast le-toast-{kind}">{mark}'
            f'<span class="le-toast-text">{html.escape(message)}</span>'
            f'{undo_btn}'
            '<button type="button" class="le-toast-x" aria-label="关闭">×</button></div>'
        )

    def _on_rewrite(self, node_id, payload):
        """处理「选中一段 → 说怎么改」的请求。

        只改命中的那一段，不动整节；改完留一次撤销。
        """
        from learning_ext.progress import rewrite as rw

        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            data = {}
        action = str(data.get("action") or "rewrite")
        snippet = str(data.get("snippet") or "")
        instruction = str(data.get("instruction") or "")

        if not node_id:
            yield gr.update(), self._toast("先在左边选一节课程。", ok=False)
            return
        if action != "undo" and len(snippet.strip()) < 3:
            yield gr.update(), self._toast("先选中要改的那句话，再点按钮。", ok=False)
            return

        yield gr.update(), self._toast(
            "正在改这一段…通常十几秒，别关页面。" if action != "undo" else "正在撤销…"
        )
        try:
            res = rw.rewrite(node_id, snippet, action, instruction)
        except Exception as exc:  # noqa: BLE001
            logger.exception("改写失败 node#%s", node_id)
            yield gr.update(), self._toast(f"改写出错：{type(exc).__name__}: {exc}", ok=False)
            return

        if not res.get("ok"):
            yield gr.update(), self._toast(res.get("message") or "没改成。", ok=False)
            return
        guide = res.get("guide") or ""
        # 撤销之后就没有「再撤销」了
        yield (
            self._truncate_guide(guide) if guide else gr.update(),
            self._toast(res.get("message") or "已更新。", ok=True, undo=action != "undo"),
        )

    def _missing_course_content(self, brief: str | None) -> str:
        brief = (brief or "").strip()
        lines = [
            "⚠️ **本节完整教学内容还没有生成成功。**",
            "",
            "可以点下方「课程内容工具」里的「重新生成本节」重新生成课程正文；"
            "右侧 AI 助教仍可基于当前知识点答疑。",
        ]
        if brief:
            lines.extend(["", "#### 路线说明", brief])
        return "\n".join(lines)

    _FENCE = re.compile(r"(```.*?```)", re.S)
    _BLANK = re.compile(r"_{3,}")

    def _normalize_blanks(self, guide: str) -> str:
        """填空题空位写的是 ______，markdown 会把它当语法吃掉，显示成一片空白。
        送显前换成一条可见的空位横线（代码块里不动）。"""

        def fix(chunk: str) -> str:
            return self._BLANK.sub(
                lambda m: '<span class="le-blank" style="width:%.1fem"></span>'
                % min(6.0, max(2.5, len(m.group()) * 0.55)),
                chunk,
            )

        parts = self._FENCE.split(guide or "")
        return "".join(p if p.startswith("```") else fix(p) for p in parts)

    def _truncate_guide(self, guide: str, max_chars: int = 15000) -> str:
        """截断超长教学内容, 在章节边界截断并提示剩余可看。"""
        guide = self._normalize_blanks(clean_heading_icons(guide))
        if len(guide) <= max_chars:
            return guide
        # 在 max_chars 附近找最后一个 ## 标题边界
        cut = guide.rfind("\n## ", 0, max_chars)
        if cut < max_chars * 0.5:
            cut = max_chars  # 找不到合适的边界就硬截
        remaining = len(guide) - cut
        return (
            guide[:cut]
            + f"\n\n---\n\n> 📄 **内容较长已截断显示（剩余约 {remaining} 字）**\n"
            + f"> 完整内容已保存，可在「❓ 追问 AI」中提问查看后续部分。\n"
        )

    # ---- 笔记 ----
    def _save_note(self, node_id, project_id, content):
        if not node_id:
            return "⚠️ 请先选择知识点"
        try:
            with Session(engine) as s:
                save_note(s, int(node_id), int(project_id), content)
            return "✅ 笔记已保存"
        except Exception as e:
            return f"❌ {e}"

    # ---- 实操课程 ----
    def _gen_practice_lesson(self, node_id, project_id):
        if not node_id:
            return "*请先选择知识点*", "⚠️ 请先选择知识点"
        try:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                proj = s.get(LearningProject, int(project_id)) if project_id else None
                topic = proj.topic if proj else ""
            ok = generate_practice_lesson_to_db(int(node_id), topic, force=True)
            if not ok:
                return "*生成失败，请稍后重试。*", "❌ 生成失败"
            with Session(engine) as s:
                task = get_practice_task(s, int(node_id))
            return self._render_practice_md(task), "✅ 已生成实操课程"
        except Exception as e:
            return f"*生成失败: {e}*", f"❌ {e}"

    # ---- 参考资料 ----
    def _ensure_resources_background(self, node_id, project_id):
        if not node_id or not project_id:
            return RESOURCE_EMPTY_MD
        try:
            with Session(engine) as s:
                existing = get_resources(s, int(node_id))
                if existing:
                    return self._render_resources_md(existing)
        except Exception:
            return RESOURCE_EMPTY_MD

        import threading

        def _worker():
            try:
                with Session(engine) as s:
                    node = s.get(KnowledgeNode, int(node_id))
                    proj = (
                        s.get(LearningProject, int(project_id)) if project_id else None
                    )
                    if not node:
                        return
                    topic = proj.topic if proj else ""
                    items = generate_resources(node, topic)
                    save_resources_to_db(s, int(node_id), int(project_id), items)
            except Exception as e:
                logger.warning(f"自动拉取参考资料失败 (node {node_id}): {e}")

        threading.Thread(
            target=_worker,
            daemon=True,
            name=f"le-resources-{node_id}",
        ).start()
        return "⏳ 正在自动拉取参考资料，稍后刷新本节即可查看。"

    def _gen_resources(self, node_id, project_id):
        """生成参考资料 (普通函数, 接受同步等待)。"""
        if not node_id:
            return "*请先选择知识点*", "⚠️ 请先选择知识点"
        try:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                proj = s.get(LearningProject, int(project_id)) if project_id else None
                topic = proj.topic if proj else ""
                items = generate_resources(node, topic)
                saved = save_resources_to_db(s, int(node_id), int(project_id), items)
                res_md = self._render_resources_md(saved)
            pulled = len(saved)
            if pulled == 0:
                return res_md, "⚠️ 未拉取到可展示参考资料"
            return res_md, f"✅ 已拉取 {pulled} 份参考资料"
        except Exception as e:
            return f"*生成失败: {e}*", f"❌ {e}"

    def _preview_resource(self, url):
        if not url or not url.strip():
            return "*请输入 URL*"
        return fetch_preview(url.strip())

    # ---- 划词解释 ----
    def _on_term_selected(self, term, node_id=None):
        if not term or not term.strip():
            return ""
        return self._do_explain(term.strip(), node_id)

    def _on_term_selected_manual(self, term, node_id):
        if not term or not term.strip():
            return "⚠️ 请先选中一个词, 或在此输入要解释的词"
        return self._do_explain(term.strip(), node_id)

    def _do_explain(self, term, node_id=None):
        try:
            with Session(engine) as s:
                nid = int(node_id) if node_id else None
                node = s.get(KnowledgeNode, nid) if nid else None
                proj = s.get(LearningProject, node.project_id) if node else None
                topic = proj.topic if proj else ""
            if not node:
                return f"**{term}**: 请先选择一个知识点, 以获得基于上下文的解释。"
            result = explain_term(term, node, topic)
            return f"### 🔍 {term}\n\n{result}"
        except Exception as e:
            return f"❌ 解释失败: {e}"

    def _append_last_assistant_to_node(self, node_id, history):
        if not node_id:
            return gr.update(), "⚠️ 请先选择知识点"
        user_question = ""
        assistant_reply = ""
        for item in reversed(history or []):
            role = item.get("role")
            content = (item.get("content") or "").strip()
            if role == "assistant" and content and not assistant_reply:
                assistant_reply = content
                continue
            if role == "user" and content and assistant_reply:
                user_question = content
                break
        if not assistant_reply:
            return gr.update(), "⚠️ 还没有可并入正文的 AI 助教回答"
        supplement = self._build_ai_supplement_markdown(user_question, assistant_reply)
        try:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                if not node:
                    return gr.update(), "⚠️ 知识点不存在"
                current = (node.description or "").rstrip()
                node.description = (
                    f"{current}\n\n{supplement}" if current else supplement
                )
                s.add(node)
                s.commit()
                updated = node.description
            return updated, "✅ 已并入本节正文末尾，原内容未改动"
        except Exception as e:
            return gr.update(), f"❌ 并入失败: {e}"

    @staticmethod
    def _build_ai_supplement_markdown(user_question: str, assistant_reply: str) -> str:
        lines = [
            "---",
            "",
            "## AI 助教补充",
        ]
        if user_question:
            lines.extend(["", f"> 学习者追问：{user_question}"])
        lines.extend(["", assistant_reply.strip()])
        return "\n".join(lines)

    # ---- 环境配置 (generator: 流式显示命令输出) ----
    def _prepare_setup(self, project_id):
        from learning_ext.practice.auto_setup import generate_install_commands
        import hashlib

        hidden = gr.update(visible=False)
        try:
            pid = int(project_id)
            with Session(engine) as session:
                project = session.get(LearningProject, pid)
                task = session.exec(select(Task).where(Task.project_id == pid, Task.task_type == "env")).first()
                if not project or not task or not task.description:
                    yield hidden, "当前项目还没有环境配置清单。", None, hidden
                    return
                description, background = task.description, project.background or ""
            yield gr.update(visible=True, value="正在整理配置方案，尚未执行任何命令。"), "正在生成方案…", None, hidden
            commands = generate_install_commands(description, background)
            if not commands:
                yield gr.update(visible=True, value="这份清单无需自动配置。"), "可按课程说明直接开始学习。", None, hidden
                return
            if not isinstance(commands, list) or any(not isinstance(c, dict) or not str(c.get("cmd") or "").strip() for c in commands):
                raise ValueError("生成的配置命令不完整，请重新生成。")
            preview = "\n\n".join(f"# {i}. {c.get('desc', '配置步骤')}\n{c['cmd']}" for i, c in enumerate(commands, 1))
            plan = {"project_id": pid, "fingerprint": hashlib.sha256(description.encode()).hexdigest(), "commands": commands}
            yield gr.update(visible=True, value=preview), "请检查上方方案。点击执行后，才会在本机安装软件或修改配置。", plan, gr.update(visible=True)
        except (TypeError, ValueError) as exc:
            yield hidden, str(exc) if project_id else "请先选择学习项目。", None, hidden
        except Exception:
            logger.exception("Failed to prepare environment setup")
            yield hidden, "配置方案生成失败，请检查模型连接后重试。", None, hidden

    def _execute_setup(self, project_id, plan):
        import hashlib
        from learning_ext.practice.auto_setup import run_all_commands

        hidden = gr.update(visible=False)
        try:
            pid = int(project_id)
            if not isinstance(plan, dict) or plan.get("project_id") != pid or not plan.get("commands"):
                yield gr.update(), "请先为当前项目生成配置方案。", None, hidden
                return
            with Session(engine) as session:
                task = session.exec(select(Task).where(Task.project_id == pid, Task.task_type == "env")).first()
                fingerprint = hashlib.sha256((task.description or "").encode()).hexdigest() if task else None
            if fingerprint != plan.get("fingerprint"):
                yield gr.update(), "环境清单已更新，请重新生成方案。", None, hidden
                return
        except (TypeError, ValueError):
            yield gr.update(), "请先选择学习项目。", None, hidden
            return
        yield gr.update(visible=True, value="开始执行已确认的配置方案…"), "正在执行…", None, hidden
        lines, outcome = [], {}
        for chunk in run_all_commands(plan["commands"], outcome=outcome):
            lines.append(chunk.rstrip("\n"))
            yield gr.update(visible=True, value="\n".join(lines)), "正在执行…", None, hidden
        status = ("部分配置失败，请查看执行记录。" if outcome.get("failed") else "命令执行成功，请验证环境后点击「已完成配置」。")
        yield gr.update(visible=True, value="\n".join(lines)), status, None, hidden

    def _apply_env(self, project_id):
        if not project_id:
            return "⚠️ 请先选择项目"
        try:
            with Session(engine) as s:
                t = s.exec(
                    select(Task)
                    .where(Task.project_id == int(project_id))
                    .where(Task.task_type == "env")
                ).first()
                if not t:
                    return "当前项目还没有环境配置清单。"
                if t:
                    t.status = "done"
                    s.add(t)
                    s.commit()
            return "✅ 环境已配置"
        except Exception as e:
            return f"❌ {e}"

    # ---- 重新生成 ----
    def _regen_current_node(self, node_id, project_id):
        """重新生成本节教学内容 (普通函数)。"""
        if not node_id:
            return "⚠️ 请先选择知识点", gr.update(), gr.update()
        try:
            nid = int(node_id)
            with Session(engine) as s:
                proj = s.get(LearningProject, int(project_id)) if project_id else None
                topic = proj.topic if proj else ""
            ok = generate_node_summary_to_db(nid, topic, force=True)
            if not ok:
                return "❌ 生成失败", gr.update(), gr.update()
            with Session(engine) as s:
                node = s.get(KnowledgeNode, nid)
                proj = s.get(LearningProject, node.project_id)
                header = self._build_node_header(node, proj)
                guide = node.description or ""
            return "✅ 已重新生成", header, guide
        except Exception as e:
            return f"❌ {e}", gr.update(), gr.update()

    def _audit_current_node(self, node_id):
        """审计当前教材是否完整全面。"""
        if not node_id:
            return "⚠️ 请先选择知识点"
        try:
            with Session(engine) as s:
                return audit_node_content(s, int(node_id))
        except Exception as e:
            return f"❌ 审计失败: {e}"

    def _regen_all(self, project_id, force=False):
        try:
            pid = int(project_id) if project_id else None
            result = regenerate_all_content(project_id=pid, force=force)
            scope = f"项目#{pid}" if pid else "所有项目"
            mode = "强制重生成" if force else "补全"
            return f"📦 **{mode}** {scope}: 排队{result['queued']}节, 跳过{result['skipped']}节。后台生成中。"
        except Exception as e:
            return f"❌ {e}"

    # ---- 状态 ----
    def _refresh_node_header(self, node_id):
        if not node_id:
            return gr.update()
        with Session(engine) as session:
            node = session.get(KnowledgeNode, int(node_id))
            if node is None:
                return gr.update()
            project = session.get(LearningProject, node.project_id)
            return self._build_node_header(node, project)

    def _set_status(self, node_id, status):
        if not node_id:
            return (
                "⚠️ 请先选择知识点",
                gr.update(),
                gr.update(),
            )
        try:
            nid = int(node_id)
            with Session(engine) as s:
                node = set_node_status(s, nid, status)
                pid = node.project_id
                proj = s.get(LearningProject, pid)
                topic = proj.topic if proj else ""
                if status == STATUS_MASTERED:
                    pending = get_nodes_without_content(s, pid, limit=3)
                    pids = [n.id for n in pending if n.id != nid]
                    if pids:
                        generate_summaries_background(pid, topic, pids)
                prog = get_project_progress(s, pid)
                progress_md = self._build_progress_md(prog)
                nodes_data = self._build_nodes_data(s, pid)
            course_c = self._build_drop_choices(nodes_data)
            if status == STATUS_MASTERED:
                msg = "🎉 已掌握！下一节内容正在后台生成。"
            elif status == STATUS_LEARNING:
                msg = "📖 已标记学习中。"
            else:
                msg = "⏭ 已跳过。"
            return (
                msg,
                progress_md,
                gr.update(choices=course_c, value=str(nid)),
            )
        except Exception as e:
            return f"❌ {e}", gr.update(), gr.update()
