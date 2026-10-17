from pathlib import Path

ASSETS = Path(__file__).parent / "assets"


def presentation_css():
    css = (ASSETS / "workspace.css").read_text(encoding="utf-8")
    css += "\n" + (ASSETS / "refinements.css").read_text(encoding="utf-8")
    return css.replace("__ASSETS__", "/file=" + ASSETS.as_posix())


BRAND = f"""<header class="le-topbar"><div class="le-brand"><img src="/file={ASSETS.as_posix()}/aethermind-logo.png" alt="以太智元 AetherMind" width="479" height="150" /></div><div class="le-app-title">Learn Everything <span>/ 学习工作台</span></div><span class="le-local">本地工作空间</span></header>"""


def welcome_html():
    return """<div class="le-home">
 <section class="le-home-intro"><span class="le-home-badge"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 6c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1v15"/></svg> 专注于理解与掌握</span><h1>让每一次学习，都有方向。</h1><p>从一个好奇的问题开始，把知识变成自己的能力。</p></section>
 <div class="le-home-label"><h2>你的学习空间</h2><span>选好下一步，专注当下</span></div>
 <section class="le-home-cards" aria-label="开始学习">
  <article class="le-home-card"><span class="le-card-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 6c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1v15"/></svg></span><span class="le-card-tag">学习工作台</span><h3>回到你的课程</h3><p>打开已有项目，继续阅读、实践和记录。遇到疑问时，随时向助教提问。</p><button data-le-nav="learning-workbench-tab">进入学习工作台 <span>→</span></button></article>
  <article class="le-home-card secondary"><span class="le-card-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg></span><span class="le-card-tag">新的开始</span><h3>探索一个新方向</h3><p>告诉 AI 你想学什么、已有的基础与目标，建立一条循序渐进的学习路线。</p><button data-le-nav="learning-path-tab">创建学习路线 <span>→</span></button></article>
 </section>
 <section class="le-home-path" aria-label="学习流程"><div class="le-home-path-title"><h2>从理解，到真正掌握</h2><span>每一步，都知道接下来做什么</span></div><div class="le-home-steps">
  <div class="le-home-step"><span>01</span><div><h3>建立路线</h3><p>明确目标，拆解知识</p></div></div>
  <div class="le-home-step"><span>02</span><div><h3>深入学习</h3><p>阅读、实践与笔记</p></div></div>
  <div class="le-home-step"><span>03</span><div><h3>间隔复习</h3><p>巩固值得记住的内容</p></div></div>
  <div class="le-home-step"><span>04</span><div><h3>检验理解</h3><p>找到薄弱处，再前进</p></div></div>
 </div></section>
 <div class="le-home-foot"><span>学习内容保存在本地，模型调用由你配置。</span><div><button data-le-nav="chat-tab">知识问答 ↗</button><button data-le-nav="quick-setup-tab">模型配置 ↗</button></div></div>
</div>"""


def polish_chat_ui(app):
    page = app.chat_page
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
        "File Collection": "文件检索范围",
        "GraphRAG Collection": "图谱检索",
        "LightRAG Collection": "关联检索",
        "Chat settings": "回答设置",
        "Information panel": "引用与来源",
        "Feedback": "反馈",
        "Suggest chat": "推荐问题",
    }
    values = {
        "## Conversations": "### 会话与资料",
        "Reasoning method": "检索方式",
        "Model": "模型",
        "Language": "语言",
    }
    for block in app.app.blocks.values():
        placeholder = getattr(block, "placeholder", None)
        if placeholder == "Browse conversation":
            block.placeholder = "选择历史对话"
        choices = getattr(block, "choices", None)
        if choices and any(isinstance(item, (tuple, list)) and item[0] in {"Search All", "Search In File(s)"} for item in choices):
            names = {"Search All": "全部资料", "Search In File(s)": "指定文件"}
            block.choices = [(names.get(item[0], item[0]), item[1]) for item in choices]
        label = getattr(block, "label", None)
        if isinstance(label, str) and label in labels:
            block.label = labels[label]
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
