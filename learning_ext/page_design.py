from html import escape

from learning_ext.home_content import illustration


_DRAWINGS = {
    "route": '<path d="M24 100h65c38 0 38-64 76-64h90"/><circle cx="24" cy="100" r="8"/><circle cx="144" cy="68" r="8"/><circle cx="255" cy="36" r="8"/><path d="m250 20 16 16-16 16"/>',
    "review": '<rect x="77" y="18" width="120" height="94" rx="14" transform="rotate(-12 137 65)"/><rect x="104" y="22" width="120" height="94" rx="14"/><path d="M130 48h50M130 62h68M130 84h32"/><path d="m198 81 7 7 14-17"/>',
    "quiz": '<circle cx="77" cy="68" r="28"/><path d="m64 68 9 9 17-20M118 68h25"/><rect x="160" y="40" width="58" height="58" rx="16"/><path d="m179 60 12 10-12 10"/>',
    "dashboard": '<path d="M40 109h210M68 109V82h29v27M126 109V57h29v52M184 109V25h29v84M68 52l58-26 58-15"/><circle cx="68" cy="52" r="5"/><circle cx="126" cy="26" r="5"/>',
    "setup": '<rect x="33" y="37" width="65" height="65" rx="20"/><path d="M54 59h23M54 72h15M98 69h83"/><rect x="181" y="24" width="68" height="85" rx="17"/><path d="m201 69 10 10 19-24"/><circle cx="140" cy="69" r="7"/>',
    "library": '<rect x="80" y="19" width="78" height="92" rx="10" transform="rotate(-12 119 65)"/><rect x="119" y="24" width="78" height="92" rx="10"/><path d="M138 48h37M138 62h37M138 76h22"/><circle cx="205" cy="88" r="23"/><path d="m221 105 18 18"/>',
    "help": '<circle cx="140" cy="68" r="49"/><path d="m159 46-10 34-33 11 11-34 32-11Z"/><circle cx="140" cy="68" r="5"/><path d="M140 7v12M140 117v12M79 68h12M189 68h12"/>',
}

_PAGES = {
    "route": ("ROUTE", "学习路线"),
    "review": ("REVIEW", "间隔复习"),
    "quiz": ("PRACTICE", "查漏测验"),
    "dashboard": ("PROGRESS", "学习进展"),
    "setup": ("CONNECTION", "模型与连接"),
    "library": ("LIBRARY", "资料库"),
    "help": ("GUIDE", "使用向导"),
}


def page_intro(kind):
    label, title = _PAGES[kind]
    artwork = {"route": "journey", "review": "writing", "quiz": "python", "dashboard": "journey", "setup": "ai", "library": "writing", "help": "journey"}[kind]
    return (
        f'<header class="le-editorial-head le-editorial-{kind}">'
        f'<div class="le-editorial-copy"><span class="le-section-label">{label}</span>'
        f'<h1>{title}</h1></div>'
        f'<div class="le-editorial-art" aria-hidden="true">{illustration(artwork)}</div></header>'
    )


def section_heading(number, title):
    return (
        f'<div class="le-section-heading"><span>{escape(number)}</span><div>'
        f'<h2>{escape(title)}</h2></div></div>'
    )



def practice_empty(kind, message):
    title = "准备好，开始回忆" if kind == "review" else "从第一题开始"
    return (
        f'<div class="le-practice-empty"><div class="le-practice-symbol" aria-hidden="true">'
        f'{illustration("writing" if kind == "review" else "python")}</div>'
        f'<h3>{title}</h3><p>{escape(message)}</p></div>'
    )


CONNECTION_STEPS = '''<ol class="le-connection-steps">
<li><span>01</span><div><strong>确认连接可用</strong></div></li>
<li><span>02</span><div><strong>保存这次设置</strong></div></li>
<li><span>03</span><div><strong>开始你的第一课</strong></div></li>
</ol>'''


HELP_CARDS = f'''<section class="le-help-cards" aria-label="选择操作向导">
<button type="button" data-le-tour-start="learning">{illustration("journey")}<strong>把一个念头<br>变成一门课程</strong><b>带我试一遍 ↗</b></button>
<button type="button" data-le-tour-start="review">{illustration("ai")}<strong>让学过的知识<br>留下来</strong><b>看看怎么做 ↗</b></button>
<button type="button" data-le-tour-start="documents">{illustration("writing")}<strong>从一份资料里<br>找到答案</strong><b>开始资料向导 ↗</b></button>
</section>'''
