import json

import pytest

from learning_ext.agent import runtime, tools


@pytest.fixture
def session(monkeypatch):
    records = []
    monkeypatch.setattr(runtime.Session, "record", lambda self, event, **details: records.append((event, details)))
    instance = runtime.Session()
    instance.records = records
    return instance


def question_call(call_id="question-1", **args):
    payload = {"question": "你想先完成哪件事？", "options": [
        {"label": "整理表格", "description": "从一张现有表格开始"}, {"label": "编写程序"}, {"label": "整理文档"}]}
    payload.update(args)
    return {"id": call_id, "name": "ask_user", "args": payload, "raw": json.dumps(payload, ensure_ascii=False)}


def model(monkeypatch, replies):
    responses, requests = iter(replies), []

    def stream(session):
        requests.append({"messages": list(session.messages), "question": session.question})
        text, calls = next(responses)
        session.messages.append({"role": "assistant", "content": text, **({"tool_calls": [
            {"id": call["id"], "type": "function", "function": {
                "name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False)}}
            for call in calls]} if calls else {})})
        yield from []
        return text, calls

    monkeypatch.setattr(runtime, "_model_stream", stream)
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: pytest.fail("A question must not execute other tools"))
    return requests


def assert_paired_history(session):
    pending = []
    for message in session.messages:
        if message.get("role") == "tool":
            assert message["tool_call_id"] in pending
            pending.remove(message["tool_call_id"])
        else:
            assert not pending
            pending = [call["id"] for call in message.get("tool_calls", [])]
    assert not pending


def test_question_is_native_tool_and_pauses_with_a_paired_receipt(session, monkeypatch):
    assert not tools.tool_needs_approval("ask_user")
    spec = tools.TOOLS["ask_user"].to_openai()["function"]["parameters"]
    assert spec["properties"]["options"]["minItems"] == 3
    assert spec["properties"]["options"]["maxItems"] == 3
    requests = model(monkeypatch, [("", [question_call()])])
    events = list(runtime.run(session, "我想学习一些东西"))
    assert len(requests) == 1 and session.pending is None
    assert events[-1] == {"kind": "question", **session.question}
    assert len(session.question["id"]) == 32
    assert session.question["options"][0]["label"] == "整理表格"
    assert session.machine.phase == "completing"
    receipt = json.loads(session.messages[-1]["content"])
    assert receipt["status"] == "awaiting_user" and receipt["operation_authorized"] is False
    assert receipt["id"] == session.question["id"]
    assert_paired_history(session)


@pytest.mark.parametrize("answer", ["整理表格", "我想先学会给照片分类，不学表格或编程。"])
def test_choice_or_free_answer_resumes_as_the_actual_user_message(session, monkeypatch, answer):
    requests = model(monkeypatch, [("", [question_call()]), ("先选一张练习用的文件。", [])])
    list(runtime.run(session, "请引导我"))
    question_id = session.question["id"]
    list(runtime.run(session, answer))
    assert session.question is None
    assert requests[1]["question"] is None
    assert requests[1]["messages"][-1] == {"role": "user", "content": answer}
    answers = [details for event, details in session.records if event == "agent_question_answered"]
    assert len(answers) == 1 and answers[0]["question_id"] == question_id and answers[0]["answer"] == answer
    assert_paired_history(session)


def test_choice_never_authorizes_the_next_action(session, monkeypatch):
    action = {"id": "write-1", "name": "run_command", "args": {"command": "echo hello"}}
    model(monkeypatch, [("", [question_call()]), ("准备执行", [action])])
    list(runtime.run(session, "帮我学电脑"))
    events = list(runtime.run(session, "允许安装"))
    assert session.question is None and session.pending == [action]
    assert events[-1]["kind"] == "need_approval"


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_empty_answer_remains_paused_without_another_model_call(session, monkeypatch, answer):
    requests = model(monkeypatch, [("", [question_call()])])
    list(runtime.run(session, "引导我"))
    previous = list(session.messages)
    events = list(runtime.run(session, answer))
    assert events == [{"kind": "question", **session.question}]
    assert len(requests) == 1 and session.messages == previous
    assert not any(event == "agent_question_answered" for event, _ in session.records)


@pytest.mark.parametrize("question_first", [True, False])
def test_question_batch_skips_control_read_and_plan_tools_with_paired_receipts(session, monkeypatch, question_first):
    question = question_call()
    others = [{"id": "write-1", "name": "run_command", "args": {"command": "echo hello"}},
              {"id": "read-1", "name": "system_info", "args": {}},
              {"id": "plan-1", "name": "update_plan", "args": {"steps": ["探测整机"]}}]
    calls = [question, *others] if question_first else [*others, question]
    model(monkeypatch, [("", calls)])
    events = list(runtime.run(session, "我想开始学习"))
    assert events[-1]["kind"] == "question"
    assert session.pending is None and session.plan is None
    skipped = [event for event in events if event["kind"] == "tool_end"]
    assert {event["call_id"] for event in skipped} == {"write-1", "read-1", "plan-1"}
    assert all(event["denied"] and not event["ok"] for event in skipped)
    assert_paired_history(session)


@pytest.mark.parametrize("args", [
    {"question": ""},
    {"question": "问题一？\n问题二？"},
    {"options": [{"label": "唯一选项"}]},
    {"options": [{"label": str(index)} for index in range(5)]},
    {"options": [{"label": "Excel"}, {"label": " excel "}]},
    {"options": ["表格", "编程"]},
    {"options": [{"label": "表格", "description": False}, {"label": "编程"}]},
    {"unexpected": True},
])
def test_invalid_question_is_rejected_without_unresolved_tools(session, monkeypatch, args):
    model(monkeypatch, [("", [question_call(**args)])])
    events = list(runtime.run(session, "引导我"))
    assert events[-1]["kind"] == "notice" and "问题未显示" in events[-1]["text"]
    assert session.question is None and session.pending is None
    assert_paired_history(session)


def test_multiple_questions_in_one_batch_are_not_presented(session, monkeypatch):
    model(monkeypatch, [("", [question_call("question-1"), question_call("question-2")])])
    events = list(runtime.run(session, "引导我"))
    assert events[-1]["kind"] == "notice" and "每次只提出一个问题" in events[-1]["text"]
    assert session.question is None
    assert_paired_history(session)


def test_new_question_has_new_identity_and_reset_clears_waiting_state(session, monkeypatch):
    requests = model(monkeypatch, [("", [question_call("question-1")]), ("", [question_call("question-2")])])
    list(runtime.run(session, "引导我"))
    previous_id = session.question["id"]
    list(runtime.run(session, "我想先换一个方向"))
    assert session.question["id"] != previous_id and len(requests) == 2
    session.reset()
    assert session.question is None and session.pending is None
    assert session.messages == [{"role": "system", "content": runtime.SYSTEM_PROMPT}]


@pytest.mark.parametrize("failure_at", ["agent_question_asked", "agent_question_answered"])
def test_question_journal_failure_clears_waiting_state_and_repairs_history(session, monkeypatch, failure_at):
    requests = model(monkeypatch, [("", [question_call()])])
    original = session.record
    if failure_at == "agent_question_answered":
        list(runtime.run(session, "引导我"))

    def record(event, **details):
        if event == failure_at:
            raise OSError("Question journal unavailable")
        original(event, **details)

    monkeypatch.setattr(session, "record", record)
    events = list(runtime.run(session, "学习表格"))
    assert events[-1]["kind"] == "error"
    assert session.question is None and session.pending is None
    assert len(requests) == 1
    assert_paired_history(session)
