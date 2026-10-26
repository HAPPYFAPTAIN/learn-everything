# Contribution — 学习工作空间与桌面 Agent 改进

日期：2026-10-26。这份文件记录本次提交相对于既有远端版本的贡献、验证范围与实现限制。

## 追加更新：课程环境适配与思考设置

本轮在 `432a6a4` 基础上修复课程更新时富文本渲染丢失的问题，恢复标题、目录、代码块与语义标注。课程准备和阅读接入本机只读环境检查，已确认满足条件的重复安装步骤折叠为参考，保留项目配置、依赖安装和实际练习；不自动将整节课程标记为掌握。

模型配置新增八类用途的思考偏好，分别保存提问、课程、总结与复习卡、路线、动手学、测验、润色及其他任务的默认、开启或关闭选项。请求层按平台能力映射参数，刷新页面后恢复保存值。GLM 5.3 系列不支持关闭思考，关闭偏好仅降为最低强度；尚未适配的接口保持平台默认。章节内的小结与课程共用一次请求，跟随课程设置。

界面统一提高正文、菜单、输入框与表单标签的字号和字重，保留标题、正文、辅助文字的层级。桌面控件以 16px 为基准，正文 17px；窄屏分别调整为 15px 和 16px。思考设置修复暗色模式下文字被旧样式覆盖的问题，明暗模式共用语义色板。

相关功能回归测试通过 246 项；本轮排版及课程、思考设置专项检查通过 33 项。浏览器验证包含明暗模式、设置保存与刷新恢复、课程富文本和已安装环境提示。未进行外部模型重生成实测。本机配置、密钥、数据库、运行日志、截图和临时脚本不属于提交内容。

## 比较基准

提交前已重新取得两个远端的分支状态。实际上传目标为 `HAPPYFAPTAIN/learn-everything` 的 `main`，基准提交为 `e18b4882ef5390a28cafe79782baa61ce1823b37`。本地 HEAD 与此基准相同，本次内容来自其后的工作目录修改与新增文件。

上游 `redmaplewww/learn-everything` 的 `main` 为 `05b58bc92f72a519943e8363cf75765b7bc76761`；个人仓库已在此基础上累积 12 个提交。本次没有向上游推送，也没有修改 Kotaemon 子模块的提交指针。

基准版本已包含动作学习、环境探索、多平台模型设置、文字润色、文件预览与 zcode 衍生核心。本次进一步完善这些能力，新增搜索执行层、账户接口边界与多维学习统计。

## 主要贡献

### 桌面教练与搜索

动手学以对话驱动，提供三个建议答案与一个自行填写入口。工具调用、结果、等待回答及授权状态有对应事件；执行阶段加入重复结果检测与步数限制，避免无进展的循环。工具结果经结构化处理后再交给模型，会话整理保留工具消息关系。

环境探索结合已安装软件与文件证据，让教学方案能依本机条件调整。新增范围受限的文件名搜索、内容搜索与网页搜索模块；Everything 加速器提供哈希验证、命名实例、索引生命周期及原生搜索回退。桌面操作持续保留当前步骤授权与执行记录，不以环境检测结果取代实际操作验证。

相关程序：`learning_ext/agent/`、`learning_ext/environment_agent/discovery.py`、`scripts/bundle_everything.py`。详见 [Agent 执行边界](docs/AGENT_EXECUTION.md) 与 [Everything 整合](docs/EVERYTHING_INTEGRATION.md)。

### 对话与模型选择

动手学接入已保存的模型连接，加入思考强度与思考内容显示设置，依模型能力处理请求参数。知识问答改善历史消息兼容性、恢复流程、引用资料呈现、流式更新及追踪最新消息的互动，减少整段重绘与版面跳动。

模型选择入口使用平台图示，菜单靠近触发位置。工具详细内容可以折叠，避免执行参数与输出占满对话画面。

相关程序：`learning_ext/chat_*.py`、`learning_ext/llm/client.py`、`learning_ext/pages/coach.py` 与对应前端资源。

### 共用接口与课程阅读

新增明暗主题的语义色彩变数、主题切换与全屏幕工作空间样式。样式统一由 `/le-presentation.css` 加载，修改 CSS 后刷新即可生效；JavaScript 仍需重启应用。侧栏支持图示模式、较大的导航字体及底部账户入口。

首页、路线、数据库、复习、设置与工作台采用较紧凑的版面。课程管理菜单统一图示、字体与排列；课程调整视窗修正栏位对齐与重叠弹层。短篇行动学习内容在工作区垂直居中，长内容仍可卷动。批量路线选择的背景、文字、勾选框及选取状态均使用共用主题色。

课程与解释内容扩充富文本、语义标注、结构图及章节小结的呈现与生成提示；选字解释和文字操作整合，减少分离的视窗与明暗混用。

### 学习记录与路线管理

看板新增累计时数、活跃天数、连续学习天数、复习评分、测验正确率、待批改数、笔记与批注、阶段进度、任务完成及各课程投入时间。可查看近期事件并导出记录；没有作答时不显示误导性的零正确率。课程状态变更写入记录，重复设置同一状态不重复计数。

学习路线支持多选删除。删除前显示名称与数量，选择改变后原确认失效；后端先验证全部项目的归属，再于同一事务删除相关资料。看板与路线查询补上用户范围限制。

相关程序：`learning_ext/dashboard/analytics.py`、`learning_ext/dashboard/service.py`、`learning_ext/progress/study.py`、`learning_ext/project_ops.py`、`learning_ext/pages/path_generator.py`。

### 后续服务器接入

新增 `learning_ext.account`，提供账户状态、身份解析与验证器接口，前端账户入口读取本机真实状态。服务器模式缺少验证能力时拒绝回落成本地身份；目前桌面应用仍限制为本机单一用户。

这是接口预留，尚未完成注册、登录、云端同步或全部业务的多用户隔离，不能直接当作多人服务部署。详见 [账户整合接口](docs/ACCOUNT_INTEGRATION.md)。

## 验证

本次上传前执行 22 个相关 Python 测试文件，结果为 **356 passed、1 skipped、39 warnings**。范围涵盖账户身份、Agent 执行与提问、桌面工具、搜索、Everything、聊天兼容与恢复、模型选择、富文本、课程呈现、学习统计、进度与批量删除。

```powershell
& kotaemon/.venv/Scripts/python.exe -m pytest tests/test_account_identity.py tests/test_agent_runtime.py tests/test_agent_desktop_tools.py tests/test_agent_outcomes.py tests/test_agent_questions.py tests/test_agent_search.py tests/test_chat_compat.py tests/test_chat_connections.py tests/test_chat_recovery.py tests/test_chat_presentation.py tests/test_chat_thinking.py tests/test_coach_models.py tests/test_discovery_search.py tests/test_everything_runtime.py tests/test_everything_search.py tests/test_explanation_rich_text.py tests/test_lesson_presentation.py tests/test_dashboard_project_ops.py tests/test_project_delete_ui.py tests/test_route_picker.py tests/test_progress_study.py tests/test_learning_dimensions_batch.py -q
```

浏览器人工检查包含明暗切换、侧栏折叠与底部对齐、模型菜单、课程调整弹层、行动学习居中，以及批量删除的选取和确认预览。删除行为使用隔离的测试数据库验证，没有删除实际学习项目。

这不是全平台端到端验证。此次没有重新执行需要实际 Everything 程序的可选集成测试、全部浏览器自动化或完整便携版打包；不同模型供应商的在线行为仍需以实际账户验证。

## 提交范围与限制

提交包含应用源代码、测试、构建脚本与文档，不包含 API 密钥、学习数据库、执行日志、临时修补脚本和个人验收截图。Everything 二进制不进入 Git，由构建脚本取得并验证，授权文件必须随便携版保留；Everything 主程序是免费软件，并非完整开源项目。

来源标记保存在未导入的 `learning_ext/_hidden_menu.py`，不挂接前端菜单或 HTTP 接口。
