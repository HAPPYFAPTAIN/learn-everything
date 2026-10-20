"""动手学 Agent 的能力层：电脑操作工具 + MCP。

包内模块：
    safety       危险命令拦截、危险工具判定
    tools        本地工具注册表（命令、文件、屏幕、系统信息）
    mcp_bridge   MCP 服务器连接（可选，读 mcp.json）
    runtime      流式对话 + 工具调用循环 + 审批
"""

from learning_ext.agent.tools import build_tool_specs, execute_tool, tool_needs_approval

__all__ = ["build_tool_specs", "execute_tool", "tool_needs_approval"]
