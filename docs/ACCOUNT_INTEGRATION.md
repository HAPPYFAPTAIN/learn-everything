# 用户身份与服务器接入接口

当前版本继续使用本地工作空间，保留已有学习数据的 `user_id="default"`。新增的 `learning_ext.account` 是服务器接入边界；当前尚未实现注册、登录页面、云同步或全业务多用户隔离。不会把输入的用户名、浏览器参数或代理头当作已认证身份。

## 已提供的接口

`GET /api/v1/account/status` 返回接口版本、运行模式、连接状态与界面能力。`GET /api/v1/account/context` 在身份有效时额外返回用户、工作空间和学习/同步/成员管理能力。响应均禁止缓存，不返回访问令牌、服务器地址、邮箱、API 密钥或验证器异常详情。

本地模式的身份如下。`default` 是兼容现有数据的内部归属键；不是可用于远程登录的凭证。

```json
{
  "api_version": 1,
  "mode": "local",
  "connection": {"configured": false, "status": "local"},
  "capabilities": {"interactive_sign_in": false, "multi_user_ui": false},
  "identity": {
    "user": {"id": "default", "display_name": "本地用户"},
    "workspace": {"id": "local", "name": "本地工作空间"},
    "source": "local",
    "capabilities": {"learning": true, "cloud_sync": false, "manage_members": false}
  }
}
```

本地接口只接受真实连接来自回环地址、Host 为 localhost 或回环地址的请求。忽略 `user_id` 查询参数、`X-User-ID`、`X-Forwarded-For` 等客户端身份信息。传入服务器令牌不会隐式切换身份。

## 配置与失败行为

- `LE_ACCOUNT_MODE` 默认 `local`，另一个有效值为 `server`。
- `LE_ACCOUNT_SERVER_URL` 是未来认证服务地址，只接受 HTTPS；本机开发允许回环 HTTP。禁止 URL 内用户名、密码、查询参数及片段。
- 在服务器模式中，没有服务器地址或验证器时，context 返回 `503 server_not_ready`，不会回落到本地用户。没有令牌返回 `401 sign_in_required`；无效、过期或验证失败返回 `401 invalid_session`。
- status 的 `adapter_ready` 仅表示适配器已注册，不表示网络连通性或登录成功。
- 当前 `custom_app.py` 明确拒绝以 `server` 模式启动旧桌面页面。现有部分业务仍固定本地归属，未完成迁移前不应直接多人部署。这个保护不影响本地运行，也不阻止在独立 FastAPI 服务中对接身份接口。

## 接入实际用户服务器

在可信后端实现 `SessionVerifier.verify(access_token, server_url=...)`，返回 `VerifiedSession`。验证器负责与真实服务对接，检查令牌签名或调用服务端会话验证接口，并确认签发方、受众、撤销状态、用户及工作空间成员资格。`VerifiedSession` 只允许由验证器创建；不能根据浏览器提交的资料直接构造。

```python
from fastapi import FastAPI
from learning_ext.account.identity import AccountSettings
from learning_ext.account.routes import register_account_routes

app = FastAPI()
register_account_routes(
    app,
    AccountSettings(mode="server", server_url="https://accounts.example.com"),
    verifier=your_session_verifier,
)
```

客户端通过 `Authorization: Bearer ...` 传递会话凭证。预留接口没有自制 JWT 解析、密码数据库或模拟登录。后续登录界面、刷新、退出、密钥存储由实际认证方案实现；不要把长期令牌放到 localStorage。cookie 登录需另行处理 HttpOnly、SameSite、CSRF 与撤销。

`ServerIdentityProvider` 再次检查返回类型、身份字段与过期时间，按配置的服务端地址、用户 subject、工作空间 ID 生成 `srv_…` 归属键。相同用户在不同服务或工作空间不会自动共享学习数据。服务端地址应保持稳定；改变地址时应进行显式身份归属迁移。

## 业务接入入口

`resolve_request_identity` 可直接用于 FastAPI dependency。只能从可信请求上下文取得身份，不能在 API 参数中接受任意 owner ID。

```python
from fastapi import Depends
from sqlmodel import Session, select
from learning_ext.account import Identity, owner_filter, require_owner, resolve_user_id
from learning_ext.account.routes import resolve_request_identity

@app.get("/api/v1/projects")
def projects(identity: Identity = Depends(resolve_request_identity)):
    with Session(engine) as session:
        return session.exec(
            select(LearningProject).where(owner_filter(LearningProject, identity))
        ).all()

def save_project(session: Session, identity: Identity, topic: str):
    project = LearningProject(user_id=resolve_user_id(identity), topic=topic)
    session.add(project)
    session.commit()
    return project

def read_project(session: Session, identity: Identity, project_id: int):
    return require_owner(session.get(LearningProject, project_id), identity)
```

`require_owner` 对不存在及不属于当前身份的记录均返回统一 404。账户错误由注册时的异常处理器统一转成响应，不泄露验证细节。上述 scope 辅助方法只处理数据归属，权限要求（如是否可写入）仍须按具体操作检查。

上线多用户之前，还需将学习项目、课程节点关联、复习、测验、笔记、资料及预览、后台备课任务、模型连接、Agent 会话与审计日志统一绑定可信身份；移除业务中的硬编码 `default`。后台任务必须携带服务端确认过的归属，不能依赖全局“当前用户”。本地旧数据与服务器账户绑定必须明确选择迁移，不能自动归入第一个登录用户。完成跨用户访问、退出/撤销、后台任务隔离测试后，再解除桌面启动保护并开放登录界面。

## 验证

`tests/test_account_identity.py` 覆盖本地兼容、伪造身份参数、回环限制、无凭证、无服务器、过期凭证、异常脱敏、跨用户/工作空间/服务归属隔离、URL 限制及启动保护。测试不访问远端服务、不保存真实令牌。

## 账户入口

侧栏底部的账户入口通过 `GET /api/v1/account/context` 读取显示名称、工作空间及同步能力，不在前端伪造登录态。接口失败时显示“暂时无法读取”。后续接入认证后，可派发 `le:account-changed` 事件刷新展示；也可使用面板内的刷新按钮。当前未提供登录或注册操作。
