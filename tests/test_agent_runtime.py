import time
from types import SimpleNamespace as NS

import pytest

from learning_ext.agent import runtime


@pytest.fixture
def session(monkeypatch):
    records = []
    monkeypatch.setattr(runtime.Session, "record", lambda self, event, **details: records.append((event, details)))
    instance = runtime.Session()
    instance.records = records
    return instance


def model(monkeypatch, replies):
    responses = iter(replies)
    def stream(session):
        text, calls = next(responses)
        if text or calls:
            session.messages.append({"role": "assistant", "content": text, **({"tool_calls": [{"id": call["id"]} for call in calls]} if calls else {})})
        yield from []
        return text, calls
    monkeypatch.setattr(runtime, "_model_stream", stream)


def call():
    return {"id": "c1", "name": "run_command", "args": {"command": "echo hello"}, "raw": '{"command":"echo hello"}'}


def test_each_write_requires_approval_even_if_old_auto_flag_set(session, monkeypatch):
    session.auto = True
    operations = []
    model(monkeypatch, [("准备输出", [call()]), ("检查结果", [])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: operations.append(args) or "退出码 0")
    events = list(runtime.run(session, "帮我做当前一步"))
    assert events[-1]["kind"] == "need_approval" and not operations
    list(runtime.approve(session, True))
    assert len(operations) == 1 and session.pending is None
    list(runtime.approve(session, True))
    assert len(operations) == 1


@pytest.mark.parametrize("mode", ["expired", "modified", "denied"])
def test_invalid_authorization_cannot_execute(session, monkeypatch, mode):
    model(monkeypatch, [("准备", [call()])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: pytest.fail("Unauthorized execution"))
    list(runtime.run(session, "当前步骤"))
    if mode == "expired": session.pending_at = time.monotonic()-91
    if mode == "modified": session.pending[0]["args"]["command"] = "changed command"
    events = list(runtime.approve(session, mode != "denied"))
    assert events[-1]["kind"] == "notice" and session.machine.phase == "completing"


def test_pending_operation_prevents_new_task_from_shifting_scope(session, monkeypatch):
    model(monkeypatch, [("准备", [call()])])
    list(runtime.run(session, "原任务"))
    before = list(session.messages)
    list(runtime.run(session, "换任务"))
    assert session.messages == before


def test_compaction_retains_task_and_tool_pairs(session):
    session.task = {"role": "user", "content": "学习目标"}
    session.messages += [session.task]
    for i in range(15):
        session.messages += [{"role": "assistant", "content": "", "tool_calls": [{"id": str(i)}]},
                             {"role": "tool", "tool_call_id": str(i), "content": "观察结果"}]
    session.compact(5)
    assert session.task in session.messages
    calls = set()
    for message in session.messages:
        calls.update(call["id"] for call in message.get("tool_calls", []))
        if message["role"] == "tool": assert message["tool_call_id"] in calls


@pytest.mark.parametrize("arguments", ["{broken", "[]"])
def test_malformed_tool_arguments_are_not_replaced_with_empty_defaults(session, monkeypatch, arguments):
    from learning_ext.llm import client
    chunks = [NS(choices=[NS(delta=NS(content=None, tool_calls=[NS(index=0, id="a", function=NS(name="run_command", arguments=arguments))]))])]
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter(chunks))
    events = list(runtime._model_stream(session))
    assert any(event["kind"] == "error" for event in events)
    assert len(session.messages) == 1


def test_empty_model_reply_does_not_poison_history(session, monkeypatch):
    from learning_ext.llm import client
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter([]))
    list(runtime._model_stream(session))
    assert session.messages == [{"role": "system", "content": runtime.SYSTEM_PROMPT}]


def test_multiple_mutations_are_not_bundled_under_one_approval(session, monkeypatch):
    model(monkeypatch, [("多项操作", [call(), {**call(), "id": "c2"}])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: pytest.fail("Batch executed"))
    events = list(runtime.run(session, "当前任务"))
    assert session.pending is None and events[-1]["kind"] == "notice"


def test_unknown_and_sensitive_tools_fail_closed():
    from learning_ext.agent.tools import tool_needs_approval
    assert tool_needs_approval("unregistered")
    assert tool_needs_approval("clipboard_get")
    assert tool_needs_approval("read_file")
    assert not tool_needs_approval("inspect_learning_environment")
