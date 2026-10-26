from __future__ import annotations

import json
import re

_DESKTOP_TOOLS = frozenset({"click_ui", "click_at", "press_keys", "type_text"})
_STRUCTURED_TOOLS = frozenset({"search_files", "search_text", "search_web", "inspect_learning_environment"})
_RESULT_TIMES = frozenset({"checked_at", "observed_at", "retrieved_at", "elapsed_ms", "duration_ms"})
_READ_UI_HEADER = re.compile(
    r"\A(window=[^\r\n]+\r?\nobservation=)[a-f0-9]{20}"
    r"(?=（90 秒内单次使用，操作后重新观察）\r?\n共 \d+ 个控件。"
    r"所有点击和键盘操作必须传完整 window 和 observation。优先按名称 click_ui：\r?\n)"
)


class ToolOutput(str):
    def __new__(cls, text, *, ok=True):
        result = super().__new__(cls, text)
        result.ok = ok
        return result


def tool_succeeded(output):
    if isinstance(output, ToolOutput):
        return output.ok
    text = str(output or "").strip()
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None
    if isinstance(data, dict) and (data.get("ok") is False or data.get("error")):
        return False
    code = re.match(r"退出码\s+(-?\d+)", text)
    if code:
        return int(code[1]) == 0
    return not re.match(
        r"(?:已拒绝|未执行|未知工具|参数不匹配|工具报错|执行出错|路径不存在|文件不存在|"
        r"没有权限|当前没有|没找到|读不到|找不到|MCP\s*(?:工具不存在|服务器已|.*失败)|"
        r"[^\n：:]{0,32}(?:失败|不可用|出错|不提供|没有可识别))", text
    )


def model_tool_output(output, limit=8000):
    if type(limit) is not int or limit < 64:
        raise ValueError("Tool context limit must be an integer of at least 64 characters")
    text = str(output)
    if len(text) <= limit:
        return text
    try:
        data = json.loads(text)
    except ValueError:
        suffix = "\n…结果过长，已截断；请缩小查询范围。"
        return text[:limit - len(suffix)] + suffix
    if isinstance(data, dict):
        data.update(truncated=True, context_truncated=True)
        for key in ("matches", "results", "evidence"):
            if isinstance(data.get(key), list):
                while data[key] and len(json.dumps(data, ensure_ascii=False)) > limit:
                    data[key].pop()
        compact = json.dumps(data, ensure_ascii=False)
        if len(compact) <= limit:
            return compact
    fallback = {"ok": tool_succeeded(output), "truncated": True,
                "excerpt": "", "next_action": "缩小查询范围以获取完整结果"}
    dump = lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(dump(fallback)) > limit:
        fallback.pop("next_action")
    lower, upper = 0, min(len(text), limit)
    while lower < upper:
        middle = (lower + upper + 1) // 2
        fallback["excerpt"] = text[:middle]
        if len(dump(fallback)) <= limit:
            lower = middle
        else:
            upper = middle - 1
    fallback["excerpt"] = text[:lower]
    return dump(fallback)


def stable_arguments(tool_name, args):
    if not isinstance(args, dict):
        return args
    if tool_name not in _DESKTOP_TOOLS or not isinstance(args.get("observation"), str):
        return dict(args)
    if not re.fullmatch(r"[a-f0-9]{20}", args["observation"]):
        return dict(args)
    return {**args, "observation": "<observation>"}


def stable_result(output, *, tool_name=None):
    text = str(output)
    if tool_name == "read_ui":
        return _READ_UI_HEADER.sub(r"\1<observation>", text, count=1)
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict) and tool_name in _STRUCTURED_TOOLS:
        data = {key: value for key, value in data.items() if key not in _RESULT_TIMES}
        if tool_name == "inspect_learning_environment":
            data.pop("trace_id", None)
    return data
