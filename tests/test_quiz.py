"""测验 service 测试。"""

from __future__ import annotations

import pytest
from sqlmodel import select

from learning_ext.db.models import KnowledgeNode, QuizAttempt, QuizQuestion
from learning_ext.quiz import generate_quiz, get_weak_nodes, grade_answer


class TestGenerateQuiz:
    def test_generates_quiz_with_questions(self, session, sample_project, mock_llm):
        node = session.exec(select(KnowledgeNode)).first()
        quiz = generate_quiz(
            session,
            "default",
            [node.id],
            project_id=sample_project.id,
            count=1,
            qtype="choice",
        )
        assert quiz.id is not None
        assert quiz.user_id == "default"
        questions = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).all()
        assert len(questions) >= 1

    def test_empty_node_ids_raises(self, session):
        with pytest.raises(ValueError, match="未找到"):
            generate_quiz(session, "default", [])

    def test_nonexistent_node_ids_raises(self, session):
        with pytest.raises(ValueError, match="未找到"):
            generate_quiz(session, "default", [99999])


class TestGradeAnswer:
    def test_grade_records_attempt(self, session, sample_project, mock_llm):
        node = session.exec(select(KnowledgeNode)).first()
        quiz = generate_quiz(
            session,
            "default",
            [node.id],
            project_id=sample_project.id,
            count=1,
        )
        q = session.exec(
            select(QuizQuestion).where(QuizQuestion.quiz_id == quiz.id)
        ).first()
        attempt = grade_answer(session, q.id, "A", "default")
        assert attempt.user_answer == "A"
        assert attempt.is_correct is True  # mock 返回 correct
        assert attempt.feedback

    def test_grade_nonexistent_question(self, session):
        with pytest.raises(ValueError, match="not found|不存在"):
            grade_answer(session, 99999, "x", "default")


class TestGetWeakNodes:
    def test_returns_low_mastery_nodes(self, session, sample_project):
        # 把一个节点 mastery 设低
        node = session.exec(select(KnowledgeNode)).first()
        node.mastery = 0.1
        session.add(node)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.5)
        assert any(n.id == node.id for n in weak)

    def test_excludes_mastered(self, session, sample_project):
        node = session.exec(select(KnowledgeNode)).first()
        node.mastery = 0.1
        node.status = "mastered"
        session.add(node)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.5)
        assert not any(n.id == node.id for n in weak)

    def test_ordered_by_mastery_asc(self, session, sample_project):
        nodes = session.exec(select(KnowledgeNode)).all()
        nodes[0].mastery = 0.5
        nodes[1].mastery = 0.1
        nodes[2].mastery = 0.3
        session.add_all(nodes)
        session.commit()
        weak = get_weak_nodes(session, sample_project.id, threshold=0.6)
        masteries = [n.mastery for n in weak]
        assert masteries == sorted(masteries)
