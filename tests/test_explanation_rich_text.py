from learning_ext.rich_text import render_rich_text


def test_learning_annotations_and_standard_markdown():
    html = render_rich_text('**核心** ++先激活环境++ ~~重装系统~~ ==重点|检查依赖== ==概念|模块== ==例子|橱柜== ==注意|装错环境==', annotations=True)
    assert '<strong>核心</strong>' in html
    assert '<u>先激活环境</u>' in html
    assert '<s>重装系统</s>' in html
    for tone in ('key', 'concept', 'example', 'warning'):
        assert f'le-highlight-{tone}' in html


def test_annotations_escape_html_and_do_not_modify_code():
    html = render_rich_text('==注意|<img src=x onerror=alert(1)>==\n\n`==重点|literal==`\n\n```python\nx = "++literal++"\n```', annotations=True)
    assert '<img' not in html
    assert '&lt;img' in html
    assert '<code>==重点|literal==</code>' in html
    assert '<u>literal</u>' not in html
    assert 'le-code-copy' in html


def test_annotation_opt_in_and_unknown_tones_remain_literal():
    assert '<mark' not in render_rich_text('==重点|原文==')
    assert '<mark' not in render_rich_text('==dangerous|原文==', annotations=True)


def test_explanation_prompt_teaches_semantic_formatting():
    from learning_ext.notes.prompts import TERM_PROMPT
    assert '==重点|' in TERM_PROMPT
    assert '++下划线++' in TERM_PROMPT
    assert '不输出 HTML' in __import__('learning_ext.notes.prompts', fromlist=['TERM_SYSTEM']).TERM_SYSTEM
