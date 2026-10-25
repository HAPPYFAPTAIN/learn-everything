"""备课队列：后台把每一节的教学内容写好，带进度。

设计取舍：
* 全局一个队列 + 2 个常驻工作线程，而不是每次开一个线程池——避免重复开线程、
  也避免同一节被两个线程同时生成。
* 同一节点在用集合 `_INFLIGHT` 去重；进度按项目统计，界面轮询 `status_md()`。
* 失败重试一次（很多失败是 LLM 偶发超时），仍失败就记下来，界面提示可重写。
"""

from __future__ import annotations

import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

_WORKERS = 2
_Q: "queue.Queue[tuple]" = queue.Queue()
_LOCK = threading.RLock()
_STATE: dict[int, dict] = {}
_INFLIGHT: set[tuple[int, int]] = set()
_STARTED = False


def _ensure_workers() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True
    for i in range(_WORKERS):
        threading.Thread(target=_loop, name=f"le-prep-{i}", daemon=True).start()
    logger.info("备课队列已启动，工作线程 %d 个", _WORKERS)


def _loop() -> None:
    while True:
        job = _Q.get()
        try:
            _run(job)
        except Exception:  # noqa: BLE001
            logger.exception("备课任务异常")
        finally:
            _Q.task_done()


def _run(job: tuple) -> None:
    pid, nid, topic, opts = job
    from learning_ext.progress.study import generate_node_summary_to_db
    from learning_ext.llm.request_gate import background_requests

    ok = False
    for attempt in range(2):
        try:
            with background_requests():
                ok = generate_node_summary_to_db(
                    nid,
                    topic,
                    force=bool(opts.get("force")),
                    learning_goal=opts.get("goal", ""),
                    environment_context=opts.get("env", ""),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("备课 node#%s 第 %d 次失败: %s", nid, attempt + 1, exc)
            ok = False
        if ok:
            break
        time.sleep(2)

    with _LOCK:
        state = _STATE.get(int(pid))
        if state is not None:
            state[int(nid)] = "done" if ok else "failed"
        _INFLIGHT.discard((int(pid), int(nid)))
    logger.info("[备课] %s node#%s %s", pid, nid, "OK" if ok else "FAIL")


def start(
    project_id: int | None,
    node_ids: list[int] | None,
    topic: str = "",
    *,
    goal: str = "",
    env: str = "",
    force: bool = False,
) -> dict:
    """把若干节丢进后台备课。重复调用安全（同一节只会排一次队）。"""
    if not project_id or not node_ids:
        return {}
    pid = int(project_id)
    _ensure_workers()
    fresh: list[int] = []
    with _LOCK:
        state = _STATE.setdefault(pid, {})
        for raw in node_ids:
            try:
                nid = int(raw)
            except (TypeError, ValueError):
                continue
            if nid <= 0:
                continue
            key = (pid, nid)
            if key in _INFLIGHT:
                continue
            _INFLIGHT.add(key)
            state[nid] = "pending"
            fresh.append(nid)
        if not fresh:
            return snapshot(pid)
    for nid in fresh:
        _Q.put((pid, nid, topic, {"goal": goal, "env": env, "force": force}))
    logger.info("[备课] 项目#%s 新排 %d 节（共 %d）", pid, len(fresh), snapshot(pid).get("total"))
    return snapshot(pid)


def snapshot(project_id: int | None) -> dict:
    if not project_id:
        return {}
    with _LOCK:
        state = _STATE.get(int(project_id))
        if not state:
            return {}
        return {
            "total": len(state),
            "done": sum(value != "pending" for value in state.values()),
            "failed": [nid for nid, value in state.items() if value == "failed"],
            "running": any(value == "pending" for value in state.values()),
        }


def node_status(project_id: int, node_id: int) -> str:
    with _LOCK:
        return _STATE.get(int(project_id), {}).get(int(node_id), "")


def is_busy(project_id: int | None) -> bool:
    return bool(snapshot(project_id).get("running"))


def status_md(project_id: int | None) -> str:
    """给界面的一行进度文案；没有在备课就返回空串。"""
    snap = snapshot(project_id)
    if not snap or not snap.get("total"):
        return ""
    total, done, failed = snap["total"], snap["done"], snap["failed"]
    if snap["running"]:
        return f"⏳ 正在备课 {done}/{total}：可以先去读已经写好的章节，后面的会自动补上。"
    if failed:
        return f"✅ 备课完成 {total - len(failed)}/{total}，还有 {len(failed)} 节没写成，可以在工作台里让我重写。"
    return f"✅ 备课完成 {total}/{total}，可以直接开始学了。"
