from datetime import datetime, timedelta
from sqlmodel import Session, select
from learning_ext.db.models import (LearningProject, KnowledgeNode, ProgressRecord, Card,
    ReviewLog, Quiz, QuizQuestion, QuizAttempt, NodeNote, NodeAnnotation, Task)


def learning_dimensions(session: Session, project_id, user_id="default"):
    project = session.get(LearningProject, project_id) if project_id else None
    pid = project_id if project and project.user_id == user_id else -1
    nodes = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.project_id == pid)).all())
    progress = list(session.exec(select(ProgressRecord).where(ProgressRecord.project_id == pid, ProgressRecord.user_id == user_id)).all())
    reviews = list(session.exec(select(ReviewLog).join(Card, ReviewLog.card_id == Card.id).where(Card.project_id == pid, Card.user_id == user_id, ReviewLog.user_id == user_id)).all())
    attempts = list(session.exec(select(QuizAttempt).join(QuizQuestion, QuizAttempt.question_id == QuizQuestion.id).join(Quiz, QuizQuestion.quiz_id == Quiz.id).where(Quiz.project_id == pid, Quiz.user_id == user_id, QuizAttempt.user_id == user_id)).all())
    notes = list(session.exec(select(NodeNote).where(NodeNote.project_id == pid, NodeNote.user_id == user_id)).all())
    annotations = list(session.exec(select(NodeAnnotation).where(NodeAnnotation.project_id == pid, NodeAnnotation.user_id == user_id)).all())
    tasks = list(session.exec(select(Task).where(Task.project_id == pid)).all())
    times = [p for p in progress if p.metric == "study_minutes" and p.value > 0]
    days = {p.recorded_at.date() for p in times}
    days.update(r.reviewed_at.date() for r in reviews)
    days.update(a.attempted_at.date() for a in attempts)
    today = datetime.utcnow().date()
    cursor = today if today in days else today - timedelta(days=1)
    streak = 0
    while cursor in days:
        streak += 1
        cursor -= timedelta(days=1)
    graded = [a for a in attempts if a.is_correct is not None]
    node_names = {n.id: f"{n.code} {n.title}".strip() for n in nodes}
    lesson_minutes = {}
    for record in times:
        if record.node_id in node_names:
            lesson_minutes[record.node_id] = lesson_minutes.get(record.node_id, 0) + record.value
    labels = {"study_minutes":"学习时长", "lesson_learning":"开始学习", "lesson_mastered":"标记掌握", "lesson_skipped":"跳过课程", "lesson_pending":"重置待学", "lesson_weak":"标记薄弱"}
    events = [{"at":p.recorded_at, "kind":labels.get(p.metric,p.metric), "lesson":node_names.get(p.node_id,"项目"), "value":f"{p.value:g}"} for p in progress]
    ratings = {1:"重来",2:"困难",3:"记住",4:"轻松"}
    events += [{"at":r.reviewed_at,"kind":"复习卡片","lesson":"记忆巩固","value":ratings.get(r.rating,"—")} for r in reviews]
    events += [{"at":a.attempted_at,"kind":"测验作答","lesson":"知识测验","value":"待批改" if a.is_correct is None else "正确" if a.is_correct else "待巩固"} for a in attempts]
    events += [{"at":n.created_at,"kind":"新增笔记","lesson":node_names.get(n.node_id,"项目"),"value":"1"} for n in notes]
    events += [{"at":n.created_at,"kind":"新增批注","lesson":node_names.get(n.node_id,"项目"),"value":"1"} for n in annotations]
    return {
        "total_minutes":sum(p.value for p in times), "active_days":len(days), "streak":streak,
        "review_count":len(reviews), "review_ratings":{name:sum(r.rating==value for r in reviews) for value,name in ratings.items()},
        "quiz_count":len(attempts), "quiz_graded":len(graded), "quiz_pending":len(attempts)-len(graded),
        "accuracy":sum(a.is_correct for a in graded)/len(graded)*100 if graded else None,
        "notes":len(notes), "annotations":len(annotations), "tasks":len(tasks), "tasks_done":sum(t.status=="done" for t in tasks),
        "stages":[{"name":label,"total":sum(n.stage==stage for n in nodes),"done":sum(n.stage==stage and n.status=="mastered" for n in nodes)} for stage,label in [("base","打好基础"),("strengthen","动手练习"),("sprint","综合运用")]],
        "lessons":[{"name":node_names[nid],"minutes":minutes} for nid,minutes in sorted(lesson_minutes.items(),key=lambda row:row[1],reverse=True)[:5]],
        "events":sorted(events,key=lambda item:item["at"],reverse=True),
    }
