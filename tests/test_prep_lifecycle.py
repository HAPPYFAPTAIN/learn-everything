import queue

import pytest
from sqlmodel import select

from learning_ext.db.models import KnowledgeNode


@pytest.fixture
def prep_queue(monkeypatch):
    from learning_ext.progress import prep

    monkeypatch.setattr(prep, "_STATE", {})
    monkeypatch.setattr(prep, "_INFLIGHT", set())
    monkeypatch.setattr(prep, "_Q", queue.Queue())
    monkeypatch.setattr(prep, "_ensure_workers", lambda: None)
    monkeypatch.setattr(prep.time, "sleep", lambda _: None)
    return prep


def test_retry_replaces_failed_result_without_counting_course_twice(prep_queue, monkeypatch):
    from learning_ext.progress import study

    prep_queue.start(7, [41, 42], "test")
    monkeypatch.setattr(study, "generate_node_summary_to_db", lambda *a, **k: False)
    prep_queue._run(prep_queue._Q.get_nowait())
    assert prep_queue.snapshot(7) == {"total": 2, "done": 1, "failed": [41], "running": True}
    prep_queue.start(7, [41, 42], "test")
    assert prep_queue.snapshot(7) == {"total": 2, "done": 0, "failed": [], "running": True}
    assert prep_queue._Q.qsize() == 2
    monkeypatch.setattr(study, "generate_node_summary_to_db", lambda *a, **k: True)
    prep_queue._run(prep_queue._Q.get_nowait())
    prep_queue._run(prep_queue._Q.get_nowait())
    assert prep_queue.snapshot(7) == {"total": 2, "done": 2, "failed": [], "running": False}
    assert prep_queue.node_status(7, 41) == "done"


@pytest.fixture
def workbench(session, sample_project, monkeypatch, prep_queue):
    import learning_ext.pages.study_workbench as module

    monkeypatch.setattr(module, "engine", session.bind)
    page = object.__new__(module.StudyWorkbenchPage)
    page._pending_node = None
    page._pending_nodes = {}
    page._prep_kicked = set()
    nodes = session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == sample_project.id)).all()
    return page, nodes


def test_reading_prepared_course_cannot_receive_previous_course_poll(workbench):
    page, nodes = workbench
    page._queue_single(nodes[0].id)
    content = "完整课程正文。" * 100
    assert page._ensure_course_content(nodes[1].id, "test", content) == content
    output = page._poll_writing()
    assert page._pending_node is None
    assert "value" not in output[0]
    assert output[2]["active"] is False


def test_returning_to_queued_course_retargets_without_duplicate_job(workbench, prep_queue):
    page, nodes = workbench
    page._queue_single(nodes[0].id)
    page._queue_single(nodes[1].id)
    page._queue_single(nodes[0].id)
    assert page._pending_node == nodes[0].id
    assert prep_queue._Q.qsize() == 2


def test_failed_preparation_stops_polling_and_course_can_retry(workbench, prep_queue, monkeypatch):
    from learning_ext.progress import study

    page, nodes = workbench
    nid = nodes[0].id
    page._queue_single(nid)
    monkeypatch.setattr(study, "generate_node_summary_to_db", lambda *a, **k: False)
    prep_queue._run(prep_queue._Q.get_nowait())
    output = page._poll_writing()
    assert "重试" in output[0]
    assert output[2]["active"] is False
    assert page._pending_node is None
    assert nid not in page._pending_nodes
    page._queue_single(nid)
    assert prep_queue.node_status(nodes[0].project_id, nid) == "pending"
    assert prep_queue._Q.qsize() == 1


def test_deleted_course_stops_polling(workbench, session):
    page, nodes = workbench
    page._pending_node = nodes[0].id
    page._pending_nodes[nodes[0].id] = "waiting"
    session.delete(nodes[0])
    session.commit()
    output = page._poll_writing()
    assert "已移除" in output[0]
    assert output[2]["active"] is False


def test_project_change_clears_previous_course_wait(workbench):
    page, nodes = workbench
    page._queue_single(nodes[0].id)
    page._on_project_change(None)
    assert page._pending_node is None


def test_failed_course_scan_can_retry_on_next_visit(workbench, monkeypatch, prep_queue):
    import learning_ext.pages.study_workbench as module

    page, nodes = workbench
    pid = nodes[0].project_id
    original = module.Session
    calls = []

    def flaky_session(engine):
        calls.append(engine)
        if len(calls) == 1:
            raise RuntimeError("temporary read failure")
        return original(engine)

    monkeypatch.setattr(module, "Session", flaky_session)
    page._kick_project_prep(pid, "test")
    assert pid not in page._prep_kicked
    page._kick_project_prep(pid, "test")
    assert pid in page._prep_kicked
    assert prep_queue._Q.qsize() == len(nodes)

