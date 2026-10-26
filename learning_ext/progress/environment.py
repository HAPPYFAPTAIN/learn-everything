from __future__ import annotations

from copy import deepcopy
import json
import logging
import platform
import re
import threading
import time

from markdown_it import MarkdownIt

from learning_ext.practice.environment import inspect_environment, requirements, TOOLS

_CACHE = {}
_LOCK = threading.Lock()
_TTL = 300
_LOG = logging.getLogger(__name__)

ENVIRONMENT_RULES = """
本机检测证据优先于通用安装教程和旧环境清单。ready 表示该项检查通过，present 仅表示程序存在。
已满足版本要求的软件不再要求下载或重装：在开头明确告知跳过哪些安装，直接进入本节实际练习。
未确认、版本不符、检测失败的条件保留检查。软件存在不代表账号、插件、服务、项目依赖已经可用。
创建项目、虚拟环境、安装第三方库、运行脚本和成果验收必须保留。不得把整节课直接标记为已掌握。
只按本机系统给主操作流程，其他系统放折叠参考。不要把环境规划当作检测结果。
"""


def _headings(markdown):
    tokens = MarkdownIt().parse(markdown or "")
    return [(token, tokens[i + 1].content) for i, token in enumerate(tokens) if token.type == "heading_open"]


def environment_report(node, topic="", context=""):
    constraints = []
    for _, pattern, _ in TOOLS.values():
        constraints.extend(match.group() for match in re.finditer(
            r"(?:" + pattern + r")\s*(?:>=|<=|>|<|==|≥|≤)\s*\d+\.\d+(?:\.\d+)?|(?:" + pattern + r")\s*\d+\.\d+(?:\.\d+)?\s*(?:\+|及以上|以上|或更高)",
            node.description or "", re.I))
    names = [item["name"] for item in requirements(node.description or "")]
    scope = "\n".join([node.title, topic, context, *names, *constraints, *[title for _, title in _headings(node.description)]])
    wanted = requirements(scope)
    key = (node.project_id, json.dumps(wanted, sort_keys=True, ensure_ascii=False))
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and time.monotonic() - cached[0] < _TTL:
            return deepcopy(cached[1])
        try:
            report = inspect_environment(scope)
            report["system"] = platform.system()
        except Exception:
            _LOG.exception("课程环境检查失败 node#%s", node.id)
            report = {"items": [], "error": True}
        _CACHE[key] = (time.monotonic(), report)
        if len(_CACHE) > 128:
            _CACHE.pop(next(iter(_CACHE)))
    try:
        from learning_ext.action_learning.service import Journal
        Journal().record({"id": f"lesson-environment-{node.project_id}", "node": node.id},
                         "lesson_environment_checked", report=report)
    except Exception:
        _LOG.exception("课程环境检查记录失败")
    return deepcopy(report)


def generation_context(node, topic, context):
    report = environment_report(node, topic, context)
    return ("课程规划（不是检测证据）：\n" + (context or "无") +
            "\n本机只读检测结果：\n" + json.dumps(report, ensure_ascii=False) + ENVIRONMENT_RULES)


def adapt_reading(node, topic, content):
    if not re.search(r"环境|安装|配置|准备|入门", node.title):
        return content
    report = environment_report(node, topic)
    items = report.get("items", [])
    if not items and not report.get("error"):
        return content
    lines = ["## 开始前：本机环境", "", "> 按检测结果安排准备步骤，仅跳过已确认满足要求的重复安装。", "",
             "| 工具 | 检查结果 | 本节安排 |", "| --- | --- | --- |"]
    safe = lambda value: str(value or "").replace("|", "／").replace("\n", " ")
    for item in items:
        ready = item["status"] in {"ready", "present"}
        result = f'{item.get("version", "")} · ' + ("已验证" if item["status"] == "ready" else "已找到" if ready else "仍需检查")
        action = "跳过重复安装；保留实际运行与配置" if ready else item.get("detail", "请在对应步骤确认")
        lines.append(f'| {safe(item["name"])} | {safe(result)} | {safe(action)} |')
    if report.get("error"):
        lines.append("\n检测暂未完成，本次不跳过任何准备步骤。")
    lines += ["", "软件存在不代表扩展、账号或服务已经就绪；项目目录、虚拟环境和脚本练习照常保留。", ""]
    headings = _headings(content)
    body_lines = content.splitlines(keepends=True)
    replacements = []
    for index, (token, title) in enumerate(headings):
        title = re.sub(r"^(?:子主题|步骤)\s*\d+\s*[:：、.]\s*", "", title)
        if not re.fullmatch(r"(?:下载并)?安装\s*(?:Python|VS Code|Git|Node\.js)(?:\s*并验证)?", title, re.I):
            continue
        start = token.map[0]
        end = next((other.map[0] for other, _ in headings[index + 1:] if int(other.tag[1:]) <= int(token.tag[1:])), len(body_lines))
        section = "".join(body_lines[start:end])
        if re.search(r"扩展|插件|虚拟环境|pip\s+install|创建|编写|激活", section, re.I):
            continue
        needed = requirements(title)
        match = next((item for item in items if needed and item["key"] == needed[0]["key"] and item["status"] in {"ready", "present"}), None)
        if not match:
            continue
        replacements.append((start, end, "\n<details><summary>已具备，跳过重复安装 · " + safe(title) + "（查看参考）</summary>\n\n" + section + "\n</details>\n\n"))
    for start, end, replacement in reversed(replacements):
        body_lines[start:end] = [replacement]
    body = "".join(body_lines)
    title = re.match(r"\A# [^\n]+\n+", body)
    prefix = title.group() if title else ""
    return prefix + "\n".join(lines) + "\n" + body[len(prefix):]
