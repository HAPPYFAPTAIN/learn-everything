import copy
import json

import pytest

from learning_ext.agent.outcomes import model_tool_output, stable_arguments, stable_result


def ui_result(token, *, window="编辑器", button="下一步"):
    return (
        f"window={window}\nobservation={token}（90 秒内单次使用，操作后重新观察）\n"
        "共 1 个控件。所有点击和键盘操作必须传完整 window 和 observation。优先按名称 click_ui：\n"
        f"Button「{button}」坐标 100,90"
    )


def test_same_ui_fingerprint_ignores_only_generated_observation_header():
    first, second = ui_result("a" * 20), ui_result("b" * 20)
    assert stable_result(first, tool_name="read_ui") == stable_result(second, tool_name="read_ui")
    assert "a" * 20 in first and "b" * 20 in second
    assert stable_result(first, tool_name="read_ui") != stable_result(ui_result("c"*20, button="取消"), tool_name="read_ui")
    assert stable_result(first, tool_name="read_ui") != stable_result(ui_result("c"*20, window="另一窗口"), tool_name="read_ui")


@pytest.mark.parametrize("tool_name", [None, "read_file", "search_text", "mcp__reader"])
def test_arbitrary_tool_body_is_not_rewritten_as_ui_evidence(tool_name):
    text = ui_result("a" * 20)
    assert stable_result(text, tool_name=tool_name) == text


@pytest.mark.parametrize("text", [
    "用户写下 observation=" + "a" * 20,
    "prefix\n" + ui_result("a" * 20),
    ui_result("a" * 19),
    ui_result("a" * 20).replace("90 秒", "别的正文"),
    "window=编辑器\nobservation=" + "a" * 20 + "\n普通正文",
])
def test_ui_normalization_requires_exact_machine_header(text):
    assert stable_result(text, tool_name="read_ui") == text


def test_observation_lookalikes_inside_control_names_are_preserved():
    body = "observation=" + "b" * 20
    result = stable_result(ui_result("a" * 20, button=body), tool_name="read_ui")
    assert body in result


@pytest.mark.parametrize("tool_name", ["click_at", "click_ui", "press_keys", "type_text"])
def test_desktop_arguments_ignore_nonce_without_mutating_execution(tool_name):
    first = {"window": "编辑器", "observation": "a" * 20, "text": "observation=" + "a" * 20,
             "context": {"observation": "a" * 20}, "x": 100}
    original = copy.deepcopy(first)
    second = {**first, "observation": "b" * 20}
    assert stable_arguments(tool_name, first) == stable_arguments(tool_name, second)
    assert first == original
    assert stable_arguments(tool_name, first)["context"] == original["context"]
    assert stable_arguments(tool_name, first) != stable_arguments(tool_name, {**second, "window": "另一个"})
    assert stable_arguments(tool_name, first) != stable_arguments(tool_name, {**second, "x": 200})


@pytest.mark.parametrize("tool_name,observation", [("search_text", "a" * 20), ("mcp__service", "a" * 20),
                                                  ("click_ui", "user's note"), ("click_ui", "a" * 21)])
def test_other_arguments_and_invalid_credentials_keep_their_meaning(tool_name, observation):
    args = {"observation": observation, "checked_at": "query date"}
    assert stable_arguments(tool_name, args) == args


def test_machine_timestamps_and_environment_trace_do_not_hide_evidence_changes():
    report = {"ok": True, "checked_at": "first", "engine": "zcode-core-python", "trace_id": "trace-one",
              "items": [{"name": "Python", "version": "3.12", "observed_at": "quoted source date"}]}
    changed = {**report, "checked_at": "second", "trace_id": "trace-two"}
    first = stable_result(json.dumps(report), tool_name="inspect_learning_environment")
    assert first == stable_result(json.dumps(changed), tool_name="inspect_learning_environment")
    assert first["items"][0]["observed_at"] == "quoted source date"
    changed["items"] = [{**report["items"][0], "version": "3.13"}]
    assert first != stable_result(json.dumps(changed), tool_name="inspect_learning_environment")
    assert stable_result(json.dumps(report), tool_name="mcp__data") == report
    assert stable_result(json.dumps(report)) == report


@pytest.mark.parametrize("limit", [64, 96, 256, 1600])
@pytest.mark.parametrize("value", [
    {"ok": False, "payload": "\x00\n\t\\\"" * 3000},
    ["\x00\\\"" * 3000],
    "\x00\n\"" * 3000,
])
def test_json_fallback_respects_serialized_budget_even_with_escaping(value, limit):
    text = json.dumps(value, ensure_ascii=False)
    result = model_tool_output(text, limit=limit)
    assert len(result) <= limit
    parsed = json.loads(result)
    assert parsed["truncated"]
    if isinstance(value, dict):
        assert parsed["ok"] is False
    assert json.loads(text) == value


def test_structured_truncation_preserves_complete_ranked_entries():
    original = {"ok": True, "matches": [{"path": f"文件{i}", "text": "正文"*100} for i in range(100)]}
    result = json.loads(model_tool_output(json.dumps(original, ensure_ascii=False), limit=1000))
    assert 0 < len(result["matches"]) < 100
    assert result["matches"] == original["matches"][:len(result["matches"])]
    assert result["context_truncated"] and result["truncated"]


def test_small_outputs_are_not_reformatted():
    source = '{ "ok": true, "matches": [] }'
    assert model_tool_output(source) == source


@pytest.mark.parametrize("limit", [True, 0, 63, 64.0])
def test_invalid_context_budget_is_explicit(limit):
    with pytest.raises(ValueError):
        model_tool_output("content", limit=limit)
