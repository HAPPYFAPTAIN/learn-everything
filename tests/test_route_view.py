import queue
import threading

from learning_ext.route_view import preparation_panel, render_route


def test_route_map_escapes_content_and_orders_courses():
    content = render_route({"summary": "<script>alert(1)</script>", "nodes": [
        {"code": "2.10", "title": "<img src=x>", "stage": "strengthen", "est_hours": 2},
        {"code": "2.2", "title": "Second", "stage": "strengthen", "est_hours": 1, "prerequisites": ["1.1"]},
    ]})
    assert '<script>' not in content and '<img' not in content
    assert content.index('[2.2]') < content.index('[2.10]')
    assert 'le-route-course' in content and '前置步骤：1.1' in content
    assert '<strong>3<small> 小时' in content


def test_preparation_panel_does_not_count_failures_as_ready():
    content = preparation_panel('<unsafe>', 10, ready=6, failed=2, running=False)
    assert 'value="6"' in content and 'max="10"' in content
    assert '2 节暂未完成' in content
    assert '&lt;unsafe&gt;' in content and '<unsafe>' not in content
    assert '课程已准备好' not in content


def test_saving_phase_does_not_claim_course_progress():
    content = preparation_panel('Python', 5, phase='saving')
    assert '<progress' not in content
    assert '正在保存你的学习安排' in content


def test_duplicate_preparation_request_returns_without_deadlock(monkeypatch):
    from learning_ext.progress import prep

    monkeypatch.setattr(prep, '_STATE', {})
    monkeypatch.setattr(prep, '_INFLIGHT', set())
    monkeypatch.setattr(prep, '_Q', queue.Queue())
    monkeypatch.setattr(prep, '_ensure_workers', lambda: None)
    results = []

    def enqueue_twice():
        results.append(prep.start(44, [101], 'Topic'))
        results.append(prep.start(44, [101], 'Topic'))

    worker = threading.Thread(target=enqueue_twice, daemon=True)
    worker.start()
    worker.join(2)
    assert not worker.is_alive(), 'Duplicate queue requests must not deadlock'
    assert results[0]['total'] == results[1]['total'] == 1
    assert prep._Q.qsize() == 1
