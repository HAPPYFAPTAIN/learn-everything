from bs4 import BeautifulSoup
import pytest

from learning_ext.db.models import KnowledgeNode
from learning_ext.progress import environment


@pytest.fixture
def evidence(monkeypatch):
    environment._CACHE.clear()
    report = {"checked_at": "2026-10-26T12:00:00+08:00", "items": [
        {"key": "python", "name": "Python", "status": "ready", "version": "3.11.6", "spec": ""},
        {"key": "code", "name": "VS Code", "status": "present", "version": "1.100", "spec": ""},
    ]}
    monkeypatch.setattr(environment, "inspect_environment", lambda text: report)
    from learning_ext.action_learning.service import Journal
    monkeypatch.setattr(Journal, "record", lambda *args, **kwargs: None)
    return report


def node(content=""):
    return KnowledgeNode(id=1, project_id=1, code="1.0", title="环境搭建：Python 与编辑器", description=content)


def test_environment_check_is_cached_and_copy_isolated(evidence, monkeypatch):
    calls = []
    monkeypatch.setattr(environment, "inspect_environment", lambda text: calls.append(text) or evidence)
    first = environment.environment_report(node())
    first["items"].clear()
    assert environment.environment_report(node())["items"]
    assert len(calls) == 1


def test_only_redundant_installation_is_folded(evidence):
    content = '## 知识点深入\n\n### 子主题 1：安装 Python 并验证\n\n安装后检查版本。\n\n```bash\npython --version\n```\n\n### 子主题 2：安装 VS Code\n\n安装 Python 扩展。\n\n### 创建项目\n\n```powershell\nmkdir demo\n```\n\n## 本节小结\n\n自己运行脚本。'
    result = environment.adapt_reading(node(content), "", content)
    from learning_ext.rich_text import render_lesson
    soup = BeautifulSoup(render_lesson(result), "html.parser")
    details = soup.select("details")
    assert len(details) == 1
    assert "python --version" in details[0].text
    assert "Python 扩展" not in details[0].text
    assert "mkdir demo" not in details[0].text
    assert "3.11.6" in soup.text
    assert soup.select_one("h2").text == "开始前：本机环境"


def test_unknown_environment_does_not_skip(evidence):
    evidence["items"][0]["status"] = "mismatch"
    content = "### 安装 Python\n\n需要新版本。"
    assert "<details>" not in environment.adapt_reading(node(content), "", content)


def test_probe_error_preserves_lesson(monkeypatch, evidence):
    def fail(text):
        raise OSError("probe failed")
    monkeypatch.setattr(environment, "inspect_environment", fail)
    content = "### 安装 Python\n\n准备步骤。"
    result = environment.adapt_reading(node(content), "", content)
    assert "本次不跳过" in result
    assert content in result


def test_explicit_lesson_version_constraints_reach_probe(evidence, monkeypatch):
    calls = []
    monkeypatch.setattr(environment, "inspect_environment", lambda text: calls.append(text) or evidence)
    environment.environment_report(node("本节要求 Python >=3.12，示例输出 Python 3.13.1。"))
    assert "Python >=3.12" in calls[0]
    assert "Python 3.13.1" not in calls[0]


def test_both_generation_paths_receive_evidence(evidence, monkeypatch):
    from learning_ext.progress import study
    prompts = []
    monkeypatch.setattr(study, "chat", lambda prompt, **kwargs: prompts.append(prompt) or "## 本节小结\n完成")
    study.generate_node_summary(node(), "Python")
    study.generate_practice_lesson(node(), "Python")
    for prompt in prompts:
        assert '"version": "3.11.6"' in prompt
        assert "不再要求下载或重装" in prompt
        assert "虚拟环境" in prompt


def test_lesson_rich_text_survives_gradio_updates():
    import asyncio
    asyncio.run(_exercise_gradio_updates())


async def _exercise_gradio_updates():
    import gradio as gr
    from gradio.state_holder import SessionState
    from learning_ext.lesson_component import LessonHTML
    with gr.Blocks() as app:
        trigger = gr.Button()
        lesson = LessonHTML()
        trigger.click(lambda: "", outputs=lesson)
    state = SessionState(app)
    fn = app.fns[0]
    for update in [gr.update(), gr.update(visible=True), gr.update(value="## 更新标题\n\n**重点**")]:
        await app.postprocess_data(fn, update, state)
        data = await app.postprocess_data(fn, "## 本节导览\n\n**重点**\n\n```python\nprint(1)\n```", state)
        soup = BeautifulSoup(data[0], "html.parser")
        assert soup.h2.text == "本节导览"
        assert soup.strong.text == "重点"
        assert soup.select_one(".le-code-copy")
        assert soup.select_one("code").text.strip() == "print(1)"
    assert lesson.get_block_name() == "html"
