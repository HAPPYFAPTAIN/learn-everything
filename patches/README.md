# 子模块补丁

`kotaemon/` 是 git submodule，指向上游 `Cinnamon/kotaemon`，我们没有推送权限。
我们对它做的改动没法通过 `git push` 带出去，所以导出成补丁存在这里。

## 0001-deepseek-empty-assistant-message.patch

**改了什么**

`libs/kotaemon/kotaemon/llms/chats/openai.py`、`endpoint_based.py`：
在真正发请求前，剔除 `content` 和 `tool_calls` 同时为空的 assistant 消息。

**为什么必须打**

DeepSeek 这类 OpenAI 兼容端点遇到空 assistant 消息会整单拒绝：

```
400 Invalid assistant message: content or tool_calls must be set
```

引用问答、会话命名、追问建议这些功能在回放历史时很容易带进这种占位消息。一旦进去，
这一轮对话的**后续每次请求都会失败**——表现为"问了没反应"或直接报错。

**不打会怎样**

本机现在正常（补丁已经在工作区里）；但如果把仓库 clone 到新机器或服务器，
这两个文件是上游原版，上述 400 会在用到引用问答/会话命名时冒出来。

**怎么打**

```bash
cd kotaemon
git apply ../patches/0001-deepseek-empty-assistant-message.patch
```

打完不需要重启任何东西，下次启动就生效。用 `git apply --check` 可以先验证能否干净应用。

## 注意

- 这两个文件是**上游代码**，将来升级 submodule 版本时补丁可能冲突，需要重新打
- 补丁只在这一处（`llms/chats/`），没有别的子模块改动
- 如果哪天上游自己修了这个问题，删掉补丁文件即可
