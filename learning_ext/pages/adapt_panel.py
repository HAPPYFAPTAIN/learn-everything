"""「课程适配度调整」弹窗。

从学习路线页搬过来的：学习的真实情况只跟当前在学的那门课有关，放在学习工作台
里点开更顺手。这里只做组件和事件，真正的分析/落库都在
`learning_ext.progress.adapt` 里。
"""

from __future__ import annotations

import logging

import gradio as gr
from ktem.db.engine import engine
from sqlmodel import Session, select

from learning_ext.db.models import LearningProject
from learning_ext.progress import adapt
from learning_ext.presentation import project_choices

logger = logging.getLogger(__name__)


class AdaptPanel:
    """挂在某个页面上的弹窗。宿主页面需要有 current_project_id（gr.State）。"""

    def __init__(self, app, host):
        self.app = app
        self.host = host

    # ---------------------------------------------------------------- UI

    def build(self):
        # 外壳铺满屏幕做遮罩，居中交给内层，这样 Gradio 控制显隐时不会被 CSS 顶掉
        with gr.Column(elem_id="le-adapt-overlay", visible=False) as self.overlay:
            with gr.Column(elem_id="le-adapt-center"):
                with gr.Column(elem_id="le-adapt-modal"):
                    with gr.Row(elem_id="le-adapt-head"):
                        gr.Markdown(
                            "### 课程适配度调整\n"
                            "根据你已经学过的部分、复习和测验表现，重新安排**后面还没学的内容**。"
                            "已经学过的章节、笔记、批注、复习卡都不会动。",
                            elem_id="le-adapt-intro",
                        )
                        self.close_btn = gr.Button(
                            "关闭", size="sm", elem_id="le-adapt-close"
                        )
                    with gr.Row(elem_id="le-adapt-scope"):
                        self.project = gr.Dropdown(
                            label="调整哪个项目", choices=[], interactive=True, scale=3
                        )
                        self.start = gr.Dropdown(
                            label="从哪一节开始调整",
                            choices=[],
                            interactive=True,
                            scale=3,
                            info="这一节之前的全部保留，只改这一节及之后。",
                        )
                        self.reload_btn = gr.Button("读取", scale=1, size="sm")
                    self.signal = gr.Markdown("", elem_id="le-adapt-signal")
                    self.note = gr.Textbox(
                        label="补充要求（可选）",
                        placeholder="例如：想加一节动手实战；理论太多，压掉一些；这块基础太差，多留点复习",
                        lines=2,
                    )
                    with gr.Row(elem_id="le-adapt-actions"):
                        self.diagnose_btn = gr.Button(
                            "开始分析", variant="primary", elem_id="le-adapt-diagnose"
                        )
                        self.apply_btn = gr.Button(
                            "确认调整后段", elem_id="le-adapt-apply"
                        )
                        self.undo_btn = gr.Button("撤销上次调整", size="sm")
                    self.report = gr.Markdown("", elem_id="le-adapt-report")
                    self.plan = gr.State(None)
        return self

    def register(self, open_btn):
        open_btn.click(
            fn=self._open,
            inputs=[self.host.current_project_id],
            outputs=[
                self.overlay,
                self.project,
                self.start,
                self.signal,
                self.report,
                self.plan,
            ],
        )
        self.close_btn.click(
            fn=lambda: gr.update(visible=False),
            outputs=[self.overlay],
        )
        self.reload_btn.click(
            fn=self._reload,
            inputs=[self.project],
            outputs=[self.project, self.start],
        )
        self.project.change(
            fn=self._on_project,
            inputs=[self.project],
            outputs=[self.start, self.signal, self.report, self.plan],
        )
        self.start.change(
            fn=self._on_start,
            inputs=[self.project, self.start],
            outputs=[self.signal, self.plan],
        )
        self.diagnose_btn.click(
            fn=self._diagnose,
            inputs=[self.project, self.start, self.note],
            outputs=[self.report, self.plan, self.host.action_status],
        )
        self.apply_btn.click(
            fn=self._apply,
            inputs=[self.project, self.start, self.plan],
            outputs=[
                self.report,
                self.plan,
                self.host.action_status,
                self.host.progress_display,
                self.host.course_drop,
            ],
        )
        self.undo_btn.click(
            fn=self._undo,
            inputs=[self.project],
            outputs=[
                self.report,
                self.host.action_status,
                self.host.progress_display,
                self.host.course_drop,
            ],
        )

    # ---------------------------------------------------------------- 数据

    def _projects(self):
        with Session(engine) as session:
            return session.exec(
                select(LearningProject)
                .where(LearningProject.user_id == "default")
                .order_by(LearningProject.updated_at.desc())
            ).all()

    def _open(self, current_pid):
        """打开弹窗：优先落在工作台当前项目上。"""
        ps = self._projects()
        if not ps:
            return (
                gr.update(visible=True),
                gr.update(choices=[], value=None),
                gr.update(choices=[], value=None),
                "*还没有学习项目*",
                "",
                None,
            )
        pid = int(current_pid) if current_pid else ps[0].id
        return (
            gr.update(visible=True),
            gr.update(choices=project_choices(ps), value=str(pid)),
            self._start_choices(pid),
            self._signal_md(pid, None),
            "",
            None,
        )

    def _reload(self, pid):
        ps = self._projects()
        pid = int(pid) if pid else (ps[0].id if ps else None)
        return (
            gr.update(choices=project_choices(ps), value=str(pid) if pid else None),
            self._start_choices(pid),
        )

    def _start_choices(self, pid):
        """可选起点只列「还没学」的节点，默认第一个。"""
        if not pid:
            return gr.update(choices=[], value=None)
        with Session(engine) as session:
            before, _ = adapt.split_nodes(session, int(pid), "__none__")
        picked = [n for n in before if (n.status or "pending") == "pending"]
        if not picked:
            return gr.update(choices=[], value=None)
        return gr.update(
            choices=[(f"{n.code} · {n.title}", n.code) for n in picked],
            value=picked[0].code,
        )

    def _on_project(self, pid):
        start_update = self._start_choices(pid)
        code = start_update.get("value") if isinstance(start_update, dict) else None
        return start_update, self._signal_md(pid, code), "", None

    def _on_start(self, pid, start_code):
        return self._signal_md(pid, start_code), None

    def _signal_md(self, pid, start_code) -> str:
        if not pid or not start_code:
            return "*选一个项目和起点，这里会显示你的学习数据。*"
        try:
            with Session(engine) as session:
                sig = adapt.collect_signals(session, int(pid), start_code)
        except Exception:
            logger.exception("读取学习数据失败")
            return "*读取学习数据失败，换个起点再试。*"
        if not sig["after"]:
            return "⚠️ 这一节之后没有可调整的内容了，换一个更靠前的起点。"

        learned = len(sig["before"])
        total = learned + len(sig["after"])
        lines = [
            f"**已学 {learned} / {total} 节**　·　项目第 {sig['days']} 天　·　"
            f"记录到的学习时长 {sig['minutes']:.0f} 分钟",
            f"复习 {len(sig['cards'])} 张卡（困难/重来 {sig['hard']} 次）　·　"
            f"测验 {sig['quiz_answered']} 题对 {sig['quiz_correct']} 题　·　"
            f"笔记 {sum(sig['notes'].values())} 条 / 批注 {sum(sig['annos'].values())} 条",
            f"**待调整：{start_code} 之后共 {len(sig['after'])} 节**",
        ]
        if learned < 2 or sig["quiz_answered"] < 3:
            lines.append("> 样本还少（已学节数或答题数不够），诊断只能给粗略判断。")
        return "\n\n".join(lines)

    def _report_md(self, plan: dict) -> str:
        old = {
            (x.get("code"), (x.get("title") or "").strip())
            for x in plan.get("old_nodes") or []
        }
        new_items = plan.get("nodes") or []
        new = [(n["code"], (n["title"] or "").strip()) for n in new_items]
        new_keys = set(new)
        added = [t for k, t in new if k not in old]
        removed = [t for k, t in old if k not in new_keys]

        rows = [
            f"### 学习诊断\n\n{plan.get('diagnosis') or '（模型未给出诊断）'}",
            "",
            f"- 节奏判断：**{plan.get('pace', '未知')}**（可信度 {plan.get('confidence', '低')}）",
        ]
        weak = plan.get("weak_points") or []
        if weak:
            rows.append("- 薄弱环节：" + "；".join(weak))
        changes = plan.get("changes") or []
        if changes:
            rows += ["", "### 打算这样调整"] + [f"- {c}" for c in changes]

        att = plan.get("after_attached") or {}
        if att.get("notes") or att.get("cards") or att.get("annotations"):
            rows += [
                "",
                f"> ⚠️ 后段目前已有 {att.get('notes', 0)} 条笔记、"
                f"{att.get('cards', 0)} 张复习卡、{att.get('annotations', 0)} 条批注。"
                f"确认调整后这些内容会随旧节点一起删除，无法恢复。",
            ]

        rows += [
            "",
            "### 后段变化",
            f"旧 **{plan.get('old_count', 0)}** 节 → 新 **{plan.get('new_count', 0)}** 节"
            f"（新增 {len(added)}、删除 {len(removed)}、保留 {len(new) - len(added)}）",
        ]
        if added:
            rows.append("\n**新增**：" + "、".join(added[:8]) + ("…" if len(added) > 8 else ""))
        if removed:
            rows.append("\n**删除**：" + "、".join(removed[:8]) + ("…" if len(removed) > 8 else ""))
        rows += [
            "",
            "### 新的后续安排",
            "\n".join(
                f"{i + 1}. `{n['code']}` {n['title']}　（{n.get('est_hours', 2)}h，难度 {n.get('difficulty', 3)}/5）"
                for i, n in enumerate(new_items[:14])
            )
            + ("\n…" if len(new_items) > 14 else ""),
            "",
            "> 确认无误后点「确认调整后段」。已学过的章节不会变。",
        ]
        return "\n".join(rows)

    # ---------------------------------------------------------------- 动作

    def _diagnose(self, pid, start_code, note):
        if not pid or not start_code:
            yield "⚠️ 先选项目和起点。", None, ""
            return
        yield "*⏳ 正在读取你的笔记、复习与测验记录，并生成新方案…（大约 20 秒）*", None, ""
        try:
            with Session(engine) as session:
                plan = adapt.diagnose_and_plan(
                    session, int(pid), start_code, (note or "").strip()
                )
        except Exception as e:
            logger.exception("课程适配度分析失败")
            yield f"❌ 分析失败：{e}", None, "分析失败，可稍后重试"
            return
        yield self._report_md(plan), plan, "分析完成，确认后再执行"

    def _refresh_after_change(self, pid):
        """调整完，把工作台的进度和课程下拉同步过来。"""
        from learning_ext.progress.study import get_project_progress

        try:
            with Session(engine) as session:
                prog = get_project_progress(session, int(pid))
                nodes_data = self.host._build_nodes_data(session, int(pid))
            return self.host._build_progress_md(prog), self.host._build_drop_choices(nodes_data)
        except Exception:
            logger.exception("刷新工作台课程下拉失败")
            return gr.update(), gr.update()

    def _apply(self, pid, start_code, plan):
        if not pid or not start_code:
            return "⚠️ 先选项目和起点。", None, "", gr.update(), gr.update()
        if not plan:
            return "⚠️ 还没有可执行的方案，先点「开始分析」。", None, "", gr.update(), gr.update()
        try:
            with Session(engine) as session:
                result = adapt.apply_plan(session, int(pid), start_code, plan)
                project = session.get(LearningProject, int(pid))
                topic = project.topic if project else ""
            created = result.get("created_ids") or []
            if created:
                from learning_ext.progress import prep

                prep.start(int(pid), created, topic)
            att = result.get("deleted_attached") or {}
            extra = ""
            if att.get("notes") or att.get("cards") or att.get("annotations"):
                extra = (
                    f"（后段原有 {att.get('notes', 0)} 条笔记、"
                    f"{att.get('cards', 0)} 张卡、{att.get('annotations', 0)} 条批注随节点移除）"
                )
            report = (
                f"✅ **已调整后段**：保留前段 {result['before_count']} 节不变，"
                f"后段 {result['old_count']} → {result['new_count']} 节，"
                f"其中新写 {len(created)} 节正在后台备课。{extra}\n\n"
                f"关掉这个窗口后点「刷新课程」就能看到新章节。"
            )
            progress_md, choices = self._refresh_after_change(pid)
            return report, None, "✅ 已按学习情况调整后续课程", progress_md, choices
        except Exception as e:
            logger.exception("应用适配方案失败")
            return f"❌ 调整失败：{e}", plan, "调整失败", gr.update(), gr.update()

    def _undo(self, pid):
        if not pid:
            return "⚠️ 先选项目。", "", gr.update(), gr.update()
        try:
            with Session(engine) as session:
                result = adapt.undo_last(session, int(pid))
            progress_md, choices = self._refresh_after_change(pid)
            return (
                f"↩️ 已撤销：后段恢复为 {result['new_count']} 节，点「刷新课程」查看。",
                "已撤销上次调整",
                progress_md,
                choices,
            )
        except Exception as e:
            return f"⚠️ 撤销失败：{e}", "撤销失败", gr.update(), gr.update()
