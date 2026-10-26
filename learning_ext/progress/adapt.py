"""课程适配度调整：按已学情况重排「还没学的那部分」。

和旧的「批量审计旧路线」最大的区别：
* 旧功能把整个项目清空重建（笔记、卡片、进度全没）；
* 这里只动**调整起点之后**的节点，起点之前的节点 id、内容、学习数据一律不动。

一次模型调用同时产出「诊断」和「后段方案」，用户确认后才落库。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from learning_ext.db.models import (
    Card,
    KnowledgeEdge,
    KnowledgeNode,
    LearningProject,
    NodeAnnotation,
    NodeNote,
    ProgressRecord,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    ReviewLog,
)
from learning_ext.llm import chat_json
from learning_ext.progress.study import course_code_sort_key

logger = logging.getLogger(__name__)

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent.parent / "kotaemon" / "ktem_app_data" / "adapt_snapshots"

SYSTEM = """你是一位学习教练，负责根据学生的真实学习表现，调整其**尚未学习**的后续课程安排。

硬性要求：
1. 只能调整「待调整区」的节点；「已学区」的节点是事实，不许修改、不许重排、不许删除。
2. 待调整区的第一个节点的编号必须紧接已学区最后一个编号（这一步由程序处理，你只负责内容）。
3. 如果学生学得慢或者掌握不牢，就把后面的内容**拆细、放缓、增加复习与练习**；
   如果学得快且掌握牢固，就**合并重复内容、提高难度、减少理论铺垫**。
4. 必须结合给出的复习正确率与测验正确率，指出具体薄弱点，并把补强安排进后段。
5. 数据不足时（已学节数少、测验次数少），必须明确说明"样本不足，判断仅供参考"，不要编造精确结论。

输出 JSON：
{
  "diagnosis": "3-6 句中文诊断，要有具体数字，指出节奏、牢固度、薄弱点",
  "pace": "偏快|正常|偏慢|样本不足",
  "confidence": "高|中|低",
  "weak_points": ["具体薄弱点，最多 4 条"],
  "changes": ["这次打算怎么调整，最多 5 条"],
  "nodes": [
    {
      "title": "节点标题",
      "description": "这个知识点要学什么、学到什么程度（1-3 句）",
      "stage": "base|strengthen|sprint",
      "est_hours": 2.0,
      "difficulty": 3,
      "prereq": [0]
    }
  ]
}

nodes 是**完整的新后段列表**，按学习顺序排列；prereq 用列表下标（0 = 新后段的第一个节点，也可以是 -1 表示"已学区最后一个节点"）。
只返回 JSON。"""

USER_TEMPLATE = """【学习主题】{topic}
【学习目标】{goal}
【每周可投入】{weekly_hours} 小时
【项目开始至今】{days} 天

【已学区（不可改动）】
{before_text}

【待调整区（当前计划，共 {after_count} 节）】
{after_text}

【学习数据】
{signal_text}

【学生补充要求】
{user_note}

请输出诊断与新的待调整区。"""


# ---------------------------------------------------------------- 数据采集


def _local(dt) -> str:
    if not dt:
        return "未知"
    try:
        return dt.replace(tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d")
    except Exception:
        return str(dt)[:10]


def split_nodes(session: Session, project_id: int, start_code: str):
    """按起点把节点切成「已学区」和「待调整区」。"""
    nodes = list(
        session.exec(
            select(KnowledgeNode).where(KnowledgeNode.project_id == int(project_id))
        ).all()
    )
    nodes.sort(key=lambda n: course_code_sort_key(n.code or ""))
    idx = next((i for i, n in enumerate(nodes) if (n.code or "") == start_code), len(nodes))
    return nodes[:idx], nodes[idx:]


def collect_signals(session: Session, project_id: int, start_code: str) -> dict:
    """把分散在四张表里的学习痕迹收成一份可读数据。"""
    project = session.get(LearningProject, int(project_id))
    before, after = split_nodes(session, project_id, start_code)

    before_ids = [n.id for n in before]
    after_ids = [n.id for n in after]

    def _counts(model, col, ids):
        if not ids:
            return {}
        rows = session.exec(select(model).where(col.in_(ids))).all()
        out: dict[int, int] = {}
        for r in rows:
            nid = getattr(r, "node_id", None)
            if nid:
                out[nid] = out.get(nid, 0) + 1
        return out

    notes = _counts(NodeNote, NodeNote.node_id, before_ids)
    annos = _counts(NodeAnnotation, NodeAnnotation.node_id, before_ids)

    # 复习：卡片 + 评分分布
    cards = []
    if before_ids:
        cards = list(
            session.exec(select(Card).where(Card.node_id.in_(before_ids))).all()
        )
    card_ids = [c.id for c in cards]
    logs = []
    if card_ids:
        logs = list(
            session.exec(select(ReviewLog).where(ReviewLog.card_id.in_(card_ids))).all()
        )
    ratings = [l.rating for l in logs if l.rating is not None]
    hard = sum(1 for r in ratings if r <= 2)      # 1 重来 / 2 困难
    good = sum(1 for r in ratings if r >= 3)
    avg_stability = (sum(c.stability for c in cards) / len(cards)) if cards else 0.0

    # 测验：按知识点聚合正误
    quiz_rows = []
    if before_ids:
        questions = session.exec(
            select(QuizQuestion).where(QuizQuestion.node_id.in_(before_ids))
        ).all()
        qids = [q.id for q in questions]
        if qids:
            attempts = session.exec(
                select(QuizAttempt).where(QuizAttempt.question_id.in_(qids))
            ).all()
            q_node = {q.id: q.node_id for q in questions}
            for a in attempts:
                quiz_rows.append((q_node.get(a.question_id), a.is_correct))
    answered = len(quiz_rows)
    correct = sum(1 for _, ok in quiz_rows if ok)

    # 学习时长（真实停留时间，来自工作台计时）
    minutes = 0.0
    try:
        rows = session.exec(
            select(ProgressRecord)
            .where(ProgressRecord.project_id == int(project_id))
            .where(ProgressRecord.metric == "study_minutes")
        ).all()
        minutes = sum(r.value or 0 for r in rows)
    except Exception:
        logger.exception("读取学习时长失败")

    learned = [n for n in before if (n.status or "") in ("mastered", "learning", "weak")]
    mastered = [n for n in before if (n.status or "") == "mastered"]
    weak_nodes = [n for n in before if (n.status or "") == "weak"]
    created = getattr(project, "created_at", None)
    days = max(1, (datetime.utcnow() - created).days + 1) if created else 1

    return {
        "project": project,
        "before": before,
        "after": after,
        "days": days,
        "minutes": minutes,
        "learned_count": len(learned),
        "mastered_count": len(mastered),
        "weak_nodes": [n.title for n in weak_nodes],
        "notes": notes,
        "annos": annos,
        "cards": cards,
        "ratings": ratings,
        "hard": hard,
        "good": good,
        "avg_stability": avg_stability,
        "quiz_answered": answered,
        "quiz_correct": correct,
    }


def _signal_text(sig: dict) -> str:
    watched = sig["learned_count"]
    total_before = len(sig["before"])
    lines = [
        f"- 已学区节点数：{total_before}（其中已掌握 {sig['mastered_count']}、学习中/薄弱 {watched - sig['mastered_count']}）",
        f"- 项目开始至今 {sig['days']} 天，记录到的实际学习时长 {sig['minutes']:.0f} 分钟",
    ]
    if total_before:
        lines.append(
            f"- 速度参考：{sig['days']} 天学完 {total_before} 节，约 {sig['days'] / max(1, total_before):.1f} 天/节"
        )
    if sig["cards"]:
        lines.append(
            f"- 复习：{len(sig['cards'])} 张卡，评分 {len(sig['ratings'])} 次"
            f"（困难/重来 {sig['hard']} 次，良好以上 {sig['good']} 次），平均稳定度 {sig['avg_stability']:.1f}"
        )
    else:
        lines.append("- 复习：还没有复习卡，无法判断记忆牢固度")
    if sig["quiz_answered"]:
        lines.append(
            f"- 测验：答过 {sig['quiz_answered']} 题，正确 {sig['quiz_correct']} 题"
            f"（{sig['quiz_correct'] / sig['quiz_answered'] * 100:.0f}%）"
        )
    else:
        lines.append("- 测验：还没有答题记录")
    note_total = sum(sig["notes"].values())
    anno_total = sum(sig["annos"].values())
    lines.append(f"- 参与度：笔记 {note_total} 条、批注 {anno_total} 条")
    if sig["weak_nodes"]:
        lines.append("- 被标记为薄弱的节点：" + "、".join(sig["weak_nodes"]))
    if sig["quiz_answered"] < 3 or total_before < 2:
        lines.append("- 注意：样本不足（已学节数少或答题少），判断只能作粗略参考")
    return "\n".join(lines)


def _nodes_text(nodes: list[KnowledgeNode]) -> str:
    if not nodes:
        return "（空）"
    return "\n".join(
        f"- {n.code} {n.title}（{n.est_hours}h，难度 {n.difficulty}/5，{n.status or 'pending'}）"
        for n in nodes
    )


# ---------------------------------------------------------------- 诊断 + 方案


def diagnose_and_plan(
    session: Session,
    project_id: int,
    start_code: str,
    user_note: str = "",
) -> dict:
    """一次模型调用：读学习数据 → 诊断 + 新后段方案（不落库）。"""
    sig = collect_signals(session, project_id, start_code)
    project = sig["project"]
    if not sig["after"]:
        raise ValueError("这个项目已经没有可调整的后续章节了")

    prompt = USER_TEMPLATE.format(
        topic=project.topic or "",
        goal=project.goal or "掌握核心知识并能应用",
        weekly_hours=project.weekly_hours or 10,
        days=sig["days"],
        before_text=_nodes_text(sig["before"]),
        after_count=len(sig["after"]),
        after_text=_nodes_text(sig["after"]),
        signal_text=_signal_text(sig),
        user_note=(user_note or "").strip() or "（无额外要求）",
    )
    raw = chat_json(prompt, system=SYSTEM, model_name=None, purpose="planning")
    if not isinstance(raw, dict) or not raw.get("nodes"):
        raise ValueError("模型没有返回可用的课程方案，请重试")

    after_ids = [n.id for n in sig["after"] if n.id]
    attached = {"notes": 0, "cards": 0, "annotations": 0}
    if after_ids:
        attached["notes"] = len(
            session.exec(select(NodeNote).where(NodeNote.node_id.in_(after_ids))).all()
        )
        attached["cards"] = len(
            session.exec(select(Card).where(Card.node_id.in_(after_ids))).all()
        )
        attached["annotations"] = len(
            session.exec(select(NodeAnnotation).where(NodeAnnotation.node_id.in_(after_ids))).all()
        )

    nodes = assign_codes(sig["after"], _normalize_nodes(raw.get("nodes") or [], sig["before"]))
    return {
        "diagnosis": (raw.get("diagnosis") or "").strip(),
        "pace": (raw.get("pace") or "样本不足").strip(),
        "confidence": (raw.get("confidence") or "低").strip(),
        "weak_points": [str(x) for x in (raw.get("weak_points") or [])][:4],
        "changes": [str(x) for x in (raw.get("changes") or [])][:5],
        "nodes": nodes,
        "old_count": len(sig["after"]),
        "new_count": len(nodes),
        "old_nodes": [{"code": n.code, "title": n.title} for n in sig["after"]],
        "after_attached": attached,
        "before_count": len(sig["before"]),
        "signals": {
            "days": sig["days"],
            "minutes": sig["minutes"],
            "learned": sig["learned_count"],
            "quiz_answered": sig["quiz_answered"],
            "quiz_correct": sig["quiz_correct"],
            "cards": len(sig["cards"]),
            "hard_ratings": sig["hard"],
        },
    }


def _normalize_nodes(raw_nodes: list, before: list[KnowledgeNode]) -> list[dict]:
    """清洗模型给的节点，字段缺失时兜底；不在这里定 code。"""
    out = []
    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        stage = item.get("stage") if item.get("stage") in ("base", "strengthen", "sprint") else "base"
        try:
            hours = float(item.get("est_hours") or 2.0)
        except (TypeError, ValueError):
            hours = 2.0
        try:
            difficulty = int(item.get("difficulty") or 3)
        except (TypeError, ValueError):
            difficulty = 3
        prereq = []
        for p in item.get("prereq") or []:
            try:
                prereq.append(int(p))
            except (TypeError, ValueError):
                continue
        out.append(
            {
                "title": title[:80],
                "description": str(item.get("description") or "").strip(),
                "stage": stage,
                "est_hours": max(0.5, min(12.0, hours)),
                "difficulty": max(1, min(5, difficulty)),
                "prereq": prereq,
            }
        )
    return out


# ---------------------------------------------------------------- 落库


def _next_code(last_code: str, used: set[str], seq: int) -> str:
    """从 last_code 往后接一个没被用过的编号。"""
    m = re.match(r"^(\d+)\.(\d+)$", last_code or "")
    if m:
        major, minor = int(m.group(1)), int(m.group(2))
        minor += 1
        while f"{major}.{minor}" in used:
            minor += 1
        return f"{major}.{minor}"
    n = seq
    while f"9.{n}" in used:
        n += 1
    return f"9.{n}"


def assign_codes(old_after: list[KnowledgeNode], new_nodes: list[dict]) -> list[dict]:
    """优先复用被替换段原有的编号，不够的往后接，保证连续且不重复。"""
    old_codes = [n.code for n in old_after if n.code]
    used = {n.code for n in old_after if n.code}
    result = []
    for i, node in enumerate(new_nodes):
        if node.get("code"):                     # 已经分配过（诊断阶段预分配）
            code = node["code"]
        elif i < len(old_codes):
            code = old_codes[i]
        else:
            last = result[-1]["code"] if result else (old_codes[-1] if old_codes else "1.0")
            code = _next_code(last, used, i + 1)
        used.add(code)
        result.append({**node, "code": code})
    return result


def snapshot_path(project_id: int) -> Path:
    return SNAPSHOT_DIR / f"project_{project_id}.json"


def save_snapshot(session: Session, project_id: int, start_code: str) -> Path:
    """把调整前的后段节点存成快照，供撤销用。"""
    _, after = split_nodes(session, project_id, start_code)
    node_by_id = {n.id: n for n in after}
    # 涉及后段的边也用 code 存下来，撤销时才不会丢依赖关系
    edge_rows = []
    if node_by_id:
        ids = list(node_by_id)
        for e in session.exec(
            select(KnowledgeEdge).where(
                (KnowledgeEdge.source_id.in_(ids)) | (KnowledgeEdge.target_id.in_(ids))
            )
        ).all():
            src = session.get(KnowledgeNode, e.source_id)
            dst = session.get(KnowledgeNode, e.target_id)
            if src and dst:
                edge_rows.append([src.code, dst.code])
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = snapshot_path(project_id)
    path.write_text(
        json.dumps(
            {
                "project_id": int(project_id),
                "start_code": start_code,
                "created_at": datetime.utcnow().isoformat(),
                "edges": edge_rows,
                "nodes": [
                    {
                        "code": n.code,
                        "title": n.title,
                        "description": n.description or "",
                        "stage": n.stage,
                        "est_hours": n.est_hours,
                        "difficulty": n.difficulty,
                        "status": n.status,
                    }
                    for n in after
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def apply_plan(
    session: Session,
    project_id: int,
    start_code: str,
    plan: dict,
    *,
    snapshot: bool = True,
) -> dict:
    """只替换起点之后的节点；前面的节点一行都不动。

    后段里「编号和标题都没变」的节点会被原样保留（连 description 一起），
    只有真正新增/改写的节点才会重建并重新备课。
    """
    before, after = split_nodes(session, project_id, start_code)
    if not after:
        raise ValueError("没有可替换的后续章节")

    new_nodes = assign_codes(after, plan.get("nodes") or [])
    if not new_nodes:
        raise ValueError("方案为空，未做任何修改")

    # 备份（撤销回放时不再备份，否则会把"被撤销的新方案"又存成快照）
    if snapshot:
        save_snapshot(session, project_id, start_code)

    # 编号 + 标题都没变的节点 = 原样保留
    keep_keys = {(x["code"], x["title"].strip()) for x in new_nodes}
    reusable = {
        n.code: n
        for n in after
        if n.code and (n.code, (n.title or "").strip()) in keep_keys
    }
    reusable_ids = {n.id for n in reusable.values()}
    deleting = [n for n in after if n.id not in reusable_ids]
    delete_ids = [n.id for n in deleting]

    attached = {
        "notes": 0,
        "cards": 0,
        "annotations": 0,
        "kept_nodes": len(reusable),
        "deleted_nodes": len(deleting),
    }
    if delete_ids:
        attached["notes"] = len(
            session.exec(select(NodeNote).where(NodeNote.node_id.in_(delete_ids))).all()
        )
        attached["cards"] = len(
            session.exec(select(Card).where(Card.node_id.in_(delete_ids))).all()
        )
        attached["annotations"] = len(
            session.exec(select(NodeAnnotation).where(NodeAnnotation.node_id.in_(delete_ids))).all()
        )

    after_ids = [n.id for n in after]

    # 依赖边全部重算：把涉及后段的边先清掉
    if after_ids:
        for edge in session.exec(
            select(KnowledgeEdge).where(
                (KnowledgeEdge.source_id.in_(after_ids))
                | (KnowledgeEdge.target_id.in_(after_ids))
            )
        ).all():
            session.delete(edge)

    # 只删需要删的节点及其挂载数据
    if delete_ids:
        for model in (NodeNote, NodeAnnotation, Card):
            for row in session.exec(select(model).where(model.node_id.in_(delete_ids))).all():
                session.delete(row)
        quizzes = session.exec(select(Quiz).where(Quiz.node_id.in_(delete_ids))).all()
        quiz_ids = [q.id for q in quizzes if q.id]
        if quiz_ids:
            questions = session.exec(
                select(QuizQuestion).where(QuizQuestion.quiz_id.in_(quiz_ids))
            ).all()
            qids = [q.id for q in questions if q.id]
            if qids:
                for a in session.exec(
                    select(QuizAttempt).where(QuizAttempt.question_id.in_(qids))
                ).all():
                    session.delete(a)
                for q in questions:
                    session.delete(q)
            for q in quizzes:
                session.delete(q)
        for row in session.exec(
            select(KnowledgeNode).where(KnowledgeNode.id.in_(delete_ids))
        ).all():
            session.delete(row)
        session.flush()

    # 补齐新节点（复用已有的，不重建）
    by_code: dict[str, KnowledgeNode] = dict(reusable)
    created_ids: list[int] = []
    for item in new_nodes:
        node = by_code.get(item["code"])
        if node is None:
            node = KnowledgeNode(
                project_id=int(project_id),
                code=item["code"],
                title=item["title"],
                description=item.get("description") or "",
                stage=item.get("stage") or "base",
                est_hours=float(item.get("est_hours") or 2.0),
                difficulty=int(item.get("difficulty") or 3),
                mastery=0.0,
                status="pending",
            )
            session.add(node)
            session.flush()
            by_code[item["code"]] = node
            created_ids.append(node.id)

    # 依赖边：优先用方案里明确给出的 code 对（撤销回放时走这条），
    # 否则按 prereq 下标推断。prereq=-1 指向「已学区最后一节」，所以查找表
    # 必须同时包含前段节点，否则跨前段的依赖会静默丢掉。
    before_last_code = before[-1].code if before else ""
    codes_in_order = [x["code"] for x in new_nodes]
    code_node = {n.code: n for n in before}
    code_node.update(by_code)
    explicit_edges = plan.get("edges")
    used_explicit = False
    if explicit_edges:
        for src_code, dst_code in explicit_edges:
            src = code_node.get(src_code)
            dst = code_node.get(dst_code)
            if src is None or dst is None or src.id == dst.id:
                continue
            session.add(
                KnowledgeEdge(
                    project_id=int(project_id),
                    source_id=src.id,
                    target_id=dst.id,
                    relation="prerequisite",
                )
            )
        used_explicit = True

    for i, item in ([] if used_explicit else enumerate(new_nodes)):
        src = code_node.get(item["code"])
        if src is None:
            continue
        for p in item.get("prereq") or []:
            if p == -1:
                target_code = before_last_code
            elif 0 <= p < len(codes_in_order):
                target_code = codes_in_order[p]
            else:
                continue
            dst = code_node.get(target_code)
            if dst is None or dst.id == src.id:
                continue
            session.add(
                KnowledgeEdge(
                    project_id=int(project_id),
                    source_id=src.id,
                    target_id=dst.id,
                    relation="prerequisite",
                )
            )

    # 路线 JSON 同步：前段保留原样，后段换成本次结果
    project = session.get(LearningProject, int(project_id))
    if project:
        try:
            data = json.loads(project.roadmap_json or "{}")
        except Exception:
            data = {}
        before_codes = {n.code for n in before}
        kept = [x for x in (data.get("nodes") or []) if x.get("code") in before_codes]
        data["nodes"] = kept + [
            {
                "code": x["code"],
                "title": x["title"],
                "description": x.get("description") or "",
                "stage": x.get("stage") or "base",
                "est_hours": float(x.get("est_hours") or 2.0),
                "difficulty": int(x.get("difficulty") or 3),
                "prerequisites": [],
            }
            for x in new_nodes
        ]
        project.roadmap_json = json.dumps(data, ensure_ascii=False)
        session.add(project)

    session.commit()
    return {
        "before_count": len(before),
        "old_count": len(after),
        "new_count": len(new_nodes),
        "created_ids": created_ids,
        "deleted_attached": attached,
    }


def undo_last(session: Session, project_id: int) -> dict:
    """用快照把后段还原回去。"""
    path = snapshot_path(project_id)
    if not path.exists():
        raise ValueError("没有可撤销的调整记录")
    data = json.loads(path.read_text(encoding="utf-8"))
    start_code = data.get("start_code") or ""
    nodes = data.get("nodes") or []
    if not nodes:
        raise ValueError("快照为空")

    plan = {"nodes": [dict(n) for n in nodes], "edges": data.get("edges") or []}
    result = apply_plan(session, project_id, start_code, plan, snapshot=False)
    path.unlink(missing_ok=True)
    return result
