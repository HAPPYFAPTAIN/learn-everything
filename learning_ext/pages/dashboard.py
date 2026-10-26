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
                    self.period = gr.Radio(choices=[("3 天", 3), ("7 天", 7), ("30 天", 30), ("90 天", 90)], value=7, show_label=False, container=False, interactive=True)
                    self.export_btn = gr.Button("导出全部记录", size="sm", scale=0, min_width=150)
                self.heatmap = gr.HTML("")
                self.export_file = gr.File(label="完整学习时长记录 · CSV", visible=False, interactive=False)
                self.export_status = gr.Markdown("")
            with gr.Column(elem_classes="le-dashboard-panel le-dashboard-week", scale=2):
                self.week_html = gr.HTML("")
        self.dimension_html = gr.HTML("", elem_id="le-dashboard-dimensions")
        with gr.Row(elem_id="le-dashboard-record-tools"):
            self.records_btn = gr.Button("导出多维学习记录", size="sm", scale=0)
            self.records_file = gr.File(label="学习记录 · CSV", visible=False, interactive=False)
            self.records_status = gr.Markdown("")
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
            self.week_html,
            self.heatmap,
            self.report,
            self.status,
            self.dimension_html,
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
        self.records_btn.click(self._export_dimensions, inputs=self.project_id, outputs=[self.records_file, self.records_status])
        self.project_id.change(lambda: (gr.update(value=None, visible=False), ""), outputs=[self.records_file, self.records_status])
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
            self._render_week(session, data["project_id"]),
            self._build_heatmap(self._activity_rows(session, data["project_id"], days)),
            data["latest_report"],
            status,
            self._render_dimensions(data["dimensions"]),
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
    def _render_week(session, project_id):
        from learning_ext.home_rail import week_activity, _weekdays

        project = session.get(LearningProject, project_id) if project_id else None
        weekly = float(getattr(project, "weekly_hours", 10.0) or 10.0)
        rows = week_activity(session, project_id)
        minutes = sum(row["minutes"] for row in rows)
        hours = minutes / 60.0
        pct = max(0.0, min(100.0, hours / weekly * 100 if weekly else 0.0))
        top = max((row["minutes"] for row in rows), default=0.0)
        bars = []
        for row in rows:
            value = row["minutes"]
            height = 4 + (value / top * 42 if top else 0)
            active = " is-active" if value > 0 else ""
            bars.append(f'<div class="le-rail-day{active}" title="{row["date"]} · {value:g} 分钟"><i style="height:{height:.0f}px"></i><span>{_weekdays(row["date"])}</span></div>')
        return (
            '<div class="le-rail-head"><span>本周节奏</span>'
            f'<small>目标 {weekly:g} 小时</small></div>'
            '<div class="le-rail-hours">'
            f'<strong>{hours:.1f}</strong><span>/ {weekly:g} 小时 · 近 7 天</span></div>'
            f'<div class="le-rail-track"><i style="width:{pct:.0f}%"></i></div>'
            f'<div class="le-rail-days">{"".join(bars)}</div>'
            '<div class="le-rail-foot">'
            f'<span>今天 {rows[-1]["minutes"] if rows else 0:g} 分钟</span>'
            f'<span>{sum(1 for row in rows if row["minutes"] > 0)} / 7 天有学习</span></div>'
        )

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
        days = int(days) if days in (3, 7, 30, 90) else 3
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


    @staticmethod
    def _render_dimensions(d):
        accuracy = f"{d['accuracy']:.0f}%" if d['accuracy'] is not None else "—"
        metrics = [(f"{d['total_minutes']/60:.1f}","累计学习 / 小时"), (d['active_days'],"有学习的天数"),
                   (d['streak'],"连续学习 / 天"), (d['review_count'],"累计复习 / 次"),
                   (accuracy,"测验正确率"), (f"{d['notes']} / {d['annotations']}","笔记 / 批注")]
        cards = ''.join(f'<div class="le-metric"><span class="val">{value}</span><span class="lbl">{label}</span></div>' for value,label in metrics)
        stages = ''.join(f'<div class="le-dimension-row"><span>{row["name"]}</span><strong>{row["done"]} / {row["total"]}</strong></div><progress max="{max(1,row["total"])}" value="{row["done"]}"></progress>' for row in d['stages'])
        ratings = ''.join(f'<span>{label} <b>{count}</b></span>' for label,count in d['review_ratings'].items())
        lessons = ''.join(f'<div class="le-dimension-row"><span>{escape(row["name"])}</span><strong>{row["minutes"]:g} 分</strong></div>' for row in d['lessons']) or '<p>开始阅读后，这里会显示课程投入。</p>'
        events = ''.join(f'<div class="le-learning-event"><time>{row["at"].strftime("%m-%d %H:%M")}</time><b>{escape(row["kind"])}</b><span>{escape(row["lesson"])}</span><strong>{escape(row["value"])}</strong></div>' for row in d['events'][:20]) or '<p>还没有学习记录。</p>'
        return (f'<div class="le-metrics le-dimension-metrics">{cards}</div><div class="le-dimension-grid">'
                f'<section><h3>阶段进展</h3>{stages}<p>实践与环境任务 {d["tasks_done"]} / {d["tasks"]} 已完成</p></section>'
                f'<section><h3>巩固与检验</h3><div class="le-review-ratings">{ratings}</div><div class="le-dimension-row"><span>测验作答</span><strong>{d["quiz_count"]} 次</strong></div><p>已批改 {d["quiz_graded"]} 次 · 待批改 {d["quiz_pending"]} 次</p></section>'
                f'<section><h3>时间花在哪里</h3>{lessons}</section></div>'
                f'<details class="le-learning-events"><summary>最近学习足迹 <span>{len(d["events"])} 条记录 · UTC</span></summary>{events}</details>')

    def _export_dimensions(self, project_id):
        from learning_ext.dashboard.analytics import learning_dimensions
        with Session(engine) as session:
            events = learning_dimensions(session, self._parse_project_id(project_id))["events"]
        if not events:
            return gr.update(value=None, visible=False), "当前项目暂无记录。"
        path = Path(tempfile.mkdtemp(prefix="learn-records-")) / "learning-records.csv"
        def cell(value):
            text = str(value)
            return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["时间（UTC）", "活动", "课程", "结果或数值"])
            for row in events:
                writer.writerow([row["at"].isoformat(), cell(row["kind"]), cell(row["lesson"]), cell(row["value"])])
        return gr.update(value=str(path), visible=True), f"已导出 {len(events)} 条记录。"
