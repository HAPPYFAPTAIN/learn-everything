import json

import pytest
import requests

from learning_ext.agent import search, web_search


@pytest.fixture(autouse=True)
def disable_native_index(monkeypatch):
    monkeypatch.setenv("LE_EVERYTHING_DISABLED", "1")


def test_file_search_is_bounded_and_skips_dependency_trees(tmp_path):
    (tmp_path / "Readme.MD").write_text("root", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "guide.md").write_text("nested", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "secret.md").write_text("dependency", encoding="utf-8")
    result = search.search_files(str(tmp_path), "*.md", max_depth=0)
    assert [item["relative_path"] for item in result["matches"]] == ["Readme.MD"]
    assert result["truncated"] and result["stop_reason"] == "depth_limit"
    assert result["skipped"]["excluded_directories"] == 1
    result = search.search_files(str(tmp_path), "*.md")
    assert [item["evidence_id"] for item in result["matches"]] == ["file:1", "file:2"]
    assert not result["truncated"]
    assert result["absence_is_not_proof"] and result["untrusted_data"]


def test_file_search_never_follows_links(tmp_path, monkeypatch):
    (tmp_path / "normal.txt").write_text("normal")
    (tmp_path / "linked.txt").write_text("outside")
    monkeypatch.setattr(search, "_linked", lambda entry: entry.name == "linked.txt")
    result = search.search_files(str(tmp_path), "*.txt")
    assert [item["relative_path"] for item in result["matches"]] == ["normal.txt"]
    assert result["skipped"]["links"] == 1


def test_entry_and_result_limits_are_explicit(tmp_path, monkeypatch):
    for index in range(5):
        (tmp_path / f"{index}.txt").write_text("fixture")
    result = search.search_files(str(tmp_path), "*.txt", limit=2)
    assert len(result["matches"]) == 2 and result["stop_reason"] == "result_limit"
    monkeypatch.setattr(search, "MAX_ENTRIES", 3)
    result = search.search_files(str(tmp_path), "*.absent")
    assert result["scanned_entries"] == 3 and result["stop_reason"] == "entry_budget"
    assert result["truncated"] and "完整" in result["next_action"]
    result = search.search_files(str(tmp_path), "*.txt")
    assert len(result["matches"]) == 3 and result["stop_reason"] == "entry_budget"


def test_time_budget_reports_partial_instead_of_absence(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_text("fixture")
    clock = iter([0, 4])
    monkeypatch.setattr(search.time, "monotonic", lambda: next(clock))
    result = search.search_files(str(tmp_path), "*")
    assert result["stop_reason"] == "time_budget" and result["truncated"]


@pytest.mark.parametrize("pattern", ["../*.txt", "sub/*.txt", "..\\*.txt", "", "a\nb"])
def test_filename_pattern_cannot_escape_scope(tmp_path, pattern):
    with pytest.raises(ValueError):
        search.search_files(str(tmp_path), pattern)


def test_rejects_whole_disk_network_and_invalid_budgets(tmp_path):
    for root in [tmp_path.anchor, "\\\\server\\share", "//server/share"]:
        with pytest.raises(ValueError):
            search.search_files(root, "*")
    for settings in [{"limit": 81}, {"limit": True}, {"max_depth": 13}]:
        with pytest.raises(ValueError):
            search.search_files(str(tmp_path), "*", **settings)


def test_text_search_returns_line_evidence_and_ignores_secrets(tmp_path):
    (tmp_path / "guide.md").write_text("Title\nUse Python here\nNo match", encoding="utf-8")
    (tmp_path / "wide.txt").write_text("PYTHON 中文", encoding="utf-16")
    (tmp_path / ".env").write_text("PYTHON=private")
    (tmp_path / "binary.dat").write_bytes(b"\x00PYTHON")
    result = search.search_text(str(tmp_path), "python")
    assert len(result["matches"]) == 2
    assert result["matches"][0]["line"] == 2
    assert result["matches"][0]["snippet"] == "Use Python here"
    assert result["skipped"]["sensitive_files"] == 1
    assert result["skipped"]["binary_files"] == 1
    assert "private" not in json.dumps(result)
    assert not search.search_text(str(tmp_path), "python", case_sensitive=True)["matches"]


def test_text_search_read_budgets_and_snippet_limits(tmp_path, monkeypatch):
    (tmp_path / "guide.txt").write_text("a" * 500 + "TARGET" + "b" * 500)
    result = search.search_text(str(tmp_path), "TARGET")
    assert "TARGET" in result["matches"][0]["snippet"]
    assert len(result["matches"][0]["snippet"]) <= 242
    monkeypatch.setattr(search, "MAX_READ_BYTES", 20)
    result = search.search_text(str(tmp_path), "TARGET")
    assert result["stop_reason"] == "read_budget" and result["truncated"]
    assert result["bytes_read"] <= 20
    monkeypatch.setattr(search, "MAX_FILE_BYTES", 10)
    assert search.search_text(str(tmp_path), "TARGET")["skipped"]["large_files"] == 1


class Response:
    def __init__(self, payload=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(payload).encode()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, chunk_size):
        yield self.raw


class Client:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def service(monkeypatch, payload=None, status=200, raw=None):
    response = Response(payload, status, raw)
    client = Client(response)
    monkeypatch.setenv("LE_SEARCH_URL", "https://search.example.org/base")
    monkeypatch.setattr(web_search.requests, "Session", lambda: client)
    return client


def test_web_search_requires_explicit_service_configuration(monkeypatch):
    monkeypatch.delenv("LE_SEARCH_URL", raising=False)
    monkeypatch.setattr(web_search.requests, "Session", lambda: pytest.fail("Must not call a public service"))
    assert web_search.search_web("Python tutorial")["error"] == "not_configured"
    for endpoint in ["file:///tmp/private", "https://user:secret@example.org", "https://example.org?q=private"]:
        monkeypatch.setenv("LE_SEARCH_URL", endpoint)
        assert web_search.search_web("test")["error"] == "invalid_configuration"


def test_web_results_have_evidence_and_domain_filter_is_enforced(monkeypatch):
    client = service(monkeypatch, {"results": [
        {"title": "<b>Python</b> &amp; venv", "url": "https://docs.python.org/3/library/venv.html#how", "content": "<i>Verified</i> docs"},
        {"title": "Duplicate", "url": "https://docs.python.org/3/library/venv.html#other"},
        {"title": "Wrong domain", "url": "https://docs.python.org.evil.example/"},
        {"title": "Wrong scheme", "url": "javascript:alert(1)"},
        {"title": "Embedded password", "url": "https://secret:password@docs.python.org/"},
    ], "unresponsive_engines": [["one", "timeout"]]})
    result = web_search.search_web("python venv", domains=["python.org"])
    assert len(result["results"]) == 1
    assert result["results"][0] == {"evidence_id": "web:1", "title": "Python & venv", "url": "https://docs.python.org/3/library/venv.html", "domain": "docs.python.org", "snippet": "Verified docs"}
    assert result["partial"] and result["evidence_level"] == "search_snippets_only"
    endpoint, options = client.calls[0]
    assert endpoint == "https://search.example.org/base/search"
    assert options["params"]["format"] == "json" and "site:python.org" in options["params"]["q"]
    assert options["allow_redirects"] is False and options["stream"] is True
    assert client.trust_env is False and client.response.closed


@pytest.mark.parametrize("status,error", [(403, "json_disabled_or_forbidden"), (429, "rate_limited"), (302, "service_error"), (500, "service_error")])
def test_web_search_service_errors_are_actionable(monkeypatch, status, error):
    service(monkeypatch, status=status)
    result = web_search.search_web("Python")
    assert result["error"] == error and not result["ok"] and result["results"] == []


def test_web_search_budgets_invalid_json_and_private_errors(monkeypatch):
    service(monkeypatch, raw=b"x" * (web_search.MAX_RESPONSE_BYTES + 1))
    assert web_search.search_web("Python")["error"] == "response_too_large"
    service(monkeypatch, raw=b"not JSON")
    assert web_search.search_web("Python")["error"] == "invalid_response"
    service(monkeypatch, payload={"results": "bad"})
    assert web_search.search_web("Python")["error"] == "invalid_response"
    client = Client(requests.ConnectionError("private-token-at-url"))
    monkeypatch.setattr(web_search.requests, "Session", lambda: client)
    result = web_search.search_web("Python")
    assert result["error"] == "connection_failed"
    assert "private-token" not in json.dumps(result)


def test_web_result_limit_and_parameter_validation(monkeypatch):
    service(monkeypatch, payload={"results": [{"url": f"https://example.org/{i}", "title": "a" * 1000, "content": "b" * 2000} for i in range(8)]})
    result = web_search.search_web("test", limit=2)
    assert len(result["results"]) == 2 and result["truncated"]
    assert len(result["results"][0]["title"]) == 180 and len(result["results"][0]["snippet"]) == 600
    for values in [{"query": ""}, {"query": "x\ny"}, {"query": "ok", "limit": True}, {"query": "ok", "domains": ["https://example.org"]}, {"query": "ok", "domains": ["*.example.org"]}]:
        with pytest.raises(ValueError):
            web_search.search_web(**values)
