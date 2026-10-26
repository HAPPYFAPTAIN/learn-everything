"""学习闭环门控：把「已掌握」从按钮变成关卡。

设计依据是费曼学习法——讲不出来就是没学会。所以一节课要过两关：
速测答对（别只是看懂了）、复述讲清（真的能说出来）。

（原来还有一道「读够时间」的门：按课时折算要求停留若干分钟。它测的是
页面驻留而不是理解，挂机就能过、读得快的人反被拦，去查资料又不计时，
已去掉。阅读时长仍然统计，只作参考数据，不再参与过关判定。）

三道门分别是：
1. 本节过关（硬门）：挡在「已掌握」上
2. 到期复习（强提醒）：学完 24 小时内该复习，欠太久顶部会警示
3. 阶段查漏（提醒）：每学 5 节提示做一次查漏测验

这里只放纯数据逻辑，不碰界面。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from learning_ext.db.models import (
    Card,
    KnowledgeNode,
    LessonGate,
    ProgressRecord,
)
from learning_ext.llm.client import chat_json, friendly_error

logger = logging.getLogger(__name__)

USER_ID = "default"
RECITE_PASS_BRIEF = 2               # 速测 3 题至少对 2 题
STAGE_STEP = 5                      # 每学 5 节提示一次查漏

RECITE_SYSTEM = """你是学习助教。用户刚学完一节内容，正在用自己的话向你复述。
你要判断他是否真的理解了核心，而不是复述原文或者敷衍。

判断标准：
1. 有没有说清「这一节到底在讲什么」（主旨，不是罗列名词）
2. 有没有出现明显错误或张冠李戴
3. 是否只是抄了原文的句子（照抄不算讲清）
4. 字数太少、答非所问、纯符号或无意义重复 → 不通过

返回 JSON：
{
  "passed": true|false,
  "feedback": "两句话内点评。通过就说清他讲对了什么；不通过就具体指出缺哪一块，不要替他讲完。",
  "missing": "不通过时，用一个短句说明缺什么；通过留空"
}
只返回 JSON。"""


def get_gate(
    session: Session, node_id: int, project_id: Optional[int] = None
) -> LessonGate:
    """取这一节的过关记录，没有就建一条空的。"""
    gate = session.exec(
        select(LessonGate).where(
            LessonGate.node_id == int(node_id),
            LessonGate.user_id == USER_ID,
        )
    ).first()
    if gate:
        return gate
    gate = LessonGate(
        user_id=USER_ID,
        node_id=int(node_id),
        project_id=int(project_id or 0),
    )
    session.add(gate)
    session.commit()
    session.refresh(gate)
    return gate


def add_dwell(session: Session, node_id: int, seconds: float) -> float:
    """累计本节阅读秒数，返回累计值。"""
    if not node_id or seconds <= 0:
        return 0.0
    gate = get_gate(session, node_id)
    gate.dwell_seconds = float(gate.dwell_seconds or 0) + float(seconds)
    gate.updated_at = datetime.utcnow()
    session.add(gate)
    session.commit()
    return gate.dwell_seconds


def mark_quiz(session: Session, node_id: int, correct: int, total: int) -> LessonGate:
    """记速测成绩。只保留最好的一次，别让重测把分数越测越低。"""
    gate = get_gate(session, node_id)
    best = int(gate.quiz_correct if gate.quiz_correct is not None else -1)
    if correct > best:
        gate.quiz_correct = int(correct)
        gate.quiz_total = int(total)
        gate.quiz_at = datetime.utcnow()
        gate.updated_at = datetime.utcnow()
        session.add(gate)
        session.commit()
        session.refresh(gate)
    return gate


def judge_recite(node: KnowledgeNode, text: str) -> dict:
    """让助教判断复述是否讲清。失败时返回可展示的中文提示。"""
    text = (text or "").strip()
    # 不卡字数：有人一句话就说到点上，有人写三百字还在绕。交给助教看内容。
    if not text:
        return {
            "passed": False,
            "feedback": "还没写呢。不看原文，用自己的话说两句就行。",
            "missing": "空着没写",
        }
    prompt = (
        f"【本节标题】{node.title}\n"
        f"【本节内容】{(node.description or '')[:3000]}\n\n"
        f"【用户的复述】{text}"
    )
    try:
        result = chat_json(prompt, system=RECITE_SYSTEM, purpose="assessment")
    except Exception as e:  # 模型不可用时不能把整页拖死
        logger.warning("复述判定失败: %s", e)
        return {
            "passed": False,
            "feedback": f"助教暂时没连上模型（{friendly_error(e)}），稍后再试，"
            f"或者先点「跳过本节」。",
            "missing": "判定失败",
            "error": True,
        }
    if not isinstance(result, dict):
        result = {}
    return {
        "passed": bool(result.get("passed")),
        "feedback": str(result.get("feedback") or "").strip(),
        "missing": str(result.get("missing") or "").strip(),
    }


def save_recite(
    session: Session, node: KnowledgeNode, text: str, verdict: dict
) -> LessonGate:
    """把复述和助教点评存下来。"""
    gate = get_gate(session, node.id, node.project_id)
    gate.recite_text = (text or "").strip()
    gate.recite_passed = bool(verdict.get("passed"))
    gate.recite_feedback = str(verdict.get("feedback") or "")
    gate.updated_at = datetime.utcnow()
    session.add(gate)
    session.commit()
    session.refresh(gate)
    return gate


def check_gate(session: Session, node: KnowledgeNode) -> dict:
    """算这一节离过关还差什么。不改任何数据。

    只看两件事：速测答对没有、复述过没过。阅读时长照旧累计在
    dwell_seconds 里，但不再作为过关条件。
    """
    gate = get_gate(session, node.id, node.project_id)
    got = float(gate.dwell_seconds or 0)
    quiz_ok = int(gate.quiz_correct or 0) >= RECITE_PASS_BRIEF
    recite_ok = bool(gate.recite_passed)
    missing = []
    if not quiz_ok:
        if gate.quiz_correct is None or gate.quiz_correct < 0:
            missing.append("还没做速测")
        else:
            missing.append(f"速测 {gate.quiz_correct}/{gate.quiz_total}，至少要 {RECITE_PASS_BRIEF}")
    if not recite_ok:
        missing.append("还没通过复述")
    return {
        "passed": quiz_ok and recite_ok,
        "quiz_ok": quiz_ok,
        "recite_ok": recite_ok,
        "dwell_seconds": round(got),
        "quiz_correct": int(gate.quiz_correct if gate.quiz_correct is not None else -1),
        "quiz_total": int(gate.quiz_total or 3),
        "recite_text": gate.recite_text,
        "recite_feedback": gate.recite_feedback,
        "missing": missing,
    }


def mark_passed(session: Session, node: KnowledgeNode) -> None:
    """两关全过、状态也落成已掌握之后，记一笔过关时间。"""
    gate = get_gate(session, node.id, node.project_id)
    gate.passed_at = datetime.utcnow()
    gate.updated_at = datetime.utcnow()
    session.add(gate)
    session.commit()


# ---------------- 第二关：到期复习 ----------------


def gate_rhythm(session: Session, project_id: int) -> dict:
    """算节奏条要显示的东西：到期卡、欠了多久、今天学了多久。"""
    now = datetime.utcnow()
    cards = session.exec(
        select(Card)
        .where(Card.user_id == USER_ID, Card.project_id == int(project_id))
        .where(Card.suspended == False)  # noqa: E712
    ).all()
    due = [c for c in cards if c.next_review and c.next_review <= now]
    earliest = min((c.next_review for c in due), default=None)

    # 今天的学习分钟：按本地日期算，跟用户看到的「今天」一致
    minutes = 0.0
    rows = session.exec(
        select(ProgressRecord).where(
            ProgressRecord.user_id == USER_ID,
            ProgressRecord.project_id == int(project_id),
            ProgressRecord.metric == "study_minutes",
        )
    ).all()
    today = datetime.now().date()
    for r in rows:
        if r.recorded_at and r.recorded_at.date() == today:
            minutes += float(r.value or 0)

    overdue_hours = 0.0
    if earliest:
        overdue_hours = max(0.0, (now - earliest).total_seconds() / 3600)

    return {
        "due_count": len(due),
        "overdue_hours": round(overdue_hours, 1),
        "today_minutes": round(minutes),
        "total_cards": len(cards),
    }


def _snooze_metric() -> str:
    # ProgressRecord 没有额外的备注字段，而 create_all 不会给老表加列，
    # 所以把日期直接编进 metric 名里，省一次迁移。
    return "gate_snooze_" + datetime.now().strftime("%Y-%m-%d")


def snooze_today(session: Session, project_id: int) -> None:
    """用户点「我先学，回头补」：今天不再用欠复习拦他。"""
    session.add(
        ProgressRecord(
            user_id=USER_ID,
            project_id=int(project_id),
            node_id=None,
            metric=_snooze_metric(),
            value=0.0,
        )
    )
    session.commit()


def is_snoozed_today(session: Session, project_id: int) -> bool:
    return bool(
        session.exec(
            select(ProgressRecord).where(
                ProgressRecord.user_id == USER_ID,
                ProgressRecord.project_id == int(project_id),
                ProgressRecord.metric == _snooze_metric(),
            )
        ).first()
    )


def stage_due(session: Session, project_id: int) -> bool:
    """已掌握节数是 5 的倍数且 > 0 → 该做一次查漏了。"""
    done = session.exec(
        select(KnowledgeNode).where(
            KnowledgeNode.project_id == int(project_id),
            KnowledgeNode.status == "mastered",
        )
    ).all()
    n = len(done)
    return n > 0 and n % STAGE_STEP == 0


# ---------------- 速测判分 ----------------


def _letter(text: str) -> str:
    """从「B」「b.」「答案 B」里抠出选项字母。"""
    import re

    m = re.search(r"[A-Ha-h]", str(text or ""))
    return m.group(0).upper() if m else ""


def grade_quick(items: list[dict], answers: list[str]) -> dict:
    """判 3 道速测。选择题本地比对，其余一次 AI 批量判，省时间也省额度。

    Returns:
        {"correct": n, "total": n, "details": [{"ok":bool,"note":str}]}
    """
    details: list[dict] = []
    pending: list[int] = []

    for i, item in enumerate(items):
        ans = (answers[i] if i < len(answers) else "").strip()
        if item.get("qtype") == "choice":
            right = _letter(item.get("answer", ""))
            got = _letter(ans)
            details.append(
                {
                    "ok": bool(right) and right == got,
                    "note": "" if right == got else f"正确答案 {right}",
                }
            )
        elif not ans:
            details.append({"ok": False, "note": "没作答"})
        else:
            details.append({"ok": False, "note": ""})
            pending.append(i)

    if pending:
        judged = _judge_batch(items, answers, pending)
        for i, ok, note in judged:
            details[i] = {"ok": ok, "note": note}

    correct = sum(1 for d in details if d["ok"])
    return {"correct": correct, "total": len(items), "details": details}


def _judge_batch(items, answers, idx: list[int]) -> list[tuple[int, bool, str]]:
    """把非选择题打包成一次请求交给模型判。失败时全部算错并说明原因。"""
    blocks = []
    for i in idx:
        it = items[i]
        blocks.append(
            f"第{i + 1}题（{it.get('qtype')}）\n题干：{it.get('stem')}\n"
            f"参考答案：{it.get('answer')}\n学生答案：{answers[i] if i < len(answers) else ''}"
        )
    prompt = (
        "逐题判断学生答案是否正确。填空允许表述差异，简答按要点覆盖判断。\n\n"
        + "\n\n".join(blocks)
        + "\n\n返回 JSON 数组，元素与题号一一对应："
        '[{"index": 1, "ok": true|false, "note": "一句话说明"}]'
    )
    try:
        result = chat_json(
            prompt,
            system="你是阅卷老师，只返回 JSON，不要多余文字。填空语义等价即算对，简答关键要点覆盖 70% 算对。",
            purpose="assessment",
        )
    except Exception as e:
        logger.warning("速测判分失败: %s", e)
        return [(i, False, "判分失败，稍后重试") for i in idx]

    if isinstance(result, dict):
        result = result.get("results") or result.get("items") or []
    rows = [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []
    # 按返回顺序一一对应，不要靠 index 去猜。模型经常把 index 填成
    # 「本次待判里的第几题」而不是原题号，靠它匹配会把上一题的结果串到下一题。
    out: list[tuple[int, bool, str]] = []
    for pos, i in enumerate(idx):
        row = rows[pos] if pos < len(rows) else None
        if row is None:
            out.append((i, False, "判分失败，稍后重试"))
            continue
        out.append((i, bool(row.get("ok")), str(row.get("note") or "")))
    return out
