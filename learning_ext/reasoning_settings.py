from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

STORE_FILE = Path(__file__).resolve().parent.parent / "ktem_app_data" / "reasoning_settings.json"
PURPOSES = {
    "qa": "提问与解释",
    "lesson": "课程与实操内容",
    "summary": "总结与复习卡",
    "planning": "学习路线与调整",
    "coach": "动手学指导",
    "assessment": "测验与评估",
    "polish": "文字润色",
    "default": "其他任务",
}
MODES = {"auto", "on", "off"}
_LOCK = threading.RLock()
_LOG = logging.getLogger(__name__)


def load():
    with _LOCK:
        try:
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("purposes"), dict):
                raise ValueError("无法识别思考设置")
            values = data["purposes"]
        except FileNotFoundError:
            values = {}
        except (OSError, ValueError, TypeError, AttributeError):
            _LOG.exception("读取思考设置失败，使用模型默认行为")
            values = {}
        return {
            key: values.get(key)
            if isinstance(values.get(key), str) and values[key] in MODES
            else "auto"
            for key in PURPOSES
        }


def save(values):
    if set(values) != set(PURPOSES) or any(
        not isinstance(value, str) or value not in MODES for value in values.values()
    ):
        raise ValueError("思考设置无效，请重新选择。")
    with _LOCK:
        STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="reasoning-", dir=STORE_FILE.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "purposes": values}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, STORE_FILE)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return "已保存，下次请求生效。"


def capability(base_url, model):
    host = (urlsplit(str(base_url or "")).hostname or "").lower()
    name = str(model or "").lower().split("/")[-1]
    if host in {"open.bigmodel.cn", "api.z.ai", "opencode.ai"} and name.startswith("glm-5.3"):
        return "forced"
    if host in {"open.bigmodel.cn", "api.z.ai"} and name.startswith(("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")):
        return "thinking"
    if host == "api.deepseek.com" and name.startswith(("deepseek-flash", "deepseek-v4", "deepseek-chat", "deepseek-reasoner")):
        return "thinking"
    if host.startswith("dashscope") and host.endswith("aliyuncs.com"):
        if name.startswith("qwen3.7-plus") or "thinking" in name or name.startswith("qwq"):
            return "forced"
        if name.startswith(("qwen3", "qwen-plus", "qwen-flash", "qwen-turbo")) and "instruct" not in name and "omni" not in name:
            return "enable_thinking"
    return "unknown"


def capability_note(base_url, model):
    kind = capability(base_url, model)
    if kind == "forced":
        fallback = "仅降低到最低强度" if str(model).lower().split("/")[-1].startswith("glm-5.3") else "仍使用平台要求的思考模式"
        return f"**{model} 必须开启思考。** 选择关闭时，{fallback}，不会真正关闭。要完全关闭，请换用支持开关的模型。"
    if kind == "unknown":
        return "当前平台或模型尚未确认思考开关协议，设置会保留；请求沿用平台默认，避免发送不兼容参数。"
    return "当前模型支持思考开关。是否展示思考过程仍由对话菜单单独控制。"


def apply(params, base_url, purpose="default", mode=None):
    if purpose not in PURPOSES:
        raise ValueError(f"未知模型任务用途：{purpose}")
    mode = load()[purpose] if mode is None else mode
    if mode not in MODES:
        raise ValueError("思考模式必须为 auto、on 或 off")
    result = dict(params)
    if mode == "auto":
        return result
    model = str(result.get("model", ""))
    kind = capability(base_url, model)
    if kind == "unknown":
        _LOG.info("思考开关未适配，保留平台默认：model=%s purpose=%s requested=%s", model, purpose, mode)
        return result
    extra = dict(result.get("extra_body") or {})
    if kind == "forced":
        if model.lower().split("/")[-1].startswith("glm-5.3"):
            extra["thinking"] = {**extra.get("thinking", {}), "type": "enabled"}
            if mode == "off":
                result["reasoning_effort"] = "low"
        if mode == "off":
            _LOG.info("模型必须思考，无法关闭：model=%s purpose=%s", model, purpose)
    else:
        if mode == "off":
            result.pop("reasoning_effort", None)
            extra.pop("reasoning_effort", None)
        if kind == "enable_thinking":
            extra["enable_thinking"] = mode == "on"
        else:
            extra["thinking"] = {**extra.get("thinking", {}), "type": "enabled" if mode == "on" else "disabled"}
    if extra:
        result["extra_body"] = extra
    return result
