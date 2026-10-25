# 让用户亲手操作的电脑教学 · 设计与实现

后续更新：学习工作台已加入「逐步行动」，并新增限定窗口的标准 UI Automation 圈选与单次授权操作。详见 [工作台逐步行动](ACTION_LEARNING.md)。下文记录的是原始独立练习器阶段；新的适配器仍不等于任意软件的像素视觉或自动操作代理。

2026-10-25。状态：三种网页练习与独立 Windows 桌面实操已验证；Windows 设置、真实 Excel 和浏览器 Agent 的专用适配器尚未接入。

## 产品判断

基本流程是“观察 → 解释一个动作 → 用户操作或明确授权演示 → 验证结果 → 下一步”。Gradio 页面只能可靠观察自己的页面，不能直接控制任意 Windows 应用。当前通过独立的 WPF 练习器验证真实桌面观察与操控，不把网页教程遮罩伪装成跨应用能力。

后续真实应用适配器应提供不抢焦点的教学侧窗。每一步显示目标、一个具体动作和可展开提示，并允许暂停与退出。高亮只是定位辅助；验证必须读取操作结果，不能因为用户点了“下一步”就判定学会。低置信度时显示“尚无法确认”，允许用户自报完成，但记录为自报，不伪装成自动验证。

完成反馈应短暂、克制：进度增加、当前步骤完成、解释刚学会的技能。每个技能最后安排一次撤去提示的独立练习，区分跟随完成与独立完成。不要用持续彩纸或弹窗打断操作。

## 三种场景的接入路线

### 电脑设置

Windows UI Automation 可以读取可访问控件的名称、类型、位置、状态，并订阅部分变化。当前已将读取、输入和结果验证用于专用 WPF 练习器，不代表 Windows 设置已经接入。正式适配器只观察用户选择的目标窗口，输出结构化状态；透明高亮窗口应鼠标穿透、不抢焦点。目标窗口移动、DPI 改变、多显示器切换时必须重算边界。

先选低风险的任务，例如显示偏好、资源管理器视图。不同 Windows 版本、语言、控件虚拟化会影响选择器。匹配应结合进程、窗口、AutomationId、控件类型与名称，不只存屏幕坐标。找不到目标时暂停，不猜位置。

普通进程不能任意读取更高完整性级别的界面。UAC、安全桌面和权限提升步骤交给用户，本产品不借 UIAccess 绕过边界。不要为了置顶窗口启用特殊辅助功能权限。

### Excel

优先做 Excel Task Pane Add-in：使用 Office.js 读取用户明确选择的练习工作簿/区域，监听 onSelectionChanged、onChanged、onFormulaChanged 等事件。验证公式、结果和范围比截图识别更可靠。例如 SUM 练习要同时核对公式引用范围和计算结果，不能只判定结果等于 90。

事件处理器在插件关闭或刷新后失效，需要重新注册；共同编辑可能产生远端事件，应区分 Local / Remote。API 支持受 Excel 版本与 requirement set 影响，接入前检测，不满足时退回用户检查。第一版只支持专门的练习工作簿，不遍历用户所有表格。

桌面 COM 可以用于 Windows 原型验证，但进程、实例和活动工作簿容易混淆；正式版本优先插件明确绑定文档，不默认连接所有已打开文件。

### AI Agent 操作

网页工具优先浏览器扩展：用户点击后临时授权当前站点，content script 读取当前页面 DOM 并呈现高亮。使用站点适配器定位新建任务、输入目标、审核计划、确认执行和检查结果。页面更新可能使定位失效，必须按版本回归，找不到就暂停。

网页自身不能直接读取其它域页面。需要独立扩展及明确授权；内嵌 WebView 的 JS/Python bridge 只适合本应用信任的页面，不可把通用 Python 执行入口暴露给任意网页。桌面版 Agent 则使用 Windows 适配器，不能把浏览器能力当作所有桌面软件都可用。

## 实现边界

后续跨应用适配器可沿用职责拆分：LessonEngine 保存步骤和状态；Observer 返回限定窗口的事实；TargetResolver 定位目标；Overlay 展示指引；Verifier 对照完成条件；Journal 记录步骤结果。模型负责解释与个性化提示，确定性验证器负责能客观检查的结果。

每步包含 task_id、step_id、目标应用与版本、目标控件描述、前置条件、动作说明、成功谓词、证据时间、提示层级和可撤销方法。状态为未开始、等待用户、验证中、通过、无法确认、暂停；不能把“超时”自动转成通过。

默认观察接口只需要 start_session(target)、read_state(session)、subscribe_state(session)、stop_session(session)，不因此获得 execute_shell 或任意输入权限。需要演示操作时，只能使用目标适配器提供的固定动作，并绑定本次授权的窗口和控件。会话令牌应短期有效；本地服务只监听回环地址并校验来源和令牌，不能让任意网站调用。

截图只作为补充：UIA 或 DOM 不可用时，用户选择目标窗口并预览后才发送。默认本地处理、排除密码字段、不记录键盘输入，不后台全屏录制；提供立即暂停和清除观察记录。当前 GLM 配置只已验证文本能力，不能假设它支持图像；视觉路径需要另外验证模型能力、费用和数据去向。

## 已实现功能

应用“动手学”页有四个入口：

- 电脑设置：打开开关 → 调整到 40%–60% → 恢复关闭。这是网页模拟练习，不改变 Windows 设置。
- Excel：输入 SUM(B1:B3) → 修改数据验证重算 → 恢复数据。只实现本课求和，不是完整表格引擎，也不操作真实 Excel 文件。
- AI Agent：写任务 → 设置执行前确认 → 写验收标准。只检查填写长度和开关，不评价任务语义或真实 Agent 执行质量。
- 桌面实操：启动独立 WPF 练习器 → 读取控件 → 输入任务文字 → 点击检查 → 撤销 → 关闭。这里会真实读取和操作 Windows 专用窗口。

前三项本地练习各包含三步引导和一次独立复做。每一步都检查当前控件状态，失败不推进；修改已通过的输入后需重新检查。进度和操作日志保存在当前浏览器的 `localStorage` 键 `le.coach.lessons.v1`，完成后可下载包含检查结果、错误和日志的 Markdown 复盘。

桌面实操使用唯一窗口标题和本次启动的进程。未启动练习器时不能读取其他窗口。启动、输入、检查和撤销需要逐项勾选授权，每次动作后授权自动取消。输入通过 UI Automation 的 `ValuePattern` 写入 `GoalInput` 并读回核对，不读写剪贴板，也不发送全局键盘输入。检查与撤销读取实际状态后才推进。

“结束并关闭”和“返回其他练习”只关闭本次启动的练习器。关闭请求定向发送到练习器窗口，不使用全局 `Alt+F4`；进程无响应时也只结束本次拥有的测试进程。该适配器不会修改系统设置、现有文档或其他应用。

## 下一阶段的验收门槛

1. Windows 设置：接入真实系统任务前，验证窗口移动、双屏、失焦和权限撤回；只操作明确授权的目标，并覆盖支持的系统版本。
2. Excel：用户自己修改练习文件；检查正确和错误公式、手填结果、撤销、重开、多人编辑和插件断开。只读取授权区域。
3. Agent：支持一个明确站点与版本，完成创建任务、审核计划与检查输出；不主动发送或替用户点击确认。
4. 观察失败、模型超时、权限撤回均可退出；不能用“我做完了”按钮代替真实接入验收。
5. 小规模用户测试比较首次完成时间、提示次数、独立复做成功率与误判率。高级感只是呈现要求，能自己复做才是教学效果。

## 本轮代码与后端影响

- `learning_ext/pages/coach_lesson.py`：桌面实操的按钮、逐步授权、状态和日志。
- `learning_ext/agent/desktop_coach.py`：练习器生命周期、UIA 读写、结果验证与定向关闭。
- `learning_ext/agent/practice_window.ps1`：独立 WPF 练习器；保留 UTF-8 BOM 以兼容 Windows PowerShell 5.1。
- `learning_ext/coach.py`、`learning_ext/assets/coach_lesson.js`、`learning_ext/assets/coach_lesson.css`：课程入口、本地校验、进度、复盘和样式。
- `learning_ext/app.py`、`custom_app.py`、`learning_ext/presentation.py`：页面注册与资源加载。自定义 CSS/JS 在启动时注入，更新后需重启 `run.bat`。

没有数据库或对外 API 变化，没有新增第三方依赖、管理员权限、模型请求或数据上传。WPF 与 UI Automation 使用 Windows 自带能力。

## 技术依据

- Microsoft UI Automation Fundamentals：https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiautocore-overview
- UI Automation 安全边界：https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview
- Excel 插件概览：https://learn.microsoft.com/office/dev/add-ins/excel/excel-add-ins-overview
- Excel 事件与生命周期：https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-events
- Chrome content scripts 与隔离环境：https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts
- pywebview JS/Python bridge：https://pywebview.flowrl.com/guide/interdomain.html

以上文档支持基础能力判断，不能替代对当前应用、系统版本和实际控件的验证。

## 本轮验收证据

- 完整运行 `kotaemon/.venv/Scripts/python.exe -m pytest tests -q`：258 passed、7 skipped、12 warnings，无失败。
- 动手学与桌面实操定向测试 11 passed；`coach_lesson.js` 的 Node.js 语法检查通过。设置状态、公式引用、修改后重算、执行确认和过短输入等拒绝路径均有覆盖。
- 在真实 Windows 桌面直接调用页面所用的 `DesktopCoach` 方法，依次通过启动、控件读取、中文输入与读回、检查、撤销和关闭。撤销后输入框为空，关闭后找不到本次练习器窗口。
- 未启动时读取被拒绝；关闭只针对本次练习器，不发送全局 `Alt+F4`；输入不经过剪贴板或全局键盘。
- Windows 设置、真实 Excel 插件和浏览器 Agent 适配器仍未实现，不能把本次专用练习器验证当作这些能力已经完成。
