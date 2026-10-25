import json
import sqlite3
import time

import pytest

from learning_ext.action_learning import service as module
from learning_ext.action_learning.service import ActionLearning, Journal, validate_steps
from learning_ext.agent import guided_desktop as desktop


@pytest.fixture
def lesson(tmp_path, monkeypatch):
    steps = [dict(title=f"操作{i}", action="打开练习中的选项", check="看到选项已展开", hint="先找到选项名称", source_index=0) for i in range(4)]
    monkeypatch.setattr(module, "chat_json", lambda *a, **k: {"steps": steps})
    service = ActionLearning(Journal(tmp_path / "journal.sqlite"))
    state = service.start("alice", 1, dict(course="测试课程", lesson="课程原句：打开练习中的选项并检查状态。", practice="", goal="做练习"))
    return service, state


def events(service):
    with service.journal.connect() as db:
        return db.execute("SELECT event,details FROM events ORDER BY id").fetchall()


def test_journal_redacts_structured_secrets_before_storage(tmp_path):
    journal = Journal(tmp_path / "audit.sqlite")
    journal.record({"id": "test"}, "tool_result", response={
        "API-Key": "provider-secret", "nested": [{"password": "private-value", "access_token": "opaque-value"}],
        "total_tokens": 42, "version": "3.11.6",
    })
    with journal.connect() as db:
        stored = db.execute("SELECT details FROM events").fetchone()[0]
    assert all(secret not in stored for secret in ("provider-secret", "private-value", "opaque-value"))
    assert json.loads(stored)["response"]["total_tokens"] == 42
    assert json.loads(stored)["response"]["version"] == "3.11.6"


def test_resume_is_owner_node_and_content_scoped(lesson):
    service, state = lesson
    service.complete(state)
    service.move(state, 1)
    resumed = service.start("alice", 1, state["context"])
    assert resumed["id"] == state["id"]
    assert resumed["index"] == 1 and resumed["done"] == [0]
    assert resumed["pending"] is None
    for owner, node, content in (("bob",1,state["context"]),("alice",2,state["context"]),("alice",1,{**state["context"],"goal":"新目标"})):
        other = service.start(owner,node,content)
        assert other["id"] != state["id"]


def test_navigation_never_claims_mastery(lesson):
    service, state = lesson
    state["pending"] = {"nonce":"unused"}
    state["observation"] = {"window":{}}
    service.move(state, 99)
    assert state["index"] == 3 and state["done"] == []
    assert state["pending"] is None and state["observation"] is None
    service.move(state, -99)
    assert state["index"] == 0
    service.complete(state)
    service.complete(state)
    assert state["done"] == [0]
    assert json.loads(events(service)[-1][1])["verified"] is False


def test_bad_model_output_rejected_without_saving(tmp_path, monkeypatch):
    service = ActionLearning(Journal(tmp_path / "journal.sqlite"))
    monkeypatch.setattr(module, "chat_json", lambda *a, **k: {"steps":[]})
    with pytest.raises(ValueError):
        service.start("alice",1,{"lesson":"原句"})
    assert events(service)[-1][0] == "decompose_failed"
    with service.journal.connect() as db:
        assert db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0


def test_steps_must_be_grounded_in_lesson(lesson):
    _, state = lesson
    bad = json.loads(json.dumps(state["steps"]))
    bad[0]["source"] = "不存在的原句"
    with pytest.raises(ValueError):
        validate_steps({"steps":bad},"课程原句")
    bad[0]["source"] = "课程原句"
    bad[0]["action"] = "a" * 2401
    with pytest.raises(ValueError):
        validate_steps({"steps":bad},"课程原句")


def test_ai_uses_full_context_and_current_step_only(lesson, monkeypatch):
    service, state = lesson
    service.move(state, 2)
    captured = {}
    def chat(prompt, **kwargs):
        captured.update(json.loads(prompt))
        return "先展开菜单"
    monkeypatch.setattr(module, "chat", chat)
    assert service.help(state,"怎么做") == "先展开菜单"
    assert captured["context"] == state["context"]
    assert captured["current"] == state["steps"][2]


def make_pending(service, state, monkeypatch):
    window = dict(hwnd=1,pid=2,started=3,title="练习窗口")
    item = dict(key="1.2",name="学习选项",type="CheckBox",action="toggle")
    state["observation"] = dict(window=window,items=[item],observed=time.time())
    monkeypatch.setattr(desktop,"highlight",lambda *a:None)
    monkeypatch.setattr(desktop,"stop_highlight",lambda *a:None)
    service.prepare_operation(state,item)
    assert state["pending"]


@pytest.mark.parametrize("reason",["unapproved","expired","step_changed","node_changed"])
def test_invalid_approval_does_not_operate(lesson,monkeypatch,reason):
    service,state = lesson
    make_pending(service,state,monkeypatch)
    calls=[]
    monkeypatch.setattr(desktop,"operate",lambda *a:calls.append(a))
    if reason == "expired": state["pending"]["expires"] = 0
    if reason == "step_changed": state["index"] += 1
    if reason == "node_changed": state["node"] += 1
    with pytest.raises(ValueError): service.execute(state,reason != "unapproved")
    assert calls == [] and state["pending"] is None
    assert events(service)[-1][0] == "operation_denied"


def test_approval_is_single_use_and_failures_logged(lesson,monkeypatch):
    service,state = lesson
    make_pending(service,state,monkeypatch)
    calls=[]
    monkeypatch.setattr(desktop,"operate",lambda *a: calls.append(a) or {"message":"已发送操作"})
    assert service.execute(state,True) == "已发送操作"
    with pytest.raises(ValueError): service.execute(state,True)
    assert len(calls) == 1
    assert "operation_approved" in [event for event,_ in events(service)]
    assert "operation_result" in [event for event,_ in events(service)]
    make_pending(service,state,monkeypatch)
    def fail(*args): raise ValueError("窗口已变化")
    monkeypatch.setattr(desktop,"operate",fail)
    with pytest.raises(ValueError): service.execute(state,True)
    assert state["pending"] is None
    assert events(service)[-1][0] == "operation_failed"


def test_logging_failure_prevents_execution(lesson,monkeypatch):
    service,state = lesson
    make_pending(service,state,monkeypatch)
    calls=[]
    monkeypatch.setattr(desktop,"operate",lambda *a:calls.append(a))
    def fail(*a,**k): raise OSError("disk full")
    monkeypatch.setattr(service.journal,"record",fail)
    with pytest.raises(OSError): service.execute(state,True)
    assert not calls and state["pending"] is None


def test_observation_expires_and_no_guessing(lesson,monkeypatch):
    service,state = lesson
    make_pending(service,state,monkeypatch)
    state["observation"]["observed"] = 0
    with pytest.raises(ValueError): service.prepare_operation(state,state["observation"]["items"][0])
    assert state["pending"] is None


def test_window_identity_and_protected_actions(monkeypatch):
    original = dict(hwnd=1,pid=2,started=3,title="练习窗口")
    monkeypatch.setattr(desktop,"windows",lambda:[{**original,"pid":99}])
    with pytest.raises(ValueError): desktop.validate_window(original)
    for name in ("删除文件","支付","提交表单","Run","安装"):
        assert not desktop.can_operate(original,dict(name=name,type="Button",action="invoke"))
    assert desktop.can_operate(original,dict(name="阅读",type="TabItem",action="select"))
    assert not desktop.can_operate(original,dict(name="终端输入",type="Edit",action="invoke"))


def test_logs_redact_secrets(lesson):
    service,state = lesson
    service.journal.record(state,"help",text="api_key=secret123 Bearer abcdefghijklmnop sk-abcdefghijklmnop")
    detail = events(service)[-1][1]
    assert "secret123" not in detail and "abcdefghijklmnop" not in detail
    assert isinstance(json.loads(detail),dict)


def test_session_scope_required(lesson):
    service,state = lesson
    for node,owner in ((2,"alice"),(1,"bob")):
        with pytest.raises(ValueError): service.require(state,node,owner)


def test_source_indices_resolve_to_real_quotes():
    item = dict(title="展开选项",action="打开练习中的选项",check="看到选项",hint="找选项名称",source_index=0)
    assert validate_steps({"steps":[item]*4},"真实原文",["真实原文"])[0]["source"] == "真实原文"
    for index in (-1,2,True,"0"):
        with pytest.raises(ValueError):
            validate_steps({"steps":[{**item,"source_index":index}]*4},"真实原文",["真实原文"])


def test_card_escapes_model_html(lesson):
    from learning_ext.pages.action_learning import action_card
    _,state = lesson
    state["steps"][0]["action"] = '<img src=x onerror="alert(1)">'
    output = action_card(state)
    assert '<img' not in output and '&lt;img' in output


def test_locate_cannot_invent_targets(lesson,monkeypatch):
    service,state = lesson
    make_pending(service,state,monkeypatch)
    monkeypatch.setattr(module,"chat_json",lambda *a,**k:{"key":"invented","reason":"click"})
    with pytest.raises(ValueError): service.locate(state)
    state["observation"]["observed"] = 0
    with pytest.raises(ValueError): service.locate(state)


def test_entry_streams_focus_loading_before_generating(lesson, monkeypatch):
    from learning_ext.pages.action_learning import ActionLearningPanel
    service, state = lesson
    panel = ActionLearningPanel(None)
    panel.service = service
    called = []
    monkeypatch.setattr(panel, "context", lambda *args: state["context"])
    original = service.start
    monkeypatch.setattr(service, "start", lambda *args: called.append(True) or original(*args))
    updates = panel.dispatch("start", None, 1, 1, "alice", None, None, "", False, False)
    loading = next(updates)
    assert loading[1]["visible"] is True and 'data-le-focus="loading"' in loading[5]
    assert not called
    ready = next(updates)
    assert ready[0]["active"] and 'data-le-step-active="true"' in ready[5]
    assert ready[0]["index"] == 0 and len(called) == 1


def test_failed_decomposition_restores_reading_with_retry(lesson, monkeypatch):
    from learning_ext.pages.action_learning import ActionLearningPanel
    panel = ActionLearningPanel(None)
    panel.service = lesson[0]
    def unavailable(*args):
        raise ValueError("本节内容还在准备，正文就绪后再拆解。")
    monkeypatch.setattr(panel, "context", unavailable)
    updates = list(panel.dispatch("start", None, 1, 1, "alice", None, None, "", False, False))
    assert updates[-1][1]["visible"] is False
    assert "还在准备" in updates[-1][2]
    assert updates[-1][5] == ""


def test_leaving_loading_state_restores_reading():
    from learning_ext.pages.action_learning import ActionLearningPanel
    panel = ActionLearningPanel(None)
    result = panel.handle("close", {"loading": True}, 1, 1, "alice", None, None, "", False, False)
    assert result[1]["visible"] is False and result[5] == ""


def test_direct_screen_entry_opens_current_step_assistant(lesson, monkeypatch):
    from learning_ext.pages.action_learning import ActionLearningPanel
    service, state = lesson
    panel = ActionLearningPanel(None)
    panel.service = service
    state.update(active=True, assist=False)
    monkeypatch.setattr(desktop, "windows", lambda: [{"hwnd": 10, "title": "练习", "process": "fixture"}])
    monkeypatch.setattr(desktop, "stop_highlight", lambda *args: None)
    result = panel.handle("screen", state, 1, 1, "alice", None, None, "", False, False)
    assert result[8]["visible"] and result[14]["visible"]
    assert result[0]["index"] == 0 and result[0]["pending"] is None
    assert events(service)[-1][0] == "screen"


def test_action_entry_precedes_long_lesson_in_flex_layout():
    from pathlib import Path
    import re
    assets = Path(__file__).resolve().parents[1] / "learning_ext/assets"
    action_css = (assets / "action_learning.css").read_text(encoding="utf-8")
    workbench_css = (assets / "workbench.css").read_text(encoding="utf-8")
    entry = re.search(r"#le-center-col\s*>\s*#le-learning-mode\s*\{([^}]+)", action_css).group(1)
    body = re.search(r"#le-center-col\s*>\s*#le-content-tabs\s*>\s*\.tabitem\s*\{([^}]+)", workbench_css).group(1)
    order = lambda rule: int(re.search(r"order\s*:\s*(\d+)", rule).group(1))
    assert order(entry) < order(body)
