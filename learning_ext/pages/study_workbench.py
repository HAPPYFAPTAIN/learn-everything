"""学习工作台：顶部选课、章节导航、阅读内容与独立助教侧窗。"""

from __future__ import annotations

import html
import json
from datetime import datetime
import logging
import re
from learning_ext.environment_view import environment_state
from learning_ext.presentation import (
    project_display_name,
    project_choices,
    clean_heading_icons,
    md_safe,
)

import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import (
    KnowledgeEdge,
    KnowledgeNode,
    LearningProject,
    NodeResource,
    QuizQuestion,
    Task,
)
from learning_ext.notes import (
    annotations,
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
from learning_ext.progress import gate
from learning_ext.progress.audit import audit_node_content
from learning_ext.llm.client import friendly_error
from learning_ext.pages.adapt_panel import AdaptPanel
from learning_ext.pages.action_learning import ActionLearningPanel

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
#le-selected-term {position:absolute!important;width:1px!important;height:1px!important;opacity:0!important;overflow:hidden!important;pointer-events:none!important;visibility:hidden!important;}
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
                with gr.Accordion("管理", open=False, elem_id="le-course-admin"):
                    with gr.Row(elem_id="le-course-refresh-actions"):
                        self.refresh_btn = gr.Button("刷新项目", size="sm")
                        self.load_list_btn = gr.Button("刷新课程", size="sm")
                    self.adapt_open_btn = gr.Button(
                        "课程适配度调整", size="sm", elem_id="le-adapt-open"
                    )
                    self.view_btn = gr.Button("重新载入当前课程", size="sm", elem_id="le-course-reload")
                    with gr.Accordion("环境配置", open=False, elem_id="le-env-setup"):
                        self.env_status = gr.HTML(environment_state(), elem_id="le-env-status")
                        self.auto_setup_plan = gr.State(value=None)
                        self.execute_setup_btn = gr.Button("确认并执行方案", size="sm", variant="primary", visible=False, elem_id="le-env-execute")
                        with gr.Row(elem_id="le-env-actions"):
                            self.auto_setup_btn = gr.Button("生成方案", size="sm", variant="primary", elem_id="le-env-generate")
                            self.apply_env_btn = gr.Button("我已配置好", size="sm", elem_id="le-env-confirm")
                        with gr.Accordion("查看命令与执行记录", open=False, elem_id="le-env-log"):
                            self.auto_setup_output = gr.Code(
                                label="命令与执行记录", show_label=False,
                                language="shell", visible=False, interactive=False,
                            )
                    with gr.Accordion("内容维护", open=False, elem_id="le-course-maintenance"):
                        self.regen_all_btn = gr.Button("补全缺失内容", size="sm")
                        self.regen_all_force_btn = gr.Button(
                            "重新生成全部内容", size="sm", variant="stop"
                        )
                        self.regen_all_status = gr.Markdown("")
                    with gr.Accordion("添加课程", open=False, elem_id="le-course-add"):
                        self.add_title = gr.Textbox(
                            label="课程标题", placeholder="例如：分布式训练进阶", lines=1
                        )
                        self.add_desc = gr.Textbox(label="想学什么", placeholder="写下重点，或让 AI 帮你补充", lines=2)
                        with gr.Row(elem_id="le-course-add-basics"):
                            self.add_stage = gr.Dropdown(
                                label="阶段", min_width=130,
                                choices=[("基础", "base"), ("强化", "strengthen"), ("冲刺", "sprint")], value="base",
                            )
                            self.add_hours = gr.Number(label="预计小时", value=2, precision=0, min_width=100)
                        with gr.Accordion("编号与难度", open=False, elem_id="le-course-add-options"):
                            self.add_code = gr.Textbox(label="课程编号", placeholder="自动安排，也可以填写 1.6", lines=1)
                            self.add_difficulty = gr.Slider(label="难度", minimum=1, maximum=5, value=3, step=1)
                        with gr.Row(elem_id="le-course-add-actions"):
                            self.add_btn = gr.Button("直接添加", size="sm")
                            self.add_ai_btn = gr.Button("AI 生成并添加", size="sm", variant="primary")
                        self.add_status = gr.Markdown("")
                    with gr.Accordion("项目设置", open=False, elem_id="le-project-settings"):
                        gr.Markdown(
                            "删除当前项目及其课程、卡片、测验、笔记和学习记录。此操作不可撤销。",
                            elem_classes=["le-delete-warning"],
                        )
                        self.delete_confirm = gr.Textbox(
                            label="输入 DELETE 确认删除",
                            placeholder="DELETE",
                            lines=1,
                            elem_id="le-delete-confirm",
                        )
                        self.delete_btn = gr.Button(
                            "删除当前项目",
                            variant="stop",
                            interactive=False,
                            elem_id="le-delete-project",
                        )
                        self.delete_status = gr.Markdown("", elem_id="le-delete-status")
            with gr.Column(scale=4, min_width=320, elem_id="le-center-col"):
                self.selected_term = gr.Textbox(
                    elem_id="le-selected-term",
                    visible=True,
                    interactive=True,
                    show_label=False,
                )
                # 学习节奏条：到期复习 / 今天学了多久 / 该做查漏了
                self.rhythm_bar = gr.HTML("", elem_id="le-rhythm-bar")
                self.action_learning = ActionLearningPanel(self).build()
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
                        gr.Markdown("### 我的总结")
                        self.note_input = gr.Textbox(
                            label="用自己的话，记下这一节最重要的内容",
                            show_label=False,
                            placeholder="读完这一节，用两三句话说说你的理解…",
                            lines=8,
                        )
                        self.save_note_btn = gr.Button(
                            "保存总结", variant="primary", size="sm"
                        )
                        self.note_status = gr.Markdown("")
                        # 正文里划词记下的批注，一条条列在这里
                        self.annotation_md = gr.HTML(
                            "", elem_id="le-annotation-list"
                        )
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
                        "已掌握本节 ✓", variant="primary", size="sm", elem_id="le-master-btn"
                    )
                self.action_status = gr.Markdown("")
        # 过关检查弹窗：点「已掌握」没过时弹出。两关缺一条就不让标已掌握，
        # 因为「看完了」和「学会了」是两件事。
        # 放页面级而不是正文里：正文的有效区在最底下，放在那儿用户点了按钮
        # 其实什么也看不见，还得自己往下翻。
        with gr.Column(elem_id="le-gate-overlay", visible=False) as self.gate_panel:
            with gr.Column(elem_id="le-gate-center"):
                with gr.Column(elem_id="le-gate-modal"):
                    with gr.Row(elem_id="le-gate-head"):
                        gr.Markdown("### 过关检查", elem_id="le-gate-title")
                        self.gate_skip_btn = gr.Button(
                            "跳过本节", size="sm", elem_id="le-gate-skip"
                        )
                        self.gate_close_btn = gr.Button(
                            "关闭", size="sm", elem_id="le-gate-close"
                        )
                    self.gate_check_md = gr.Markdown("", elem_id="le-gate-check-md")
                    # 两块分标签页，而不是上下堆。堆在一起时「讲一遍」和「跳过」
                    # 会被挤到弹窗滚动区外，用户根本不知道还有这两步。
                    with gr.Tabs(elem_id="le-gate-tabs") as self.gate_tabs:
                        with gr.Tab("① 速测", id="le-gate-tab-quiz"):
                            self.gate_quiz_md = gr.Markdown(
                                "", elem_id="le-gate-quiz-md"
                            )
                            with gr.Row(elem_id="le-gate-answers"):
                                self.gate_ans1 = gr.Textbox(label="第 1 题", lines=1)
                                self.gate_ans2 = gr.Textbox(label="第 2 题", lines=1)
                                self.gate_ans3 = gr.Textbox(label="第 3 题", lines=1)
                            with gr.Row(elem_id="le-gate-quiz-actions"):
                                self.gate_submit = gr.Button(
                                    "提交速测", size="sm", variant="primary"
                                )
                                self.gate_quiz_btn = gr.Button("换一组题", size="sm")
                            self.gate_quiz_result = gr.Markdown(
                                "", elem_id="le-gate-quiz-result"
                            )
                        with gr.Tab("② 讲一遍", id="le-gate-tab-recite"):
                            gr.Markdown(
                                "不看原文，用自己的话说清这一节在讲什么、为什么是这样。"
                                "讲不出来，说明还没真懂。"
                            )
                            self.recite_input = gr.Textbox(
                                label="你的复述",
                                lines=4,
                                placeholder="比如：这一节主要在说……，因为……，所以……",
                                elem_id="le-gate-recite-input",
                            )
                            self.recite_btn = gr.Button(
                                "让助教看看讲清楚没有", size="sm", variant="primary"
                            )
                            self.recite_feedback = gr.Markdown(
                                "", elem_id="le-gate-recite-fb"
                            )
                    self.gate_quiz_state = gr.State([])
                # 「跳过 / 已掌握」之后要自动进入的下一节
                self.gate_next_id = gr.State(None)

        # 课程适配度调整：点按钮弹出中号窗口
        self.adapt_panel = AdaptPanel(self._app, self).build()

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
        # 批注的桥：同一套做法（写值 → 点隐藏按钮）
        with gr.Row(elem_id="le-anno-bridge"):
            self.anno_payload = gr.Textbox(
                value="", show_label=False, container=False, elem_id="le-anno-payload"
            )
            self.anno_trigger = gr.Button("批注", elem_id="le-anno-trigger")
        # 学习时长：前端每 30 秒把「刚才停留的秒数」写进这个隐藏框再点隐藏按钮，
        # 后端累加成 study_minutes。看板的「近 7 天学习」终于有真实数据了。
        with gr.Row(elem_id="le-time-bridge"):
            self.time_payload = gr.Textbox(
                value="", show_label=False, container=False, elem_id="le-time-payload"
            )
            self.time_trigger = gr.Button("计时", elem_id="le-time-trigger")
        # 节奏条上的「我先学，回头补」：同一套隐藏桥，记录今天已确认过
        # 跳转后把页面拉回顶部：Gradio 事件的 js 在请求前跑，滚了也会被新内容顶回去，
        # 所以用一个隐藏元素做信号，内容一变前端就去滚。
        self.scroll_kick = gr.HTML("", elem_id="le-scroll-kick")
        with gr.Row(elem_id="le-snooze-bridge"):
            self.snooze_payload = gr.Textbox(
                value="", show_label=False, container=False, elem_id="le-snooze-payload"
            )
            self.snooze_trigger = gr.Button("补", elem_id="le-snooze-trigger")
        # 备课轮询：正文还在写时，写好了自动替换，用户不用点任何按钮
        self.prep_timer = gr.Timer(3.0, active=False)

    # ==================== 事件绑定 ====================

    def on_register_events(self):
        self.action_learning.register()
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
            self.annotation_md,
            self.prep_timer,  # 只有真的在等备课才把轮询打开
        ]
        self.view_btn.click(
            fn=self._on_node_select,
            inputs=[self.course_drop],
            outputs=view_outputs,
        ).then(
            fn=self._refresh_rhythm,
            inputs=[self.current_project_id],
            outputs=[self.rhythm_bar],
        )
        self.course_drop.change(
            fn=self._on_course_change,
            inputs=[self.course_drop],
            outputs=view_outputs,
        ).then(
            fn=self._refresh_rhythm,
            inputs=[self.current_project_id],
            outputs=[self.rhythm_bar],
        )

        # 备课轮询：正文还在写 → 写好了自动替换（无需用户点按钮）
        # 注意：gr.Timer 的 tick 不会给事件传输入，所以这里不留 inputs，
        # 由页面自己记住「当前在等哪一节」。
        # show_progress="hidden" 必须加：不加的话每 3 秒都会在正文组件上盖一层
        # 半透明遮罩 + spinner，读文章时看着就是不停地闪。
        self.prep_timer.tick(
            fn=self._poll_writing,
            outputs=[self.node_guide, self.practice_md, self.prep_timer],
            show_progress="hidden",
        )

        # 课程适配度调整弹窗
        self.adapt_panel.register(self.adapt_open_btn)

        # 学习时长心跳
        self.time_trigger.click(
            fn=self._on_study_tick,
            inputs=[self.current_node_id, self.current_project_id, self.time_payload],
            outputs=None,
            show_progress="hidden",
        )
        self.snooze_trigger.click(
            fn=self._on_snooze,
            inputs=[self.snooze_payload],
            outputs=[self.rhythm_bar],
            show_progress="hidden",
        )

        # 选段改写：前端把请求写进隐藏输入框后点这个按钮
        self.rewrite_trigger.click(
            fn=self._on_rewrite,
            inputs=[self.current_node_id, self.rewrite_payload],
            outputs=[self.node_guide, self.rewrite_note],
        )
        # 划词批注：新增 / 删除
        self.anno_trigger.click(
            fn=self._on_annotate,
            inputs=[self.current_node_id, self.current_project_id, self.anno_payload],
            outputs=[self.annotation_md, self.rewrite_note],
        )

        # 环境配置
        self.auto_setup_btn.click(
            fn=self._prepare_setup,
            inputs=[self.current_project_id],
            outputs=[self.auto_setup_output, self.env_status, self.auto_setup_plan, self.execute_setup_btn],
            show_progress="hidden",
        )
        self.execute_setup_btn.click(
            fn=self._execute_setup,
            inputs=[self.current_project_id, self.auto_setup_plan],
            outputs=[self.auto_setup_output, self.env_status, self.auto_setup_plan, self.execute_setup_btn],
            show_progress="hidden",
        )
        self.apply_env_btn.click(
            fn=self._apply_env,
            inputs=[self.current_project_id],
            outputs=[self.env_status],
            show_progress="hidden",
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
        # 「已掌握」不再是点一下就成：先过两关（测对、讲清）
        self.master_btn.click(
            fn=self._try_master,
            inputs=[self.current_node_id],
            outputs=[
                self.node_header,
                self.action_status,
                self.progress_display,
                self.course_drop,
                self.gate_panel,
                self.gate_check_md,
                self.rhythm_bar,
                self.gate_tabs,
                self.gate_next_id,
            ],
        ).then(
            fn=self._gate_auto_quiz,
            inputs=[self.current_node_id, self.gate_quiz_state],
            outputs=[self.gate_quiz_md, self.gate_quiz_state, self.gate_quiz_result],
        ).then(
            # 跳过 / 已掌握之后自动进下一节，不用再回上面点下拉
            fn=self._goto_next_after_gate,
            inputs=[self.gate_next_id],
            outputs=[*view_outputs, self.course_drop, self.scroll_kick],
        )
        self.gate_quiz_btn.click(
            fn=self._gate_make_quiz,
            inputs=[self.current_node_id],
            outputs=[self.gate_quiz_md, self.gate_quiz_state, self.gate_quiz_result],
        )
        self.gate_submit.click(
            fn=self._gate_submit,
            inputs=[
                self.current_node_id,
                self.gate_ans1,
                self.gate_ans2,
                self.gate_ans3,
                self.gate_quiz_state,
            ],
            outputs=[
                self.gate_quiz_result,
                self.gate_check_md,
                self.gate_tabs,
            ],
        )
        self.recite_btn.click(
            fn=self._gate_recite,
            inputs=[self.current_node_id, self.recite_input],
            outputs=[self.recite_feedback, self.gate_check_md],
        )
        self.gate_skip_btn.click(
            fn=self._gate_skip,
            inputs=[self.current_node_id],
            outputs=[
                self.node_header,
                self.action_status,
                self.progress_display,
                self.course_drop,
                self.gate_panel,
                self.rhythm_bar,
                self.gate_next_id,
            ],
        ).then(
            fn=self._goto_next_after_gate,
            inputs=[self.gate_next_id],
            outputs=[*view_outputs, self.course_drop, self.scroll_kick],
        )
        self.gate_close_btn.click(
            fn=lambda: gr.update(visible=False),
            outputs=[self.gate_panel],
        )
        # 主页面这个「跳过本节」跟弹窗里的是同一个动作，也应该自动进下一节
        self.skip_btn.click(
            fn=self._gate_skip,
            inputs=[self.current_node_id],
            outputs=[
                self.node_header,
                self.action_status,
                self.progress_display,
                self.course_drop,
                self.gate_panel,
                self.rhythm_bar,
                self.gate_next_id,
            ],
        ).then(
            fn=self._goto_next_after_gate,
            inputs=[self.gate_next_id],
            outputs=[*view_outputs, self.course_drop, self.scroll_kick],
        )

        # 页面加载后自动初始化: 填充项目+课程+预加载第一节内容
        load_outputs = self.load_outputs = [
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
            self.annotation_md,  # 11: 正文批注（刷新页面后不该消失）
            self.prep_timer,  # 12: 备课轮询开关
        ]
        self.project_id.input(
            lambda: ("", gr.update(interactive=False)),
            outputs=[self.delete_confirm, self.delete_btn],
        )
        self.delete_confirm.input(
            lambda text: gr.update(interactive=(text or "").strip() == "DELETE"),
            inputs=[self.delete_confirm],
            outputs=[self.delete_btn],
        )
        self.delete_btn.click(
            fn=self._delete_current_project,
            inputs=[self.current_project_id, self.delete_confirm],
            outputs=[*load_outputs, self.delete_confirm, self.delete_btn, self.delete_status],
            concurrency_limit=1,
        )
        try:
            self._app.app.load(
                fn=self._auto_init,
                outputs=load_outputs,
                js=WORD_LOOKUP_JS,
            ).then(
                fn=self._refresh_rhythm,
                inputs=[self.current_project_id],
                outputs=[self.rhythm_bar],
            )
        except Exception as e:
            logger.warning(f"demo.load 注册失败: {e}")

    # ==================== 业务函数 ====================

    def _build_node_header(self, node, proj):
        from html import escape
        level = {1: "轻松入门", 2: "基础入门", 3: "进阶探索", 4: "深入实践", 5: "挑战提升"}.get(node.difficulty, "循序渐进")
        return f'<div class="le-lesson-heading"><span class="le-lesson-kicker">LESSON {escape(str(node.code))}</span><h2>{escape(node.title)}</h2><div class="le-lesson-meta"><span>◷ 约 {node.est_hours:g} 小时</span><span>{level}</span><span class="le-lesson-state">{escape(STATUS_LABEL.get(node.status, node.status))}</span></div></div>'

    def _build_progress_md(self, prog):
        # 工具条里只有一行，详细拆分留给看板
        return f"**{prog['done']} / {prog['total']}** · 已掌握 {prog['done']}"

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
                environment_state("done", "环境已配置", "可以回到课程，继续这一节。") if env_task.status == "done" else environment_state()
            )
        return "", environment_state("empty", "暂时无需准备", "当前项目还没有环境配置清单，可先阅读课程。")

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
    def _auto_init(self, project_id=None):
        """页面加载后: 填充项目/课程下拉框 + 预加载第一个可学节点的教学内容。"""
        self._pending_node = None
        try:
            with Session(engine) as s:
                projs = s.exec(
                    select(LearningProject).order_by(LearningProject.id.desc())
                ).all()
                if not projs:
                    return [
                        gr.update(choices=[], value=None),
                        "",
                        gr.update(choices=[], value=None),
                        None,
                        "",
                        None,
                        "*请先创建学习路线*",
                        "",
                        "*本节暂无实操课程。*",
                        "",
                        RESOURCE_EMPTY_MD,
                        self._annotation_empty(),
                        self._timer_update(),
                    ]
                pid = next((p.id for p in projs if str(p.id) == str(project_id)), projs[0].id)
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
                anno_html = self._annotation_empty()
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
                        # 批注也要跟着预加载，否则刷新页面正文里的数字标会不见
                        anno_html = annotations.render_html(
                            annotations.list_for_node(s, first_node_id),
                            node.description or "",
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
                    anno_html,  # 11: 正文批注
                    self._timer_update(),  # 12: 备课轮询开关
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
                self._annotation_empty(),
                self._timer_update(),
            ]

    # ---- 项目相关 ----
    def _delete_current_project(self, project_id, confirm):
        confirmation = (confirm or "").strip()

        def failure(message):
            return [gr.update() for _ in range(13)] + [
                gr.update(value=confirm or ""),
                gr.update(interactive=confirmation == "DELETE"),
                message,
            ]

        try:
            pid = int(project_id)
        except (TypeError, ValueError):
            return failure("请先选择要删除的项目")
        if pid <= 0:
            return failure("请先选择要删除的项目")
        if confirmation != "DELETE":
            return failure("请输入 DELETE 确认删除")
        with Session(engine) as session:
            project = session.get(LearningProject, pid)
            if project is None or project.user_id != "default":
                return failure("项目不存在或无权删除")
            name = project_display_name(project)
        from learning_ext.progress import prep

        if prep.is_busy(pid):
            return failure("当前项目正在备课，完成后再删除")
        try:
            from learning_ext.project_ops import delete_project

            with Session(engine) as session:
                delete_project(session, pid)
        except Exception:
            logger.exception("删除项目失败 #%s", pid)
            return failure("删除失败，请稍后重试")
        getattr(self, "_prep_kicked", set()).discard(pid)
        getattr(self, "_pending_nodes", {}).clear()
        self._pending_node = None
        refreshed = self._auto_init()
        return list(refreshed) + [
            "",
            gr.update(interactive=False),
            f"已删除项目「{html.escape(name)}」及其学习记录",
        ]

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
        self._pending_node = None
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
        self._pending_node = None
        logger.info(f"[工作台] _on_node_select 被调用, node_id={node_id!r}")
        if not node_id or node_id == "__stage__":
            return (
                None,
                "*请先在下拉框中选择一节课，再点「查看课程」*",
                "",
                "*本节暂无实操课程。*",
                "",
                RESOURCE_EMPTY_MD,
                self._annotation_empty(),
                self._timer_update(),
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
                self._annotation_empty(),
                self._timer_update(),
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
                    self._annotation_empty(),
                    self._timer_update(),
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
            # 批注列表：一句一条，guide 传原始正文用于判断「原文是否已被改动」
            anno_html = annotations.render_html(
                annotations.list_for_node(session, nid), guide
            )

        logger.info(
            f"[工作台] 加载节点 [{node.code}] {node.title}, guide长度={len(guide)}"
        )

        guide = self._ensure_course_content(nid, topic, guide)
        guide = self._truncate_guide(guide)
        logger.info(f"[工作台] 返回内容, guide长度={len(guide)}")

        return (
            nid,
            header,
            guide,
            practice_md,
            note_content,
            res_md,
            anno_html,
            self._timer_update(),
        )

    def _timer_update(self):
        """有章节正在后台备课才开轮询，否则关掉。

        常驻轮询（active=True）会让 Gradio 每 3 秒跑一次事件、并在组件上
        重绘一遍加载态，读文章时界面就一直闪。改成按需开关后，安静时零刷新。
        """
        return gr.update(active=self._pending_node is not None)

    @staticmethod
    def _annotation_empty() -> str:
        return annotations.render_html([], "")

    def _on_course_change(self, node_id):
        if not node_id or node_id == "__stage__":
            return tuple(gr.update() for _ in range(8))
        return self._on_node_select(node_id)

    def _ensure_course_content(self, node_id: int, topic: str, guide: str | None) -> str:
        """有内容就直接给；没有就排进后台备课，先显示「正在写这一节」。

        以前这里是同步生成，用户点进来会卡住几十秒，失败还给一段「去点按钮」的提示；
        现在一律不阻塞，写完由定时器自动替换。
        """
        current = guide or ""
        self._pending_node = None
        if is_content_valid(current):
            getattr(self, "_pending_nodes", {}).pop(node_id, None)
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
        kicked = getattr(self, "_prep_kicked", None)
        if kicked is None:
            kicked = self._prep_kicked = set()
        if pid in kicked:
            return
        try:
            with Session(engine) as session:
                nodes = session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.project_id == pid)
                ).all()
                missing = [n.id for n in nodes if not is_content_valid(n.description)]
        except Exception:
            logger.exception("扫描缺失教学内容失败")
            return
        kicked.add(pid)
        if missing:
            prep.start(pid, missing, topic)
            logger.info("[工作台] 项目#%s 后台补备 %d 节", pid, len(missing))

    def _poll_writing(self):
        """定时检查：正在写的这一节写好了没，好了就替换正文。

        gr.Timer 不会传输入，所以用 self._pending_node 记住当前在等哪一节；
        替换成功后清掉，避免每 3 秒重复推同一份内容。
        """
        from learning_ext.progress import prep

        nid = self._pending_node
        if not nid:
            # 没在等任何一节：顺手把轮询关掉，别让它在后台空转
            return gr.update(), gr.update(), gr.update(active=False)
        try:
            with Session(engine) as session:
                node = session.get(KnowledgeNode, int(nid))
                if self._pending_node != nid:
                    return gr.update(), gr.update(), gr.update()
                if not node:
                    self._pending_node = None
                    self._pending_nodes.pop(int(nid), None)
                    return "这节课程已移除，请选择其他章节。", "", gr.update(active=False)
                if not is_content_valid(node.description):
                    if prep.node_status(node.project_id, int(nid)) in {"failed", "done"}:
                        self._pending_node = None
                        self._pending_nodes.pop(int(nid), None)
                        return (
                            "这一节暂时没能准备好。检查模型连接后，重新选择这节课程即可重试。",
                            gr.update(),
                            gr.update(active=False),
                        )
                    return gr.update(), gr.update(), gr.update()
                practice_md = self._render_practice_md(get_practice_task(session, int(nid)))
                body = node.description or ""
        except Exception:
            logger.exception("读取备课结果失败")
            return gr.update(), gr.update(), gr.update()
        if self._pending_node != nid:
            return gr.update(), gr.update(), gr.update()
        self._pending_node = None
        self._pending_nodes.pop(int(nid), None)
        logger.info("[工作台] node#%s 备课完成，自动替换正文", nid)
        # 写完了就把轮询关掉：留着它每 3 秒重绘一次正文，界面会闪
        return self._truncate_guide(body), practice_md, gr.update(active=False)

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

    def _on_annotate(self, node_id, project_id, payload):
        """阅读页划词记的一条批注：新增或删除。"""
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            data = {}
        action = str(data.get("action") or "add")

        if not node_id:
            return gr.update(), self._toast("先在左边选一节课程。", ok=False)
        try:
            nid = int(node_id)
        except (TypeError, ValueError):
            return gr.update(), self._toast("课程还没准备好，稍等再试。", ok=False)

        try:
            with Session(engine) as session:
                if action == "del":
                    ok = annotations.remove(session, int(data.get("id") or 0))
                    msg = "已删除这条批注" if ok else "这条批注已经不在了"
                elif action == "update":
                    body = str(data.get("body") or "").strip()
                    if not body:
                        return gr.update(), self._toast("批注不能是空的。", ok=False)
                    ok = annotations.update(
                        session, int(data.get("id") or 0), body
                    )
                    msg = "已更新这条批注" if ok else "这条批注已经不在了"
                else:
                    quote = str(data.get("quote") or "").strip()
                    body = str(data.get("body") or "").strip()
                    if len(quote) < 2:
                        return gr.update(), self._toast(
                            "没拿到选中的文字，刷新页面再试一次。", ok=False
                        )
                    if not body:
                        return gr.update(), self._toast("批注是空的，没保存。", ok=False)
                    annotations.add(session, nid, project_id, quote, body)
                    msg = "已记下这一条"

                node = session.get(KnowledgeNode, nid)
                html = annotations.render_html(
                    annotations.list_for_node(session, nid),
                    node.description if node else "",
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("批注操作失败 node#%s", node_id)
            return gr.update(), self._toast(f"出错了：{type(exc).__name__}: {exc}", ok=False)

        return html, self._toast(f"{msg} · 可在「笔记」里查看", ok=True)

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
                    yield hidden, environment_state("empty", "暂时无需准备", "当前项目还没有环境配置清单，可先阅读课程。"), None, hidden
                    return
                description, background = task.description, project.background or ""
            yield hidden, environment_state("loading", "正在整理配置方案", "根据当前课程准备步骤，尚未执行任何命令。"), None, hidden
            commands = generate_install_commands(description, background)
            if not commands:
                yield hidden, environment_state("done", "无需额外配置", "可按课程说明直接开始学习。"), None, hidden
                return
            if not isinstance(commands, list) or any(not isinstance(c, dict) or not str(c.get("cmd") or "").strip() for c in commands):
                raise ValueError("生成的配置命令不完整，请重新生成。")
            preview = "\n\n".join(f"# {i}. {c.get('desc', '配置步骤')}\n{c['cmd']}" for i, c in enumerate(commands, 1))
            plan = {"project_id": pid, "fingerprint": hashlib.sha256(description.encode()).hexdigest(), "commands": commands}
            yield gr.update(visible=True, value=preview), environment_state("ready", f"已准备 {len(commands)} 个步骤", "展开下方命令检查。确认执行后，才会在本机安装软件或修改配置。", commands), plan, gr.update(visible=True)
        except (TypeError, ValueError) as exc:
            yield hidden, environment_state("error", "还不能生成方案", str(exc) if project_id else "请先选择学习项目。"), None, hidden
        except Exception:
            logger.exception("Failed to prepare environment setup")
            yield hidden, environment_state("error", "方案暂未生成", "配置方案生成失败，请检查模型连接后重试。"), None, hidden

    def _execute_setup(self, project_id, plan):
        import hashlib
        from learning_ext.practice.auto_setup import run_all_commands

        hidden = gr.update(visible=False)
        try:
            pid = int(project_id)
            if not isinstance(plan, dict) or plan.get("project_id") != pid or not plan.get("commands"):
                yield gr.update(), environment_state("error", "请重新准备方案", "请先为当前项目生成配置方案。"), None, hidden
                return
            with Session(engine) as session:
                task = session.exec(select(Task).where(Task.project_id == pid, Task.task_type == "env")).first()
                fingerprint = hashlib.sha256((task.description or "").encode()).hexdigest() if task else None
            if fingerprint != plan.get("fingerprint"):
                yield gr.update(), environment_state("error", "配置清单有变化", "环境清单已更新，请重新生成方案。"), None, hidden
                return
        except (TypeError, ValueError):
            yield gr.update(), environment_state("error", "尚未选择课程", "请先选择学习项目。"), None, hidden
            return
        yield gr.update(visible=True, value="开始执行已确认的配置方案…"), environment_state("running", "正在配置学习环境", "正在执行你确认的方案，详细输出保留在执行记录中。"), None, hidden
        lines, outcome = [], {}
        for chunk in run_all_commands(plan["commands"], outcome=outcome):
            lines.append(chunk.rstrip("\n"))
            yield gr.update(visible=True, value="\n".join(lines)), environment_state("running", "正在配置学习环境", "正在执行你确认的方案，详细输出保留在执行记录中。"), None, hidden
        status = environment_state("error", "有步骤未完成", "部分配置失败，请查看执行记录。") if outcome.get("failed") else environment_state("review", "配置步骤已完成", "命令执行成功，请验证环境后点击「我已配置好」。")
        yield gr.update(visible=True, value="\n".join(lines)), status, None, hidden

    def _apply_env(self, project_id):
        if not project_id:
            return environment_state("error", "尚未选择课程", "请先选择项目")
        try:
            with Session(engine) as s:
                t = s.exec(
                    select(Task)
                    .where(Task.project_id == int(project_id))
                    .where(Task.task_type == "env")
                ).first()
                if not t:
                    return environment_state("empty", "暂时无需准备", "当前项目还没有环境配置清单。")
                if t:
                    t.status = "done"
                    s.add(t)
                    s.commit()
            return environment_state("done", "环境已配置", "可以回到课程，继续这一节。")
        except Exception as e:
            logger.exception("Failed to confirm environment setup")
            return environment_state("error", "暂时未能保存", "请稍后重试，配置状态尚未更新。")

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

    def _on_snooze(self, payload):
        """用户说「我先学，回头补」：今天不再拿欠复习提醒他。"""
        try:
            pid = int(str(payload or "").strip())
        except (TypeError, ValueError):
            return gr.update()
        try:
            with Session(engine) as s:
                gate.snooze_today(s, pid)
                return self._rhythm_html(s, pid)
        except Exception:
            logger.exception("记录「回头补」失败")
            return gr.update()

    def _on_study_tick(self, node_id, project_id, payload):
        """前端心跳：把刚才的停留秒数记成学习时长。"""
        try:
            seconds = float(str(payload or "0").strip() or 0)
        except (TypeError, ValueError):
            return
        if not node_id or not project_id or seconds <= 0:
            return
        minutes = round(min(seconds, 600) / 60.0, 2)
        if minutes <= 0:
            return
        try:
            from learning_ext.progress import record_study_time

            with Session(engine) as s:
                record_study_time(s, "default", int(project_id), int(node_id), minutes)
                # 同一份心跳也累计到本节过关时长上，省一次前端请求。
                # 上限和上面一致，防止切回标签页时一次性冲进一大段。
                gate.add_dwell(s, int(node_id), min(seconds, 600))
        except Exception:
            logger.exception("记录学习时长失败")

    def _make_cards_in_background(self, node_id: int, content: str) -> None:
        """把刚学完的这一节提炼成复习卡（已有卡就跳过），后台跑。"""
        import threading

        def worker():
            from learning_ext.db.models import Card
            from learning_ext.fsrs_review.service import generate_cards_from_node

            try:
                with Session(engine) as s:
                    has = s.exec(select(Card).where(Card.node_id == int(node_id))).first()
                    if has:
                        return
                    node = s.get(KnowledgeNode, int(node_id))
                    text = content or (node.description if node else "")
                    cards = generate_cards_from_node(
                        s, int(node_id), "default", text, count=5
                    )
                    logger.info("[工作台] node#%s 生成复习卡 %d 张", node_id, len(cards))
            except Exception:
                logger.exception("后台生成复习卡失败 node#%s", node_id)

        threading.Thread(target=worker, name=f"le-cards-{node_id}", daemon=True).start()

    # ---- 学习闭环门控：两关不过不给标已掌握 ----

    def _gate_check_md(self, chk: dict) -> str:
        """把两关状态写成人话，缺什么说清楚。"""

        def mk(ok):
            return "✓" if ok else "○"

        quiz_txt = (
            "还没测"
            if chk["quiz_correct"] < 0
            else f"{chk['quiz_correct']}/{chk['quiz_total']}"
        )
        lines = [
            "#### 还差一点，先把这两关过了",
            f"- {mk(chk['quiz_ok'])} **本节速测**：{quiz_txt}（至少答对 2 题）",
            f"- {mk(chk['recite_ok'])} **复述**："
            + ("助教认可讲清了" if chk["recite_ok"] else "还没通过"),
        ]
        if chk["recite_feedback"] and not chk["recite_ok"]:
            lines.append(f"\n> 助教上次的点评：{chk['recite_feedback']}")
        if not chk["passed"]:
            lines.append("\n这两关都过了，再点一次「已掌握本节 ✓」。")
        return "\n".join(lines)

    def _rhythm_html(self, session, pid) -> str:
        """顶部节奏条：到期多少、欠多久、今天学了多久、该不该查漏。"""
        try:
            r = gate.gate_rhythm(session, int(pid))
            snoozed = gate.is_snoozed_today(session, int(pid))
        except Exception:
            logger.exception("读取学习节奏失败")
            return ""
        parts = []
        if r["due_count"]:
            overdue_days = int(r["overdue_hours"] // 24)
            cls = "warn" if r["overdue_hours"] > 24 else "info"
            txt = f"<b>{r['due_count']} 张卡到期</b>"
            if overdue_days >= 1:
                txt += f"，已经欠了 {overdue_days} 天"
            parts.append(f'<span class="le-rhythm-item {cls}">{txt}</span>')
            parts.append(
                '<button type="button" class="le-rhythm-btn" '
                'data-goto="learning-review-tab">去复习</button>'
            )
            if overdue_days >= 1 and not snoozed:
                parts.append(
                    f'<button type="button" class="le-rhythm-btn ghost" '
                    f'data-snooze="{int(pid)}">我先学，回头补</button>'
                )
        else:
            parts.append('<span class="le-rhythm-item quiet">暂无到期卡片，专心学</span>')
        parts.append(
            f'<span class="le-rhythm-item quiet">今天已学 {r["today_minutes"]} 分钟</span>'
        )
        try:
            stage = gate.stage_due(session, int(pid))
        except Exception:
            stage = False
        if stage:
            parts.append(
                '<span class="le-rhythm-item info">学到整数节，做一次查漏更稳</span>'
                '<button type="button" class="le-rhythm-btn" '
                'data-goto="learning-quiz-tab">去查漏</button>'
            )
        return '<div class="le-rhythm-inner">' + "".join(parts) + "</div>"

    def _refresh_rhythm(self, pid):
        """只刷新顶部节奏条。挂在切换课程之后，不动正文。"""
        if not pid:
            return ""
        try:
            with Session(engine) as s:
                return self._rhythm_html(s, int(pid))
        except Exception:
            logger.exception("刷新节奏条失败")
            return ""

    def _try_master(self, node_id):
        """点「已掌握」：先过两关。没过就展开检查面板，过了才真落状态。"""
        if not node_id:
            return (
                gr.update(),
                "⚠️ 请先选择课程",
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )
        nid = int(node_id)
        try:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, nid)
                if not node:
                    raise ValueError("这一节不存在")
                pid = node.project_id
                chk = gate.check_gate(s, node)
                if not chk["passed"]:
                    return (
                        gr.update(),
                        "先把这两关过了，再标已掌握。",
                        gr.update(),
                        gr.update(),
                        gr.update(visible=True),
                        self._gate_check_md(chk),
                        self._rhythm_html(s, pid),
                        gr.update(
                            selected=(
                                "le-gate-tab-recite"
                                if chk["quiz_ok"]
                                else "le-gate-tab-quiz"
                            )
                        ),
                        gr.update(),
                    )
            msg, prog, course = self._set_status(nid, STATUS_MASTERED)
            with Session(engine) as s:
                node = s.get(KnowledgeNode, nid)
                gate.mark_passed(s, node)
                proj = s.get(LearningProject, pid)
                header = self._build_node_header(node, proj)
                rhythm = self._rhythm_html(s, pid)
                next_id = self._next_node_id(s, node)
            tail = " 已跳到下一节。" if next_id else " 这一节是最后一节。"
            return (
                header,
                msg + tail + " 速测和复述都过了，这一节才算真的学会。",
                prog,
                course,
                gr.update(visible=False),
                "",
                rhythm,
                gr.update(),
                next_id,
            )
        except Exception as e:
            logger.exception("过关检查失败")
            return (
                gr.update(),
                f"❌ {e}",
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )

    def _next_node_id(self, session, node):
        """按编号顺序找下一节。已经是最后一节返回 None。"""
        try:
            rows = session.exec(
                select(KnowledgeNode).where(
                    KnowledgeNode.project_id == node.project_id
                )
            ).all()
            ordered = sort_nodes_by_code(list(rows))
            for i, n in enumerate(ordered):
                if n.id == node.id:
                    return ordered[i + 1].id if i + 1 < len(ordered) else None
        except Exception:
            logger.exception("查找下一节失败")
        return None

    def _goto_next_after_gate(self, next_id):
        """跳过 / 已掌握之后直接翻到下一节，省得用户再回顶部点下拉。"""
        n = 9  # view_outputs 8 项 + 课程下拉
        if not next_id:
            return tuple(gr.update() for _ in range(n)) + ("",)
        try:
            res = self._on_node_select(str(next_id))
            if not isinstance(res, tuple):
                res = tuple(res)
            # 最后一项是滚动信号：内容变了前端才知道该滚回顶部
            kick = f'<i data-kick="{int(datetime.now().timestamp() * 1000)}"></i>'
            return res + (gr.update(value=str(next_id)), kick)
        except Exception:
            logger.exception("自动跳到下一节失败")
            return tuple(gr.update() for _ in range(n)) + ("",)

    def _gate_auto_quiz(self, node_id, items):
        """弹窗一打开就把题出好——不该让用户先点一下才知道要考什么。

        已经刷过题（items 非空）或这一节的速测已经过了，就不再花钱调模型。
        """
        if not node_id:
            return gr.update(), items, gr.update()
        try:
            if items:
                return gr.update(), items, gr.update()
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                if not node:
                    return gr.update(), items, gr.update()
                chk = gate.check_gate(s, node)
            if chk["quiz_ok"]:
                return gr.update(), items, gr.update()
        except Exception:
            logger.exception("进入过关检查时读取状态失败")

        return self._gate_make_quiz(node_id)

    def _gate_skip(self, node_id):
        """弹窗里也能直接跳过，不用先关窗再去找按钮。"""
        if not node_id:
            return (
                gr.update(),
                "⚠️ 请先选择课程",
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )
        try:
            nid = int(node_id)
            msg, prog, course = self._set_status(nid, STATUS_SKIPPED)
            with Session(engine) as s:
                node = s.get(KnowledgeNode, nid)
                proj = s.get(LearningProject, node.project_id) if node else None
                header = self._build_node_header(node, proj) if node else gr.update()
                rhythm = self._rhythm_html(s, node.project_id) if node else gr.update()
                next_id = self._next_node_id(s, node) if node else None
            return (
                header,
                msg + (" 已跳到下一节。" if next_id else " 这一节是最后一节。")
                + " 跳过不计入进度，也不生成复习卡。",
                prog,
                course,
                gr.update(visible=False),
                rhythm,
                next_id,
            )
        except Exception as e:
            logger.exception("跳过本节失败")
            return (
                gr.update(),
                f"❌ {e}",
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
                gr.update(),
            )

    def _gate_make_quiz(self, node_id):
        """给这一节出 3 道速测。"""
        if not node_id:
            return "先选一节课程。", [], ""
        try:
            from learning_ext.quiz.service import generate_quiz

            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                if not node:
                    raise ValueError("这一节不存在")
                quiz = generate_quiz(
                    s,
                    "default",
                    [node.id],
                    project_id=node.project_id,
                    count=3,
                    qtype="mixed",
                )
                rows = s.exec(
                    select(QuizQuestion)
                    .where(QuizQuestion.quiz_id == quiz.id)
                    .order_by(QuizQuestion.id)
                ).all()
                items = [
                    {
                        "qtype": q.qtype,
                        "stem": q.stem,
                        "options": q.options or "",
                        "answer": q.answer,
                    }
                    for q in rows
                ]
                title = node.title
        except Exception as e:
            logger.exception("出速测题失败")
            return f"❌ 出题失败：{friendly_error(e)}", [], ""

        if not items:
            return "❌ 这次没出出题来，再试一次。", [], ""

        blocks = [f"围绕「{title}」的 {len(items)} 道速测："]
        for i, it in enumerate(items, 1):
            blocks.append(f"**{i}. {md_safe(it['stem'])}**")
            opts = []
            try:
                raw = json.loads(it["options"]) if it["options"] else []
                opts = raw if isinstance(raw, list) else []
            except Exception:
                opts = []
            if opts:
                blocks.extend(f"　　{x}" for x in opts)
        blocks.append("> 选择题填字母（如 B），填空和简答直接写关键词。")
        return "\n\n".join(blocks), items, ""

    def _gate_submit(self, node_id, a1, a2, a3, items):
        """判速测，记最好成绩。"""
        if not node_id or not items:
            return "还没出题，稍等一下。", gr.update(), gr.update()
        try:
            result = gate.grade_quick(list(items), [a1, a2, a3])
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                gate.mark_quiz(s, node.id, result["correct"], result["total"])
                chk = gate.check_gate(s, node)
            lines = [f"**速测 {result['correct']}/{result['total']}**"]
            for i, d in enumerate(result["details"], 1):
                lines.append(
                    f"- 第 {i} 题 {'✅' if d['ok'] else '❌'}"
                    + (f"　{d['note']}" if d["note"] else "")
                )
            passed = result["correct"] >= gate.RECITE_PASS_BRIEF
            if passed:
                lines.append("\n速测过了。接着把这一节用自己的话讲一遍。")
            else:
                lines.append(
                    f"\n至少要对 {gate.RECITE_PASS_BRIEF} 题。回头翻一下正文，再测一次。"
                )
            return (
                "\n".join(lines),
                self._gate_check_md(chk),
                gr.update(
                    selected=(
                        "le-gate-tab-recite" if passed else "le-gate-tab-quiz"
                    )
                ),
            )
        except Exception as e:
            logger.exception("提交速测失败")
            return (
                f"❌ 判分失败：{friendly_error(e)}",
                gr.update(),
                gr.update(),
            )

    def _gate_recite(self, node_id, text):
        """让助教判断复述是否讲清。"""
        if not node_id:
            return "先选一节课程。", gr.update()
        if not (text or "").strip():
            return "还没写呢。不看原文，用自己的话说两句。", gr.update()
        try:
            with Session(engine) as s:
                node = s.get(KnowledgeNode, int(node_id))
                if not node:
                    raise ValueError("这一节不存在")
                verdict = gate.judge_recite(node, text)
                gate.save_recite(s, node, text, verdict)
                chk = gate.check_gate(s, node)
            head = "✅ 助教认为你讲清了。" if verdict["passed"] else "⬜ 还差点意思。"
            fb = verdict.get("feedback") or ""
            return (
                f"{head}{fb}",
                "" if chk["passed"] else self._gate_check_md(chk),
            )
        except Exception as e:
            logger.exception("复述判定失败")
            return f"❌ 判定失败：{friendly_error(e)}", gr.update()

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
                body_for_cards = node.description or ""
                if status == STATUS_MASTERED:
                    # 学完就把它变成复习卡，否则「间隔复习」永远是空的，
                    # 「学习 → 记住」这条路是断的。放到后台线程，别卡界面。
                    self._make_cards_in_background(nid, body_for_cards)
                prog = get_project_progress(s, pid)
                progress_md = self._build_progress_md(prog)
                nodes_data = self._build_nodes_data(s, pid)
            course_c = self._build_drop_choices(nodes_data)
            if status == STATUS_MASTERED:
                msg = "🎉 已掌握！复习卡正在后台生成，下一节也在准备中。"
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
