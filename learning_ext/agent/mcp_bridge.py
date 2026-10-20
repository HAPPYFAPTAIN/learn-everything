"""MCP 桥接：把外部 MCP 服务器的工具并入动手学的工具表。

配置文件（可选）：learning_ext/agent/mcp.json
    {
      "mcpServers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\\\Users"],
          "env": {}
        }
      }
    }

不配就只用内置工具；任何连接失败都静默降级（写进应用日志），不影响对话。
工具名统一成 mcp__<服务器>__<工具>，因为模型侧函数名只允许字母数字下划线短横线。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "mcp.json"
_CACHE: dict = {"ts": 0.0, "specs": [], "map": {}}
_TTL = 120.0
_LOADING = False


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("mcp.json 解析失败：%s", exc)
        return {}
    servers = data.get("mcpServers") or data.get("servers") or {}
    return servers if isinstance(servers, dict) else {}


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(text))[:40]


def _params(cfg: dict):
    from mcp import StdioServerParameters

    env = {**os.environ}
    env.update({str(k): str(v) for k, v in (cfg.get("env") or {}).items()})
    return StdioServerParameters(
        command=cfg.get("command", ""),
        args=[str(a) for a in (cfg.get("args") or [])],
        env=env,
    )


async def _list_one(cfg: dict, timeout: float = 25.0):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async def run():
        async with stdio_client(_params(cfg)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

    return await asyncio.wait_for(run(), timeout=timeout)


async def _call_one(cfg: dict, tool: str, args: dict, timeout: float = 60.0):
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async def run():
        async with stdio_client(_params(cfg)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool, arguments=args or {})

    return await asyncio.wait_for(run(), timeout=timeout)


def _refresh() -> None:
    """拉取所有服务器的工具清单，结果缓存 2 分钟。"""
    global _LOADING
    if _LOADING:
        return
    servers = _read_config()
    if not servers:
        _CACHE.update({"ts": time.time(), "specs": [], "map": {}})
        return
    _LOADING = True
    specs: list[dict] = []
    mapping: dict[str, tuple[str, str]] = {}
    try:
        for server_name, cfg in servers.items():
            if not isinstance(cfg, dict) or not cfg.get("command"):
                continue
            try:
                result = asyncio.run(_list_one(cfg))
            except Exception as exc:  # noqa: BLE001
                logger.warning("MCP 服务器 %s 连接失败：%s", server_name, exc)
                continue
            for tool in getattr(result, "tools", []) or []:
                full = f"mcp__{_safe(server_name)}__{_safe(tool.name)}"
                mapping[full] = (server_name, tool.name)
                specs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": full,
                            "description": (tool.description or "")[:800]
                            or f"{server_name} 提供的工具 {tool.name}",
                            "parameters": tool.inputSchema
                            or {"type": "object", "properties": {}},
                        },
                    }
                )
    finally:
        _LOADING = False
        _CACHE.update({"ts": time.time(), "specs": specs, "map": mapping})


def mcp_tool_specs() -> list[dict]:
    if time.time() - _CACHE["ts"] > _TTL:
        try:
            _refresh()
        except Exception as exc:  # noqa: BLE001
            logger.warning("MCP 工具刷新失败：%s", exc)
            _CACHE.update({"ts": time.time(), "specs": [], "map": {}})
    return list(_CACHE["specs"])


def mcp_tool_count() -> int:
    return len(mcp_tool_specs())


def mcp_call(full_name: str, args: dict) -> str:
    mcp_tool_specs()  # 确保映射已建立
    target = _CACHE["map"].get(full_name)
    if not target:
        return f"MCP 工具不存在或服务器未连接：{full_name}"
    server_name, tool_name = target
    servers = _read_config()
    cfg = servers.get(server_name)
    if not isinstance(cfg, dict):
        return f"MCP 服务器已从配置中移除：{server_name}"
    try:
        result = asyncio.run(_call_one(cfg, tool_name, args))
    except Exception as exc:  # noqa: BLE001
        return f"MCP 调用失败：{type(exc).__name__}: {exc}"

    parts: list[str] = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[{getattr(item, 'type', 'content')}]")
    body = "\n".join(parts).strip() or "（无返回内容）"
    if getattr(result, "isError", False):
        body = "工具报错：" + body
    return body[:6000]
