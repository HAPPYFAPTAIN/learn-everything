from collections import Counter
from functools import partial
import html
import json
from pathlib import Path
import re
from types import SimpleNamespace

import gradio as gr
import pytest

from learning_ext.pages import coach


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(coach.runtime.Session, "record", lambda *args, **kwargs: None)
    return coach.CoachPage(SimpleNamespace())


def applied_updates(rows):
    state = [None] * 21
    for row in rows:
        for index, value in enumerate(row):
            if value == gr.skip():
                continue
            if isinstance(value, dict) and isinstance(state[index], dict):
                state[index] = {**state[index], **value}
            else:
                state[index] = value
        yield list(state)


def frame_messages(source):
    match = re.fullmatch(r'<div data-coach-frame\b[^>]*>(.*)</div>', source, re.S)
    assert match is not None
    assert "<" not in match[1]
    payload = json.loads(html.unescape(match[1]))
    assert isinstance(payload, dict)
    return payload


def frame_html(source):
    return "".join(frame_messages(source).values())


def question_model(monkeypatch, page):
    question = {"question": "你想先完成哪件事？", "options": [
        {"label": "整理表格", "description": "从已有文件开始"}, {"label": "编写程序"}, {"label": "整理文档"}]}
    replies = iter([("", [{"id": "ask-1", "name": "ask_user", "args": question}]), ("从一个小练习开始。", [])])
    requests, records = [], []
    monkeypatch.setattr(page.session, "record", lambda event, **details: records.append((event, details)))

    def stream(session):
        requests.append(list(session.messages))
        text, calls = next(replies)
        session.messages.append({"role": "assistant", "content": text, **({"tool_calls": [
            {"id": call["id"], "type": "function", "function": {
                "name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False)}}
            for call in calls]} if calls else {})})
        if text:
            yield {"kind": "delta", "text": text}
        return text, calls

    monkeypatch.setattr(coach.runtime, "_model_stream", stream)
    monkeypatch.setattr(coach.runtime, "execute_tool", lambda *args: pytest.fail("Question answers must not perform computer operations"))
    return question, requests, records


def test_real_agent_is_active_and_suggestions_only_fill_input(page, monkeypatch):
    monkeypatch.setattr(coach.runtime, "run", lambda *args: pytest.fail("A suggestion must not run the agent"))
    root = Path(__file__).resolve().parents[1]
    source = (root / "learning_ext/app.py").read_text(encoding="utf-8")
    assert "self.coach_page = CoachPage(self)" in source
    assert "self.coach_page = CoachLessonPage(self)" not in source
    for name in ("env", "files", "window"):
        assert page._fill_suggestion(name)["value"] == coach._SUGGESTIONS[name]
    assert page.items == []
    assert not page._busy


def test_streaming_updates_tools_and_restores_controls(page, monkeypatch):
    def stream(session, text):
        assert text == "检查环境"
        yield {"kind": "step"}
        yield {"kind": "delta", "text": "先检查"}
        yield {"kind": "tool_start", "call_id": "read-1", "name": "system_info", "args": {}}
        yield {"kind": "tool_end", "call_id": "read-1", "name": "system_info", "output": "Python 已安装", "ok": True, "ms": 12}
        yield {"kind": "delta", "text": "可以直接开始。"}

    monkeypatch.setattr(coach.runtime, "run", stream)
    updates = list(page._on_send("检查环境"))
    states = list(applied_updates(updates))
    assert updates[0][4] == {"__type__": "update", "interactive": False, "value": "", "placeholder": "告诉我你的进展，或接着问…"}
    assert all(not row[5]["interactive"] and not row[6]["interactive"] for row in states[:-1])
    assert any(row[5] == gr.skip() and row[6] == gr.skip() for row in updates[1:-1])
    assert any('data-status="run"' in frame_html(row[1]) for row in updates)
    assert any('data-status="ok"' in frame_html(row[1]) and "Python 已安装" in frame_html(row[1]) for row in updates)
    assert re.search(r'<details class="le-tool"[^>]*data-call-id="read-1"', frame_html(updates[-1][1]))
    assert updates[-1][4]["interactive"] is True
    assert "value" not in updates[-1][4]
    assert updates[-1][5]["interactive"] is True
    assert updates[-1][6]["interactive"] is True
    assert updates[-1][10]["visible"] is False
    assert not page._busy


def test_running_turn_cannot_be_reentered_or_cleared(page, monkeypatch):
    runs = []

    def stream(session, text):
        runs.append(text)
        yield {"kind": "delta", "text": "正在观察"}

    monkeypatch.setattr(coach.runtime, "run", stream)
    first = page._on_send("原始任务")
    next(first)
    assert page._busy
    assert page._fill_suggestion("env") == {"__type__": "update"}
    list(page._on_send("重复任务"))
    list(page._on_clear())
    assert page.items == [{"type": "user", "text": "原始任务"}]
    assert not runs
    list(first)
    assert runs == ["原始任务"]
    assert not page._busy


def test_pending_approval_preserves_draft_and_does_not_start_another_task(page, monkeypatch):
    page.session.pending = [{"id": "write-1", "name": "type_text", "args": {"text": "hello"}}]
    monkeypatch.setattr(coach.runtime, "run", lambda *args: pytest.fail("Pending action must be resolved first"))
    updates = list(page._on_send("先等等，我想修改"))
    assert all("value" not in row[4] for row in updates)
    assert updates[-1][5]["interactive"] is False
    assert updates[-1][7]["interactive"] is True
    assert updates[-1][8]["interactive"] is True


def test_denial_without_tool_start_has_visible_receipt(page, monkeypatch):
    page.session.pending = [{"id": "write-1", "name": "type_text", "args": {"text": "hello"}}]

    def deny(session, allow):
        assert allow is False
        session.pending = None
        yield {"kind": "tool_end", "call_id": "write-1", "name": "type_text", "args": {"text": "hello"},
               "output": "你拒绝了这次操作，未执行。", "denied": True, "ok": False, "ms": 0}

    monkeypatch.setattr(coach.runtime, "approve", deny)
    updates = list(page._on_deny())
    assert len(page.items) == 1
    assert page.items[0]["status"] == "denied"
    assert '<pre class="le-tool-out">你拒绝了这次操作，未执行。</pre>' in frame_html(updates[-1][1])
    assert updates[-1][2]["visible"] is False
    assert updates[-1][5]["interactive"] is True


def test_pending_tool_is_updated_in_place_when_approved(page, monkeypatch):
    call = {"id": "write-1", "name": "type_text", "args": {"text": "hello"}}
    page.session.pending = [call]
    list(page._consume(iter([{"kind": "need_approval", "calls": [call]}])))
    assert page.items[0]["status"] == "pending"

    def approve(session, allow):
        assert allow is True
        assert session.auto is False
        session.pending = None
        yield {"kind": "tool_start", "call_id": call["id"], "name": call["name"], "args": call["args"]}
        yield {"kind": "tool_end", "call_id": call["id"], "name": call["name"], "output": "已输入", "ok": True}

    monkeypatch.setattr(coach.runtime, "approve", approve)
    page.session.auto = True
    list(page._on_allow())
    assert len(page.items) == 1
    assert page.items[0]["status"] == "ok"
    assert page.items[0]["output"] == "已输入"


@pytest.mark.parametrize("operation", ["send", "approve"])
def test_exception_releases_busy_lock(page, monkeypatch, operation):
    def fail(*args):
        raise RuntimeError("模拟连接中断")

    monkeypatch.setattr(coach.runtime, "run", fail)
    monkeypatch.setattr(coach.runtime, "approve", fail)
    updates = list(page._on_send("检查") if operation == "send" else page._on_allow())
    assert not page._busy
    assert updates[-1][6]["interactive"] is True
    assert "模拟连接中断" in frame_html(updates[-1][1])
    assert page._turn_lock.acquire(blocking=False)
    page._turn_lock.release()


def test_clear_restores_empty_state_and_clears_input(page):
    page.items.append({"type": "user", "text": "之前的任务"})
    previous_session = page.session
    page.session.pending = [{"id": "old", "name": "type_text", "args": {}}]
    page.session.pending_at = 123
    page.session.stalled = True
    page.session.steps_used = 9
    page.session.repeated_results = {"old": 3}
    page.session.question = {"id": "old-question", "question": "此前的问题？", "options": [{"label": "一"}, {"label": "二"}]}
    page._push(force=True, snapshot=True)
    result = list(page._on_clear())[-1]
    assert page.items == []
    assert page.session.id != previous_session.id
    assert page.session.pending is None
    assert page.session.pending_at == 0
    assert page.session.steps_used == 0
    assert not page.session.stalled
    assert not page.session.repeated_results
    assert page.session.question is None
    assert not page._render_cache
    assert result[4]["value"] == ""
    assert result[10]["visible"] is True
    assert result[11]["visible"] is True
    assert result[12]["visible"] is False and result[18] == ""
    assert frame_messages(result[1]) == {}


def test_component_events_share_queue_and_do_not_expose_demo(page):
    with gr.Blocks() as blocks:
        page.on_building_ui()
        page.on_register_events()
    assert len(page._outputs) == 21
    assert page._outputs[1] is page.stream and page.transcript not in page._outputs
    assert page._outputs[18] is page.question_id
    assert not page.question_id.stateful
    ids = {item.elem_id for item in blocks.blocks.values() if hasattr(item, "elem_id")}
    assert {"le-coach-welcome", "le-coach-suggestions", "le-coach-suggest-env", "le-coach-suggest-files",
            "le-coach-suggest-window", "le-coach-approve", "le-coach-composer", "le-coach-stream",
            "le-coach-question", "le-coach-question-copy", *{f"le-coach-option-{index}" for index in range(4)}}.issubset(ids)
    assert "le-desktop-coach" not in ids
    events = [item for item in blocks.fns.values() if item.fn == page._on_send]
    assert len(events) == 2
    assert {item.concurrency_id for item in events} == {"desktop-coach"}
    assert all(item.concurrency_limit == 1 for item in events)
    options = [item for item in blocks.fns.values() if isinstance(item.fn, partial) and item.fn.func == page._select_option]
    assert {item.fn.args for item in options} == {(0,), (1,), (2,), (3,)}
    assert all(item.inputs == [page.question_id] and item.outputs == page._outputs for item in options)
    assert all(item.concurrency_id == "desktop-coach" and item.concurrency_limit == 1 for item in options)
    css = (Path(coach.__file__).resolve().parents[1] / "assets" / "coach.css").read_text(encoding="utf-8")
    assert re.search(r'#le-coach-stream\s*\{[^}]*display:\s*none', css)


def test_render_escapes_untrusted_text_and_literal_fence_markers(page):
    page.items = [{"type": "ai", "text": '<script>alert(1)</script>\n§999§\n[x](https://a.test/"onclick="alert(1))'}]
    rendered = page._render()
    assert "<script>" not in rendered
    assert '"onclick=' not in rendered
    assert "§999§" in rendered


def test_code_uses_shared_highlighting_and_copy_button(page):
    page.items = [{"type": "ai", "text": "执行：\n```python\nprint('hello')\n```"}]
    rendered = page._render()
    assert 'class="le-code-block"' in rendered
    assert 'class="le-code-copy"' in rendered
    assert '<span aria-live="polite">复制</span>' in rendered
    assert "hello" in rendered


def test_tool_titles_match_registered_environment_and_search_tools(page):
    page.items = [{"type": "tool", "name": name, "status": "run"}
                  for name in ("inspect_learning_environment", "search_text", "search_web")]
    rendered = page._render()
    assert "检查学习环境" in rendered
    assert "查找文件内容" in rendered
    assert "搜索公开网页" in rendered


def test_compact_tool_summary_keeps_parameters_inside_disclosure(page):
    page.items = [{"type": "tool", "name": "run_command", "call_id": "cmd-1", "status": "ok",
                   "args": {"command": "private-command-marker", "cwd": "private-directory-marker"},
                   "output": "command-result-marker", "ms": 2040}]
    rendered = page._render()
    summary = re.search(r'<summary class="le-tool-head">(.*?)</summary>', rendered, re.S).group(1)
    assert "执行命令" in summary and "已完成" in summary and "2.0s" in summary
    assert "private-command-marker" not in summary and "private-directory-marker" not in summary
    assert "command-result-marker" not in summary
    assert "private-command-marker" in rendered and "private-directory-marker" in rendered
    assert "command-result-marker" in rendered
    assert not re.search(r'<details\b[^>]*\bopen(?:[ =>])', rendered)


def test_approval_contains_complete_escaped_operation(page):
    content = '<img src=x onerror="alert(1)">' + "long-content-" * 60
    rendered = page._approve_text([{"name": "write_file", "args": {
        "path": "test.txt", "content": content, "append": False,
    }}])
    assert "查看完整操作内容" in rendered
    assert '<img ' not in rendered
    assert "&lt;img" in rendered
    assert "long-content-" * 60 in rendered
    assert "append&quot;: false" in rendered


def test_native_question_renders_options_and_choice_resumes_with_label(page, monkeypatch):
    question, requests, records = question_model(monkeypatch, page)
    updates = list(page._on_send("我想学点东西"))
    final = updates[-1]
    question_id = final[18]
    assert final[12]["visible"] and question["question"] in final[13]
    assert final[14] == gr.update(visible=True, interactive=True, variant="secondary", value="整理表格\n从已有文件开始")
    assert final[15] == gr.update(visible=True, interactive=True, variant="secondary", value="编写程序")
    assert final[16]["visible"] and final[17]["visible"]
    assert final[17]["value"] == "自己填写"
    assert len(requests) == 1 and question_id == page.session.question["id"]
    assert not any(item.get("text") == question["question"] for item in page.items)
    answer_updates = list(page._on_option(0, question_id))
    assert requests[1][-1] == {"role": "user", "content": "整理表格"}
    assert page.session.question is None
    assert answer_updates[-1][12]["visible"] is False and answer_updates[-1][18] == ""
    question_index = next(index for index, item in enumerate(page.items) if item.get("text") == question["question"])
    assert page.items[question_index]["type"] == "ai"
    assert page.items[question_index + 1] == {"type": "user", "text": "整理表格"}
    answers = [details for event, details in records if event == "agent_question_answered"]
    assert len(answers) == 1 and answers[0]["question_id"] == question_id and answers[0]["answer"] == "整理表格"


def test_question_accepts_free_text_without_forcing_a_listed_option(page, monkeypatch):
    question, requests, records = question_model(monkeypatch, page)
    list(page._on_send("请一步步引导我"))
    answer = "我想整理照片，不是表格或编程。"
    updates = list(page._on_send(answer))
    assert requests[1][-1] == {"role": "user", "content": answer}
    assert page.session.question is None
    assert updates[-1][12]["visible"] is False
    assert sum(item.get("text") == question["question"] for item in page.items) == 1
    assert sum(event == "agent_question_answered" for event, _ in records) == 1


@pytest.mark.parametrize("index, supplied_id", [(0, "old-question"), (-1, "current-question"), (2, "current-question")])
def test_old_question_or_invalid_option_cannot_answer_current_question(page, monkeypatch, index, supplied_id):
    page.session.question = {"id": "current-question", "question": "当前的问题？", "options": [{"label": "一"}, {"label": "二"}]}
    original = dict(page.session.question)
    monkeypatch.setattr(coach.runtime, "run", lambda *args: pytest.fail("Stale or invalid options must be rejected before runtime"))
    updates = list(page._on_option(index, supplied_id))
    assert page.session.question == original and page.items == []
    assert updates[-1][18] == "current-question" and updates[-1][12]["visible"]
    assert not page._busy and page._turn_lock.acquire(blocking=False)
    page._turn_lock.release()


def test_duplicate_choice_while_busy_or_after_answer_is_ignored(page, monkeypatch):
    question, requests, records = question_model(monkeypatch, page)
    list(page._on_send("帮我选个起点"))
    question_id = page.session.question["id"]
    first = page._on_option(0, question_id)
    first_update = next(first)
    assert page._busy and all(not first_update[index]["interactive"] for index in range(14, 18))
    list(page._on_option(1, question_id))
    assert len(requests) == 1
    list(first)
    list(page._on_option(1, question_id))
    assert len(requests) == 2 and page.session.question is None
    assert sum(item.get("type") == "user" and item.get("text") == "整理表格" for item in page.items) == 1
    assert not any(item.get("type") == "user" and item.get("text") == "编写程序" for item in page.items)
    assert sum(item.get("text") == question["question"] for item in page.items) == 1
    assert sum(event == "agent_question_answered" for event, _ in records) == 1


def test_question_heading_escapes_untrusted_html(page):
    page.session.question = {"id": "question-1", "question": '<img src=x onerror="alert(1)">',
                             "options": [{"label": "一"}, {"label": "二"}]}
    updates = page._push(force=True, snapshot=True)
    assert "<img " not in updates[13] and "&lt;img" in updates[13]
    assert updates[18] == "question-1"


def test_settled_history_markdown_is_parsed_once_during_many_deltas(page, monkeypatch):
    calls = Counter()
    original = coach._markdown

    def markdown(text):
        calls[text] += 1
        return original(text)

    monkeypatch.setattr(coach, "_markdown", markdown)
    settled = [f"settled-message-{index} " + "history " * 80 for index in range(60)]
    page.items = [{"type": "ai", "text": text} for text in settled]
    page._push(force=True, snapshot=True)
    page.items.append({"type": "ai", "text": "", "live": True})
    for index in range(12):
        page.items[-1]["text"] = f"streamed-answer-{index}"
        page._push(force=True)
    page._push(force=True)
    page._push(force=True, snapshot=True)
    assert all(calls[text] == 1 for text in settled)
    assert sum(calls.values()) == len(settled) + 12


def test_frames_are_self_contained_escaped_json_and_unchanged_controls_are_skipped(page):
    page.items = [{"type": "ai", "text": f"settled-history-{index}: " + "x" * 2000} for index in range(40)]
    snapshot = page._push(force=True, snapshot=True)
    page.items.append({"type": "ai", "text": "current-answer-1", "live": True})
    frame_one = page._push(force=True)
    page.items[-1]["text"] = "current-answer-2"
    frame_two = page._push(force=True)
    unchanged = page._push(force=True)
    settled = frame_messages(snapshot[1])
    for frame in (frame_one, frame_two):
        assert len(frame) == 21
        messages = frame_messages(frame[1])
        assert len(messages) == len(settled) + 1
        assert all(messages[key] == value for key, value in settled.items())
        assert "<div data-message-id=" not in frame[1]
        assert all(value == gr.skip() for index, value in enumerate(frame) if index != 1)
    assert "current-answer-2" in frame_html(frame_two[1]) and "current-answer-1" not in frame_html(frame_two[1])
    assert frame_messages(unchanged[1]) == frame_messages(frame_two[1])
    recovered = page._push(force=True, snapshot=True)
    assert frame_messages(recovered[1]) == frame_messages(frame_two[1])


def test_skipping_initial_frames_still_recovers_user_assistant_and_tool_history(page, monkeypatch):
    def stream(session, text):
        yield {"kind": "step"}
        yield {"kind": "delta", "text": "正在检查已有环境。"}
        yield {"kind": "tool_start", "call_id": "read-1", "name": "system_info", "args": {}}
        yield {"kind": "tool_end", "call_id": "read-1", "name": "system_info", "args": {},
               "output": "环境已确认", "ok": True, "ms": 10}

    monkeypatch.setattr(coach.runtime, "run", stream)
    updates = list(page._on_send("请帮我检查环境"))
    delivered = updates[2:]
    tool_frame = next(row[1] for row in delivered if 'data-status="ok"' in frame_html(row[1]))
    recovered = frame_messages(tool_frame)
    assert list(recovered) == [f"{page.session.id}-{index}" for index in range(3)]
    assert "请帮我检查环境" in list(recovered.values())[0]
    assert "正在检查已有环境。" in list(recovered.values())[1]
    assert "环境已确认" in list(recovered.values())[2]
    assert 'data-call-id="read-1"' in list(recovered.values())[2]
    assert 'class="le-msg le-me"' in list(recovered.values())[0]

def test_thinking_status_is_visible_only_while_waiting(page):
    page.typing = True
    assert '正在思考如何指点' in page._render()
    assert 'role="status"' in page._render()
    list(page._consume(iter([{'kind': 'delta', 'text': '先确认你的目标。'}])))
    assert '正在思考如何指点' not in page._render()
    page.session.question = {'id': 'q1', 'question': '想学什么？', 'options': [{'label': '办公'}, {'label': '编程'}]}
    assert page._push(force=True, snapshot=True)[4]['placeholder'] == '写下你的回答，或补充具体情况…'


def test_question_selection_waits_for_confirmation(page, monkeypatch):
    _, requests, _ = question_model(monkeypatch, page)
    list(page._on_send("请引导我"))
    question_id = page.session.question["id"]
    updates = page._select_option(1, question_id)
    assert len(requests) == 1
    assert updates[15]["variant"] == "primary"
    assert updates[20]["interactive"]
    list(page._confirm_question("", question_id))
    assert requests[-1][-1]["content"] == "编写程序"


def test_fourth_answer_is_explicit_free_text_and_stale_safe(page, monkeypatch):
    _, requests, _ = question_model(monkeypatch, page)
    list(page._on_send("请引导我"))
    question_id = page.session.question["id"]
    updates = page._select_option(3, question_id)
    assert updates[19]["visible"] and len(requests) == 1
    list(page._confirm_question("我想整理照片", "old-question"))
    assert len(requests) == 1
    list(page._confirm_question("我想整理照片", question_id))
    assert requests[-1][-1]["content"] == "我想整理照片"
    assert page.session.question is None
