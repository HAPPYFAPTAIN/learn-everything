# 空 assistant 消息兼容修复

Learn Everything 在 `LearningApp.__init__()` 中自动调用
`learning_ext.chat_compat.configure_chat_compat()`，启动时为 Kotaemon 的
OpenAI、Azure、Structured Output 和 EndpointChatLLM 路径启用消息校验。
修复代码保存在主仓库，不修改只读的 `kotaemon/` 子模块；新机器拉取后无需手动打补丁。
更新后必须重启已经运行的应用，旧 Python 进程不会自动加载新代码。

校验会移除没有正文、没有工具调用的 assistant 消息，保留其他消息的顺序和内容。
空白字符串、None 和空内容容器视为空正文。工具调用以及旧版 function_call 保留，
消息对象携带的调用信息会在转换时保留。原始会话历史不被修改。
若输入为空，或过滤后没有消息，则在发送前抛出 ValueError；不恢复无效消息，
也不编造用户输入。已有非 assistant 消息不会被过滤，所以不需要另设“保留最后一条”的兜底。

## 独立使用 Kotaemon 的补丁

`0001-deepseek-empty-assistant-message.patch` 是面向上游 `9ad3e4e4` 的独立补丁。
`kotaemon-deepseek-compat.patch` 保留为同内容的兼容文件名，只选其中一个使用。
它们新增 `message_validation.py`，并修改 `openai.py` 与 `endpoint_based.py`，
使用与主应用相同的消息处理逻辑，不依赖 `learning_ext`。

这些补丁用于单独维护 Kotaemon 的工作副本，Learn Everything 无需应用它们。
在允许修改的独立副本中可以先检查，再应用：

```bash
git apply --check /path/to/0001-deepseek-empty-assistant-message.patch
git apply /path/to/0001-deepseek-empty-assistant-message.patch
```

应用后重启服务。升级上游时需重新检查补丁兼容性，不能根据补丁文件存在就认为已生效。

## 验证

```powershell
kotaemon\.venv\Scripts\python.exe -m pytest tests\test_chat_compat.py tests\test_rag_requests.py -q
```

测试使用本地严格校验服务与真实 OpenAI SDK，不调用外部模型、不读取 API 密钥。
覆盖空回复历史连续追问、同步/异步/流式请求、Endpoint 路径、空列表拒绝、
工具调用保留、原始历史不变，以及重复初始化。
