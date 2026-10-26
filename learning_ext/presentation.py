from pathlib import Path

ASSETS = Path(__file__).parent / "assets"


def chat_model_choices(models):
    def title(name, item):
        spec = item.get("spec", {})
        return str(spec.get("model") or spec.get("model_name") or name)

    default = next((title(name, item) for name, item in models.items() if item.get("default")), None)
    choices = [(f"{default} · 默认" if default else "默认模型", "(default)")]
    choices.extend((f"{title(name, item)} · {name}" if title(name, item) != name else name, name) for name, item in models.items())
    return choices


def refresh_chat_models(current):
    import gradio as gr
    from ktem.llms.manager import llms

    choices = chat_model_choices(llms.info())
    value = current if current in {value for _, value in choices} else "(default)"
    return gr.update(choices=choices, value=value)


def presentation_css():
    css = (ASSETS / "workspace.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "refinements.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "workbench.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "nav.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "outline.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "coach.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "onboarding.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "selects.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "home.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "pages.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "route.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "coach_lesson.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "vendor/fonts/fonts.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "knowledge.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "notebook.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "platforms.css").read_text(encoding="utf-8")
    from learning_ext.model_platforms import platform_css
    css += "\n" + platform_css()
    css += "\n" + (ASSETS / "action_learning.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "rich_text.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "motion.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "signature.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "consumer.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "settings_panels.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "compact.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "theme_layout.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "refine.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "refine_home.css").read_text(encoding="utf-8")
    for page_layer in ("refine_route", "refine_review", "refine_workbench",
                       "refine_settings", "refine_library", "refine_assistant"):
        css += "\n" + (ASSETS / f"{page_layer}.css").read_text(encoding="utf-8")
    for workspace_layer in ("fullscreen_shell", "fullscreen_content", "chat_follow_latest", "route_browser", "chat_surface", "chat_references", "chat_thinking"):
        css += "\n" + (ASSETS / f"{workspace_layer}.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "reasoning_settings.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "typography.css").read_text(encoding="utf-8")
    return css.replace("__ASSETS__", "/file=" + ASSETS.as_posix())


BRAND = f"""<header class="le-topbar"><div class="le-brand"><img src="/file={ASSETS.as_posix()}/aethermind-logo.png" alt="以太智元 AetherMind" width="479" height="150" /></div><div class="le-app-title">Learn Everything <span>/ 学习首页</span></div></header>"""


_BOOK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 6c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1v15"/></svg>'
_PLUS_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>'


def _workbench_card() -> str:
    """有课程时才出现的入口：回到已有课程。"""
    return (
        f'<article class="le-home-card"><span class="le-card-icon">{_BOOK_ICON}</span>'
        '<span class="le-card-tag">学习工作台</span><h3>回到你的课程</h3>'
        "<p>打开已有项目，继续阅读、实践和记录。遇到疑问时，随时向助教提问。</p>"
        '<button data-le-nav="learning-workbench-tab">进入学习工作台 <span>→</span></button></article>'
    )


def _path_card(primary: bool = False) -> str:
    """建新路线。没有课程时它是唯一的卡，所以用主样式、文案也更直接。"""
    if primary:
        cls, tag = "le-home-card", "从零开始"
        title = "先给自己建一条学习路线"
        desc = "告诉 AI 你想学什么、已有的基础与目标。路线建好，学习工作台就会出现在这一页。"
    else:
        cls, tag = "le-home-card secondary", "新的开始"
        title = "探索一个新方向"
        desc = "告诉 AI 你想学什么、已有的基础与目标，建立一条循序渐进的学习路线。"
    return (
        f'<article class="{cls}"><span class="le-card-icon">{_PLUS_ICON}</span>'
        f'<span class="le-card-tag">{tag}</span><h3>{title}</h3><p>{desc}</p>'
        '<button data-le-nav="learning-path-tab">创建学习路线 <span>→</span></button></article>'
    )


def welcome_html(has_course: bool = True) -> str:
    """学习首页。没有任何课程时只给「建路线」，课程出现后才长出工作台入口。"""
    if has_course:
        label = (
            '<div class="le-home-label"><h2>你的学习空间</h2>'
            "<span>选好下一步，专注当下</span></div>"
        )
        cards = (
            f'<section class="le-home-cards" aria-label="开始学习">'
            f"{_workbench_card()}{_path_card()}</section>"
        )
    else:
        label = (
            '<div class="le-home-label"><h2>还没有课程</h2>'
            "<span>先建一条学习路线，工作台才会打开</span></div>"
        )
        cards = (
            '<section class="le-home-cards le-home-cards-single" aria-label="开始学习">'
            f"{_path_card(primary=True)}</section>"
        )
    return f"""<div class="le-home">
 <section class="le-home-intro"><span class="le-home-badge">{_BOOK_ICON} 专注于理解与掌握</span><h1>让每一次学习，都有方向。</h1><p>从一个好奇的问题开始，把知识变成自己的能力。</p></section>
 {label}
 {cards}
 <section class="le-home-path" aria-label="学习流程"><div class="le-home-path-title"><h2>从理解，到真正掌握</h2><span>每一步，都知道接下来做什么</span></div><div class="le-home-steps">
  <div class="le-home-step"><span>01</span><div><h3>建立路线</h3><p>明确目标，拆解知识</p></div></div>
  <div class="le-home-step"><span>02</span><div><h3>深入学习</h3><p>阅读、实践与笔记</p></div></div>
  <div class="le-home-step"><span>03</span><div><h3>间隔复习</h3><p>巩固值得记住的内容</p></div></div>
  <div class="le-home-step"><span>04</span><div><h3>检验理解</h3><p>找到薄弱处，再前进</p></div></div>
 </div></section>
 <div class="le-home-foot"><span>学习内容保存在本地，模型调用由你配置。</span><div><button data-le-nav="chat-tab">知识问答 ↗</button><button data-le-nav="quick-setup-tab">模型配置 ↗</button></div></div>
</div>"""


def polish_chat_ui(app):
    from learning_ext.chat_presentation import configure_chat_presentation

    page = app.chat_page
    configure_chat_presentation(page)
    page.chat_panel.chatbot.placeholder = (
        "从一个问题开始。直接提问，或点下方「资料」选择参考文件。"
    )
    page.chat_panel.text_input.placeholder = "输入问题，按回车发送…"
    page.chat_control.conversation.label = "历史对话"
    page.chat_control.cb_suggest_chat.label = "推荐问题"
    page.chat_suggestion.accordion.elem_id = "le-chat-suggestions"
    page.chat_suggestion.accordion.label = "你可以接着问"
    page.chat_suggestion.accordion.open = True
    samples = ["帮我总结这份资料的核心内容", "把重要概念用简单的例子解释清楚", "根据资料整理三个值得继续探索的问题"]
    type(page.chat_suggestion).CHAT_SAMPLES = samples
    page.chat_suggestion.examples.value = {"headers": ["推荐问题"], "data": [[text] for text in samples], "metadata": None}
    page.chat_suggestion.default_example.value = [[text] for text in samples]

    page.quick_urls.placeholder = "或粘贴资料网址"
    page.quick_urls.label = "资料网址"
    page.quick_file_upload.label = "参考文件"
    friendly = {"simple": "标准检索", "complex": "深入检索", "(default)": "使用默认模型", "English": "英语", "Chinese": "中文", "Japanese": "日语", "French": "法语", "German": "德语", "citation: highlight": "高亮来源原文", "citation: inline": "在回答中标注来源"}
    for name, label, info in [
        ("reasoning_type", "检索方式", "标准检索适合日常资料问答。"),
        ("model_type", "回答模型", "默认使用已配置的模型。"),
        ("language", "回答语言", "选择希望 AI 使用的语言。"),
        ("citation", "来源展示", "选择引用来源的显示方式。"),
    ]:
        component = getattr(page, name)
        component.label = label
        component.info = info
        component.show_label = True
        component.container = True
        component.choices = [(friendly.get(str(text), str(text)), value) for text, value in component.choices]
    from ktem.llms.manager import llms
    page.model_type.choices = chat_model_choices(llms.info())
    page.model_type.info = None
    page.model_type.filterable = False
    from learning_ext.chat_connections import configure_chat_connections
    configure_chat_connections(app, page)
    from learning_ext.chat_language import configure_auto_language
    configure_auto_language(page)
    page.use_mindmap_check.label = "附带思维导图"
    page.use_mindmap_check.info = "把回答中的要点整理成图。"
    page.use_mindmap_check.container = True

    for name, label in [
        ("btn_new", "新对话"),
        ("btn_conversation_rn", "重命名"),
        ("btn_del", "删除"),
    ]:
        button = getattr(page.chat_control, name, None)
        if button is not None:
            button.value = label
            button.icon = None
    labels = {
        "Quick Upload": "添加资料",
        "File Collection": "参考范围",
        "GraphRAG Collection": "图谱检索",
        "LightRAG Collection": "关联检索",
        "Chat settings": "回答设置",
        "Information panel": "引用与来源",
        "Feedback": "反馈",
        "Suggest chat": "推荐问题",
        "Correctness:": "回答是否准确",
        "Other issue:": "其他问题",
        "Share this conversation": "共享这段对话",
    }
    values = {
        "## Conversations": "### 会话与资料",
        "Reasoning method": "检索方式",
        "Model": "模型",
        "Language": "语言",
        "Report": "提交反馈",
        "This will send the current chat and the user settings to help with investigation": "反馈会保存当前对话与设置，便于排查问题。",
    }
    for block in app.app.blocks.values():
        placeholder = getattr(block, "placeholder", None)
        if placeholder == "Browse conversation":
            block.placeholder = "选择历史对话"
        choices = getattr(block, "choices", None)
        feedback_names = {"The answer is correct": "回答准确", "The answer is incorrect": "回答有误", "The answer is offensive": "内容不适当", "The evidence is incorrect": "引用不准确"}
        if choices and any(isinstance(item, (tuple, list)) and item[0] in feedback_names for item in choices):
            block.choices = [(feedback_names.get(item[0], item[0]), item[1]) for item in choices]
        if isinstance(placeholder, str) and placeholder.startswith("More detail (e.g."):
            block.placeholder = "哪里需要改进？写下你的发现…"
        if choices and any(isinstance(item, (tuple, list)) and item[0] in {"Search All", "Search In File(s)"} for item in choices):
            names = {"Search All": "全部资料", "Search In File(s)": "指定文件"}
            block.choices = [(names.get(item[0], item[0]), item[1]) for item in choices]
        label = getattr(block, "label", None)
        if isinstance(label, str) and label in labels:
            block.label = labels[label]
            if label == "Quick Upload":
                block.elem_id = "le-chat-add-source"
            if label in {"Quick Upload", "GraphRAG Collection", "LightRAG Collection"}:
                block.open = False
        value = getattr(block, "value", None)
        if isinstance(value, str) and value in values:
            block.value = values[value]


def project_display_name(project):
    title = " ".join((project.title or "").split())
    values = (project.topic, title) if len(title) > 42 else (title, project.topic)
    for value in values:
        name = " ".join((value or "").split())
        if len(name) > 1 and name.lower() not in {"test", "untitled"}:
            return name if len(name) <= 42 else name[:41] + "…"
    return f"未命名学习项目 · {project.id}"


def project_choices(projects):
    from collections import Counter
    from datetime import timezone

    projects = list(projects)
    names = [project_display_name(p) for p in projects]
    counts = Counter(names)
    labels = []
    for project, name in zip(projects, names):
        if counts[name] > 1:
            created = getattr(project, "created_at", None)
            if created:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                name += created.astimezone().strftime(" · %m-%d %H:%M 创建")
            else:
                name += f" · 项目 {project.id}"
        labels.append(name)
    collisions = Counter(labels)
    return [(f"{name} · {p.id}" if collisions[name] > 1 else name, str(p.id)) for p, name in zip(projects, labels)]


def clean_heading_icons(markdown):
    import re
    lines = []
    fenced = False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        if not fenced and re.match(r"^#{1,6} ", line):
            line = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]", "", line)
            line = re.sub(r"^(#{1,6}) +", r"\1 ", line)
        lines.append(line)
    return "\n".join(lines)


def md_safe(text: str) -> str:
    """展示用：把连续下划线转义掉。

    Markdown 会把 `______` 当成强调/粗体语法吃掉，填空题的挖空就消失了
    （四个环节依次是 、、、。 这种）。只改展示，不动存储。
    """
    import re as _re

    return _re.sub(r"_{2,}", lambda m: "\\_" * min(len(m.group()), 12), text or "")
