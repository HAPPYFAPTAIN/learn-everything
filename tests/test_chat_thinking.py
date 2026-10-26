import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from learning_ext import chat_thinking
from learning_ext.chat_compat import configure_chat_compat


def test_preferences_default_and_validation():
    assert chat_thinking.normalize_preferences(None) == {"effort": "low", "show_thinking": False}
    assert chat_thinking.normalize_preferences({"effort": "max"}) == {"effort": "max", "show_thinking": False}
    assert chat_thinking.normalize_preferences({"show_thinking": True}) == {"effort": "low", "show_thinking": True}
    for bad, message in [
        ({"effort": "medium", "show_thinking": False}, "思考强度"),
        ({"effort": "low", "show_thinking": 1}, "开关"),
        ({"effort": "low", "show_thinking": False, "logprobs": True}, "未知设置"),
        ("low", "应为"),
        (5, "应为"),
    ]:
        with pytest.raises(ValueError, match=message):
            chat_thinking.normalize_preferences(bad)


def test_effort_only_exists_for_supported_models():
    for model in ("kimi-k3.1-pro", "Kimi-K3.1", "moonshot/kimi-k3.1-pro", "glm-5.3", "glm-5.3-flash"):
        assert chat_thinking.supports_effort(model)
        assert chat_thinking.effort_for(model, "max") == "max"
        assert chat_thinking.effort_for(model, None) == "low"
        assert chat_thinking.effort_for(model, "medium") == "low"
    for model in ("kimi-k3", "glm-5", "minimax-m3.1", "deepseek-chat", "", None):
        assert not chat_thinking.supports_effort(model)
        assert chat_thinking.effort_for(model, "max") is None
        assert "reasoning_effort" not in chat_thinking.apply_effort({"model": model}, model, "max")


def test_thinking_html_is_escaped_and_blank_reasoning_is_ignored():
    html = chat_thinking.thinking_html("先看 <script>alert(1)</script> & 再答")
    assert html.startswith('<details class="le-reasoning"><summary>思考过程</summary><blockquote>')
    assert html.endswith("</blockquote></details>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html and "&amp;" in html
    assert chat_thinking.thinking_html("   ") == ""
    assert chat_thinking.thinking_html(None) == ""


def test_strip_reasoning_prefix_removes_only_our_leading_block():
    html = chat_thinking.thinking_html("思考 </blockquote></details> 伪造")
    assert chat_thinking.strip_reasoning_prefix(f"{html}\n\n真正回答") == "真正回答"
    assert chat_thinking.strip_reasoning_prefix(f"{html}真正回答") == "真正回答"
    assert chat_thinking.strip_reasoning_prefix(html) == ""
    assert chat_thinking.strip_reasoning_prefix(f"\n{html}\n真正回答") == "真正回答"

    foreign = "<details><summary>思考过程</summary><blockquote>别的内容</blockquote></details>"
    other_class = '<details class="evidence"><summary>思考过程</summary><blockquote>别的内容</blockquote></details>'
    in_middle = f"回答在前{html}"
    for value in (foreign, other_class, in_middle, "普通回答", ""):
        assert chat_thinking.strip_reasoning_prefix(value) == value
    assert chat_thinking.strip_reasoning_prefix(None) is None


def test_preferences_context_is_isolated_and_restored():
    assert chat_thinking.current_preferences() == {"effort": "low", "show_thinking": False}
    with chat_thinking.using({"effort": "high", "show_thinking": True}):
        assert chat_thinking.current_preferences() == {"effort": "high", "show_thinking": True}
        with chat_thinking.using({"effort": "max", "show_thinking": False}):
            assert chat_thinking.current_preferences()["effort"] == "max"
        assert chat_thinking.current_preferences()["effort"] == "high"
    assert chat_thinking.current_preferences() == {"effort": "low", "show_thinking": False}


def test_state_helpers_are_lenient():
    state = {}
    chat_thinking.remember(state, {"effort": "high", "show_thinking": True})
    assert state == {"learning_chat_thinking": {"effort": "high", "show_thinking": True}}
    assert chat_thinking.from_state(state) == {"effort": "high", "show_thinking": True}
    assert chat_thinking.from_state({}) == {"effort": "low", "show_thinking": False}
    assert chat_thinking.from_state({"learning_chat_thinking": {"effort": "bad"}}) == {"effort": "low", "show_thinking": False}
    assert chat_thinking.from_state(None) == {"effort": "low", "show_thinking": False}
    chat_thinking.remember(None, {"effort": "max"})


def chunk(delta, finish=None, logprobs=None):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "kimi-k3.1-pro",
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": finish, "logprobs": logprobs}
        ],
    }


def test_stream_without_reasoning_is_returned_untouched():
    from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

    plain = [ChatCompletionChunk(**chunk({"content": "答案"})), ChatCompletionChunk(**chunk({}, finish="stop"))]
    assert list(chat_thinking.stream_with_thinking(plain)) == plain
    assert list(chat_thinking.render_text_stream(plain)) == ["答案"]


@pytest.fixture(autouse=True)
def install_compat():
    configure_chat_compat()


@pytest.fixture
def model_server():
    state = {"chunks": [], "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(body)
            if not body.get("stream"):
                answer = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body.get("model", "test"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "答案",
                                "reasoning_content": "直连思考",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(answer).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for item in state["chunks"]:
                self.wfile.write(b"data: " + json.dumps(item).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/v1"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def stream_text(model_server, model="kimi-k3.1-pro", preferences=None):
    from kotaemon.base import HumanMessage
    from kotaemon.llms.chats.openai import ChatOpenAI

    llm = ChatOpenAI(api_key="test", base_url=model_server["url"], model=model, max_retries=0)
    with chat_thinking.using(preferences):
        pieces = list(llm.stream([HumanMessage(content="hi")]))
    return pieces, model_server["requests"][-1]


def test_saved_token_preferences_drive_the_real_request(model_server, monkeypatch):
    from kotaemon.base import HumanMessage

    from learning_ext import chat_connections as connections

    record = dict(provider="kimi", api_key="secret", base_url=model_server["url"], chat_model="kimi-k3.1-pro")
    monkeypatch.setattr(connections.connection_store, "find_connection", lambda **kw: record)
    token = connections.model_token("record-one", "kimi-k3.1-pro", {"effort": "max", "show_thinking": True})
    llm, preferences = connections.selection_for(token)
    model_server["chunks"] = [
        chunk({"content": None, "reasoning_content": "来自 token 的思考"}),
        chunk({"content": "答案"}),
        chunk({}, finish="stop"),
    ]
    with chat_thinking.using(preferences):
        pieces = list(llm.stream([HumanMessage(content="hi")]))
    texts = [piece.text for piece in pieces]
    assert texts[0] == '<details class="le-reasoning"><summary>思考过程</summary><blockquote>来自 token 的思考</blockquote></details>'
    assert texts[1] == "答案"
    assert model_server["requests"][-1]["reasoning_effort"] == "max"


def test_real_stream_separates_thinking_from_answer(model_server):
    model_server["chunks"] = [
        chunk({"role": "assistant", "content": None}),
        chunk({"content": None, "reasoning_content": "先想 <一步>，"}),
        chunk({"content": None, "reasoning_content": "再看资料。"}),
        chunk({"content": "OK"}, logprobs={"content": [{"token": "OK", "logprob": -0.1, "bytes": None, "top_logprobs": []}]}),
        chunk({"content": " 完成"}, logprobs={"content": [{"token": " 完成", "logprob": -0.2, "bytes": None, "top_logprobs": []}]}),
        chunk({}, finish="stop"),
    ]
    pieces, request = stream_text(model_server, preferences={"effort": "high", "show_thinking": True})
    texts = [piece.text for piece in pieces]
    assert texts[0] == (
        '<details class="le-reasoning"><summary>思考过程</summary><blockquote>先想 &lt;一步&gt;，再看资料。</blockquote></details>'
    )
    assert "".join(texts[1:]) == "OK 完成"
    assert "".join(texts).count("OK") == 1
    assert pieces[0].logprobs == []
    assert pieces[1].logprobs == [-0.1] and pieces[2].logprobs == [-0.2]
    assert request["reasoning_effort"] == "high"
    assert "extra_body" not in request


def test_thinking_disabled_keeps_answer_only(model_server):
    model_server["chunks"] = [
        chunk({"content": None, "reasoning_content": "隐藏的推理"}),
        chunk({"content": "答案"}),
        chunk({}, finish="stop"),
    ]
    pieces, request = stream_text(model_server, preferences={"effort": "high", "show_thinking": False})
    assert "".join(piece.text for piece in pieces) == "答案"
    assert all("details" not in piece.text for piece in pieces)
    assert request["reasoning_effort"] == "high"


def test_same_chunk_with_thinking_and_answer(model_server):
    model_server["chunks"] = [
        chunk({"content": "答案", "reasoning_content": "同块思考"}),
        chunk({}, finish="stop"),
    ]
    pieces, _ = stream_text(model_server, preferences={"effort": "low", "show_thinking": True})
    texts = [piece.text for piece in pieces]
    assert texts == [
        '<details class="le-reasoning"><summary>思考过程</summary><blockquote>同块思考</blockquote></details>',
        "答案",
    ]


def test_reasoning_only_still_renders_thinking_block(model_server):
    model_server["chunks"] = [
        chunk({"content": None, "reasoning_content": "只有推理"}),
        chunk({}, finish="stop"),
    ]
    pieces, _ = stream_text(model_server, preferences={"effort": "max", "show_thinking": True})
    assert [piece.text for piece in pieces] == [
        '<details class="le-reasoning"><summary>思考过程</summary><blockquote>只有推理</blockquote></details>'
    ]


def test_unsupported_model_never_receives_effort_but_can_show_thinking(model_server):
    model_server["chunks"] = [
        chunk({"content": None, "reasoning_content": "可见"}),
        chunk({"content": "答案"}),
        chunk({}, finish="stop"),
    ]
    pieces, request = stream_text(model_server, model="deepseek-chat", preferences={"effort": "max", "show_thinking": True})
    assert "reasoning_effort" not in request
    assert [piece.text for piece in pieces][0].startswith('<details class="le-reasoning">')
    assert pieces[-1].text == "答案"


def test_direct_client_stream_uses_effort_and_thinking(model_server, monkeypatch):
    from openai import OpenAI

    from learning_ext.llm import client as module

    model_server["chunks"] = [
        chunk({"content": None, "reasoning_content": "直连思考"}),
        chunk({"content": "直连答案"}),
        chunk({}, finish="stop"),
    ]
    monkeypatch.setattr(
        module,
        "_get_client",
        lambda: (OpenAI(api_key="test", base_url=model_server["url"], max_retries=0), {"base_url": model_server["url"], "chat_model": "kimi-k3.1-pro"}),
    )
    pieces = list(module.chat("hi", stream=True, effort="max", show_thinking=True))
    assert pieces == [
        '<details class="le-reasoning"><summary>思考过程</summary><blockquote>直连思考</blockquote></details>',
        "直连答案",
    ]
    assert model_server["requests"][-1]["reasoning_effort"] == "max"

    monkeypatch.setattr(
        module,
        "_get_client",
        lambda: (OpenAI(api_key="test", base_url=model_server["url"], max_retries=0), {"base_url": model_server["url"], "chat_model": "glm-5.3"}),
    )
    assert list(module.chat("hi", stream=True)) == ["直连答案"]
    assert model_server["requests"][-1]["model"] == "glm-5.3"
    assert model_server["requests"][-1]["reasoning_effort"] == "low"


def test_direct_client_non_stream_can_show_thinking(model_server, monkeypatch):
    from openai import OpenAI

    from learning_ext.llm import client as module

    monkeypatch.setattr(
        module,
        "_get_client",
        lambda: (OpenAI(api_key="test", base_url=model_server["url"], max_retries=0), {"base_url": model_server["url"], "chat_model": "kimi-k3.1-pro"}),
    )
    answer = module.chat("hi", effort="high", show_thinking=True)
    assert answer == '<details class="le-reasoning"><summary>思考过程</summary><blockquote>直连思考</blockquote></details>\n\n答案'
    assert model_server["requests"][-1]["reasoning_effort"] == "high"
    assert module.chat("hi", effort="high") == "答案"


def test_direct_client_rejects_bad_preferences(model_server, monkeypatch):
    from learning_ext.llm import client as module

    monkeypatch.setattr(module, "_get_client", lambda: (_ for _ in ()).throw(AssertionError("must validate first")))
    with pytest.raises(ValueError, match="思考强度"):
        module.chat("hi", effort="ultra")
    with pytest.raises(ValueError, match="开关"):
        module.chat("hi", show_thinking="yes")
