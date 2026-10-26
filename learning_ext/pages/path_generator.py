"""学习路线 Tab - 选题 → AI 拆知识 DAG → 可视化展示。

这是阶段 1 的核心 Tab，演示如何把 learning_ext 业务模块接入 Kotaemon 的 BasePage。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from learning_ext.page_design import page_intro
import gradio as gr
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import KnowledgeNode, LearningProject
from learning_ext.path_generator import (
    audit_existing_roadmap,
    audit_and_rewrite_roadmap,
    export_roadmap_bundle,
    generate_roadmap,
    import_roadmap_bundle,
    load_roadmap,
    refine_roadmap,
    replace_project_roadmap,
    save_roadmap,
)
from learning_ext.progress.study import course_code_sort_key, sort_nodes_by_code

logger = logging.getLogger(__name__)


class PathGeneratorPage(BasePage):
    """学习路线生成与展示页面"""

    public_events = ["onProjectCreated", "onProjectSwitched"]

    def __init__(self, app):
        super().__init__(app)
        # 当前项目 id 状态
        self.current_project_id = gr.State(None)
        self.delete_confirmation_project_id = gr.State(None)
        # 保存后那一段进度文案的固定部分（备课进度会追加在后面）
        self._save_base_md = ""
        self._last_prep_md = ""
        self._save_pid: int | None = None

    def on_building_ui(self):
        gr.HTML(page_intro("route"))
        gr.HTML('<div class="le-flow-context"><button type="button" data-le-nav="learning-guide-tab">返回学习安排</button></div>')
        with gr.Accordion("已有路线与管理 · 需要时展开", open=False, elem_id="le-route-history"):
            self.project_list = gr.Radio(
                label="选择学习路线",
                show_label=False,
                choices=[],
                value=None,
                interactive=True,
                elem_id="le-route-picker",
            )
            self.history_empty = gr.HTML(
                '<div class="le-route-picker-empty"><strong>从第一条路线开始</strong>'
                '<span>先选择你想学会的事。</span></div>',
                elem_id="le-route-history-empty",
            )
            with gr.Row(elem_id="le-route-actions"):
                self.refresh_btn = gr.Button("刷新列表", size="sm")
                self.export_roadmap_btn = gr.Button("导出学习路线", size="sm")
            self.export_roadmap_file = gr.File(
                label="下载路线文件", interactive=False, visible=False,
                elem_id="le-route-export-file",
            )
            with gr.Accordion("路线文件 · 导入与导出", open=False, elem_id="le-route-files"):
                self.import_roadmap_file = gr.File(
                    label="选择路线文件", file_types=[".json"],
                    elem_id="le-route-import-file",
                )
                self.import_roadmap_btn = gr.Button("导入学习路线", variant="primary")
            with gr.Accordion("项目管理", open=False, elem_id="le-route-management") as self.management:
                self.batch_selection = gr.CheckboxGroup(label="选择要删除的路线", choices=[], interactive=True, elem_id="le-route-batch-list")
                self.batch_review = gr.Button("删除选中路线", variant="stop", size="sm")
                self.batch_summary = gr.Markdown("", elem_id="le-route-batch-summary")
                self.batch_confirmed = gr.State([])
                self.batch_commit = gr.Button("确认删除", variant="stop", interactive=False, visible=False)
                with gr.Row(visible=False):
                    self.delete_confirm = gr.Textbox(
                        label="确认删除", show_label=False, placeholder="DELETE", lines=1,
                        elem_id="le-route-delete-confirm",
                    )
                    self.delete_btn = gr.Button("删除所选路线", variant="stop", size="sm")
        with gr.Row(elem_id="le-planner"):
            with gr.Column(visible=False, elem_id="le-plan-input"):
                gr.HTML('<div id="le-wizard-header"><div class="le-wizard-top"><span data-wizard-count>01 / 04</span><span>为你定制学习路线</span></div><div class="le-wizard-track"><i></i></div><h2 data-wizard-title>想学点什么？</h2><p data-wizard-hint>从一个想解决的问题开始，一句话就够。</p><div data-wizard-feedback role="status" aria-live="polite"></div></div>')
                self.topic_input = gr.Textbox(
                    label="想学什么", elem_id="le-wizard-topic",
                    placeholder="例如：从零理解 Transformer，并实现一个小型语言模型",
                    lines=3,
                )
                self.background_input = gr.Textbox(
                    label="已有基础 · 可选", elem_id="le-wizard-background",
                    placeholder="例如：熟悉 Python，了解基础线性代数",
                    lines=2,
                )
                self.goal_input = gr.Textbox(
                    label="希望达到的目标 · 可选", elem_id="le-wizard-goal",
                    placeholder="例如：读懂论文，并独立完成一次实验",
                    lines=2,
                )
                self.hours_input = gr.Slider(
                    label="每周投入 / 小时", elem_id="le-wizard-hours", minimum=1, maximum=40, value=3, step=1
                )
                gr.HTML('<div id="le-wizard-nav"><button data-wizard-back>返回</button><button data-wizard-next>继续 →</button></div>')
                self.generate_btn = gr.Button("生成我的学习路线 →", variant="primary", elem_id="le-wizard-generate")
                gr.Markdown(
                    "首次使用需先在「模型配置」连接模型。完成这四步后，即可生成并预览路线。"
                )
            with gr.Column(scale=3, min_width=340, elem_id="le-plan-preview"):
                gr.HTML('<div class="le-preview-heading"><div><h2>阶段与课程</h2></div><button type="button" data-le-nav="learning-guide-tab">调整学习目标</button></div>')
                self.generating = gr.HTML("", visible=False, elem_id="le-route-generating")
                self.roadmap_output = gr.Markdown(
                    self._roadmap_to_markdown({}),
                    elem_classes=["learning-roadmap", "le-route-result"], elem_id="le-route-output",
                )
                self.status = gr.Markdown("", elem_id="le-route-status")
                with gr.Row(elem_id="le-route-decisions"):
                    self.save_btn = gr.Button(
                        "就按这个学 →", variant="primary", interactive=False, visible=False, elem_id="le-route-save"
                    )
                    self.regenerate_btn = gr.Button(
                        "重新规划", size="sm", visible=False, elem_id="le-route-regenerate"
                    )
                self.save_note = gr.Markdown(
                    "确认后会保存路线并开始备课，准备好的章节会陆续出现。", visible=False, elem_id="le-route-save-note"
                )
                self.save_progress = gr.HTML("", elem_id="le-route-save-progress")
                self.prep_context = gr.State({})
                self.open_course = gr.Button("打开这门课程 →", variant="primary", visible=False, elem_id="le-open-saved-course")
        # 备课进度轮询（保存后自动刷新，不用再点任何按钮）
        self.prep_timer = gr.Timer(4.0, active=False)

        # 保存路线时要读它，界面上不露出来
        self.roadmap_json = gr.Code(language="json", label="路线 JSON", visible=False)

    def on_register_events(self):
        """绑定按钮事件"""
        self._app.app.load(
            fn=self._refresh_picker,
            inputs=[self.current_project_id],
            outputs=[self.project_list, self.history_empty],
            show_progress="hidden",
        )
        self._app.app.load(self._latest_route, outputs=[self.roadmap_output, self.roadmap_json, self.current_project_id, self.status], show_progress="hidden").then(self._load_preparation, inputs=[self.current_project_id], outputs=[self.save_progress, self.prep_context, self.prep_timer], show_progress="hidden")
        self.roadmap_json.change(
            fn=self._route_actions,
            inputs=[self.roadmap_json, self.current_project_id],
            outputs=[self.save_btn, self.regenerate_btn, self.open_course, self.save_note],
            show_progress="hidden",
        )
        project_changed = self.current_project_id.change(
            fn=self._route_actions,
            inputs=[self.roadmap_json, self.current_project_id],
            outputs=[self.save_btn, self.regenerate_btn, self.open_course, self.save_note],
            show_progress="hidden",
        ).then(
            self._sync_route_selection,
            inputs=[self.current_project_id],
            outputs=[self.project_list, self.history_empty, self.delete_confirm,
                     self.export_roadmap_file, self.delete_confirmation_project_id],
            show_progress="hidden",
        )
        for event in self._app.get_event("onProjectSwitched"):
            project_changed = project_changed.then(**event)
        self.generate_btn.click(
            self._begin_generation,
            outputs=[self.current_project_id, self.save_progress, self.status, self.roadmap_json, self.roadmap_output, self.generating, self.generate_btn, self.regenerate_btn],
            show_progress="hidden",
        ).then(
            fn=self._generate_preview,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
            ],
            outputs=[self.roadmap_output, self.roadmap_json, self.status, self.generating, self.generate_btn, self.regenerate_btn],
            show_progress="full",
        ).then(
            fn=self._refresh_picker,
            inputs=[self.current_project_id],
            outputs=[self.project_list, self.history_empty],
            show_progress="hidden",
        )

        self.regenerate_btn.click(
            self._begin_generation,
            outputs=[self.current_project_id, self.save_progress, self.status, self.roadmap_json, self.roadmap_output, self.generating, self.generate_btn, self.regenerate_btn],
            show_progress="hidden",
        ).then(
            fn=self._generate_preview,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
            ],
            outputs=[self.roadmap_output, self.roadmap_json, self.status, self.generating, self.generate_btn, self.regenerate_btn],
            show_progress="full",
        )

        # 保存：生成器流式输出进度 (自动搜集资料 + 生成环境清单)
        self.save_btn.click(lambda: gr.update(interactive=False), outputs=self.save_btn, show_progress="hidden").then(
            fn=self._handle_save_with_setup,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
                self.roadmap_json,
            ],
            outputs=[self.current_project_id, self.save_progress, self.status, self.prep_context],
            show_progress="hidden",
        ).then(
            fn=self._refresh_picker,
            inputs=[self.current_project_id],
            outputs=[self.project_list, self.history_empty],
            show_progress="hidden",
        ).then(
            # 备课排队了才把定时器打开；备完由 _poll_prep 自己关掉。
            # 常驻轮询会让每次 tick 都重绘一遍组件，界面就一直在闪。
            fn=lambda: gr.update(active=True),
            outputs=[self.prep_timer],
        ).then(self._route_actions, inputs=[self.roadmap_json, self.current_project_id], outputs=[self.save_btn, self.regenerate_btn, self.open_course, self.save_note], show_progress="hidden")

        # 备课进度：排队期间每 4 秒看一眼，备完自动停
        # show_progress="hidden" 必须加：不加的话每次 tick 都会在组件上盖一层
        # 半透明遮罩 + spinner，界面看着就是一直在闪
        self.prep_timer.tick(
            fn=self._poll_prep,
            inputs=[self.prep_context],
            outputs=[self.save_progress, self.prep_timer, self.prep_context],
            show_progress="hidden",
        )

        self.refresh_btn.click(
            fn=self._refresh_current_route,
            inputs=[self.current_project_id],
            outputs=[self.project_list, self.history_empty, self.roadmap_output,
                     self.roadmap_json, self.current_project_id, self.status,
                     self.save_progress, self.prep_context, self.prep_timer],
            show_progress="hidden",
        )

        self.project_list.input(
            fn=self._begin_route_selection,
            outputs=[self.delete_confirm, self.delete_confirmation_project_id,
                     self.export_roadmap_file],
            show_progress="hidden",
        ).then(
            fn=self._handle_load,
            inputs=[self.project_list],
            outputs=[
                self.roadmap_output,
                self.roadmap_json,
                self.current_project_id,
                self.status,
            ],
            show_progress="hidden",
        ).then(self._load_preparation, inputs=[self.current_project_id], outputs=[self.save_progress, self.prep_context, self.prep_timer], show_progress="hidden")
        self.delete_confirm.input(
            fn=self._bind_delete_confirmation,
            inputs=[self.delete_confirm, self.project_list, self.current_project_id],
            outputs=[self.delete_confirmation_project_id],
            show_progress="hidden",
        )
        self.export_roadmap_btn.click(
            fn=self._handle_export_roadmap_selection,
            inputs=[self.project_list],
            outputs=[self.export_roadmap_file, self.status],
            show_progress="hidden",
        )
        self.import_roadmap_btn.click(
            fn=self._handle_import_roadmap_selection,
            inputs=[self.import_roadmap_file, self.current_project_id],
            outputs=[
                self.project_list,
                self.history_empty,
                self.roadmap_output,
                self.roadmap_json,
                self.current_project_id,
                self.status,
            ],
            show_progress="hidden",
        ).then(self._load_preparation, inputs=[self.current_project_id], outputs=[self.save_progress, self.prep_context, self.prep_timer], show_progress="hidden")
        self.delete_btn.click(
            fn=self._handle_delete_selection,
            inputs=[self.project_list, self.delete_confirm, self.current_project_id,
                    self.delete_confirmation_project_id],
            outputs=[self.project_list, self.history_empty, self.roadmap_output, self.roadmap_json,
                     self.current_project_id, self.status, self.delete_confirm,
                     self.delete_confirmation_project_id],
            show_progress="hidden",
        ).then(self._load_preparation, inputs=[self.current_project_id], outputs=[self.save_progress, self.prep_context, self.prep_timer], show_progress="hidden")

        self._app.app.load(self._batch_choices, outputs=self.batch_selection, show_progress="hidden")
        self.current_project_id.change(self._batch_choices, outputs=self.batch_selection, show_progress="hidden")
        self.refresh_btn.click(self._batch_choices, outputs=self.batch_selection, show_progress="hidden")
        self.batch_selection.input(lambda: ([], "", gr.update(visible=False, interactive=False)),
            outputs=[self.batch_confirmed, self.batch_summary, self.batch_commit], show_progress="hidden")
        self.batch_review.click(self._review_batch_delete, inputs=self.batch_selection,
            outputs=[self.batch_confirmed, self.batch_summary, self.batch_commit], show_progress="hidden")
        self.batch_commit.click(self._commit_batch_delete,
            inputs=[self.batch_selection, self.batch_confirmed, self.current_project_id],
            outputs=[self.batch_selection, self.batch_confirmed, self.batch_summary, self.batch_commit,
                     self.project_list, self.history_empty, self.roadmap_output, self.roadmap_json,
                     self.current_project_id, self.status], show_progress="hidden"
        ).then(self._load_preparation, inputs=self.current_project_id,
               outputs=[self.save_progress, self.prep_context, self.prep_timer], show_progress="hidden")

    def _batch_choices(self):
        return gr.update(choices=[(row[1], row[0]) for row in self._refresh_projects()], value=[])

    def _review_batch_delete(self, selection):
        from html import escape
        ids = sorted({int(value) for value in (selection or [])})
        rows = {row[0]: row[1] for row in self._refresh_projects()}
        if not ids or any(pid not in rows for pid in ids):
            return [], "请选择当前列表中的路线。", gr.update(visible=False, interactive=False)
        names = "".join(f"<li>{escape(rows[pid])}</li>" for pid in ids)
        return ids, f"<strong>将删除 {len(ids)} 条路线</strong><ul>{names}</ul><p>课程、笔记和学习记录会一并删除，无法撤销。</p>", gr.update(value=f"确认删除 {len(ids)} 条路线", visible=True, interactive=True)

    def _commit_batch_delete(self, selection, confirmed, current_project_id):
        from learning_ext.project_ops import delete_projects
        ids = sorted({int(value) for value in (selection or [])})
        if not ids or ids != sorted(confirmed or []):
            return (gr.update(), [], "选择已变化，请重新确认。", gr.update(visible=False),
                    *(gr.update() for _ in range(6)))
        try:
            with Session(engine) as session:
                result = delete_projects(session, ids)
            logger.info("Batch deleted learning projects: %s", result["project_ids"])
        except Exception:
            logger.exception("批量删除失败")
            return (gr.update(), [], "未能完成删除，请刷新后重试。", gr.update(visible=False),
                    *(gr.update() for _ in range(6)))
        current = self._selected_project_id(current_project_id)
        if current in ids:
            markdown, raw, current, _ = self._latest_route()
        else:
            markdown, raw = gr.update(), gr.update()
        return (self._batch_choices(), [], f"已删除 {len(ids)} 条路线。", gr.update(visible=False),
                *self._refresh_picker(current), markdown, raw, current, "")

    # ---- 业务处理函数 ----

    @staticmethod
    def _save_availability(raw):
        try:
            valid = bool(json.loads(raw or "{}").get("nodes"))
        except (ValueError, TypeError, AttributeError):
            valid = False
        return gr.update(interactive=valid, visible=valid)

    @classmethod
    def _route_actions(cls, raw, project_id):
        from learning_ext.route_view import route_action_label

        save = cls._save_availability(raw)
        if project_id:
            save = gr.update(interactive=False, visible=False)
        try:
            roadmap = json.loads(raw or "{}")
            if not isinstance(roadmap, dict):
                roadmap = {}
        except (ValueError, TypeError, AttributeError):
            roadmap = {}
        open_course = gr.update(visible=bool(project_id), value=route_action_label(roadmap))
        return save, gr.update(visible=False), open_course, gr.update(visible=save["visible"])

    @staticmethod
    def _begin_generation():
        waiting = '<div class="le-route-wait" role="status" aria-live="polite"><h3>正在把你的目标拆成小步骤</h3><p>AI 正在拟定路线，并检查知识点的先后顺序。<br>这可能需要一点时间，完成后会自动显示在这里。</p><div class="le-route-wait-note">你会先看到预览，确认之后才会保存。</div></div>'
        return None, "", "", "{}", "", gr.update(value=waiting, visible=True), gr.update(interactive=False), gr.update(interactive=False)

    def _generate_preview(self, topic, background, goal, hours):
        result = self._handle_generate(topic, background, goal, hours)
        return *result, gr.update(visible=False), gr.update(interactive=True), gr.update(interactive=True)

    def _handle_generate(self, topic, background, goal, hours):
        """生成路线"""
        if not topic or not topic.strip():
            return "", "{}", "⚠️ 请输入选题"
        try:
            roadmap = generate_roadmap(
                topic=topic.strip(),
                background=background or "",
                goal=goal or "",
                weekly_hours=float(hours) if hours else 10.0,
            )
            audited = audit_and_rewrite_roadmap(
                roadmap=roadmap,
                topic=topic.strip(),
                background=background or "",
                goal=goal or "",
                weekly_hours=float(hours) if hours else 10.0,
            )
            audit = audited.pop("_audit", {})
            audited_md = self._roadmap_to_markdown(audited)
            audit_md = self._audit_to_markdown(audit)
            return (
                f"{audited_md}\n\n<details><summary>查看路线检查结果</summary>\n\n{audit_md}\n\n</details>",
                json.dumps(audited, ensure_ascii=False, indent=2),
                "✅ 路线已准备好。确认适合你后，点「就按这个学」保存。",
            )
        except Exception as e:
            logger.exception("生成路线失败")
            return "", "{}", f"❌ 生成失败: {e}"

    def _handle_refine(self, current_json, instruction):
        """按意见调整路线"""
        if not instruction or not instruction.strip():
            return "", current_json, "⚠️ 请输入调整意见"
        try:
            current = json.loads(current_json) if current_json else {}
            refined = refine_roadmap(current, instruction.strip())
            md = self._roadmap_to_markdown(refined)
            return (
                md,
                json.dumps(refined, ensure_ascii=False, indent=2),
                "✅ 路线已调整",
            )
        except Exception as e:
            logger.exception("调整路线失败")
            return "", current_json, f"❌ 调整失败: {e}"

    @staticmethod
    def _preparation_view(context):
        from learning_ext.progress import prep
        from learning_ext.progress.study import is_content_valid
        from learning_ext.route_view import preparation_panel

        with Session(engine) as session:
            nodes = session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == context["pid"])).all()
            ready = sum(is_content_valid(n.description or "") for n in nodes)
        snapshot = prep.snapshot(context["pid"])
        return preparation_panel(context["topic"], len(nodes), env_ready=context.get("env_ready", True), ready=ready,
                                 failed=len(set(snapshot.get("failed", []))), running=snapshot.get("running", False))

    def _load_preparation(self, pid):
        from learning_ext.progress import prep

        if not pid:
            return "", {}, gr.update(active=False)
        with Session(engine) as session:
            project = session.get(LearningProject, int(pid))
            if not project:
                return "", {}, gr.update(active=False)
            context = {"pid": int(pid), "topic": project.topic, "env_ready": None}
        content = self._preparation_view(context)
        return content, {**context, "last": content}, gr.update(active=prep.is_busy(pid))

    def _poll_prep(self, context):
        from learning_ext.progress import prep

        if not context or not context.get("pid"):
            return gr.update(), gr.update(active=False), gr.update()
        content = self._preparation_view(context)
        active = prep.is_busy(context["pid"])
        if context.get("last") == content:
            return gr.update(), gr.update(active=active), gr.update()
        return content, gr.update(active=active), {**context, "last": content}

    def _handle_save_with_setup(self, topic, background, goal, hours, roadmap_json):
        from learning_ext.route_view import preparation_panel
        from learning_ext.progress import prep

        if not roadmap_json or roadmap_json == "{}":
            yield None, "", "请先生成路线：回到学习首页填写目标即可。", {}
            return
        try:
            roadmap = json.loads(roadmap_json)
        except json.JSONDecodeError:
            yield None, "", "路线解析失败，请返回学习首页重新生成。", {}
            return
        count = len(roadmap.get("nodes", []))
        yield None, preparation_panel(topic, count, phase="saving"), "", {}
        try:
            with Session(engine) as session:
                project = save_roadmap(session=session, user_id="default", topic=topic or "未命名选题",
                                       background=background or "", goal=goal or "",
                                       weekly_hours=float(hours) if hours else 3.0, roadmap=roadmap)
                pid = project.id
        except Exception:
            logger.exception("保存项目失败")
            yield None, "", "暂时未能保存。路线预览还在，请稍后重试。", {}
            return
        context = {"pid": pid, "topic": topic, "count": count, "env_ready": True}
        yield pid, preparation_panel(topic, count, phase="environment"), "", {}
        try:
            from learning_ext.progress.study import generate_env_checklist, save_env_tasks
            env_md = generate_env_checklist(topic or "未命名选题", background or "")
            with Session(engine) as session:
                save_env_tasks(session, pid, env_md)
        except Exception:
            logger.exception("环境清单生成失败")
            env_md = ""
            context["env_ready"] = False
        with Session(engine) as session:
            nodes = session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == pid)).all()
            ordered_ids = [n.id for n in sort_nodes_by_code(list(nodes))]
        prep.start(pid, ordered_ids, topic or "", goal=goal or "", env=env_md)
        content = self._preparation_view(context)
        yield pid, content, "", {**context, "last": content}

    @staticmethod
    def _selected_project_id(value):
        try:
            project_id = int(value)
        except (TypeError, ValueError):
            return None
        return project_id if project_id > 0 else None

    @classmethod
    def _picker_updates(cls, rows, project_id=None):
        choices = [
            (f"{row[1]}\n{row[2].split(' ', 1)[0]} 节已完成", row[0])
            for row in rows
        ]
        selected = cls._selected_project_id(project_id)
        if selected not in {value for _, value in choices}:
            selected = None
        return (
            gr.update(choices=choices, value=selected, visible=bool(choices)),
            gr.update(visible=not choices),
        )

    def _refresh_picker(self, project_id=None):
        return self._picker_updates(self._refresh_projects(), project_id)

    def _refresh_current_route(self, project_id=None):
        picker = self._refresh_picker(project_id)
        if self._selected_project_id(project_id) is None:
            return *picker, *(gr.update() for _ in range(7))
        markdown, raw, current, status = self._handle_load(project_id)
        return *picker, markdown, raw, current, status, *self._load_preparation(current)

    @staticmethod
    def _begin_route_selection():
        return gr.update(value=""), None, gr.update(value=None, visible=False)

    @classmethod
    def _bind_delete_confirmation(cls, confirmation, project_id, current_project_id):
        selected = cls._selected_project_id(project_id)
        current = cls._selected_project_id(current_project_id)
        if (confirmation or "").strip() == "DELETE" and selected == current:
            return selected
        return None

    def _sync_route_selection(self, project_id):
        return (
            *self._refresh_picker(project_id),
            gr.update(value=""),
            gr.update(value=None, visible=False),
            None,
        )

    def _project_brief_md(self, proj) -> str:
        """把建档时填的那几项原样摆出来。

        用户隔几天回来，看到一堆章节标题，会想不起当初为什么这么排。
        """
        if proj is None:
            return ""
        from html import escape
        rows = []
        if (proj.topic or "").strip():
            rows.append(f'<div class="le-goal-primary"><span>我想学会</span><strong>{escape(proj.topic.strip())}</strong></div>')
        if (proj.background or "").strip():
            rows.append(f'<div><span>我的起点</span><p>{escape(proj.background.strip())}</p></div>')
        if (proj.goal or "").strip() and proj.goal.strip() != (proj.topic or "").strip():
            rows.append(f'<div><span>期待的改变</span><p>{escape(proj.goal.strip())}</p></div>')
        if proj.weekly_hours:
            rows.append(f'<div><span>学习节奏</span><p>每周 <b>{proj.weekly_hours:g}</b> 小时</p></div>')
        if proj.created_at:
            rows.append(f'<div><span>启程于</span><p>{proj.created_at.strftime("%Y.%m.%d")}</p></div>')
        if not rows:
            return ""
        return '<div class="le-goal-memory">' + ''.join(rows) + '</div>'

    def _handle_load(self, project_id):
        """加载已有项目"""
        project_id = self._selected_project_id(project_id)
        if project_id is None:
            return gr.update(), gr.update(), gr.update(), "请先选择一条学习路线。"
        try:
            with Session(engine) as session:
                proj = session.get(LearningProject, int(project_id))
                brief = self._project_brief_md(proj)
                roadmap = load_roadmap(session, int(project_id))
                md = self._roadmap_to_markdown({**roadmap, "topic": proj.topic if proj else ""})
                if brief:
                    md = f'{md}\n\n<details class="le-goal-disclosure"><summary>我的学习初衷</summary>{brief}</details>'
                return (
                    md,
                    json.dumps(roadmap, ensure_ascii=False, indent=2),
                    int(project_id),
                    "",
                )
        except Exception as e:
            logger.exception("加载项目失败")
            return "", "{}", None, f"❌ 加载失败: {e}"

    def _latest_route(self):
        with Session(engine) as session:
            project = session.exec(select(LearningProject).join(KnowledgeNode).where(LearningProject.user_id == "default", LearningProject.status == "active").order_by(LearningProject.id.desc())).first()
            pid = project.id if project else None
        if pid:
            return self._handle_load(pid)
        return self._roadmap_to_markdown({}), "{}", None, ""

    def _handle_export_roadmap(self, project_id):
        """导出项目学习路线为格式化 JSON 文件。"""
        project_id = self._selected_project_id(project_id)
        if project_id is None:
            return None, "请先选择要导出的学习路线。"
        try:
            with Session(engine) as session:
                payload = export_roadmap_bundle(session, int(project_id))
                project = session.get(LearningProject, project_id)
                title = project.title or "未命名路线"
            export_dir = Path(".tmp") / "roadmap_exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            path = export_dir / f"learning_route_{int(project_id)}.json"
            path.write_text(payload, encoding="utf-8")
            return str(path), f"已导出「{title}」。"
        except Exception as e:
            logger.exception("导出学习路线失败")
            return None, f"❌ 导出失败: {e}"

    def _handle_export_roadmap_selection(self, project_id):
        path, status = self._handle_export_roadmap(project_id)
        return gr.update(value=path, visible=bool(path)), status

    def _handle_import_roadmap(self, file_obj):
        """导入格式化学习路线 JSON，创建新项目。"""
        if file_obj is None:
            return (
                self._refresh_projects(),
                gr.update(),
                gr.update(),
                None,
                "⚠️ 请先选择 JSON 文件",
            )
        try:
            path = str(file_obj) if isinstance(file_obj, (str, Path)) else file_obj.name
            payload = Path(path).read_text(encoding="utf-8")
            with Session(engine) as session:
                project = import_roadmap_bundle(session, payload, user_id="default")
                roadmap = load_roadmap(session, project.id)
                md = self._roadmap_to_markdown({**roadmap, "topic": project.topic})
                return (
                    self._refresh_projects(),
                    md,
                    json.dumps(roadmap, ensure_ascii=False, indent=2),
                    project.id,
                    f"已导入「{project.title or '未命名路线'}」。",
                )
        except Exception as e:
            logger.exception("导入学习路线失败")
            return (
                self._refresh_projects(),
                gr.update(),
                gr.update(),
                None,
                f"❌ 导入失败: {e}",
            )

    def _handle_import_roadmap_selection(self, file_obj, current_project_id):
        rows, markdown, raw, project_id, status = self._handle_import_roadmap(file_obj)
        selected = project_id if project_id is not None else current_project_id
        return (
            *self._picker_updates(rows, selected),
            markdown,
            raw,
            project_id if project_id is not None else gr.update(),
            status,
        )

    def _handle_delete_project(self, project_id, confirm):
        """删除项目及其学习数据"""
        project_id = self._selected_project_id(project_id)
        if project_id is None:
            return self._refresh_projects(), "请先选择要删除的学习路线。"
        if (confirm or "").strip() != "DELETE":
            return self._refresh_projects(), "⚠️ 如需删除，请在确认文本中输入 DELETE"
        try:
            from learning_ext.project_ops import delete_project

            with Session(engine) as session:
                project = session.get(LearningProject, project_id)
                title = project.title if project else "未命名路线"
                delete_project(session, int(project_id))
            return (
                self._refresh_projects(),
                f"✅ 已删除项目「{title}」及其学习记录。",
            )
        except Exception as e:
            logger.exception("删除项目失败")
            return self._refresh_projects(), f"❌ 删除失败: {e}"

    def _handle_delete_selection(self, project_id, confirm, current_project_id, confirmed_project_id=None):
        selected = self._selected_project_id(project_id)
        current = self._selected_project_id(current_project_id)
        confirmed = self._selected_project_id(confirmed_project_id)
        if (confirm or "").strip() == "DELETE" and (
            selected is None or selected != current or selected != confirmed
        ):
            return (
                *self._refresh_picker(current),
                gr.update(), gr.update(), gr.update(),
                "路线已切换，请重新输入 DELETE 确认。", "", None,
            )
        rows, status = self._handle_delete_project(project_id, confirm)
        deleted = status.startswith("✅") and selected not in {row[0] for row in rows}
        if not deleted:
            return (
                *self._picker_updates(rows, current_project_id),
                gr.update(), gr.update(), gr.update(), status, gr.update(), gr.update(),
            )
        if current == selected:
            next_id = rows[0][0] if rows else None
            if next_id:
                markdown, raw, current, _ = self._handle_load(next_id)
            else:
                markdown, raw, current = self._roadmap_to_markdown({}), "{}", None
        else:
            markdown, raw = gr.update(), gr.update()
        return (
            *self._picker_updates(rows, current),
            markdown, raw, current, status, "", None,
        )

    def _handle_audit_project(self, project_id):
        """审计旧项目路线，替换路线并批量重生成课程内容。"""
        try:
            project_ids = self._parse_audit_project_ids(project_id)
            with Session(engine) as session:
                if not project_ids:
                    project_ids = [
                        p.id
                        for p in session.exec(
                            select(LearningProject).order_by(LearningProject.id)
                        ).all()
                        if p.id is not None
                    ]
                if not project_ids:
                    return (
                        self._refresh_projects(),
                        gr.update(),
                        gr.update(),
                        "⚠️ 当前没有可审计的项目",
                        "⚠️ 当前没有可审计的项目",
                    )

            results = []
            last_improved = None
            last_md = ""
            for pid in project_ids:
                with Session(engine) as session:
                    project = session.get(LearningProject, pid)
                    if project is None:
                        raise ValueError(f"项目 #{pid} 不存在")
                    current = load_roadmap(session, pid)
                    audit, improved = audit_existing_roadmap(
                        roadmap=current,
                        topic=project.topic,
                        background=project.background,
                        goal=project.goal,
                        weekly_hours=project.weekly_hours,
                    )
                    replace_project_roadmap(session, pid, improved)

                from learning_ext.progress.study import regenerate_all_content

                regen = regenerate_all_content(project_id=pid, force=True)
                audit_md = self._audit_to_markdown(audit)
                md = self._roadmap_to_markdown(improved)
                results.append(
                    {
                        "project_id": pid,
                        "topic": project.topic,
                        "title": project.title,
                        "audit": audit,
                        "audit_md": audit_md,
                        "roadmap": improved,
                        "roadmap_md": md,
                        "queued": regen["queued"],
                    }
                )
                last_improved = improved
                last_md = md

            if len(results) == 1:
                result = results[0]
                status = (
                    f"✅ 项目 #{result['project_id']} 已完成路线审计并替换路线。"
                    f"课程内容已排队强制重生成：{result['queued']} 节。"
                )
                return (
                    self._refresh_projects(),
                    f"{result['audit_md']}\n\n---\n\n{result['roadmap_md']}",
                    json.dumps(result["roadmap"], ensure_ascii=False, indent=2),
                    result["audit_md"],
                    status,
                )

            total_queued = sum(r["queued"] for r in results)
            summary_lines = ["## 批量路线审计结果"]
            for result in results:
                audit = result["audit"] or {}
                summary_lines.append(
                    f"- 项目 #{result['project_id']} {result['topic']}："
                    f"评分 {audit.get('score', '未知')}，"
                    f"结论 {audit.get('verdict', '未知')}，已排队 {result['queued']} 节"
                )
            audit_report = "\n\n".join(
                [
                    f"### 项目 #{result['project_id']}\n\n{result['audit_md']}"
                    for result in results
                ]
            )
            roadmap_md = "\n\n---\n\n".join(
                [
                    "\n".join(summary_lines),
                    last_md or "*路线为空*",
                ]
            )
            payload = {
                "projects": [
                    {
                        "project_id": result["project_id"],
                        "audit": result["audit"],
                        "roadmap": result["roadmap"],
                    }
                    for result in results
                ],
                "last_roadmap": last_improved,
            }
            id_list = ", ".join(f"#{result['project_id']}" for result in results)
            status = (
                f"✅ 已完成 {len(results)} 个项目（{id_list}）的路线审计和替换，"
                f"课程内容已排队强制重生成：{total_queued} 节。"
            )
            return (
                self._refresh_projects(),
                roadmap_md,
                json.dumps(payload, ensure_ascii=False, indent=2),
                audit_report,
                status,
            )
        except Exception as e:
            logger.exception("项目路线审计失败")
            return (
                self._refresh_projects(),
                gr.update(),
                gr.update(),
                f"❌ 审计失败: {e}",
                f"❌ 审计失败: {e}",
            )

    @staticmethod
    def _parse_audit_project_ids(project_id) -> list[int]:
        if project_id is None:
            return []
        if isinstance(project_id, (int, float)):
            value = int(project_id)
            return [value] if value > 0 else []
        raw = str(project_id).strip()
        if not raw or raw in {"0", "0.0"}:
            return []
        for sep in [",", "，", ";", "；", "\n", "\t"]:
            raw = raw.replace(sep, " ")
        ids: list[int] = []
        for part in raw.split():
            value = int(float(part))
            if value > 0 and value not in ids:
                ids.append(value)
        return ids

    def _refresh_projects(self):
        """刷新项目列表"""
        try:
            from learning_ext.progress.study import get_project_progress

            with Session(engine) as session:
                projects = session.exec(
                    select(LearningProject)
                    .where(LearningProject.user_id == "default")
                    .order_by(LearningProject.id.desc())
                    .limit(100)
                ).all()
                rows = []
                for p in projects:
                    prog = get_project_progress(session, p.id)
                    title = " ".join((p.topic or p.title or "未命名路线").split())
                    if len(title) > 34:
                        title = title[:34] + "…"
                    rows.append(
                        [
                            p.id,
                            title,
                            f"{prog['done']}/{prog['total']} ({prog['pct']}%)",
                            p.created_at.strftime("%Y-%m-%d %H:%M")
                            if p.created_at
                            else "-",
                        ]
                    )
                logger.info("[路径页] 读取历史路线 %d 条", len(rows))
                return rows
        except Exception:
            # 以前这里静默 return []，出错时界面上只是「空列表」，
            # 看起来跟「一条都没生成过」一模一样，没法排查。
            logger.exception("[路径页] 读取历史路线失败")
            return []

    @staticmethod
    def _audit_to_markdown(audit: dict) -> str:
        if not audit:
            return "## 路线审计\n\n*审计结果为空，已保留生成路线。*"
        lines = [
            "## 路线自动审计",
            f"- **评分**：{audit.get('score', '未知')}",
            f"- **结论**：{audit.get('verdict', '未知')}",
        ]
        problems = audit.get("problems") or []
        if problems:
            lines.append("\n### 发现的问题")
            lines.extend(f"- {p}" for p in problems)
        changes = audit.get("changes") or []
        if changes:
            lines.append("\n### 自动改动")
            lines.extend(f"- {c}" for c in changes)
        return "\n".join(lines)

    @staticmethod
    def _roadmap_to_markdown(roadmap: dict) -> str:
        from learning_ext.route_view import render_route

        return render_route(roadmap)

    def as_gradio_component(self):
        return self.current_project_id
