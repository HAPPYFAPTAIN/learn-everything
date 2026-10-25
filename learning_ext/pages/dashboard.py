from __future__ import annotations

import logging
import os

from learning_ext.page_design import page_intro
import gradio as gr
import csv
import math
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from html import escape
from ktem.app import BasePage
from ktem.db.engine import engine
from sqlmodel import Session, select
from learning_ext.db.models import LearningProject, ProgressRecord
from learning_ext.presentation import project_display_name, project_choices

from learning_ext.dashboard import build_dashboard_data, seed_demo_learning_data

logger = logging.getLogger(__name__)


class DashboardPage(BasePage):
    """学习进度看板"""

    def __init__(self, app):
        super().__init__(app)

    def on_building_ui(self):
        gr.HTML(page_intro("dashboard"))
        with gr.Row(elem_id="le-dashboard-toolbar"):
            self.project_id = gr.Dropdown(label="学习项目", show_label=False, choices=[], value=None, interactive=True, scale=5)
            self.refresh_btn = gr.Button("更新数据", size="sm", scale=0, min_width=120)
        self.metric_html = gr.HTML("")
        with gr.Row(elem_id="le-dashboard-charts"):
            with gr.Column(elem_classes="le-dashboard-panel", scale=2):
                gr.Markdown("### 知识掌握分布")
                self.status_md = gr.HTML("")
            with gr.Column(elem_classes="le-dashboard-panel", scale=3):
                gr.Markdown("### 每日学习时长")
                with gr.Row(elem_id="le-activity-tools"):
                    self.period = gr.Radio(choices=[("最近 3 天", 3), ("最近 30 天", 30)], value=3, show_label=False, container=False, interactive=True)
                    self.export_btn = gr.Button("导出全部记录", size="sm", scale=0, min_width=150)
                self.heatmap = gr.HTML("")
                self.export_file = gr.File(label="完整学习时长记录 · CSV", visible=False, interactive=False)
                self.export_status = gr.Markdown("")
        with gr.Accordion("学习回顾", open=False, elem_id="le-dashboard-reflection"):
            self.report = gr.Markdown("")
        self.status = gr.Markdown("")
        self.seed_btn = None
        if os.environ.get("LE_ENABLE_DEMO") == "1":
            with gr.Accordion("查看演示功能", open=False):
                gr.Markdown("演示项目独立保存，数据不代表真实学习进度。")
                self.seed_btn = gr.Button("创建演示项目", size="sm")

    def on_register_events(self):
        outputs = [
            self.project_id,
            self.metric_html,
            self.status_md,
            self.heatmap,
            self.report,
            self.status,
        ]
        self.project_id.change(
            fn=self._load_dashboard,
            inputs=[self.project_id, self.period],
            outputs=outputs,
        )
        self.refresh_btn.click(
            fn=self._load_dashboard,
            inputs=[self.project_id, self.period],
            outputs=outputs,
        )
        self.period.change(self._load_activity, inputs=[self.project_id, self.period], outputs=self.heatmap)
        self.export_btn.click(self._export_activity, inputs=[self.project_id], outputs=[self.export_file, self.export_status])
        self.project_id.change(lambda: (gr.update(value=None, visible=False), ""), inputs=[], outputs=[self.export_file, self.export_status])
        if self.seed_btn is not None:
            self.seed_btn.click(fn=self._seed_demo_data, inputs=[], outputs=outputs)
        try:
            self._app.app.load(fn=self._load_dashboard, inputs=[], outputs=outputs)
        except Exception as e:
            logger.warning(f"看板初始化事件注册失败: {e}")

    def _seed_demo_data(self):
        with Session(engine) as session:
            project = seed_demo_learning_data(session)
            return self._dashboard_outputs(session, project.id, "演示项目已创建，以下为演示数据。")

    def _load_dashboard(self, project_id=None, days=3):
        pid = self._parse_project_id(project_id)
        with Session(engine) as session:
            return self._dashboard_outputs(session, pid, "", days)

    def _dashboard_outputs(self, session: Session, project_id: int | None, status: str, days=3):
        data = build_dashboard_data(session, project_id=project_id)
        value = str(data["project_id"]) if data["project_id"] is not None else None
        return (
            gr.update(choices=project_choices(session.exec(select(LearningProject).where(LearningProject.user_id == "default").order_by(LearningProject.id.desc())).all()), value=value),
            self._next_steps(data) + self._render_metrics(data["metrics"]),
            self._render_status(data["status_counts"]),
            self._build_heatmap(self._activity_rows(session, data["project_id"], days)),
            data["latest_report"],
            status,
        )

    @staticmethod
    def _parse_project_id(project_id):
        if project_id in (None, "", 0):
            return None
        try:
            return int(project_id)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _render_metrics(metrics: dict) -> str:
        avg_mastery = metrics["avg_mastery"] * 100
        mastered_class = "le-metric le-metric-mastered"
        if not metrics["mastered_nodes"]:
            mastered_class += " is-empty"
        return f"""
<div class="le-metrics">
  <div class="le-metric"><span class="val">{metrics["total_nodes"]}</span><span class="lbl">知识点总数</span></div>
  <div class="{mastered_class}"><span class="val">{metrics["mastered_nodes"]}</span><span class="lbl">已掌握</span></div>
  <div class="le-metric"><span class="val">{avg_mastery:.0f}%</span><span class="lbl">平均掌握度</span></div>
  <div class="le-metric"><span class="val">{metrics["week_minutes"]:.0f}</span><span class="lbl">近 7 天学习（分钟）</span></div>
  <div class="le-metric"><span class="val">{metrics["due_cards"]}/{metrics["total_cards"]}</span><span class="lbl">待复习 / 全部卡片</span></div>
</div>
"""

    @staticmethod
    def _next_steps(data):
        m = data["metrics"]
        if m["due_cards"]:
            title, text, tab = "先巩固，再前进", f"{m['due_cards']} 张卡片到期", "learning-review-tab"
            action = "开始复习"
        elif data["status_counts"].get("weak", 0):
            title, text, tab = "回顾薄弱知识点", "", "learning-quiz-tab"
            action = "进入测验"
        else:
            title, text, tab = "继续你的学习", "", "learning-workbench-tab"
            action = "进入工作台"
        detail = f"<p>{text}</p>" if text else ""
        return f'<div class="le-dashboard-next"><div><strong>{title}</strong>{detail}</div><button data-le-nav="{tab}">{action} →</button></div>'

    @staticmethod
    def _render_status(status_counts: dict) -> str:
        labels = {"mastered": "已掌握", "learning": "学习中", "weak": "需巩固", "pending": "待学习", "skipped": "已跳过"}
        total = sum(status_counts.values())
        rows = []
        for key, label in labels.items():
            n = status_counts.get(key, 0)
            pct = n / total * 100 if total else 0
            rows.append(f'<div class="le-distribution"><div><span>{label}</span><strong>{n} <small>个</small></strong></div><div class="le-track"><span style="width:{pct:.1f}%" class="{key}"></span></div></div>')
        return '<div class="le-status-bars">' + ''.join(rows) + '</div>'

    @staticmethod
    def _activity_records(session, project_id):
        project = session.get(LearningProject, project_id) if project_id else None
        if project is None or project.user_id != "default":
            return []
        return session.exec(select(ProgressRecord).where(
            ProgressRecord.project_id == project_id,
            ProgressRecord.user_id == "default",
            ProgressRecord.metric == "study_minutes",
        ).order_by(ProgressRecord.recorded_at, ProgressRecord.id)).all()

    @classmethod
    def _activity_rows(cls, session, project_id, days=3):
        days = 30 if days == 30 else 3
        totals = {}
        for record in cls._activity_records(session, project_id):
            date = record.recorded_at.date().isoformat()
            totals[date] = totals.get(date, 0) + record.value
        today = datetime.utcnow().date()
        return [{"date": (today - timedelta(days=ago)).isoformat(),
                 "minutes": totals.get((today - timedelta(days=ago)).isoformat(), 0)}
                for ago in range(days - 1, -1, -1)]

    def _load_activity(self, project_id, days):
        with Session(engine) as session:
            return self._build_heatmap(self._activity_rows(session, self._parse_project_id(project_id), days))

    def _export_activity(self, project_id):
        with Session(engine) as session:
            rows = self._activity_records(session, self._parse_project_id(project_id))
            if not rows:
                return gr.update(value=None, visible=False), "当前项目暂无学习时长记录可导出。"
            folder = Path(tempfile.mkdtemp(prefix="learn-activity-"))
            path = folder / "learning-time-all.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["记录编号", "项目编号", "知识点编号", "记录时间（UTC）", "学习时长（分钟）"])
                for row in rows:
                    writer.writerow([row.id, row.project_id, row.node_id or "", row.recorded_at.isoformat(sep=" "), row.value])
            return gr.update(value=str(path), visible=True), f"已导出全部 {len(rows)} 条记录，点击文件下载。不受图表时间范围限制。"

    @staticmethod
    def _build_heatmap(rows: list[dict]):
        maximum = max((row["minutes"] for row in rows), default=0)
        upper = max(10, math.ceil(maximum / 10) * 10)
        bars = []
        for i, row in enumerate(rows):
            minutes = max(0, row["minutes"])
            date = escape(row["date"])
            label = date[5:] if len(rows) <= 3 or i % 6 == 0 or i == len(rows)-1 else ""
            bars.append(f'<div class="le-day"><div class="le-day-slot"><div class="le-day-bar" style="height:{minutes / upper * 100:.2f}%" tabindex="0" aria-label="{date}，{minutes:g} 分钟"><span class="le-day-tip">{date} · {minutes:g} 分钟</span></div></div><span class="le-day-date">{label}</span></div>')
        ticks = ''.join(f'<span style="bottom:{i*25}%">{upper*i/4:g}</span>' for i in range(5))
        total = sum(row["minutes"] for row in rows)
        empty = '<p class="le-activity-empty">这段时间暂无学习时长记录</p>' if not maximum else ''
        return f'<div class="le-activity-summary">累计 <strong>{total:g}</strong> 分钟<span>按记录日期（UTC）统计</span></div><div class="le-activity-chart"><div class="le-chart-axis">{ticks}</div><div class="le-day-grid" style="--days:{max(1,len(rows))}">{"".join(bars)}</div>{empty}</div>'
