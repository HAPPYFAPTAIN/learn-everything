from html import escape
import re


def upload_feedback(result, info, files=None):
    result, info = result or "", info or ""
    rows = []
    for line in result.splitlines():
        if "|" not in line:
            continue
        success = line.lstrip().startswith("✅")
        content = line.split("|", 1)[1].strip()
        name, _, detail = content.partition(": ") if not success else (content, "", "")
        if success:
            message = "已加入，可用于知识问答"
        elif any(word in detail.lower() for word in ("connection", "retryerror", "timeout", "connect")):
            message = "模型服务暂时连不上。可先保存原件阅读，连接恢复后再解析。"
        elif "预览" in detail:
            message = "暂时无法生成预览，请检查文件是否完整后重试。"
        elif any(word in detail.lower() for word in ("exist", "already", "同名")):
            message = "资料已存在；需要替换时，展开“更新已有资料”。"
        else:
            message = "这份资料未能完成解析。可先保存原件，或查看处理详情。"
        rows.append(f'<div class="le-import-item {"is-ready" if success else "needs-attention"}"><span class="le-import-icon" aria-hidden="true">{"✓" if success else "!"}</span><div><strong>{escape(name)}</strong><p>{message}</p></div><span class="le-import-tag">{"已就绪" if success else "待处理"}</span></div>')
    matches = re.findall(r"Indexing\s*\[(\d+)/(\d+)\]", info)
    total = int(matches[-1][1]) if matches else len(files or [])
    failed = any('needs-attention' in row for row in rows)
    finished = bool(total and len(rows) >= total)
    if not total and not result and not info:
        title, subtitle, state = "先选择一份资料", "支持文档、PDF 和图片。", "idle"
    elif "Error:" in info and not finished:
        title, subtitle, state = "整理暂时中断", "可以先保存原件阅读，稍后再试。", "attention"
    elif finished:
        title = "有资料需要处理" if failed else "资料已准备好"
        subtitle, state = f"已处理 {len(rows)} 份资料", "attention" if failed else "ready"
    else:
        title, state = "正在整理资料", "working"
        subtitle = f"已完成 {len(rows)} / {total} 份" if total else "正在准备，请稍候"
    return f'<section class="le-import-feedback" data-state="{state}" role="status" aria-live="polite"><header><span class="le-import-orbit" aria-hidden="true"></span><div><h3>{title}</h3><p>{subtitle}</p></div></header><div class="le-import-items">{"".join(rows)}</div></section>'


def attach_upload_feedback(page):
    import gradio as gr
    with page.upload_progress_panel:
        panel = gr.HTML(upload_feedback("", ""), elem_classes=["le-import-summary"])
    for component in (page.upload_result, page.upload_info):
        component.elem_classes = [*(component.elem_classes or []), "le-import-log"]
        component.change(upload_feedback, [page.upload_result, page.upload_info, page.files], [panel], show_progress="hidden", trigger_mode="always_last")

