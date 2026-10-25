import asyncio
import copy
import json
import threading
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import BaseModel

from kotaemon.base import AIMessage, HumanMessage, SystemMessage
from kotaemon.llms.chats.endpoint_based import EndpointChatLLM
from kotaemon.llms.chats.openai import (
    AzureChatOpenAI, ChatOpenAI, StructuredOutputChatOpenAI,
)
from learning_ext.chat_compat import configure_chat_compat
from learning_ext.chat_messages import prepare_messages, sanitize_messages


TOOL = {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}


@pytest.fixture(autouse=True)
def install_guard():
    configure_chat_compat()


@pytest.mark.parametrize("content", [None, "", " \n\t", [], {}])
def test_empty_assistant_is_removed_without_mutating_history(content):
    messages = [{"role": "system", "content": "system"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": content},
                {"role": "user", "content": "follow up"}]
    before = copy.deepcopy(messages)
    assert sanitize_messages(messages) == [messages[0], messages[1], messages[3]]
    assert messages == before


@pytest.mark.parametrize("messages", [[], [{"role": "assistant", "content": ""}],
                                      [{"role": "assistant", "content": None, "tool_calls": []}]])
def test_empty_request_is_rejected(messages):
    with pytest.raises(ValueError, match="没有有效消息"):
        sanitize_messages(messages)


def test_preserves_calls_multimodal_and_non_assistant_messages():
    messages = [{"role": "assistant", "content": None, "tool_calls": [TOOL]},
                {"role": "tool", "tool_call_id": "call_1", "content": ""},
                {"role": "assistant", "content": "", "function_call": TOOL["function"]},
                {"role": "assistant", "content": [{"type": "text", "text": "answer"}]},
                {"role": "user", "content": ""}]
    assert sanitize_messages(messages) == messages


def test_real_message_serialization_retains_tool_calls():
    raw = AIMessage(content="", additional_kwargs={"tool_calls": [TOOL]})
    structured = AIMessage(content="", tool_calls=[{"id": "call_1", "name": "lookup", "args": {}}])
    for message in (raw, structured):
        assert prepare_messages(message) == [{"role": "assistant", "content": "", "tool_calls": [TOOL]}]
    assert prepare_messages("hello") == [{"role": "user", "content": "hello"}]
    assert prepare_messages(SystemMessage(content="system")) == [{"role": "system", "content": "system"}]


def test_configuration_is_idempotent():
    original = ChatOpenAI.prepare_params
    configure_chat_compat()
    assert ChatOpenAI.prepare_params is original


@pytest.mark.parametrize("usage", [None, {}, {"prompt_tokens": 2}, {"completion_tokens": 3}])
def test_endpoint_accepts_optional_usage_and_has_bounded_wait(monkeypatch, usage):
    reply = Mock()
    reply.json.return_value = {"choices": [{"message": {"content": "OK"}}], "usage": usage}
    post = Mock(return_value=reply)
    monkeypatch.setattr("requests.post", post)
    result = EndpointChatLLM(endpoint_url="https://example.invalid/chat").invoke("hello")
    assert result.text == "OK"
    assert result.total_tokens == sum((usage or {}).values())
    assert post.call_args.kwargs["timeout"] == (10, 120)
    reply.raise_for_status.assert_called_once()


def test_endpoint_reports_http_failure_before_reading_completion(monkeypatch):
    from requests import HTTPError
    reply = Mock()
    reply.raise_for_status.side_effect = HTTPError("503 Service Unavailable")
    monkeypatch.setattr("requests.post", Mock(return_value=reply))
    with pytest.raises(HTTPError, match="503"):
        EndpointChatLLM(endpoint_url="https://example.invalid/chat").invoke("hello")
    reply.json.assert_not_called()


class Answer(BaseModel):
    answer: str


@pytest.mark.parametrize("cls,extra", [(ChatOpenAI, {}),
                                      (StructuredOutputChatOpenAI, {"response_schema": Answer}),
                                      (AzureChatOpenAI, {"azure_deployment": "test"})])
def test_direct_params_are_guarded_for_every_provider(cls, extra):
    llm = cls(api_key="test", **extra)
    params = llm.prepare_params(messages=[{"role": "assistant", "content": ""},
                                         {"role": "user", "content": "follow up"}], stream=False)
    assert params["messages"] == [{"role": "user", "content": "follow up"}]
    with pytest.raises(ValueError, match="没有有效消息"):
        llm.prepare_params(messages=[], stream=False)


@pytest.fixture
def strict_server():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(data)
            messages = data["messages"]
            invalid = not messages or any(
                m["role"] == "assistant" and not (m.get("content") or "").strip()
                and not m.get("tool_calls") and not m.get("function_call") for m in messages
            )
            self.send_response(400 if invalid else 200)
            streaming = data.get("stream") and not invalid
            self.send_header("Content-Type", "text/event-stream" if streaming else "application/json")
            self.end_headers()
            if invalid:
                result = {"error": {"message": "Invalid assistant message: content or tool_calls must be set"}}
            else:
                result = {"id": "test", "object": "chat.completion", "created": 1, "model": "test",
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"},
                                       "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
            if streaming:
                chunk = {"id": "test", "object": "chat.completion.chunk", "created": 1, "model": "test",
                         "choices": [{"index": 0, "delta": {"content": "OK"}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
            else:
                self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_repeated_followups_reach_strict_server_sync_async_and_stream(strict_server):
    from openai import AsyncOpenAI, OpenAI

    url, received = strict_server
    history = [HumanMessage(content="hello"), AIMessage(content=""), HumanMessage(content="follow up")]
    llm = ChatOpenAI(api_key="test", base_url=url, model="test", max_retries=0)
    assert llm.invoke(history).text == "OK"
    assert llm.invoke(history).text == "OK"
    assert "".join(chunk.text for chunk in llm.stream(history)) == "OK"

    async def run():
        assert (await llm.ainvoke(history)).text == "OK"
        async with AsyncOpenAI(api_key="test", base_url=url, max_retries=0) as client:
            stream = await llm.aopenai_response(client, messages=[
                {"role": "assistant", "content": ""}, {"role": "user", "content": "follow up"}
            ], stream=True)
            assert "".join([chunk.choices[0].delta.content async for chunk in stream]) == "OK"

    asyncio.run(run())
    endpoint = EndpointChatLLM(endpoint_url=url)
    assert endpoint.invoke(history).text == "OK"
    assert asyncio.run(endpoint.ainvoke(history)).text == "OK"
    assert len(received) == 7
    assert all(m["role"] != "assistant" for request in received for m in request["messages"])
    assert history[1].content == ""
    before = len(received)
    for model in (llm, endpoint):
        for bad in ([], [AIMessage(content="")]):
            with pytest.raises(ValueError, match="没有有效消息"):
                model.invoke(bad)
    assert len(received) == before

    with OpenAI(api_key="test", base_url=url, max_retries=0) as client:
        from openai import BadRequestError
        with pytest.raises(BadRequestError, match="Invalid assistant message"):
            client.chat.completions.create(model="test", messages=[{"role": "assistant", "content": ""}])
