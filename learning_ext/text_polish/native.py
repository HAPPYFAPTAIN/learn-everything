from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import sys


RESULT_PREFIX = "__LE_POLISH_RESULT__:"
MAX_INPUT = 131072
MAX_TEXT = 12000
ERROR = "暂时无法润色，请检查模型配置后重试。"


def handle_request(raw: str) -> dict:
    request_id = ""
    try:
        request = json.loads(raw)
        if not isinstance(request, dict):
            raise ValueError
        request_id = request.get("id", "")
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 80:
            request_id = ""
            raise ValueError
        text = request.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError
        from learning_ext.text_polish.service import polish_request

        result = json.loads(polish_request(json.dumps(
            {"id": request_id, "text": text, "kind": "goal"}, ensure_ascii=False
        )))
        polished = result.get("text")
        if (result.get("ok") is not True or result.get("id") != request_id
                or not isinstance(polished, str) or not polished.strip()
                or len(polished) > MAX_TEXT):
            raise ValueError
        return {"id": request_id, "ok": True, "text": polished,
                "error": "", "changed": polished != text}
    except Exception:
        return {"id": request_id, "ok": False, "text": "", "error": ERROR, "changed": False}


def run(source, output) -> None:
    raw = source.read(MAX_INPUT + 1)
    with open(os.devnull, "w", encoding="utf-8") as quiet:
        with contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
            result = handle_request(raw) if len(raw) <= MAX_INPUT else {
                "id": "", "ok": False, "text": "", "error": ERROR, "changed": False
            }
    output.write(RESULT_PREFIX + json.dumps(result, ensure_ascii=False) + "\n")
    output.flush()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.stdin.reconfigure(encoding="utf-8-sig")
    sys.stdout.reconfigure(encoding="utf-8")
    run(sys.stdin, sys.stdout)
