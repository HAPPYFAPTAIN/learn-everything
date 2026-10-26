from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid
from datetime import datetime
from contextlib import contextmanager

from learning_ext.llm import chat, chat_json
from .prompts import DECOMPOSE, HELP, LOCATE
from learning_ext.practice.environment import adapt_steps
from learning_ext.environment_agent import explore_environment

LOG_PATH = Path(__file__).resolve().parents[2] / "output/runtime/action-learning.sqlite3"


def redact(text):
    text = str(text)
    text = re.sub(r"(?i)(?:sk-|Bearer\s+)[\w.\-]{8,}", "[已隐藏密钥]", text)
    return re.sub(r"(?i)((?:api[_ -]?key|token|password|密码|密钥)\s*[:=]\s*)[^\s,;]+", r"\1[已隐藏]", text)


def scrub(value):
    if isinstance(value, dict):
        sensitive = {"apikey", "token", "accesstoken", "refreshtoken", "password", "passwd", "secret", "clientsecret", "authorization", "cookie", "setcookie", "密码", "密钥"}
        return {key: "[已隐藏]" if re.sub(r"[\s_-]", "", str(key)).lower() in sensitive else scrub(item)
                for key, item in value.items()}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return redact(value) if isinstance(value, str) else value


class Journal:
    def __init__(self, path=LOG_PATH):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, owner TEXT, node INTEGER, fingerprint TEXT, data TEXT, updated REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, time REAL, session TEXT, node INTEGER, step INTEGER, event TEXT, details TEXT)")
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, state, event, **details):
        details.setdefault("trace_id", state.get("id", ""))
        with self.connect() as db:
            db.execute("INSERT INTO events(time,session,node,step,event,details) VALUES(?,?,?,?,?,?)", (
                time.time(), state.get("id", ""), state.get("node"), state.get("index", 0), event,
                json.dumps(scrub(details), ensure_ascii=False),
            ))

    def save(self, state):
        data = {key: state[key] for key in ("id", "owner", "node", "fingerprint", "steps", "index", "done")}
        data.update({key: state[key] for key in ("environment", "skipped", "resume_index") if key in state})
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?,?,?)", (
                state["id"], state["owner"], state["node"], state["fingerprint"],
                json.dumps(data, ensure_ascii=False), time.time(),
            ))

    def resume(self, owner, node, fingerprint):
        with self.connect() as db:
            row = db.execute("SELECT data FROM sessions WHERE owner=? AND node=? AND fingerprint=? ORDER BY updated DESC LIMIT 1", (owner, node, fingerprint)).fetchone()
        return json.loads(row[0]) if row else None


def source_excerpts(context):
    source = context["lesson"] + "\n\n" + context.get("practice", "")
    return [block.strip()[:700] for block in re.split(r"\n\s*\n", source) if len(block.strip()) > 12]


def validate_steps(result, source, sources=None):
    steps = result.get("steps") if isinstance(result, dict) else None
    if not isinstance(steps, list) or not 4 <= len(steps) <= 40:
        raise ValueError("拆解结果不完整，请重试。")
    clean = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("步骤格式无效，请重试。")
        if sources is not None:
            index = step.get("source_index")
            if type(index) is not int or not 0 <= index < len(sources):
                raise ValueError("有一步缺少原文依据，请重新拆解。")
            step = {**step, "source": sources[index]}
        item = {}
        for key, limit in (("title", 100), ("action", 2400), ("check", 600), ("hint", 1000), ("source", 1200)):
            value = step.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > limit:
                raise ValueError("步骤内容过长或缺少完成标准，请重试。")
            item[key] = value.strip()
        if item["source"] not in source:
            raise ValueError("有一步缺少原文依据，请重新拆解。")
        clean.append(item)
    return clean


class ActionLearning:
    def __init__(self, journal=None):
        self.journal = journal or Journal()

    def start(self, owner, node, context):
        fingerprint = hashlib.sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        state = self.journal.resume(owner, node, fingerprint)
        if state:
            state.update(context=context, pending=None, observation=None)
            self.journal.record(state, "resume")
            report = state.get("environment", {})
            try:
                age = time.time() - datetime.fromisoformat(report.get("checked_at", "")).timestamp()
            except (ValueError, TypeError):
                age = 301
            if not 0 <= age < 300 or report.get("engine") != "zcode-core-python":
                report = self.inspect_environment(state)
            else:
                self.journal.record(state, "environment_reused", age_seconds=round(age))
            self.apply_environment(state, report)
            return state
        state = dict(id=uuid.uuid4().hex, owner=owner, node=node, fingerprint=fingerprint,
                     context=context, index=0, done=[], pending=None, observation=None)
        self.journal.record(state, "decompose_started")
        try:
            report = self.inspect_environment(state)
            sources = source_excerpts(context)
            result = chat_json(json.dumps(dict(context=context, environment=report, sources=[dict(index=i,text=excerpt) for i,excerpt in enumerate(sources)]), ensure_ascii=False), system=DECOMPOSE, purpose="coach")
            state["steps"] = validate_steps(result, context["lesson"] + "\n" + context.get("practice", ""), sources)
        except Exception as exc:
            self.journal.record(state, "decompose_failed", error=type(exc).__name__)
            raise
        self.journal.save(state)
        self.journal.record(state, "decompose_completed", count=len(state["steps"]))
        self.apply_environment(state, report)
        return state

    def inspect_environment(self, state):
        return explore_environment(state["context"], planner=chat_json, session_id=state["id"],
                                   emit=lambda event, **details: self.journal.record(state, event, **details))

    def recheck_environment(self, state):
        self.revoke(state, "environment_recheck")
        self.apply_environment(state, self.inspect_environment(state))
        return state

    def apply_environment(self, state, report):
        state["resume_index"] = max(0, state["index"]) if state["index"] >= 0 else state.get("resume_index", 0)
        state["environment"] = report
        state["skipped"] = adapt_steps(state["steps"], report)
        if report["items"]:
            state["index"] = -1
        self.journal.record(state, "environment_checked", report=report)
        self.journal.record(state, "environment_steps_adapted", skipped=state["skipped"])
        self.journal.save(state)

    @staticmethod
    def next_index(state, delta):
        index = state["index"]
        skipped = state.get("skipped", {})
        if index == -1 and delta > 0:
            start = state.get("resume_index", 0)
            remaining = [i for i in range(start, len(state["steps"])) if str(i) not in skipped]
            if not remaining:
                remaining = [i for i in range(len(state["steps"])) if str(i) not in skipped]
            return remaining[0] if remaining else -1
        target = index + delta
        while 0 <= target < len(state["steps"]) and str(target) in skipped:
            target += 1 if delta > 0 else -1
        if target < 0 and state.get("environment", {}).get("items"):
            return -1
        return max(0, min(target, len(state["steps"])-1)) if not skipped else (target if 0 <= target < len(state["steps"]) else index)

    @staticmethod
    def require(state, node, owner):
        if not state or state.get("node") != node or state.get("owner") != owner:
            raise ValueError("课程已变化，请重新进入逐步行动。")

    def move(self, state, delta):
        state["pending"] = None
        state["observation"] = None
        state["index"] = self.next_index(state, delta)
        self.journal.save(state)
        self.journal.record(state, "navigate", direction=delta)
        return state

    def complete(self, state):
        if state["index"] < 0 or str(state["index"]) in state.get("skipped", {}):
            return state
        if state["index"] not in state["done"]:
            state["done"].append(state["index"])
        self.journal.save(state)
        self.journal.record(state, "self_reported_complete", verified=False)
        return state

    def hint(self, state):
        self.journal.record(state, "hint")
        if state["index"] < 0:
            return "已满足的安装与版本检查会自动跳过。项目目录、虚拟环境和动手练习仍需完成；安装后可点「重新检查环境」。"
        return state["steps"][state["index"]]["hint"]

    def help(self, state, question):
        if not str(question or "").strip():
            question = "我该怎么开始这一步？"
        self.journal.record(state, "ai_help_requested", question=question)
        current = state["steps"][state["index"]] if state["index"] >= 0 else dict(title="学习前的环境检查", action="确认已找到与尚未验证的工具", check="了解哪些重复准备会跳过")
        answer = chat(json.dumps(dict(context=state["context"], environment=state.get("environment"), current=current, question=question), ensure_ascii=False), system=HELP, purpose="coach")
        self.journal.record(state, "ai_help_result", answer=answer)
        return answer

    def locate(self, state):
        if state["index"] < 0:
            raise ValueError("进入具体行动后再使用屏幕引导。")
        observation = state.get("observation")
        if not observation or time.time() - observation["observed"] > 180:
            raise ValueError("先选择窗口并读取控件。")
        self.journal.record(state, "ai_locate_requested", window=observation["window"]["title"])
        result = chat_json(json.dumps(dict(context=state["context"], current=state["steps"][state["index"]], controls=observation["items"]), ensure_ascii=False), system=LOCATE, purpose="coach")
        key = result.get("key") if isinstance(result, dict) else None
        item = next((item for item in observation["items"] if item["key"] == key), None)
        self.journal.record(state, "ai_locate_result", key=key, found=bool(item))
        if not item:
            raise ValueError("还不能准确定位。可以手动选择控件，或让 AI 解释这一步。")
        return item

    def prepare_operation(self, state, item):
        if state["index"] < 0:
            raise ValueError("进入具体行动后再使用屏幕引导。")
        from learning_ext.agent import guided_desktop as desktop
        state["pending"] = None
        observation = state.get("observation")
        if not observation or item not in observation["items"] or time.time() - observation["observed"] > 180:
            raise ValueError("控件列表已过期，请重新读取。")
        window = observation["window"]
        self.journal.record(state, "highlight_requested", window=window["title"], control=item["name"])
        desktop.highlight(state["id"], window, item)
        self.journal.record(state, "highlight_started", control=item["name"], duration=6)
        if desktop.can_operate(window, item):
            state["pending"] = dict(window=window, item=item, index=state["index"], node=state["node"],
                                    expires=time.time()+90, nonce=uuid.uuid4().hex)
        return state

    def execute(self, state, approved):
        from learning_ext.agent import guided_desktop as desktop
        pending = state.get("pending")
        state["pending"] = None
        if not approved or not pending or pending["index"] != state["index"] or pending["node"] != state["node"] or pending["expires"] < time.time():
            self.journal.record(state, "operation_denied", approved=bool(approved))
            raise ValueError("本次授权无效或已过期。请先圈出目标，再授权这一次操作。")
        self.journal.record(state, "operation_approved", nonce=pending["nonce"], window=pending["window"]["title"], control=pending["item"]["name"], action=pending["item"]["action"])
        desktop.stop_highlight(state["id"])
        try:
            result = desktop.operate(pending["window"], pending["item"])
        except Exception as exc:
            self.journal.record(state, "operation_failed", error=type(exc).__name__)
            raise
        self.journal.record(state, "operation_result", result=result, lesson_verified=False)
        return result["message"]

    def revoke(self, state, event="authorization_revoked"):
        from learning_ext.agent import guided_desktop as desktop
        state["pending"] = None
        state["observation"] = None
        desktop.stop_highlight(state["id"])
        self.journal.record(state, event)
