import html
import re

from learning_ext.progress.study import course_code_sort_key


def esc(value):
    return html.escape(str(value or ""), quote=True)


STATUS_LABELS = {
    "mastered": "已掌握",
    "learning": "学习中",
    "reviewing": "待复习",
    "weak": "需巩固",
    "skipped": "已跳过",
}


def _status(node):
    return node.get("status") or "pending"


def _ordered_nodes(nodes):
    return sorted(nodes, key=lambda node: course_code_sort_key(node.get("code", "")))


def _node_display_title(node):
    code = str(node.get("code") or "").strip()
    title = " ".join(str(node.get("title") or "未命名章节").split())
    return f"[{code}] {title}" if code else title


def next_route_node(roadmap):
    nodes = roadmap.get("nodes", []) if roadmap else []
    ordered = _ordered_nodes(nodes)
    for statuses in ({"learning"}, {"weak"}, {"pending"}, {"reviewing"}):
        selected = next((node for node in ordered if _status(node) in statuses), None)
        if selected is not None:
            return selected
    return next((node for node in ordered if _status(node) not in {"mastered", "skipped"}), None)


def route_action_label(roadmap):
    nodes = roadmap.get("nodes", []) if roadmap else []
    selected = next_route_node(roadmap)
    if selected is None:
        if nodes and all(_status(node) == "mastered" for node in nodes):
            return "打开课程，回顾已学内容 →"
        return "打开这门课程 →"
    action = {"learning": "继续学习", "weak": "巩固复习", "reviewing": "继续复习"}.get(_status(selected), "开始学习")
    title = _node_display_title(selected)
    if len(title) > 36:
        title = title[:35] + "…"
    return f"{action}：{title} →"


def render_route(roadmap):
    nodes = roadmap.get("nodes", []) if roadmap else []
    if not nodes:
        return '<div class="le-route-empty" role="status"><strong>暂无学习路线</strong><p>从学习首页创建一个目标。</p></div>'
    hours = sum(float(n.get("est_hours") or 0) for n in nodes)
    groups = [("base", "打好基础", ""), ("strengthen", "动手练习", ""), ("sprint", "综合运用", "")]
    known = {key for key, _, _ in groups}
    groups += [(key, key, "") for key in dict.fromkeys(n.get("stage", "base") for n in nodes) if key not in known]
    groups = [(key, title, _ordered_nodes([n for n in nodes if n.get("stage", "base") == key])) for key, title, _ in groups]
    groups = [group for group in groups if group[2]]
    stage_count = len(groups)
    selected = next_route_node(roadmap)
    current_stage = selected.get("stage", "base") if selected else None
    active_stage = current_stage or groups[0][0]
    mastered = sum(_status(node) == "mastered" for node in nodes)
    title = roadmap.get("topic") or roadmap.get("title") or "课程总览"
    completion = "全部完成" if mastered == len(nodes) else f"已掌握 {mastered} / {len(nodes)} 节"
    parts = ['<div class="le-route-map le-route-browser">', f'<div class="le-route-overview"><div class="le-route-title"><h3>{esc(title)}</h3><span class="le-route-completion">{completion}</span></div><div class="le-route-metrics"><div><strong>{len(nodes)}</strong><span>节课程</span></div><div><strong>{hours:g}<small> 小时</small></strong><span>预计学时</span></div><div><strong>{stage_count}</strong><span>个阶段</span></div></div></div>']
    parts.append('<div class="le-route-browser-grid"><nav class="le-route-stage-nav" role="tablist" aria-label="学习阶段" aria-orientation="vertical" hidden>')
    for index, (key, title, stage_nodes) in enumerate(groups, 1):
        is_active = key == active_stage
        done = sum(_status(node) == "mastered" for node in stage_nodes)
        current_badge = '<span class="le-stage-current">当前阶段</span>' if key == current_stage else ""
        parts.append(f'<button type="button" class="le-route-stage-tab" role="tab" data-stage-index="{index}" aria-selected="{str(is_active).lower()}" tabindex="{0 if is_active else -1}"><span class="le-stage-number">{index:02}</span><span class="le-stage-heading"><span class="le-stage-title">{esc(title)}</span><span class="le-stage-progress">{done} / {len(stage_nodes)} 已掌握</span></span>{current_badge}<span class="le-stage-count">{len(stage_nodes)} 节</span></button>')
    parts.append('</nav><div class="le-route-stage-panels">')
    for index, (key, title, stage_nodes) in enumerate(groups, 1):
        is_current = key == current_stage
        current_class = " is-current" if is_current else ""
        is_open = " open" if key == active_stage else ""
        current_badge = '<span class="le-stage-current">当前阶段</span>' if is_current else ""
        parts.append(f'<section class="le-route-stage-panel" data-stage-index="{index}" role="tabpanel" tabindex="0"><details class="le-route-stage{current_class}"{is_open}><summary><span class="le-stage-number">{index:02}</span><span class="le-stage-heading"><span class="le-stage-title">{esc(title)}</span></span>{current_badge}<span class="le-stage-count">{len(stage_nodes)} 节</span><span class="le-stage-chevron" aria-hidden="true">⌄</span></summary><div class="le-stage-courses">')
        for node in stage_nodes:
            status = STATUS_LABELS.get(_status(node), "待学习")
            prerequisites = "、".join(str(c) for c in node.get("prerequisites", [])) or "可以从这里开始"
            description = str(node.get("description") or "在工作台打开这一节，查看讲解、例子和练习。")
            description = re.sub(r"(?m)^#{1,6}\s+.*$", "", description)
            description = re.sub(r"\s+", " ", description).strip()
            if len(description) > 220:
                description = description[:220] + "…"
            next_class = " is-next" if node is selected else ""
            next_badge = '<span class="le-course-next-label">接下来</span>' if node is selected else ""
            parts.append(f'<details class="le-route-course{next_class}"><summary><span class="le-course-code">[{esc(node.get("code"))}]</span><span class="le-course-title">{esc(node.get("title"))}</span>{next_badge}<span class="le-course-time">{esc(node.get("est_hours", 2))} 小时</span><span class="le-course-chevron" aria-hidden="true">⌄</span></summary><div class="le-course-detail"><span class="le-course-state">{status}</span><p>{esc(description)}</p><div>前置步骤：{esc(prerequisites)}</div></div></details>')
        parts.append('</div></details></section>')
    parts.append('</div></div>')
    if roadmap.get("summary"):
        parts.append(f'<details class="le-route-intro"><summary>路线说明</summary><p>{esc(roadmap["summary"])}</p></details>')
    parts.append('</div>')
    return "".join(parts)


def preparation_panel(topic, count, *, phase="preparing", env_ready=True, ready=0, failed=0, running=True):
    count = max(0, int(count))
    ready = min(count, max(0, int(ready)))
    failed = min(count - ready, max(0, int(failed)))
    saved = phase != "saving"
    environment = phase not in ("saving", "environment")
    title = "正在保存你的学习安排" if not saved else "你的学习安排已保存"
    if phase == "environment":
        subtitle = "正在整理学习环境清单，课程会接着准备。"
    elif phase == "saving":
        subtitle = "正在把这条路线保存到本地。"
    elif ready == count and count:
        subtitle = "课程已准备好，可以开始第一节了。"
    elif not running and failed:
        subtitle = "部分章节需要重试，可以先学习已准备好的内容。"
    elif not running:
        subtitle = "进入课程后会继续准备内容。已经完成的章节可以直接阅读。"
    else:
        subtitle = "正在逐节备课。你可以进入课程，准备好的章节会陆续出现。"
    env_label = "工作台查看" if env_ready is None else ("已整理" if env_ready else "待补充")
    steps = [("保存路线", saved, "已完成" if saved else "进行中"), ("学习环境", environment and bool(env_ready), env_label if environment else ("进行中" if saved else "稍后")), ("课程内容", ready == count and bool(count), ("已就绪" if ready == count and count else "逐节准备") if environment else "稍后")]
    parts = [f'<section class="le-prep-panel" data-prep-phase="{esc(phase)}" aria-live="polite"><div class="le-prep-heading"><span class="le-prep-symbol" aria-hidden="true">{ "✓" if saved else "·"}</span><div><span class="le-eyebrow">准备你的学习空间</span><h3>{title}</h3><p>{esc(topic)}</p></div></div><ol class="le-prep-steps">']
    for index, (label, done, state) in enumerate(steps, 1):
        parts.append(f'<li class="{"is-done" if done else "is-pending"}"><span>{"✓" if done else f"0{index}"}</span><div><strong>{label}</strong><small>{state}</small></div></li>')
    parts.append('</ol>')
    if environment:
        parts.append(f'<div class="le-prep-count"><span>课程准备进度</span><strong>{ready}<small> / {count} 节</small></strong></div><progress max="{max(1, count)}" value="{ready}" aria-label="已准备好的课程">{ready}/{count}</progress>')
        if failed:
            parts.append(f'<p class="le-prep-retry">{failed} 节暂未完成，可在工作台重试。</p>')
    parts.append(f'<p class="le-prep-subtitle">{subtitle}</p></section>')
    return "".join(parts)
