"""动手学的安全边界。

两层：
1. 硬拦截：几条「一条命令就能毁掉机器」的模式，直接拒绝，不进入审批。
2. 软确认：会修改磁盘/系统的工具（执行命令、写文件、开应用等）默认要求用户点「允许」。
   runtime 在非自动模式下会停在 need_approval 事件上等用户决定。
"""

from __future__ import annotations

import re

# 需要用户确认的工具（其余为只读，直接执行）
APPROVAL_TOOLS = {
    "run_command",
    "write_file",
    "open_path",
    "clipboard_set",
    # 真正动鼠标键盘/启动程序，属于「接管电脑」，默认都要点头
    "click_at",
    "click_ui",
    "press_keys",
    "type_text",
    "launch_app",
}

# 无论是否自动模式，一律拒绝
_BLOCKED = [
    (r"\bformat\s+[a-z]:", "格式化磁盘"),
    (r"\bdiskpart\b", "磁盘分区操作"),
    (r"\bbcdedit\b", "修改启动配置"),
    (r"\bcipher\s+/w", "擦除磁盘空闲空间"),
    (r"\bvssadmin\s+delete\s+shadows", "删除卷影副本"),
    (r"\breg\s+delete\s+hklm", "删除系统注册表项"),
    (r"remove-item\s+.*-recurse.*\b[a-z]:\\(?:\s|$|\*)", "递归删除盘符根目录"),
    (r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s+/(\s|$)", "递归删除根目录"),
    (r"\b(del|erase)\s+/[sf].*[a-z]:\\(\s|$|\*)", "递归删除盘符根目录"),
    (r"\brd\s+/s\s+/q\s+[a-z]:\\(\s|$)", "递归删除盘符根目录"),
    (r"\bshutdown\b|\bstop-computer\b|\brestart-computer\b", "关机或重启"),
    (r":\(\)\s*\{.*\};?\s*:", "fork 炸弹"),
    (r"\.\s*\|.*\s*&\s*$", "自我复制式管道"),
]


def blocked_reason(command: str) -> str | None:
    """命中硬拦截就返回原因，否则 None。"""
    low = (command or "").lower()
    for pattern, reason in _BLOCKED:
        if re.search(pattern, low):
            return reason
    return None


def needs_approval(tool_name: str) -> bool:
    return tool_name in APPROVAL_TOOLS
