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


@pytest.mark.parametrize("chunks", [
    [],
    [NS(choices=[NS(finish_reason="stop", delta=None)])],
    [NS(choices=[NS(delta=NS(reasoning_content="Private reasoning"))]),
     NS(choices=[NS(finish_reason="stop", delta=None)])],
    [NS(choices=[NS(delta=NS(content=" \n"))]),
     NS(choices=[NS(finish_reason="stop", delta=None)])],
])
def test_empty_model_reply_has_visible_notice_without_poisoning_history(session, monkeypatch, chunks):
    from learning_ext.llm import client

    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter(chunks))
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    events = list(runtime._model_stream(session))
    assert events[-1]["kind"] == "notice"
    assert "未获取到有效回复" in events[-1]["text"]
    assert session.messages == [{"role": "system", "content": runtime.SYSTEM_PROMPT}]


@pytest.mark.parametrize("finish_reason", ["length", "content_filter"])
@pytest.mark.parametrize("arguments", ["{}", '{"partial":'])
def test_incomplete_tool_response_never_executes_or_enters_history(session, monkeypatch, finish_reason, arguments):
    from learning_ext.llm import client

    chunks = [NS(choices=[NS(delta=NS(content="Partial explanation",
                                    tool_calls=[NS(index=0, id="read-1", function=NS(name="system_info", arguments=arguments))]))]),
              NS(choices=[NS(finish_reason=finish_reason, delta=None)])]
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter(chunks))
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: pytest.fail("An incomplete response cannot execute tools"))
    events = list(runtime.run(session, "Inspect the environment"))
    assert events[-1]["kind"] == "error"
    assert "本轮没有执行操作" in events[-1]["message"]
    assert any(event == {"kind": "delta", "text": "Partial explanation"} for event in events)
    assert session.machine.phase == "error" and session.pending is None
    assert session.messages[-1] == {"role": "assistant", "content": "Partial explanation"}
    assert not any(message.get("tool_calls") or message.get("role") == "tool" for message in session.messages)


@pytest.mark.parametrize("finish_reason, explanation", [("length", "长度上限"), ("content_filter", "过滤")])
def test_incomplete_text_reply_preserves_text_and_explains_termination(session, monkeypatch, finish_reason, explanation):
    from learning_ext.llm import client

    chunks = [NS(choices=[NS(delta=NS(content="Partial reply"))]),
              NS(choices=[NS(finish_reason=finish_reason, delta=NS())])]
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter(chunks))
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    events = list(runtime.run(session, "Explain the current step"))
    assert events[-1]["kind"] == "notice"
    assert explanation in events[-1]["text"] and "未获取完整回复" in events[-1]["text"]
    assert {"kind": "delta", "text": "Partial reply"} in events
    assert session.messages[-1] == {"role": "assistant", "content": "Partial reply"}
    assert session.machine.phase == "completing"


def test_streamed_tool_reasoning_is_preserved_for_followup_but_not_displayed(session, monkeypatch):
    from learning_ext.llm import client

    requests = []
    replies = iter([
        [NS(choices=[NS(delta=NS(reasoning_content="Private "))]),
         NS(choices=[NS(delta=NS(reasoning_content="reasoning", content="Checking",
                                tool_calls=[NS(index=0, id="read-1", function=NS(name="system_info", arguments="{"))]))]),
         NS(choices=[NS(delta=NS(tool_calls=[NS(index=0, function=NS(arguments="}"))]))])],
        [NS(choices=[NS(delta=NS(content="Ready"))])],
    ])

    def stream(messages, specs):
        requests.append(messages)
        return iter(next(replies))

    monkeypatch.setattr(client, "stream_tool_response", stream)
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: "checked")
    events = list(runtime.run(session, "Inspect the environment"))
    assistant = next(message for message in requests[1] if message.get("tool_calls"))
    assert assistant["reasoning_content"] == "Private reasoning"
    assert assistant["content"] == "Checking"
    assert assistant["tool_calls"][0]["function"]["arguments"] == "{}"
    assert any(message.get("tool_call_id") == "read-1" for message in requests[1])
    assert [event["text"] for event in events if event["kind"] == "delta"] == ["Checking", "Ready"]
    assert all("Private" not in str(event) and "reasoning_content" not in event for event in events)


def test_tool_reasoning_from_failed_stream_is_cleared_before_retry(session, monkeypatch):
    from learning_ext.llm import client

    attempts = []

    def stream(messages, specs):
        attempts.append(messages)
        if len(attempts) == 1:
            yield NS(choices=[NS(delta=NS(reasoning_content="Discard this partial reasoning"))])
            raise TimeoutError("stream timed out")
        yield NS(choices=[NS(delta=NS(reasoning_content="Keep this reasoning",
                                     tool_calls=[NS(index=0, id="read-1", function=NS(name="system_info", arguments="{}"))]))])

    monkeypatch.setattr(client, "stream_tool_response", stream)
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    monkeypatch.setattr(runtime.time, "sleep", lambda *args: None)
    assert list(runtime._model_stream(session)) == []
    assert len(attempts) == 2
    assert session.messages[-1]["reasoning_content"] == "Keep this reasoning"


@pytest.mark.parametrize("reasoning", [None, ""])
def test_tool_responses_without_reasoning_do_not_add_empty_field(session, monkeypatch, reasoning):
    from learning_ext.llm import client

    delta = NS(tool_calls=[NS(index=0, id="read-1", function=NS(name="system_info", arguments="{}"))])
    if reasoning is not None:
        delta.reasoning_content = reasoning
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter([NS(choices=[NS(delta=delta)])]))
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    assert list(runtime._model_stream(session)) == []
    assert "reasoning_content" not in session.messages[-1]


def test_missing_tool_ids_are_unique_across_responses_and_keep_history_paired(session, monkeypatch):
    from learning_ext.llm import client

    replies = iter([
        [NS(choices=[NS(delta=NS(tool_calls=[
            NS(index=0, function=NS(name="system_info", arguments="{}")),
            NS(index=1, function=NS(name="list_windows", arguments="{}")),
            NS(index=2, id="upstream-call", function=NS(name="observe_screen", arguments="{}")),
        ]))])],
        [NS(choices=[NS(delta=NS(tool_calls=[NS(index=0, function=NS(name="system_info", arguments="{}"))]))])],
        [NS(choices=[NS(delta=NS(content="Ready"))])],
    ])
    monkeypatch.setattr(client, "stream_tool_response", lambda *args: iter(next(replies)))
    monkeypatch.setattr(runtime, "build_tool_specs", lambda: [])
    monkeypatch.setattr(runtime, "execute_tool", lambda name, args: f"Checked {name}")
    events = list(runtime.run(session, "Inspect the environment"))
    call_ids = [call["id"] for message in session.messages for call in message.get("tool_calls", [])]
    assert len(call_ids) == len(set(call_ids)) == 4
    assert call_ids[2] == "upstream-call"
    assert call_ids[0].rsplit("_", 1)[0] == call_ids[1].rsplit("_", 1)[0]
    assert call_ids[0].rsplit("_", 1)[0] != call_ids[3].rsplit("_", 1)[0]
    assert [message["tool_call_id"] for message in session.messages if message["role"] == "tool"] == call_ids
    assert [event["call_id"] for event in events if event["kind"] == "tool_start"] == call_ids
    assert [event["call_id"] for event in events if event["kind"] == "tool_end"] == call_ids


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


@pytest.mark.parametrize("output", ["退出码 1 · 用时 0.1s\n失败", '工具报错：not found', '{"ok": false, "error": "not_configured"}'])
def test_tool_failures_are_not_reported_as_success(session, monkeypatch, output):
    model(monkeypatch, [("准备", [call()]), ("请检查", [])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: output)
    list(runtime.run(session, "当前步骤"))
    events = list(runtime.approve(session, True))
    assert not next(e for e in events if e["kind"] == "tool_end")["ok"]
    assert not next(data for event, data in session.records if event == "agent_tool_completed")["ok"]


def test_repeated_failure_stops_before_third_call(session, monkeypatch):
    search = {"id": "s1", "name": "search_files", "args": {"root": "x", "pattern": "*"}}
    model(monkeypatch, [("查找", [search]), ("重试", [{**search, "id": "s2"}])])
    executions = []
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: executions.append(args) or '{"ok":false,"error":"unreadable"}')
    events = list(runtime.run(session, "找文件"))
    assert len(executions) == 2
    assert events[-1]["kind"] == "notice" and "没有新结果" in events[-1]["text"]


def test_budget_does_not_reset_after_each_approval(session, monkeypatch):
    monkeypatch.setattr(runtime, "MAX_STEPS", 2)
    model(monkeypatch, [("第一步", [call()]), ("第二步", [{**call(), "id": "c2"}])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: "退出码 0")
    list(runtime.run(session, "当前步骤"))
    list(runtime.approve(session, True))
    events = list(runtime.approve(session, True))
    assert session.steps_used == 2
    assert events[-1]["kind"] == "notice" and session.machine.phase == "completing"


def test_large_structured_results_remain_valid_json():
    import json
    from learning_ext.agent.outcomes import model_tool_output, stable_result
    report = {"ok": True, "checked_at": "now", "matches": [{"path": f"file-{i}", "snippet": "内容" * 300} for i in range(60)]}
    content = model_tool_output(json.dumps(report, ensure_ascii=False), limit=1600)
    result = json.loads(content)
    assert len(content) <= 1600 and result["context_truncated"]
    assert 0 < len(result["matches"]) < 60
    assert stable_result('{"ok":true,"checked_at":"first"}', tool_name="search_files") == stable_result('{"ok":true,"checked_at":"second"}', tool_name="search_files")


def test_compaction_preserves_later_goal_and_user_constraints(session):
    instructions = ["先学 Python", "改为学习 Excel，只使用已安装的软件", "不要修改原始表格"]
    for instruction in instructions:
        session.messages.append({"role": "user", "content": instruction})
        for index in range(8):
            session.messages.extend([
                {"role": "assistant", "tool_calls": [{"id": f"{instruction}-{index}"}]},
                {"role": "tool", "tool_call_id": f"{instruction}-{index}", "content": "读取结果"},
            ])
        session.compact(6)
    assert [message["content"] for message in session.messages if message["role"] == "user"] == instructions


@pytest.mark.parametrize("failure_at", ["agent_tool_started", "agent_tool_completed", "agent_approval_resolved"])
def test_journal_failure_stops_actions_and_keeps_tool_history_valid(session, monkeypatch, failure_at):
    calls = []
    model(monkeypatch, [("准备", [call()])])
    monkeypatch.setattr(runtime, "execute_tool", lambda *args: calls.append(args) or "退出码 0\n动作已完成")
    list(runtime.run(session, "当前步骤"))
    original = session.record

    def fail_record(event, **details):
        if event == failure_at:
            raise OSError("test audit storage unavailable")
        original(event, **details)

    monkeypatch.setattr(session, "record", fail_record)
    events = list(runtime.approve(session, True))
    assert events[-1]["kind"] == "error"
    assert session.machine.phase == "error" and session.pending is None
    outputs = [message for message in session.messages if message["role"] == "tool"]
    assert len(outputs) == 1 and outputs[0]["tool_call_id"] == "c1"
    if failure_at == "agent_tool_completed":
        assert len(calls) == 1 and "动作已完成" in outputs[0]["content"]
        assert any(event["kind"] == "tool_end" for event in events)
    else:
        assert not calls
    assert "不要重复执行" in session.messages[-1]["content"]


def test_current_plan_reaches_model_after_old_tool_history_is_compacted(session, monkeypatch):
    import json
    from learning_ext.llm import client
    session.plan = {"steps": ["准备副本", "在副本中练习", "检查结果"], "index": 1}
    original = list(session.messages)
    requests = []
    monkeypatch.setattr(client, "stream_tool_response", lambda messages, specs: requests.append(messages) or iter([]))
    list(runtime._model_stream(session))
    assert json.dumps(session.plan, ensure_ascii=False) in requests[0][1]["content"]
    assert "不授予执行权限" in requests[0][1]["content"]
    assert session.messages == original
