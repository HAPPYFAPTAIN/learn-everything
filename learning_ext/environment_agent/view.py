from html import escape


def environment_card(state):
    report = state.get("environment", {})
    items = report.get("items", [])
    verified = sum(item["status"] in {"ready", "present"} for item in items)
    labels = {"ready": "已验证", "present": "已找到", "missing": "待确认", "unknown": "待验证", "mismatch": "版本待调整"}
    rows = "".join(
        f'<li class="le-env-item" data-status="{escape(item["status"])}"><div><strong>{escape(item["name"])}</strong>'
        f'<span>{escape(item.get("version") or "尚未确认版本")}</span></div><b>{labels.get(item["status"], "待确认")}</b>'
        f'<p>{escape(item["detail"])}</p></li>' for item in items
    )
    skipped = "".join(f'<li><strong>{escape(state["steps"][int(index)]["title"])}</strong><span>{escape(reason)}</span></li>'
                      for index, reason in state.get("skipped", {}).items())
    changes = f'<details class="le-env-skips"><summary>将跳过 {len(state["skipped"])} 项重复准备</summary><ul>{skipped}</ul></details>' if skipped else '<p class="le-env-footnote">没有可直接跳过的准备项，继续按步骤验证。</p>'
    incomplete = '<span class="le-env-limited">部分条件待确认</span>' if not report.get("complete") else ""
    return (f'<article class="le-action-card le-env-intro" data-le-step-active="true" data-le-focus="step" data-step="environment">'
            f'<div class="le-action-kicker"><span>开始之前 · 本机环境</span>{incomplete}</div>'
            f'<h2>从你已有的工具开始</h2><p>已确认 {verified} 项条件。重复安装会跳过，动手练习照常保留。</p>'
            f'<ul class="le-env-evidence">{rows}</ul>{changes}'
            '<div class="le-env-boundary">本次只检查软件与版本。不会安装、修改设置或代替你完成练习。</div></article>')
