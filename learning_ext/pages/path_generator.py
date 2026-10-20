"""学习路线 Tab - 选题 → AI 拆知识 DAG → 可视化展示。

这是阶段 1 的核心 Tab，演示如何把 learning_ext 业务模块接入 Kotaemon 的 BasePage。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

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
        # 保存后那一段进度文案的固定部分（备课进度会追加在后面）
        self._save_base_md = ""
        self._last_prep_md = ""
        self._save_pid: int | None = None

    def on_building_ui(self):
        gr.Markdown(
            "# 建立学习路线\n先明确目标，再预览路线。确认合适后保存，进入学习工作台。"
        )
        with gr.Row(elem_id="le-planner"):
            with gr.Column(scale=2, min_width=300, elem_id="le-plan-input"):
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
                    label="每周投入 / 小时", elem_id="le-wizard-hours", minimum=1, maximum=40, value=10, step=1
                )
                gr.HTML('<div id="le-wizard-nav"><button data-wizard-back>返回</button><button data-wizard-next>继续 →</button></div>')
                self.generate_btn = gr.Button("生成我的学习路线 →", variant="primary", elem_id="le-wizard-generate")
                gr.Markdown(
                    "首次使用需先在「模型配置」连接模型。完成这四步后，即可生成并预览路线。"
                )
            with gr.Column(scale=3, min_width=340, elem_id="le-plan-preview"):
                gr.HTML('<div class="le-preview-heading"><button data-wizard-edit>← 修改学习偏好</button><h2>你的学习路线</h2><p>生成完成后，确认内容再保存。</p></div>')
                self.roadmap_output = gr.Markdown(
                    "**你的下一段学习，从这里展开。**\n\n生成后，在这里查看知识点、先后依赖与预估学时。也可以在下方调整路线。",
                    elem_classes=["learning-roadmap", "le-route-result"],
                )
                self.save_btn = gr.Button(
                    "保存路线，开始学习 →", variant="primary", interactive=False
                )
                gr.Markdown(
                    "保存后所有课程都会自动备课，你可以立刻去工作台读，后面的章节会自动补上。"
                )
                self.save_progress = gr.Markdown("")
        # 备课进度轮询（保存后自动刷新，不用再点任何按钮）
        self.prep_timer = gr.Timer(4.0, active=True)

        with gr.Accordion("调整路线与重新规划", open=False):
            self.regenerate_btn = gr.Button("重新规划", elem_id="le-route-regenerate")
            self.roadmap_json = gr.Code(language="json", label="路线 JSON")
            self.refine_input = gr.Textbox(
                label="调整意见 (自然语言)",
                placeholder="如：增加分布式训练的内容；删掉 RNN 部分；把难度调低",
            )
            self.refine_btn = gr.Button("按意见调整路线", elem_id="le-route-refine")

        with gr.Accordion("已有项目 · 查看、导入与管理", open=False):
            self.project_list = gr.Dataframe(
                headers=["ID", "标题", "选题", "进度", "状态", "创建时间"],
                datatype=["number", "str", "str", "str", "str", "str"],
                interactive=False,
                value=[],
            )
            with gr.Row():
                self.refresh_btn = gr.Button("刷新项目列表")
                self.load_project_id = gr.Number(
                    label="加载项目 ID", value=0, precision=0
                )
                self.load_btn = gr.Button("加载该项目路线", elem_id="le-route-load")
            with gr.Accordion("导入 / 导出学习路线", open=False):
                gr.Markdown(
                    "导出会生成格式化 JSON 文件，包含项目元信息和完整路线；导入会新建一个学习项目。"
                )
                with gr.Row():
                    self.export_project_id = gr.Number(
                        label="导出项目 ID", value=0, precision=0
                    )
                    self.export_roadmap_btn = gr.Button("导出学习路线")
                self.export_roadmap_file = gr.File(
                    label="下载导出的学习路线 JSON", interactive=False
                )
                self.import_roadmap_file = gr.File(
                    label="导入学习路线 JSON", file_types=[".json"]
                )
                self.import_roadmap_btn = gr.Button("导入学习路线", variant="primary")
            with gr.Accordion("批量审计旧路线", open=False):
                gr.Markdown(
                    "对已有项目执行路线完整性审计。系统会自动重写路线，并按新路线批量重新生成课程内容。"
                    "可输入单个 ID、多个 ID（逗号/空格分隔），或留空审计全部项目。"
                )
                with gr.Row():
                    self.audit_project_id = gr.Textbox(
                        label="项目 ID（留空=全部）",
                        placeholder="例如：3 或 3,5,8",
                        lines=1,
                    )
                    self.audit_project_btn = gr.Button(
                        "审计并重生成该项目", variant="primary"
                    )
                self.audit_project_output = gr.Markdown("")
            with gr.Accordion("删除项目", open=False):
                gr.Markdown("输入项目 ID，并输入 `DELETE` 确认后删除。")
                with gr.Row():
                    self.delete_project_id = gr.Number(
                        label="删除项目 ID", value=0, precision=0
                    )
                    self.delete_confirm = gr.Textbox(
                        label="确认文本", placeholder="DELETE", lines=1
                    )
                    self.delete_btn = gr.Button("删除项目", variant="stop")

        self.status = gr.Markdown("")

    def on_register_events(self):
        """绑定按钮事件"""
        self.roadmap_json.change(
            fn=self._save_availability,
            inputs=[self.roadmap_json],
            outputs=[self.save_btn],
        )
        self.generate_btn.click(
            fn=self._handle_generate,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
            ],
            outputs=[self.roadmap_output, self.roadmap_json, self.status],
        ).then(
            fn=self._refresh_projects,
            outputs=[self.project_list],
        )

        self.regenerate_btn.click(
            fn=self._handle_generate,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
            ],
            outputs=[self.roadmap_output, self.roadmap_json, self.status],
        )

        self.refine_btn.click(
            fn=self._handle_refine,
            inputs=[self.roadmap_json, self.refine_input],
            outputs=[self.roadmap_output, self.roadmap_json, self.status],
        )

        # 保存：生成器流式输出进度 (自动搜集资料 + 生成环境清单)
        self.save_btn.click(
            fn=self._handle_save_with_setup,
            inputs=[
                self.topic_input,
                self.background_input,
                self.goal_input,
                self.hours_input,
                self.roadmap_json,
            ],
            outputs=[self.current_project_id, self.save_progress, self.status],
        ).then(
            fn=self._refresh_projects,
            outputs=[self.project_list],
        )

        # 备课进度：每 4 秒看一眼（Timer 不传输入，用 _save_pid 记当前项目）
        self.prep_timer.tick(
            fn=self._poll_prep,
            outputs=[self.save_progress],
        )

        self.refresh_btn.click(fn=self._refresh_projects, outputs=[self.project_list])

        self.load_btn.click(
            fn=self._handle_load,
            inputs=[self.load_project_id],
            outputs=[
                self.roadmap_output,
                self.roadmap_json,
                self.current_project_id,
                self.status,
            ],
        )
        self.export_roadmap_btn.click(
            fn=self._handle_export_roadmap,
            inputs=[self.export_project_id],
            outputs=[self.export_roadmap_file, self.status],
        )
        self.import_roadmap_btn.click(
            fn=self._handle_import_roadmap,
            inputs=[self.import_roadmap_file],
            outputs=[
                self.project_list,
                self.roadmap_output,
                self.roadmap_json,
                self.current_project_id,
                self.status,
            ],
        )
        self.delete_btn.click(
            fn=self._handle_delete_project,
            inputs=[self.delete_project_id, self.delete_confirm],
            outputs=[self.project_list, self.status],
        )
        self.audit_project_btn.click(
            fn=self._handle_audit_project,
            inputs=[self.audit_project_id],
            outputs=[
                self.project_list,
                self.roadmap_output,
                self.roadmap_json,
                self.audit_project_output,
                self.status,
            ],
        )

    # ---- 业务处理函数 ----

    @staticmethod
    def _save_availability(raw):
        try:
            valid = bool(json.loads(raw or "{}").get("nodes"))
        except (ValueError, TypeError, AttributeError):
            valid = False
        return gr.update(interactive=valid)

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
                f"{audit_md}\n\n---\n\n{audited_md}",
                json.dumps(audited, ensure_ascii=False, indent=2),
                "✅ 路线已生成，并已自动审计补全，可保存为项目",
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

    def _poll_prep(self):
        """刷新备课进度：只在文案真的变化时才更新界面。"""
        from learning_ext.progress import prep

        pid = self._save_pid
        if not pid or not self._save_base_md:
            return gr.update()
        md = prep.status_md(pid)
        if not md:
            return gr.update()
        text = self._save_base_md + "\n\n" + md
        if text == self._last_prep_md:
            return gr.update()
        self._last_prep_md = text
        return gr.update(value=text)

    def _handle_save_with_setup(self, topic, background, goal, hours, roadmap_json):
        """保存为项目 + 自动搜集资料 + 生成环境清单 (生成器，流式输出进度)。

        步骤：
            1. 保存项目 + 知识点到库
            2. 生成学习环境配置清单 (落库为 Task，待用户确认)
            3. 为每个知识点生成学习摘要 (存入 description)
            4. 提示去学习工作台
        """
        if not roadmap_json or roadmap_json == "{}":
            yield None, "", "⚠️ 请先生成路线"
            return
        try:
            roadmap = json.loads(roadmap_json)
        except json.JSONDecodeError as e:
            yield None, "", f"❌ 路线 JSON 解析失败: {e}"
            return

        # ---- 1. 保存项目和知识点 ----
        yield None, "⏳ 正在保存学习路线...", ""
        try:
            with Session(engine) as session:
                project = save_roadmap(
                    session=session,
                    user_id="default",
                    topic=topic or "未命名选题",
                    background=background or "",
                    goal=goal or "",
                    weekly_hours=float(hours) if hours else 10.0,
                    roadmap=roadmap,
                )
                pid = project.id
                ptitle = project.title
                nodes_count = len(roadmap.get("nodes", []))
        except Exception as e:
            logger.exception("保存项目失败")
            yield None, f"❌ 保存失败: {e}", ""
            return

        progress_md = f"✅ **步骤 1/3 完成**：已保存项目 #{pid}「{ptitle}」，共 {nodes_count} 个知识点\n\n"
        yield pid, progress_md + "⏳ 正在生成学习环境配置清单...", ""

        # ---- 2. 生成环境配置清单 ----
        try:
            from learning_ext.progress.study import (
                generate_env_checklist,
                save_env_tasks,
            )

            env_md = generate_env_checklist(topic or "未命名选题", background or "")
            with Session(engine) as session:
                save_env_tasks(session, pid, env_md)
            progress_md += "✅ **步骤 2/3 完成**：学习环境配置清单已生成（待你在工作台确认应用）\n\n"
            yield (
                pid,
                progress_md
                + "⏳ 正在为每个知识点搜集学习资料（这一步较慢，请耐心等待）...",
                "",
            )
        except Exception as e:
            logger.exception("环境清单生成失败")
            env_md = ""
            progress_md += f"⚠️ 环境清单生成失败（不影响学习）: {e}\n\n"
            yield pid, progress_md + "⏳ 正在搜集知识点资料...", ""

        # ---- 3. 全部交给后台备课队列，界面不再卡住 ----
        # 查出所有节点 id (按 code 排序)
        with Session(engine) as session:
            db_nodes = session.exec(
                select(KnowledgeNode).where(KnowledgeNode.project_id == pid)
            ).all()
            db_nodes = sort_nodes_by_code(list(db_nodes))
            ordered_ids = [n.id for n in db_nodes]

        # 3. 全部丢进后台备课队列（不再串行卡界面）
        from learning_ext.progress import prep

        prep.start(
            pid,
            ordered_ids,
            topic or "",
            goal=goal or "",
            env=env_md,
        )
        self._save_base_md = (
            progress_md
            + f"✅ **步骤 3/3 完成**：已保存 {len(ordered_ids)} 节，正在后台备课\n\n"
            + "> 你现在就可以点顶部 **「📚 学习工作台」** 开始读，"
            + "写好的章节会自动出现，不用等也不用点按钮。"
        )
        self._save_pid = pid
        self._last_prep_md = ""
        yield pid, self._save_base_md + "\n\n" + prep.status_md(pid), (
            f"✅ 项目 #{pid} 已就绪，去「📚 学习工作台」开始学习吧！"
        )

    def _handle_load(self, project_id):
        """加载已有项目"""
        if not project_id or int(project_id) <= 0:
            return "", "{}", None, "⚠️ 请输入有效的项目 ID"
        try:
            with Session(engine) as session:
                roadmap = load_roadmap(session, int(project_id))
                md = self._roadmap_to_markdown(roadmap)
                return (
                    md,
                    json.dumps(roadmap, ensure_ascii=False, indent=2),
                    int(project_id),
                    f"✅ 已加载项目 #{int(project_id)}",
                )
        except Exception as e:
            logger.exception("加载项目失败")
            return "", "{}", None, f"❌ 加载失败: {e}"

    def _handle_export_roadmap(self, project_id):
        """导出项目学习路线为格式化 JSON 文件。"""
        if not project_id or int(project_id) <= 0:
            return None, "⚠️ 请输入有效的项目 ID"
        try:
            with Session(engine) as session:
                payload = export_roadmap_bundle(session, int(project_id))
            export_dir = Path(".tmp") / "roadmap_exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            path = export_dir / f"learning_route_{int(project_id)}.json"
            path.write_text(payload, encoding="utf-8")
            return str(path), f"✅ 已导出项目 #{int(project_id)} 的学习路线"
        except Exception as e:
            logger.exception("导出学习路线失败")
            return None, f"❌ 导出失败: {e}"

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
            path = getattr(file_obj, "name", None) or str(file_obj)
            payload = Path(path).read_text(encoding="utf-8")
            with Session(engine) as session:
                project = import_roadmap_bundle(session, payload, user_id="default")
                roadmap = load_roadmap(session, project.id)
                md = self._roadmap_to_markdown(roadmap)
                return (
                    self._refresh_projects(),
                    md,
                    json.dumps(roadmap, ensure_ascii=False, indent=2),
                    project.id,
                    f"✅ 已导入学习路线并创建项目 #{project.id}",
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

    def _handle_delete_project(self, project_id, confirm):
        """删除项目及其学习数据"""
        if not project_id or int(project_id) <= 0:
            return self._refresh_projects(), "⚠️ 请输入有效的项目 ID"
        if (confirm or "").strip() != "DELETE":
            return self._refresh_projects(), "⚠️ 如需删除，请在确认文本中输入 DELETE"
        try:
            from learning_ext.project_ops import delete_project

            with Session(engine) as session:
                result = delete_project(session, int(project_id))
            deleted = result["deleted"]
            total = sum(deleted.values())
            return (
                self._refresh_projects(),
                f"✅ 已删除项目 #{int(project_id)}，清理 {total} 条相关数据",
            )
        except Exception as e:
            logger.exception("删除项目失败")
            return self._refresh_projects(), f"❌ 删除失败: {e}"

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
                    .order_by(LearningProject.id.desc())
                    .limit(50)
                ).all()
                rows = []
                for p in projects:
                    prog = get_project_progress(session, p.id)
                    rows.append(
                        [
                            p.id,
                            p.title,
                            p.topic[:40],
                            f"{prog['done']}/{prog['total']} ({prog['pct']}%)",
                            p.status,
                            p.created_at.strftime("%Y-%m-%d %H:%M"),
                        ]
                    )
                return rows
        except Exception:
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
        """把路线 JSON 转成 markdown (含 markmap mindmap 语法，Kotaemon 自动渲染)"""
        if not roadmap or "nodes" not in roadmap:
            return "*路线为空*"

        lines = [f"# {roadmap.get('summary', '学习路线')}\n"]

        # 按 stage 分组
        stages: dict[str, list] = {}
        for node in roadmap.get("nodes", []):
            stages.setdefault(node.get("stage", "base"), []).append(node)

        stage_names = {
            "base": "🌱 基础阶段",
            "strengthen": "💪 强化阶段",
            "sprint": "🔥 冲刺阶段",
        }

        for stage_key in ["base", "strengthen", "sprint"]:
            nodes = stages.get(stage_key, [])
            if not nodes:
                continue
            lines.append(f"## {stage_names.get(stage_key, stage_key)}\n")
            for node in sorted(
                nodes, key=lambda x: course_code_sort_key(x.get("code", ""))
            ):
                mastery_pct = ""
                if "mastery" in node:
                    mastery_pct = f" _(掌握 {node['mastery']:.0%})_"
                status_icon = {
                    "mastered": "✅",
                    "reviewing": "🔄",
                    "learning": "📖",
                    "weak": "⚠️",
                    "pending": "⏳",
                }.get(node.get("status", "pending"), "⏳")
                prereq = node.get("prerequisites", [])
                prereq_str = f" `需先学: {','.join(prereq)}`" if prereq else ""
                lines.append(
                    f"- {status_icon} **[{node['code']}] {node['title']}** "
                    f"`{node.get('est_hours', 2)}h` `难度{node.get('difficulty', 3)}/5`"
                    f"{prereq_str}{mastery_pct}"
                )
                if node.get("description"):
                    lines.append(f"  - {node['description']}")
            lines.append("")

        lines.append("---")
        lines.append(
            f"_共 {len(roadmap.get('nodes', []))} 个知识点 · "
            f"预估 {sum(n.get('est_hours', 0) for n in roadmap.get('nodes', []))} 小时_"
        )
        return "\n".join(lines)

    def as_gradio_component(self):
        return self.current_project_id
