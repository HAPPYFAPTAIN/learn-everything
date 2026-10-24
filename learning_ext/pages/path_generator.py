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
        # 历史路线放最上面：回来第一件事是找回上次那条，
        # 藏在页面最底部的折叠面板里，相当于看不见。
        with gr.Column(elem_id="le-route-history"):
            gr.HTML(
                '<div class="le-history-head"><div><h2>你的学习路线</h2>'
                '<p>生成过的路线都存在本机，点一条继续学；没有合适的就在下面新建。</p></div></div>'
            )
            self.project_list = gr.Dataframe(
                headers=["ID", "标题", "进度", "创建时间"],
                datatype=["number", "str", "str", "str"],
                interactive=False,
                value=[],
                row_count=(3, "dynamic"),
                elem_id="le-route-table",
            )
            with gr.Row(elem_id="le-route-actions"):
                self.refresh_btn = gr.Button("刷新列表", size="sm")
                self.load_project_id = gr.Number(
                    label="项目 ID", value=0, precision=0
                )
                self.load_btn = gr.Button(
                    "打开这条路线", variant="primary", elem_id="le-route-load"
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
        self.prep_timer = gr.Timer(4.0, active=False)

        # 保存路线时要读它，界面上不露出来
        self.roadmap_json = gr.Code(language="json", label="路线 JSON", visible=False)

        self.regenerate_btn = gr.Button(
            "重新生成整条路线", size="sm", elem_id="le-route-regenerate"
        )

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
        # 打开页面就把历史路线填进列表。以前这里只靠「刷新项目列表」按钮，
        # 面板又是默认收起的，等于生成过的路线全看不见。
        self._app.app.load(
            fn=self._refresh_projects,
            inputs=[],
            outputs=[self.project_list],
        )
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
        ).then(
            # 备课排队了才把定时器打开；备完由 _poll_prep 自己关掉。
            # 常驻轮询会让每次 tick 都重绘一遍组件，界面就一直在闪。
            fn=lambda: gr.update(active=True),
            outputs=[self.prep_timer],
        )

        # 备课进度：排队期间每 4 秒看一眼，备完自动停
        # show_progress="hidden" 必须加：不加的话每次 tick 都会在组件上盖一层
        # 半透明遮罩 + spinner，界面看着就是一直在闪
        self.prep_timer.tick(
            fn=self._poll_prep,
            outputs=[self.save_progress, self.prep_timer],
            show_progress="hidden",
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
        # 点表格里的某一行 = 打开这条路线
        self.project_list.select(
            fn=self._handle_pick_row,
            inputs=[self.project_list],
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
        """刷新备课进度：只在文案真的变化时才更新界面；备完顺手把定时器关掉。"""
        from learning_ext.progress import prep

        pid = self._save_pid
        if not pid or not self._save_base_md:
            return gr.update(), gr.update(active=False)
        busy = prep.is_busy(pid)
        md = prep.status_md(pid)
        text = (self._save_base_md + "\n\n" + md) if md else ""
        if not busy:
            # 队列空了：把最后一份状态推上去，然后停止轮询
            if text and text != self._last_prep_md:
                self._last_prep_md = text
                return gr.update(value=text), gr.update(active=False)
            return gr.update(), gr.update(active=False)
        if not md or text == self._last_prep_md:
            return gr.update(), gr.update()
        self._last_prep_md = text
        return gr.update(value=text), gr.update()

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

    def _handle_pick_row(self, data, evt: gr.SelectData):
        """点表格里的一行，直接打开那条路线（不用再输 ID）。"""
        pid = 0
        try:
            row = evt.index[0]
            if hasattr(data, "iloc"):
                pid = int(data.iloc[row, 0])
            else:
                pid = int(data[row][0])
        except Exception:
            pid = 0
        if pid <= 0:
            return tuple(gr.update() for _ in range(4))
        return self._handle_load(pid)

    def _project_brief_md(self, proj) -> str:
        """把建档时填的那几项原样摆出来。

        用户隔几天回来，看到一堆章节标题，会想不起当初为什么这么排。
        """
        if proj is None:
            return ""
        rows = []
        if (proj.topic or "").strip():
            rows.append(f"- **想学什么**：{proj.topic.strip()}")
        if (proj.background or "").strip():
            rows.append(f"- **已有基础**：{proj.background.strip()}")
        if (proj.goal or "").strip():
            rows.append(f"- **想达到**：{proj.goal.strip()}")
        if proj.weekly_hours:
            rows.append(f"- **每周投入**：{proj.weekly_hours:g} 小时")
        if proj.created_at:
            rows.append(f"- **创建时间**：{proj.created_at.strftime('%Y-%m-%d')}")
        if not rows:
            return ""
        return "#### 你当初提的需求\n\n" + "\n".join(rows)

    def _handle_load(self, project_id):
        """加载已有项目"""
        if not project_id or int(project_id) <= 0:
            return "", "{}", None, "⚠️ 请输入有效的项目 ID"
        try:
            with Session(engine) as session:
                proj = session.get(LearningProject, int(project_id))
                brief = self._project_brief_md(proj)
                roadmap = load_roadmap(session, int(project_id))
                md = self._roadmap_to_markdown(roadmap)
                if brief:
                    md = f"{brief}\n\n---\n\n{md}"
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
                    title = p.title or "（未命名路线）"
                    # 生成的标题经常是一整段话，不截断会把表格撑成横向滚动
                    if len(title) > 46:
                        title = title[:46] + "…"
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
        """把路线 JSON 转成 markdown (含 markmap mindmap 语法，Kotaemon 自动渲染)"""
        if not roadmap or "nodes" not in roadmap:
            return "*路线为空*"

        summary = (roadmap.get("summary") or "学习路线").strip()
        if len(summary) > 46:
            summary = summary[:46].rstrip("，。、, ") + "…"
        lines = [f"# {summary}\n"]

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
                # 这里不再输出每节的 description：路线页是用来「看清结构」的，
                # 铺开正文会变成几千字，反而看不出这条路线分几块。
            lines.append("")

        lines.append("---")
        lines.append(
            f"_共 {len(roadmap.get('nodes', []))} 个知识点 · "
            f"预估 {sum(n.get('est_hours', 0) for n in roadmap.get('nodes', []))} 小时_"
        )
        return "\n".join(lines)

    def as_gradio_component(self):
        return self.current_project_id
