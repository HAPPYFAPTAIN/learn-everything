# 让用户亲手操作的电脑教学 · 设计与可行性

2026-10-17。状态：已加入网页交互原型；真实跨应用观察与高亮尚未接入。

## 产品判断

可行，但需要把“自动执行”改为“观察 → 解释一个动作 → 用户执行 → 验证结果 → 下一步”。现有 Gradio 页面只能可靠观察自己的页面；不能将当前页的教程遮罩直接延伸到 Windows 设置、Excel 或其它浏览器窗口。

应提供一个不抢焦点的教学侧窗。每一步显示：目标、一个具体动作、为什么这样做、可展开提示、暂停与退出。高亮是定位辅助；验证读取操作结果，不能因为用户点了“下一步”就判定学会。低置信度时显示“尚无法确认”，允许用户自报完成，但记录为自报，不伪装成自动验证。

完成反馈应短暂、克制：进度增加、当前步骤完成、解释刚学会的技能。每个技能最后安排一次撤去提示的独立练习，区分跟随完成与独立完成。不要用持续彩纸或弹窗打断操作。

## 三种场景的接入路线

### 电脑设置

Windows UI Automation 可以读取可访问控件的名称、类型、位置、状态，并订阅部分变化。桌面伴随进程只观察用户选择的目标窗口，输出结构化状态。透明高亮窗口绘制在目标控件附近，鼠标穿透、不抢焦点；不使用模拟点击。目标窗口移动、DPI 改变、多显示器切换时必须重算边界。

先选低风险的任务，例如显示偏好、资源管理器视图。不同 Windows 版本、语言、控件虚拟化会影响选择器。匹配应结合进程、窗口、AutomationId、控件类型与名称，不只存屏幕坐标。找不到目标时暂停，不猜位置。

普通进程不能任意读取更高完整性级别的界面。UAC、安全桌面和权限提升步骤交给用户，本产品不借 UIAccess 绕过边界。不要为了置顶窗口启用特殊辅助功能权限。

### Excel

优先做 Excel Task Pane Add-in：使用 Office.js 读取用户明确选择的练习工作簿/区域，监听 onSelectionChanged、onChanged、onFormulaChanged 等事件。验证公式、结果和范围比截图识别更可靠。例如 SUM 练习要同时核对公式引用范围和计算结果，不能只判定结果等于 90。

事件处理器在插件关闭或刷新后失效，需要重新注册；共同编辑可能产生远端事件，应区分 Local / Remote。API 支持受 Excel 版本与 requirement set 影响，接入前检测，不满足时退回用户检查。第一版只支持专门的练习工作簿，不遍历用户所有表格。

桌面 COM 可以用于 Windows 原型验证，但进程、实例和活动工作簿容易混淆；正式版本优先插件明确绑定文档，不默认连接所有已打开文件。

### AI Agent 操作

网页工具优先浏览器扩展：用户点击后临时授权当前站点，content script 读取当前页面 DOM 并呈现高亮。使用站点适配器定位新建任务、输入目标、审核计划、确认执行和检查结果。页面更新可能使定位失效，必须按版本回归，找不到就暂停。

网页自身不能直接读取其它域页面。需要独立扩展及明确授权；内嵌 WebView 的 JS/Python bridge 只适合本应用信任的页面，不可把通用 Python 执行入口暴露给任意网页。桌面版 Agent 则使用 Windows 适配器，不能把浏览器能力当作所有桌面软件都可用。

## 建议的实现边界

LessonEngine 保存步骤和状态；Observer 返回限定窗口/区域的事实；TargetResolver 定位目标；Overlay 展示指引；Verifier 对照完成条件；Journal 记录步骤结果。模型负责解释与个性化提示，确定性验证器负责能客观检查的结果。

每步包含 task_id、step_id、目标应用与版本、目标控件描述、前置条件、动作说明、成功谓词、证据时间、提示层级、可撤销方法。状态为未开始、等待用户、验证中、通过、无法确认、暂停；不能把“超时”自动转成通过。

最小观察接口只需要 start_session(target)、read_state(session)、subscribe_state(session)、stop_session(session)。不要提供 execute_shell、click、type 等执行接口。会话令牌应短期有效、绑定目标窗口；本地服务只监听回环地址，校验来源和令牌，不能让任意网站调用。

截图只作为补充：UIA 或 DOM 不可用时，用户选择目标窗口并预览后才发送。默认本地处理、排除密码字段、不记录键盘输入，不后台全屏录制；提供立即暂停和清除观察记录。当前 GLM 配置只已验证文本能力，不能假设它支持图像；视觉路径需要另外验证模型能力、费用和数据去向。

## 已实现原型

应用“动手学”页有三种本地练习：

- 设置：打开开关 → 调整到 40%–60% → 恢复关闭。
- Excel：输入 SUM(B1:B3) → 修改输入验证重算 → 无完整答案提示再次练习。只实现本课求和，不是完整表格引擎。
- Agent：写任务 → 设置执行前确认 → 写验收标准。当前只检查填写长度和开关，不宣称能评价任务语义或真实 Agent 执行质量。

每一步检查当前控件状态，失败不推进；用户修改已通过的输入后需重新检查。没有外部发送、截图、自动电脑操作或持久化记录。原型的作用是验收教学交互，不是宣称真实 Windows / Excel 已被接入。

## 下一阶段的验收门槛

1. Windows：在测试窗口移动、缩放、双屏和失焦后仍正确定位；停止会话后不再观察；实际夜间模式任务验证须覆盖支持的系统版本。
2. Excel：用户自己修改练习文件；检查正确和错误公式、手填结果、撤销、重开、多人编辑和插件断开。只读取授权区域。
3. Agent：支持一个明确站点与版本，完成创建任务、审核计划与检查输出；不主动发送或替用户点击确认。
4. 观察失败、模型超时、权限撤回均可退出；不能用“我做完了”按钮代替这些真实接入验收。
5. 小规模用户测试比较首次完成时间、提示次数、独立复做成功率与误判率。高级感只是呈现要求，能自己复做才是教学效果。

## 本轮代码与后端影响

增加 learning_ext/coach.py、assets/coach.js；app.py 注册页面，custom_app.py 加载脚本。无数据库或对外 API 变化，无新增桌面权限、模型请求或数据上传。refinements.css 管理本轮版面与动效，尊重 prefers-reduced-motion；公司图标复用官网原始 PNG。

## 技术依据

- Microsoft UI Automation Fundamentals：https://learn.microsoft.com/en-us/windows/win32/winauto/entry-uiautocore-overview
- UI Automation 安全边界：https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview
- Excel 插件概览：https://learn.microsoft.com/office/dev/add-ins/excel/excel-add-ins-overview
- Excel 事件与生命周期：https://learn.microsoft.com/en-us/office/dev/add-ins/excel/excel-add-ins-events
- Chrome content scripts 与隔离环境：https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts
- pywebview JS/Python bridge：https://pywebview.flowrl.com/guide/interdomain.html

以上文档支持基础能力判断，不能替代对当前应用、系统版本和实际控件的验证。

## 本轮验收证据

- 完整回归 158 passed、7 skipped（联网测试本轮未重跑）；页面注册测试 35 passed，JS 语法检查通过。
- 浏览器：三种练习各三步均实际完成；未操作的开关、把 90 当作公式、过短验收文字均被拒绝；关闭已确认的执行边界后最终检查不能通过，重新打开后通过。
- 750 CSS px 窄窗口中单列显示，scrollWidth 与 clientWidth 同为 731，无页面横向溢出；验收后已恢复桌面窗口。
- 官网原始标志实际加载，导航图标与当前目标高亮核验通过；桌面截图 E:\yitai_website\output\learning-coach-prototype.png。
- 真实跨应用适配器未实现、未测试；本次交付为可行性研究和可操作教学原型。
