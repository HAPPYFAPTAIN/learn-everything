from __future__ import annotations

import html
from datetime import datetime, timedelta

from sqlmodel import select

from learning_ext.db.models import LearningProject, ProgressRecord


def week_activity(session, project_id, days=7):
    if project_id is None:
        return []
    records = session.exec(select(ProgressRecord).where(
        ProgressRecord.project_id == project_id,
        ProgressRecord.user_id == "default",
        ProgressRecord.metric == "study_minutes",
    ).order_by(ProgressRecord.recorded_at, ProgressRecord.id)).all()
    totals = {}
    for record in records:
        key = record.recorded_at.date().isoformat()
        totals[key] = totals.get(key, 0.0) + float(record.value or 0.0)
    today = datetime.utcnow().date()
    return [{"date": (today - timedelta(days=ago)).isoformat(),
             "minutes": totals.get((today - timedelta(days=ago)).isoformat(), 0.0)}
            for ago in range(days - 1, -1, -1)]


def _weekdays(iso_date):
    return "一二三四五六日"[datetime.fromisoformat(iso_date).weekday()]


def _week_card(session, project_id, metrics):
    project = session.get(LearningProject, project_id) if project_id else None
    weekly = float(getattr(project, "weekly_hours", 10.0) or 10.0)
    minutes = float(metrics.get("week_minutes") or 0.0)
    hours = minutes / 60.0
    pct = max(0.0, min(100.0, hours / weekly * 100 if weekly else 0.0))
    rows = week_activity(session, project_id)
    top = max((row["minutes"] for row in rows), default=0.0)
    bars = []
    for index, row in enumerate(rows):
        minutes = row["minutes"]
        height = 4 + (minutes / top * 42 if top else 0)
        active = " is-active" if minutes > 0 else ""
        bars.append(
            f'<div class="le-rail-day{active}" title="{row["date"]} · {minutes:g} 分钟">'
            f'<i style="height:{height:.0f}px"></i><span>{_weekdays(row["date"])}</span></div>'
        )
    today_minutes = rows[-1]["minutes"] if rows else 0.0
    active_days = sum(1 for row in rows if row["minutes"] > 0)
    return (
        '<section class="le-rail-card le-rail-week">'
        '<div class="le-rail-head"><span>本周节奏</span>'
        f'<small>目标 {weekly:g} 小时</small></div>'
        '<div class="le-rail-hours">'
        f'<strong>{hours:.1f}</strong><span>/ {weekly:g} 小时 · 近 7 天</span></div>'
        f'<div class="le-rail-track" role="progressbar" aria-valuenow="{pct:.0f}" aria-valuemin="0" aria-valuemax="100">'
        f'<i style="width:{pct:.0f}%"></i></div>'
        f'<div class="le-rail-days">{"".join(bars)}</div>'
        '<div class="le-rail-foot">'
        f'<span>今天 {today_minutes:g} 分钟</span><span>{active_days} / 7 天有学习</span></div>'
        '</section>'
    )


def _links_card(due):
    review_text = f"待复习 <b>{due}</b> 张" if due else "没有到期卡片，去复习一下"
    return (
        '<section class="le-rail-card le-rail-links">'
        '<div class="le-rail-head"><span>接下来</span></div>'
        f'<a data-le-nav="learning-review-tab"><span>{review_text}</span><i>→</i></a>'
        '<a data-le-nav="learning-workbench-tab"><span>继续当前课程</span><i>→</i></a>'
        '<a data-le-nav="learning-quiz-tab"><span>做一次查漏测验</span><i>→</i></a>'
        '<a data-le-nav="indices-tab"><span>翻翻学习资料</span><i>→</i></a>'
        '</section>'
    )


def _start_card():
    return (
        '<section class="le-rail-card le-rail-start">'
        '<div class="le-rail-head"><span>从这里开始</span></div>'
        '<ol class="le-rail-steps">'
        '<li><b>选一个方向</b><span>或在下方写一句想学会的事</span></li>'
        '<li><b>预览学习路线</b><span>确认后再生成课程</span></li>'
        '<li><b>每天学一小节</b><span>复习和测验会自动跟上</span></li>'
        '</ol></section>'
    )


def build_home_rail(session, project_id):
    from learning_ext.dashboard import build_dashboard_data

    data = build_dashboard_data(session, project_id=project_id)
    metrics = data.get("metrics", {})
    cards = []
    if project_id:
        cards.append(_week_card(session, project_id, metrics))
    else:
        cards.append(_start_card())
    cards.append(_links_card(int(metrics.get("due_cards") or 0)))
    return f'<aside class="le-rail" aria-label="学习概览">{"".join(cards)}</aside>'
