import json
from types import SimpleNamespace

from learning_ext.text_polish_ui import TextPolishUI, mark_fields


def field(classes=None):
    return SimpleNamespace(elem_classes=classes or [])


def test_marks_user_prose_without_touching_credentials_or_control_fields():
    topic, key, url, code, deletion, note, answer, composer, group = [field() for _ in range(9)]
    app = SimpleNamespace(
        onboarding_page=SimpleNamespace(topic=topic),
        quick_setup_page=SimpleNamespace(api_key=key, base_url=url),
        learning_workbench_page=SimpleNamespace(
            add_code=code, delete_confirm=deletion, note_input=note, gate_ans1=answer
        ),
        chat_page=SimpleNamespace(chat_panel=SimpleNamespace(text_input=composer)),
        _index_1=SimpleNamespace(group_name=group),
    )
    mark_fields(app)
    mark_fields(app)
    assert topic.elem_classes == ["le-polishable", "le-polish-kind-goal"]
    assert note.elem_classes == ["le-polishable", "le-polish-kind-note"]
    assert answer.elem_classes == ["le-polishable", "le-polish-kind-answer"]
    assert composer.elem_classes == ["le-polishable", "le-polish-kind-question"]
    assert group.elem_classes == ["le-polishable", "le-polish-kind-title"]
    assert all(not item.elem_classes for item in [key, url, code, deletion])


def test_transport_escapes_model_markup(monkeypatch):
    from learning_ext.text_polish import service

    monkeypatch.setattr(service, "polish_request", lambda payload: json.dumps(
        {"id": "test", "ok": True, "text": '<img src=x onerror="oops">'}
    ))
    html = TextPolishUI.run("request")
    assert "<img" not in html
    assert "&lt;img" in html
    assert "data-le-polish-response" in html
