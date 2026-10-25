from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import json
import logging
import re
import threading
import uuid

from learning_ext import llm
from learning_ext.text_polish.prompts import PURPOSES, build_prompt


MAX_TEXT_LENGTH = 12_000
MAX_CONTEXT_LENGTH = 800
MAX_OUTPUT_LENGTH = 16_000
MAX_PAYLOAD_LENGTH = 100_000

_LOG = logging.getLogger(__name__)
_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_PROTECTED = re.compile(
    r"(?P<fenced>^[ \t]{0,3}(?P<fence>`{3,}|~{3,})[^\r\n]*"
    r"(?:\r?\n[\s\S]*?(?:^[ \t]{0,3}(?P=fence)[ \t]*(?=\r?$)|\Z)|\Z))"
    r"|(?P<inline>(?P<ticks>`+)[^\r\n]*?(?P=ticks))"
    r"|(?P<url>(?:[A-Za-z][A-Za-z0-9+.-]*://|mailto:|www\.)"
    r"[^\s<>\"`，。！？；、（）【】]+)"
    r"|(?P<mention>(?<![\w@])@[^\s@,，。！？!?;；:<>\"()\[\]{}]+)",
    re.MULTILINE | re.IGNORECASE,
)
_NUMBER = re.compile(r"[+-]?\d+(?:[.,]\d+)*(?:[eE][+-]?\d+)?(?:%|％)?")
_PLACEHOLDER = re.compile(r"⟦KEEP_[^⟧\r\n]*⟧")


class _QuietPolishCall(logging.Filter):
    def __init__(self):
        super().__init__()
        self.thread_id = threading.get_ident()

    def filter(self, record):
        return record.thread != self.thread_id


@contextmanager
def _private_model_call():
    # The shared client logs provider error bodies; suppress only this call's thread.
    logger = logging.getLogger("learning_ext.llm")
    privacy_filter = _QuietPolishCall()
    logger.addFilter(privacy_filter)
    try:
        yield
    finally:
        logger.removeFilter(privacy_filter)


def _protected_spans(text: str):
    for match in _PROTECTED.finditer(text):
        value = match.group()
        if match.group("url"):
            value = value.rstrip(".,;:!?")
            for closing, opening in ((")", "("), ("]", "["), ("}", "{")):
                while value.endswith(closing) and value.count(closing) > value.count(opening):
                    value = value[:-1]
        yield match.start(), match.start() + len(value), value


def _protect(text: str) -> tuple[str, list[tuple[str, str]]]:
    nonce = uuid.uuid4().hex
    while nonce in text:
        nonce = uuid.uuid4().hex
    spans = []
    pieces = []
    position = 0
    for index, (start, end, value) in enumerate(_protected_spans(text)):
        token = f"⟦KEEP_{nonce}_{index}⟧"
        pieces.extend((text[position:start], token))
        spans.append((token, value))
        position = end
    pieces.append(text[position:])
    return "".join(pieces), spans


def _restore(text: str, spans: list[tuple[str, str]]) -> str | None:
    positions = []
    for token, _ in spans:
        if text.count(token) != 1:
            return None
        positions.append(text.index(token))
    if positions != sorted(positions):
        return None
    for token, value in spans:
        text = text.replace(token, value)
    return text


def _reply(request_id: str, *, kind: str, length: int, result: str, **body) -> str:
    _LOG.info("text_polish kind=%s length=%d result=%s", kind, length, result)
    return json.dumps({"id": request_id, **body}, ensure_ascii=False)


def polish_request(payload: str) -> str:
    request_id = ""
    kind = "invalid"
    length = 0

    def fail(message: str, result: str) -> str:
        return _reply(
            request_id, kind=kind, length=length, result=result, ok=False, error=message
        )

    if not isinstance(payload, str) or len(payload) > MAX_PAYLOAD_LENGTH:
        return fail("润色请求无效，请重试。", "invalid_payload")
    try:
        data = json.loads(payload)
    except (ValueError, RecursionError):
        return fail("润色请求无效，请重试。", "invalid_payload")
    if not isinstance(data, dict):
        return fail("润色请求无效，请重试。", "invalid_payload")
    candidate_id = data.get("id")
    if not isinstance(candidate_id, str) or not _REQUEST_ID.fullmatch(candidate_id):
        return fail("润色请求无效，请重试。", "invalid_id")
    request_id = candidate_id
    candidate_kind = data.get("kind")
    if not isinstance(candidate_kind, str) or candidate_kind not in PURPOSES:
        return fail("暂不支持此类文本的润色。", "invalid_kind")
    kind = candidate_kind
    source = data.get("text")
    if not isinstance(source, str):
        return fail("请先输入要润色的文字。", "invalid_text")
    length = len(source)
    if not source.strip():
        return fail("请先输入要润色的文字。", "empty_input")
    if length > MAX_TEXT_LENGTH:
        return fail("文字过长，请缩短到 12000 字以内后重试。", "oversize_input")
    context = data.get("context", "")
    if not isinstance(context, str):
        return fail("润色请求无效，请重试。", "invalid_context")

    protected_source, spans = _protect(source)
    system, prompt = build_prompt(kind, protected_source, context[:MAX_CONTEXT_LENGTH])
    try:
        with _private_model_call():
            output = llm.chat(
                prompt,
                system=system,
                temperature=0.1,
                max_tokens=min(16_384, max(512, len(protected_source) * 2 + 512)),
            )
    except Exception:
        return fail("暂时无法润色，请检查模型配置或稍后重试。原文已保留。", "model_error")
    if not isinstance(output, str) or not output.strip():
        return fail("模型未返回有效文字，请重试。原文已保留。", "empty_output")
    if len(output) > max(MAX_OUTPUT_LENGTH, len(protected_source) * 2):
        return fail("润色结果过长，请重试。原文已保留。", "oversize_output")
    restored = _restore(output.strip(), spans)
    if restored is None:
        return fail("润色结果改动了代码或链接等内容，请重试。原文已保留。", "protected_changed")
    if len(restored) > min(MAX_OUTPUT_LENGTH, max(length * 2, length + 300)):
        return fail("润色结果过长，请重试。原文已保留。", "oversize_output")
    original_spans = [value for _, _, value in _protected_spans(source)]
    result_spans = [value for _, _, value in _protected_spans(restored)]
    if (
        original_spans != result_spans
        or Counter(_NUMBER.findall(source)) != Counter(_NUMBER.findall(restored))
        or Counter(_PLACEHOLDER.findall(source)) != Counter(_PLACEHOLDER.findall(restored))
    ):
        return fail("润色结果改动了代码、链接或数字，请重试。原文已保留。", "content_changed")
    if (
        kind == "question"
        and any(mark in source for mark in "?？")
        and not any(mark in restored for mark in "?？")
    ):
        return fail("润色结果未保留原问题，请重试。原文已保留。", "question_changed")
    if restored == source.strip():
        restored = source
    return _reply(
        request_id,
        kind=kind,
        length=length,
        result="changed" if restored != source else "unchanged",
        ok=True,
        text=restored,
        changed=restored != source,
    )
