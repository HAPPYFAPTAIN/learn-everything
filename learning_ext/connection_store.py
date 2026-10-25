from __future__ import annotations

import ctypes
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

from learning_ext.model_platforms import PLATFORMS, connection_error, profile_for


STORE_FILE = Path(__file__).resolve().parent.parent / "ktem_app_data" / "model_connections.dpapi"
_LOCK = threading.RLock()
FIELDS = ("base_url", "api_key", "chat_model", "embed_model")


def _crypt(data: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("本机加密存储目前需要 Windows。")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    fn = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError("无法读取或保存本机加密连接，请使用原 Windows 账户。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def connection_id(provider, base_url):
    identity = provider + "\n" + base_url.strip().rstrip("/")
    return hashlib.sha256(identity.encode()).hexdigest()[:24]


def _read():
    if not STORE_FILE.exists():
        return {}
    data = json.loads(_crypt(STORE_FILE.read_bytes(), decrypt=True))
    if data.get("version") != 1 or not isinstance(data.get("connections"), dict):
        raise ValueError("连接存储格式无法识别。")
    return data["connections"]


def _write(records):
    payload = _crypt(json.dumps({"version": 1, "connections": records}, ensure_ascii=False).encode())
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix="connections-", dir=STORE_FILE.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, STORE_FILE)
    finally:
        Path(path).unlink(missing_ok=True)


def list_connections():
    with _LOCK:
        return list(reversed(list(_read().values())))


def remember(provider, config, verified=False, only_if_missing=False):
    clean = {field: str(config.get(field) or "").strip() for field in FIELDS}
    clean["base_url"] = clean["base_url"].rstrip("/")
    if provider not in PLATFORMS or connection_error(clean["base_url"], clean["api_key"]):
        return None
    if any("\n" in v or "\r" in v for v in clean.values()):
        return None
    key = connection_id(provider, clean["base_url"])
    with _LOCK:
        records = _read()
        old = records.get(key, {})
        if only_if_missing and old:
            return key
        same = all(old.get(field) == clean[field] for field in FIELDS)
        record = {**clean, "id": key, "provider": provider,
                  "verified": bool(verified or (same and old.get("verified")))}
        records.pop(key, None)
        records[key] = record
        _write(records)
    return key


def find_connection(provider=None, base_url=None, record_id=None):
    for record in list_connections():
        if record_id is not None:
            if record["id"] == record_id:
                return record
        elif record["provider"] == provider and (base_url is None or record["base_url"] == base_url.strip().rstrip("/")):
            return record
    return None


def connection_choices(active):
    choices = []
    for record in list_connections():
        provider = record["provider"]
        cfg = PLATFORMS.get(provider)
        if not cfg:
            continue
        profile = profile_for(provider, record["base_url"])
        if profile == "自定义地址":
            profile = "Coding" if "/coding/" in record["base_url"] else record["base_url"].split("://", 1)[-1]
        label = f'{cfg["name"]} · {profile} · {record["chat_model"] or "待选模型"}'
        if all(record.get(field) == active.get(field, "") for field in FIELDS):
            label += " · 使用中"
        choices.append((label, record["id"]))
    return choices
