from bs4 import BeautifulSoup
import pytest

from learning_ext.rich_text import render_rich_text


def soup(text, **options):
    return BeautifulSoup(render_rich_text(text, **options), "html.parser")


def test_saved_plain_commands_become_one_copyable_block():
    rendered = soup("在 PowerShell 中执行：\nmkdir agent-learning\ncd agent-learning\n进入你为本课程创建的项目根目录。", legacy_commands=True)
    assert len(rendered.select(".le-code-block")) == 1
    assert rendered.select_one("pre code").text == "mkdir agent-learning\ncd agent-learning\n"
    assert rendered.select_one(".le-code-language").text == "PowerShell"
    assert rendered.select_one("button")['aria-label'] == "复制代码"
    assert "进入你为本课程" not in rendered.select_one("pre").text


@pytest.mark.parametrize("language", ["python", "powershell", "json", "unknown-language"])
def test_fenced_code_keeps_indentation_and_literal_characters(language):
    code = 'if a < 3:\n    print("你好 & <script>")\n\n    value = `literal`\n'
    rendered = soup(f"说明\n\n```{language}\n{code}```", legacy_commands=True)
    assert rendered.select_one("pre code").text == code
    assert not rendered.select("script")
    assert len(rendered.select(".le-code-block")) == 1
    if language != "unknown-language":
        assert rendered.select("pre code span")


def test_markdown_prose_inline_code_and_lists():
    rendered = soup("**创建文件夹**\n\n1. 打开 `PowerShell`\n2. 输入命令\n\n[文档](https://example.com)")
    assert rendered.strong.text == "创建文件夹"
    assert rendered.select_one("li code").text == "PowerShell"
    assert len(rendered.select("li")) == 2
    assert rendered.a['href'] == "https://example.com"


def test_html_and_unsafe_links_remain_inert():
    rendered = soup('<img src=x onerror="alert(1)">\n<script>alert(1)</script>\n[跳转](javascript:alert(1))\n![图片](https://example.com/tracker.png)')
    assert not rendered.select("img,script,iframe")
    assert not rendered.select("a[href^=javascript]")
    assert "<img" in rendered.text


def test_old_content_normalization_does_not_rewrite_prose_or_existing_code():
    rendered = soup("Python 是一种编程语言。\n\n`cd example`\n\n```text\nmkdir example\n```\n\n    cd example\n", legacy_commands=True)
    assert len(rendered.select(".le-code-block")) == 2
    assert rendered.select_one("p").text == "Python 是一种编程语言。"
    assert [code.text for code in rendered.select("pre code")] == ["mkdir example\n", "cd example\n"]


def test_powershell_continuation_is_copied_as_one_command():
    command = 'New-Item `\n  -Path "学习目录" `\n  -ItemType Directory'
    rendered = soup("执行以下命令：\n" + command + "\n然后检查文件夹。", legacy_commands=True)
    assert rendered.select_one("pre code").text == command + "\n"


def test_action_card_formats_saved_content_without_mutation():
    from learning_ext.pages.action_learning import action_card
    action = "在 PowerShell 中执行：\nmkdir agent-learning\ncd agent-learning"
    step = dict(title="创建项目文件夹", action=action, check="终端末尾为 `agent-learning`", source="```powershell\nmkdir agent-learning\n```")
    rendered = BeautifulSoup(action_card(dict(index=0, steps=[step], done=[])), "html.parser")
    assert rendered.select_one(".le-action-instruction pre code").text == "mkdir agent-learning\ncd agent-learning\n"
    assert rendered.select_one(".le-action-check code").text == "agent-learning"
    assert rendered.select_one(".le-action-source .le-code-copy")
    assert step['action'] == action
