from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from learning_ext.db.models import (
    Card,
    DailyReport,
    KnowledgeEdge,
    KnowledgeNode,
    LearningProject,
    NodeAnnotation,
    NodeNote,
    NodeResource,
    ProgressRecord,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    ReviewLog,
    Task,
)


def _delete_rows(session: Session, rows: list[Any]) -> int:
    for row in rows:
        session.delete(row)
    return len(rows)


def _ids(rows: list[Any]) -> list[int]:
    return [row.id for row in rows if row.id is not None]


def _dedupe_by_id(rows: list[Any]) -> list[Any]:
    seen: set[int] = set()
    result = []
    for row in rows:
        if row.id is None or row.id not in seen:
            result.append(row)
            if row.id is not None:
                seen.add(row.id)
    return result


def clear_project_learning_data(
    session: Session, project_id: int, *, commit: bool = True
) -> dict:
    project = session.get(LearningProject, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    nodes = list(
        session.exec(
            select(KnowledgeNode).where(KnowledgeNode.project_id == project_id)
        ).all()
    )
    node_ids = _ids(nodes)

    cards = list(session.exec(select(Card).where(Card.project_id == project_id)).all())
    if node_ids:
        cards.extend(
            session.exec(select(Card).where(Card.node_id.in_(node_ids))).all()
        )
        cards = _dedupe_by_id(cards)
    card_ids = _ids(cards)

    quizzes = list(
        session.exec(select(Quiz).where(Quiz.project_id == project_id)).all()
    )
    if node_ids:
        quizzes.extend(
            session.exec(select(Quiz).where(Quiz.node_id.in_(node_ids))).all()
        )
        quizzes = _dedupe_by_id(quizzes)
    quiz_ids = _ids(quizzes)

    questions: list[QuizQuestion] = []
    if quiz_ids:
        questions.extend(
            session.exec(
                select(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids))
            ).all()
        )
    if node_ids:
        questions.extend(
            session.exec(
                select(QuizQuestion).where(QuizQuestion.node_id.in_(node_ids))
            ).all()
        )
    questions = _dedupe_by_id(questions)
    question_ids = _ids(questions)

    deleted = {
        "review_logs": 0,
        "cards": 0,
        "quiz_attempts": 0,
        "quiz_questions": 0,
        "quizzes": 0,
        "progress_records": 0,
        "daily_reports": 0,
        "tasks": 0,
        "notes": 0,
        "annotations": 0,
        "resources": 0,
        "edges": 0,
        "nodes": 0,
        "projects": 0,
    }

    if card_ids:
        deleted["review_logs"] = _delete_rows(
            session,
            list(
                session.exec(
                    select(ReviewLog).where(ReviewLog.card_id.in_(card_ids))
                ).all()
            ),
        )
    deleted["cards"] = _delete_rows(session, cards)

    if question_ids:
        deleted["quiz_attempts"] = _delete_rows(
            session,
            list(
                session.exec(
                    select(QuizAttempt).where(
                        QuizAttempt.question_id.in_(question_ids)
                    )
                ).all()
            ),
        )
    deleted["quiz_questions"] = _delete_rows(session, questions)
    deleted["quizzes"] = _delete_rows(session, quizzes)

    deleted["progress_records"] = _delete_rows(
        session,
        list(
            session.exec(
                select(ProgressRecord).where(ProgressRecord.project_id == project_id)
            ).all()
        ),
    )
    deleted["daily_reports"] = _delete_rows(
        session,
        list(
            session.exec(
                select(DailyReport).where(DailyReport.project_id == project_id)
            ).all()
        ),
    )
    deleted["tasks"] = _delete_rows(
        session,
        list(session.exec(select(Task).where(Task.project_id == project_id)).all()),
    )
    deleted["notes"] = _delete_rows(
        session,
        list(
            session.exec(select(NodeNote).where(NodeNote.project_id == project_id)).all()
        ),
    )
    deleted["annotations"] = _delete_rows(
        session,
        list(
            session.exec(
                select(NodeAnnotation).where(NodeAnnotation.project_id == project_id)
            ).all()
        ),
    )
    deleted["resources"] = _delete_rows(
        session,
        list(
            session.exec(
                select(NodeResource).where(NodeResource.project_id == project_id)
            ).all()
        ),
    )
    deleted["edges"] = _delete_rows(
        session,
        list(
            session.exec(
                select(KnowledgeEdge).where(KnowledgeEdge.project_id == project_id)
            ).all()
        ),
    )
    deleted["nodes"] = _delete_rows(session, nodes)
    if commit:
        session.commit()

    return {"project_id": project_id, "deleted": deleted}


def delete_project(session: Session, project_id: int) -> dict:
    project = session.get(LearningProject, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    result = clear_project_learning_data(session, project_id, commit=False)
    result["deleted"]["projects"] = _delete_rows(session, [project])
    session.commit()

    return result


def delete_projects(session: Session, project_ids: list[int], user_id: str = "default") -> dict:
    ids = sorted(set(int(value) for value in project_ids))
    if not ids or len(ids) > 100:
        raise ValueError("请选择 1 至 100 条学习路线。")
    projects = [session.get(LearningProject, pid) for pid in ids]
    if any(project is None or project.user_id != user_id for project in projects):
        raise ValueError("部分路线已不存在或不属于当前用户，请刷新后重试。")
    try:
        for project in projects:
            clear_project_learning_data(session, project.id, commit=False)
            session.delete(project)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"project_ids": ids, "count": len(ids)}
