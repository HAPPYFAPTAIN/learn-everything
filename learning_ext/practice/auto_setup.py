"""AI 自动环境配置 service。

流程：
    1. AI 读取环境清单 Markdown → 生成可在 Windows 执行的命令脚本
    2. 用户确认后，逐条执行命令，实时返回输出
"""

from __future__ import annotations

import logging
import json
import os
import subprocess
from typing import Iterator

from learning_ext.llm import chat_json
from learning_ext.agent.prompts import SETUP
from learning_ext.environment_agent.service import audited_exploration
from learning_ext.practice.environment import skip_reason

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = SETUP


def generate_install_commands(
    env_checklist_md: str, background: str = ""
) -> list[dict]:
    """让 AI 把环境清单转成可执行命令列表。"""
    report = audited_exploration({"lesson": env_checklist_md, "background": background}, planner=chat_json)
    prompt = json.dumps({"checklist": env_checklist_md, "background": background, "environment": report}, ensure_ascii=False)
    result = chat_json(prompt, system=SYSTEM_PROMPT, purpose="coach")
    if isinstance(result, dict) and "commands" in result:
        result = result["commands"]
    if not isinstance(result, list):
        raise ValueError("配置方案格式无效，请重新生成。")
    if any(not isinstance(item, dict) or not isinstance(item.get("cmd"), str) or not item["cmd"].strip() for item in result):
        raise ValueError("配置方案包含无效命令。")
    return [item for item in result if not skip_reason({"title": str(item.get("desc", "")), "action": item["cmd"]}, report)]


def run_command_streaming(cmd: str) -> Iterator[str]:
    """流式执行单条 PowerShell 命令，yield 实时输出。"""
    full_cmd = [
        "powershell",
        "-NoProfile",
        "-Command",
        "$ErrorActionPreference = 'Stop'; " + cmd + "; if ($LASTEXITCODE) { exit $LASTEXITCODE }",
    ]
    try:
        proc = subprocess.Popen(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=os.environ.copy(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                yield line + "\n"
        proc.wait()
        rc = proc.returncode
        if rc == 0:
            yield "[退出码 0 ✓]\n"
        else:
            yield f"[退出码 {rc} ⚠️ 可能失败]\n"
    except FileNotFoundError:
        yield "[错误] 找不到 powershell\n"
    except Exception as e:
        yield f"[错误] {e}\n"


def run_all_commands(commands: list[dict], *, outcome: dict | None = None) -> Iterator[str]:
    """流式执行多条命令，yield 带步骤标记的实时输出。"""
    total = len(commands)
    if outcome is not None:
        outcome.update(total=total, success=0, failed=0)
    if total == 0:
        yield "✅ 该学习主题无需配置环境，可直接开始学习。\n"
        return

    yield f"共 {total} 条命令，开始执行...\n\n"
    success = 0
    failed = 0
    for i, c in enumerate(commands, 1):
        cmd = str(c.get("cmd") or "").strip() if isinstance(c, dict) else ""
        if not cmd:
            failed += 1
            yield f"[错误] 第 {i} 条配置命令无效，未执行。\n"
            continue
        desc = c.get("desc", "")
        danger = c.get("danger", "low")
        warn = " ⚠️高危" if danger == "high" else ""
        yield f"━━━ [{i}/{total}] {desc}{warn} ━━━\n"
        yield f"$ {cmd}\n"
        last = ""
        try:
            for line in run_command_streaming(cmd):
                yield line
                last = line
            if "退出码 0" in last:
                success += 1
            else:
                failed += 1
        except Exception as e:
            yield f"[异常] {e}\n"
            failed += 1
        yield "\n"

    if outcome is not None:
        outcome.update(success=success, failed=failed)
    yield f"━━━ 完成 ━━━\n✅ 成功 {success} | ⚠️ 失败/警告 {failed} | 共 {total}\n"
    if failed == 0:
        yield "\n🎉 环境配置完成！可以开始学习了。\n"
    else:
        yield "\n💡 部分命令失败，可能：① 需管理员权限；② 软件已装（可忽略）；③ 网络。检查上方输出。\n"
