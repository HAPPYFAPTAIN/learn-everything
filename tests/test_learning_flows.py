from datetime import datetime
from types import SimpleNamespace
import pytest
from sqlmodel import select
from learning_ext.db.models import (
    Card,
    KnowledgeNode,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    ReviewLog,
)
from learning_ext.quiz.service import generate_quiz, grade_answer


def test_invalid_quiz_does_not_save_partial_rows(session, sample_project, monkeypatch):
    import learning_ext.quiz.service as service

    node = session.exec(select(KnowledgeNode)).first()
    monkeypatch.setattr(
        service,
        "chat_json",
        lambda *a, **k: [
            {
                "stem": "Question",
                "answer": "A",
                "qtype": "choice",
                "options": ["A", "B"],
            }
        ],
    )
    with pytest.raises(ValueError):
        generate_quiz(session, "default", [node.id], project_id=sample_project.id)
    assert session.exec(select(Quiz)).all() == []
    assert session.exec(select(QuizQuestion)).all() == []


def test_choice_grading_is_local_and_idempotent(
    session, sample_project, mock_llm, monkeypatch
):
    import learning_ext.quiz.service as service

    node = session.exec(select(KnowledgeNode)).first()
    quiz = generate_quiz(session, "default", [node.id], count=1)
    q = session.exec(
        select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
    ).first()
    assert q.node_id == node.id
    monkeypatch.setattr(
        service,
        "chat_json",
        lambda *a, **k: pytest.fail("Choice grading must not call LLM"),
    )
    first = grade_answer(session, q.id, "B")
    assert first.is_correct is False
    second = grade_answer(session, q.id, "A")
    assert second.id == first.id
    assert len(session.exec(select(QuizAttempt)).all()) == 1
    with pytest.raises(ValueError, match="无权"):
        grade_answer(session, q.id, "A", "another-user")


def test_multiple_nodes_require_valid_question_mapping(
    session, sample_project, mock_llm, monkeypatch
):
    import learning_ext.quiz.service as service

    monkeypatch.setattr(
        service,
        "chat_json",
        lambda *a, **k: [
            {
                "stem": "Question",
                "answer": "Answer",
                "qtype": "short",
                "node_code": "missing",
            }
        ],
    )
    nodes = session.exec(select(KnowledgeNode)).all()
    with pytest.raises(ValueError, match="知识点"):
        generate_quiz(session, "default", [n.id for n in nodes])
    assert session.exec(select(Quiz)).all() == []


def test_review_card_creation_rating_and_next(session, sample_project, monkeypatch):
    import learning_ext.pages.review as page_module

    monkeypatch.setattr(page_module, "engine", session.bind)
    page = object.__new__(page_module.ReviewPage)
    node = session.exec(select(KnowledgeNode)).first()
    assert "已保存" in page._add(str(node.id), "Question 1", "Answer 1")
    assert "已保存" in page._add(str(node.id), "Question 2", "Answer 2")
    first = page._load_next(str(sample_project.id))
    card_id = first[2]
    assert first[1]["visible"] is False
    assert all(update["interactive"] is False for update in first[7:])
    page._rate(card_id, False, str(sample_project.id), 3)
    assert session.exec(select(ReviewLog)).all() == []
    second = page._rate(card_id, True, str(sample_project.id), 3)
    assert second[2] != card_id
    assert second[3] is False
    session.expire_all()
    card = session.get(Card, card_id)
    assert card.reps == 1
    assert card.next_review > datetime.utcnow()
    page._rate(card_id, True, str(sample_project.id), 3)
    assert len(session.exec(select(ReviewLog)).all()) == 1


def test_quiz_ui_submit_and_resume(session, sample_project, mock_llm, monkeypatch):
    import learning_ext.pages.quiz as page_module

    monkeypatch.setattr(page_module, "engine", session.bind)
    page = object.__new__(page_module.QuizPage)
    node = session.exec(select(KnowledgeNode)).first()
    quiz = generate_quiz(
        session, "default", [node.id], project_id=sample_project.id, count=1
    )
    ids = [
        q.id
        for q in session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).all()
    ]
    display = page._display(ids, 0)
    assert display[1]["visible"] is True
    assert display[2]["visible"] is False
    empty = page._submit(ids, 0, None, "")
    assert "填写答案" in empty[0]
    result = page._submit(ids, 0, "A", "")
    assert "回答正确" in result[0]
    assert result[1]["interactive"] is False
    assert result[2]["interactive"] is True
    assert "题1?" in result[3]
    resumed = page._resume(str(sample_project.id))
    assert resumed[0] == ids
    assert resumed[1] == len(ids)
    assert "参考答案" in resumed[3]


def test_route_save_requires_valid_preview():
    from learning_ext.pages.path_generator import PathGeneratorPage

    assert PathGeneratorPage._save_availability("{}")["interactive"] is False
    assert PathGeneratorPage._save_availability("invalid")["interactive"] is False
    assert (
        PathGeneratorPage._save_availability('{"nodes":[{"code":"1"}]}')["interactive"]
        is True
    )


def test_truncated_model_output_is_not_treated_as_complete(monkeypatch):
    import learning_ext.llm.client as client

    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="Partial course"),
            )
        ]
    )
    fake = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    monkeypatch.setattr(client, "_get_client", lambda: (fake, {
        "chat_model": "test", "base_url": "https://example.invalid/v1"
    }))
    with pytest.raises(RuntimeError, match="长度上限"):
        client.chat("synthetic test", max_tokens=100, retries=0)


def test_course_switch_selects_a_real_node(session, sample_project, monkeypatch):
    import learning_ext.pages.study_workbench as module
    from learning_ext.progress import prep

    monkeypatch.setattr(module, "engine", session.bind)
    monkeypatch.setattr(prep, "start", lambda *args, **kwargs: {})
    page = object.__new__(module.StudyWorkbenchPage)
    output = page._on_project_change(str(sample_project.id))
    assert output[1]["value"] is not None
    assert (
        session.get(KnowledgeNode, int(output[1]["value"])).project_id
        == sample_project.id
    )


def test_model_settings_update_both_runtime_pools(monkeypatch):
    import sys
    from learning_ext.pages.quick_setup import _apply_to_runtime

    class Pool(dict):
        def update(self, name, spec, default):
            self[name] = spec

    chat_pool = Pool(openai={})
    embedding_pool = Pool(openai={})
    monkeypatch.setitem(
        sys.modules, "ktem.llms.manager", SimpleNamespace(llms=chat_pool)
    )
    monkeypatch.setitem(
        sys.modules,
        "ktem.embeddings.manager",
        SimpleNamespace(embedding_models_manager=embedding_pool),
    )
    result = _apply_to_runtime(
        "https://example.invalid/v1", "test-only-key", "test-chat", "test-embedding"
    )
    assert result == "ok"
    assert chat_pool["openai"]["model"] == "test-chat"
    assert embedding_pool["openai"]["model"] == "test-embedding"
