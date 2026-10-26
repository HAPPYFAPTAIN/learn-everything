from __future__ import annotations

import ipaddress

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from learning_ext.account.identity import (
    AccountError, AccountSettings, LocalIdentityProvider, ServerIdentityProvider,
    SessionVerifier,
)


def _local_request(request: Request):
    try:
        address = ipaddress.ip_address(request.client.host if request.client else "")
        if not address.is_loopback:
            raise ValueError("Not loopback")
        host = request.url.hostname or ""
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError("Not localhost")
    except ValueError:
        raise AccountError("local_only", "本地用户接口仅供本机使用。", 403) from None


def _access_token(request: Request):
    header = request.headers.get("authorization", "")
    if not header:
        return None
    kind, _, token = header.partition(" ")
    if kind.lower() != "bearer" or not token.strip() or len(token) > 16384:
        raise AccountError("invalid_session", "登录凭证无效。")
    return token.strip()


def resolve_request_identity(request: Request):
    provider = getattr(request.app.state, "le_identity_provider", None)
    if provider is None:
        raise AccountError("server_not_ready", "用户身份接口尚未初始化。", 503)
    if isinstance(provider, LocalIdentityProvider):
        _local_request(request)
    identity = provider.resolve(_access_token(request))
    request.state.learning_identity = identity
    return identity


def register_account_routes(app, settings: AccountSettings | None = None, verifier: SessionVerifier | None = None):
    if getattr(app.state, "le_account_registered", False):
        return
    settings = settings or AccountSettings.from_environment()
    provider = LocalIdentityProvider() if settings.mode == "local" else ServerIdentityProvider(settings, verifier)
    ready = bool(settings.server_url and verifier is not None)
    router = APIRouter(prefix="/api/v1/account", tags=["account"])
    headers = {"Cache-Control": "no-store", "Pragma": "no-cache", "Vary": "Authorization"}

    async def account_error(request: Request, exc: AccountError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status, headers=headers)

    app.add_exception_handler(AccountError, account_error)

    def status():
        return {
            "api_version": 1,
            "mode": settings.mode,
            "connection": {
                "configured": bool(settings.server_url),
                "status": "local" if settings.mode == "local" else ("adapter_ready" if ready else "not_connected"),
            },
            "capabilities": {"interactive_sign_in": False, "multi_user_ui": False},
        }

    @router.get("/status")
    def account_status(request: Request):
        try:
            if settings.mode == "local":
                _local_request(request)
            return JSONResponse(status(), headers=headers)
        except AccountError as exc:
            return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status, headers=headers)

    @router.get("/context")
    def account_context(request: Request):
        try:
            identity = resolve_request_identity(request)
            return JSONResponse({**status(), "identity": identity.public()}, headers=headers)
        except AccountError as exc:
            return JSONResponse({**status(), "error": {"code": exc.code, "message": exc.message}}, status_code=exc.status, headers=headers)

    app.state.le_identity_provider = provider
    app.state.le_account_registered = True
    app.include_router(router)
