from types import SimpleNamespace
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from learning_ext.account.identity import (
    AccountError, AccountSettings, LocalIdentityProvider, ServerIdentityProvider,
    VerifiedSession, owner_filter, require_local_desktop, require_owner, resolve_user_id,
)
from learning_ext.account.routes import register_account_routes


class Verifier:
    def __init__(self, claims=None, error=None):
        self.claims = claims or VerifiedSession("alice", "Alice", "work", "Workspace", time.time() + 120)
        self.error = error
        self.seen = []

    def verify(self, access_token, *, server_url):
        self.seen.append((access_token, server_url))
        if self.error:
            raise self.error
        return self.claims


def test_client(app, address="127.0.0.1"):
    async def transport(scope, receive, send):
        scope = {**scope, "client": (address, 50000)}
        await app(scope, receive, send)
    return TestClient(transport, base_url="http://127.0.0.1")


test_client.__test__ = False


def client(settings=None, verifier=None):
    app = FastAPI()
    register_account_routes(app, settings or AccountSettings(), verifier)
    return test_client(app)


def test_local_account_preserves_existing_owner_and_disables_cloud_features():
    response = client().get("/api/v1/account/context?user_id=someone-else")
    assert response.status_code == 200
    payload = response.json()
    assert payload["identity"]["user"] == {"id": "default", "display_name": "本地用户"}
    assert payload["identity"]["capabilities"] == {"learning": True, "cloud_sync": False, "manage_members": False}
    assert not payload["capabilities"]["multi_user_ui"]
    assert response.headers["cache-control"] == "no-store"


def test_local_mode_does_not_accept_server_token_or_forwarded_identity():
    app_client = client()
    assert app_client.get("/api/v1/account/context", headers={"Authorization": "Bearer secret"}).status_code == 401
    response = app_client.get("/api/v1/account/context", headers={"X-User-ID": "admin", "X-Forwarded-For": "1.2.3.4"})
    assert response.json()["identity"]["user"]["id"] == "default"


def test_local_routes_reject_remote_client_and_untrusted_host():
    app = FastAPI()
    register_account_routes(app, AccountSettings())
    remote = test_client(app, "192.168.1.8")
    assert remote.get("/api/v1/account/context").status_code == 403
    local = client()
    assert local.get("/api/v1/account/status", headers={"Host": "attacker.example"}).status_code == 403


def test_unconfigured_server_never_falls_back_to_local():
    app_client = client(AccountSettings("server"))
    response = app_client.get("/api/v1/account/context")
    assert response.status_code == 503
    assert "identity" not in response.json()
    assert response.json()["connection"]["status"] == "not_connected"
    assert app_client.get("/api/v1/account/status").status_code == 200


def test_server_tokens_are_verified_and_not_returned():
    verifier = Verifier()
    app_client = client(AccountSettings("server", "https://accounts.example/v1"), verifier)
    assert app_client.get("/api/v1/account/context").status_code == 401
    response = app_client.get("/api/v1/account/context?user_id=admin", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200
    assert response.json()["identity"]["user"]["id"].startswith("srv_")
    assert "secret-token" not in response.text
    assert "https://accounts.example" not in response.text
    assert verifier.seen == [("secret-token", "https://accounts.example/v1")]


@pytest.mark.parametrize("header", ["Basic secret", "Bearer", "Bearer ", "Bearer " + "x" * 16385], ids=["basic", "missing", "empty", "oversized"])
def test_invalid_authorization_header_does_not_reach_verifier(header):
    verifier = Verifier()
    response = client(AccountSettings("server", "https://accounts.example"), verifier).get(
        "/api/v1/account/context", headers={"Authorization": header}
    )
    assert response.status_code == 401
    assert not verifier.seen


@pytest.mark.parametrize("expiry", [0, time.time() - 1, float("inf"), float("nan")])
def test_expired_or_invalid_session_is_rejected(expiry):
    provider = ServerIdentityProvider(AccountSettings("server", "https://accounts.example"), Verifier(
        VerifiedSession("alice", "Alice", "work", "Work", expiry)
    ))
    with pytest.raises(AccountError, match="登录状态已失效"):
        provider.resolve("secret")


def test_verifier_failure_does_not_expose_details_or_credentials():
    response = client(AccountSettings("server", "https://accounts.example"), Verifier(error=RuntimeError("token-secret url-private"))).get(
        "/api/v1/account/context", headers={"Authorization": "Bearer token-secret"}
    )
    assert response.status_code == 401
    assert "secret" not in response.text and "private" not in response.text


def test_server_owner_is_isolated_by_server_subject_and_workspace():
    def identity(server="https://one.example", subject="alice", workspace="work"):
        return ServerIdentityProvider(AccountSettings("server", server), Verifier(
            VerifiedSession(subject, "Alice", workspace, "Work", time.time() + 120)
        )).resolve("token")
    identities = [identity(), identity(subject="bob"), identity(workspace="personal"), identity(server="https://two.example")]
    assert len({resolve_user_id(item) for item in identities}) == 4
    assert resolve_user_id(identity()) == resolve_user_id(identities[0])
    record = SimpleNamespace(user_id=identities[0].user_id)
    assert require_owner(record, identities[0]) is record
    with pytest.raises(AccountError) as exc:
        require_owner(record, identities[1])
    assert exc.value.status == 404


def test_owner_filter_matches_local_data_model_without_changing_schema():
    from learning_ext.db.models import LearningProject
    expression = owner_filter(LearningProject, LocalIdentityProvider().resolve())
    assert expression.right.value == "default"
    with pytest.raises(AccountError):
        resolve_user_id(None)


@pytest.mark.parametrize("url", ["http://remote.example", "https://user:password@remote.example", "https://example/?token=secret", "https://example/#token", "file:///tmp/account", "https://example:bad"])
def test_account_server_configuration_rejects_insecure_or_secret_urls(url):
    with pytest.raises(ValueError):
        AccountSettings("server", url)


def test_environment_and_legacy_desktop_guard():
    assert AccountSettings.from_environment({}) == AccountSettings()
    require_local_desktop(AccountSettings())
    with pytest.raises(RuntimeError, match="归属迁移"):
        require_local_desktop(AccountSettings("server", "https://accounts.example"))
    with pytest.raises(ValueError):
        AccountSettings.from_environment({"LE_ACCOUNT_MODE": "unknown"})


def test_route_registration_is_idempotent():
    app = FastAPI()
    register_account_routes(app, AccountSettings())
    register_account_routes(app, AccountSettings())
    assert len([route for route in app.routes if route.path.startswith("/api/v1/account/")]) == 2
