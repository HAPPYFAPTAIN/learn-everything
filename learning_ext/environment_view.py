from html import escape


def environment_state(state="idle", title="准备好，再开始", detail="按课程需要准备工具，也可以直接确认已有环境。", steps=None):
    busy = state in {"loading", "running"}
    symbol = "✓" if state == "done" else "!" if state == "error" else "↗"
    items = "".join(
        f'<li><span>{index:02d}</span><div>{escape(str(step.get("desc") or "配置步骤"))}</div></li>'
        for index, step in enumerate(steps or [], 1)
    )
    checklist = f'<ol class="le-env-steps">{items}</ol>' if items else ""
    return (
        f'<section class="le-env-state" data-env-state="{escape(state)}" role="status" aria-live="polite" aria-busy="{str(busy).lower()}">'
        f'<div class="le-env-symbol" aria-hidden="true">{symbol}</div>'
        f'<div class="le-env-copy"><h3>{escape(title)}</h3><p>{escape(detail)}</p></div>'
        f'{"<div class=le-env-loading aria-hidden=true><i></i></div>" if busy else ""}'
        f'</section>{checklist}'
    )
