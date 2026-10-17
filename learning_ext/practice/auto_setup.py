"""AI 自动环境配置 service。

流程：
    1. AI 读取环境清单 Markdown → 生成可在 Windows 执行的命令脚本
    2. 用户确认后，逐条执行命令，实时返回输出
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Iterator

from learning_ext.llm import chat_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位 Windows 环境配置专家。用户有一份学习环境配置清单，你的任务是把它转换成**可以在 Windows 命令行直接执行**的脚本。

输出格式：严格返回一个 JSON 数组，每个元素是一条命令：
[
  {
    "cmd": "实际执行的命令 (PowerShell 命令)",
    "desc": "这条命令做什么 (中文一句话)",
    "danger": "low | medium | high"
  }
]

规则：
1. 只输出真正必要的命令，跳过"可选"项
2. 优先用 winget（Windows 包管理器）装软件，格式：winget install --id <ID> -e --accept-source-agreements --accept-package-agreements
3. 常见软件 winget ID：Python=Python.Python.3.12, Node.js=OpenJS.NodeJS.LTS, Git=Git.Git, VSCode=Microsoft.VisualStudioCode, Docker=Docker.DockerDesktop, Rust=Rustlang.Rustup, Go=GoLang.Go, Java=EclipseAdoptium.Temurin.21.JDK
4. 设置环境变量用 PowerShell: [Environment]::SetEnvironmentVariable('Name','Value','User')
5. 创建目录: New-Item -ItemType Directory -Force -Path <path>
6. danger=high 标记可能破坏现有环境的命令 (如卸载、覆盖系统变量)
7. 如果清单是理论类主题无需环境配置，返回空数组 []
8. 只返回 JSON，不要任何解释、不要 markdown 代码块标记"""


def generate_install_commands(
    env_checklist_md: str, background: str = ""
) -> list[dict]:
    """让 AI 把环境清单转成可执行命令列表。"""
    prompt = f"""请把以下环境配置清单转换成 Windows 可执行命令。

【学习者背景】{background or "未知"}

【环境配置清单】
{env_checklist_md}

请输出命令 JSON 数组。"""
    result = chat_json(prompt, system=SYSTEM_PROMPT)
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "commands" in result:
        return result["commands"]
    return []


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
