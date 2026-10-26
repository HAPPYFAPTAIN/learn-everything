from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
from dataclasses import dataclass, field
from typing import Mapping, Protocol
from urllib.parse import urlsplit


class AccountError(Exception):
    def __init__(self, code: str, message: str, status: int = 401):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class AccountSettings:
    mode: str = "local"
    server_url: str = field(default="", repr=False)

    def __post_init__(self):
        if self.mode not in ("local", "server"):
            raise ValueError("LE_ACCOUNT_MODE must be local or server")
        if self.server_url:
            parsed = urlsplit(self.server_url)
            parsed.port
            try:
                local = ipaddress.ip_address(parsed.hostname or "").is_loopback
            except ValueError:
                local = parsed.hostname == "localhost"
            if (
                not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment
                or (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            ):
                raise ValueError("Account server requires HTTPS without URL credentials")

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None):
        values = os.environ if environment is None else environment
        return cls(
            mode=values.get("LE_ACCOUNT_MODE", "local").strip().lower(),
            server_url=values.get("LE_ACCOUNT_SERVER_URL", "").strip().rstrip("/"),
        )


@dataclass(frozen=True)
class Identity:
    user_id: str
    display_name: str
    workspace_id: str
    workspace_name: str
    source: str
    permissions: tuple[str, ...] = ()

    def public(self):
        return {
            "user": {"id": self.user_id, "display_name": self.display_name},
            "workspace": {"id": self.workspace_id, "name": self.workspace_name},
            "source": self.source,
            "capabilities": {
                "learning": "learning" in self.permissions,
                "cloud_sync": "sync" in self.permissions,
                "manage_members": "members" in self.permissions,
            },
        }


@dataclass(frozen=True)
class VerifiedSession:
    subject: str
    display_name: str
    workspace_id: str
    workspace_name: str
    expires_at: float
    permissions: tuple[str, ...] = ("learning",)


class SessionVerifier(Protocol):
    def verify(self, access_token: str, *, server_url: str) -> VerifiedSession: ...


class IdentityProvider(Protocol):
    def resolve(self, access_token: str | None = None) -> Identity: ...


class LocalIdentityProvider:
    def resolve(self, access_token: str | None = None) -> Identity:
        if access_token:
            raise AccountError("local_only", "当前使用本地工作空间，尚未连接用户服务器。")
        return Identity("default", "本地用户", "local", "本地工作空间", "local", ("learning",))


class ServerIdentityProvider:
    def __init__(self, settings: AccountSettings, verifier: SessionVerifier | None = None):
        self.settings = settings
        self.verifier = verifier

    def resolve(self, access_token: str | None = None) -> Identity:
        if not self.settings.server_url or self.verifier is None:
            raise AccountError("server_not_ready", "用户服务器尚未接入。", 503)
        if not access_token:
            raise AccountError("sign_in_required", "请先登录。")
        try:
            claims = self.verifier.verify(access_token, server_url=self.settings.server_url)
            if not isinstance(claims, VerifiedSession):
                raise ValueError("Invalid session contract")
            if not (time.time() < claims.expires_at < float("inf")):
                raise ValueError("Expired session")
            for value in (claims.subject, claims.workspace_id, claims.display_name, claims.workspace_name):
                if not isinstance(value, str) or not value.strip() or len(value) > 256:
                    raise ValueError("Invalid identity")
            if not isinstance(claims.permissions, tuple):
                raise ValueError("Invalid permissions")
        except Exception:
            raise AccountError("invalid_session", "登录状态已失效，请重新登录。") from None
        boundary = [self.settings.server_url, claims.subject, claims.workspace_id]
        owner = "srv_" + hashlib.sha256(json.dumps(boundary).encode()).hexdigest()
        permissions = tuple(p for p in claims.permissions if p in ("learning", "sync", "members"))
        return Identity(owner, claims.display_name, claims.workspace_id, claims.workspace_name, "server", permissions)


def resolve_user_id(identity: Identity) -> str:
    if not isinstance(identity, Identity) or not identity.user_id:
        raise AccountError("identity_required", "无法确认当前用户。")
    if identity.source not in ("local", "server"):
        raise AccountError("identity_required", "无法确认当前用户。")
    if identity.source == "server" and not identity.user_id.startswith("srv_"):
        raise AccountError("identity_required", "无法确认当前用户。")
    return identity.user_id


def owner_filter(model, identity: Identity):
    return model.user_id == resolve_user_id(identity)


def require_owner(record, identity: Identity):
    if record is None or getattr(record, "user_id", None) != resolve_user_id(identity):
        raise AccountError("not_found", "内容不存在或无法访问。", 404)
    return record


def require_local_desktop(settings: AccountSettings | None = None):
    settings = settings or AccountSettings.from_environment()
    if settings.mode != "local":
        raise RuntimeError("当前桌面页面仍使用本地数据。服务器用户接口已预留；完成全部数据归属迁移前，不能以 server 模式启动桌面应用。")
