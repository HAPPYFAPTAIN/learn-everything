"""正文批注：在阅读界面选中一句，记一句话，一条条收进笔记页。

和整节笔记（`NodeNote`）分开存：
* `NodeNote` 是"这一节我理解到什么"，一段自由文本；
* `NodeAnnotation` 是"这句话我想记一笔"，一句一条，带原文快照。

原文快照是必要的：正文会被改写，改写后靠 quote 去正文里做匹配，
匹配不上就标「原文已改动」，批注本身不丢。
"""

from __future__ import annotations

import html
import json
import logging
import re

from sqlmodel import Session, select

from learning_ext.db.models import NodeAnnotation

logger = logging.getLogger(__name__)

MAX_QUOTE = 600
MAX_BODY = 2000


def _key(s: str) -> str:
    """去掉空白和标点，只留中英文数字，用于跨 markdown 的宽松匹配。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", s or "")


def add(
    session: Session,
    node_id: int,
    project_id: int | None,
    quote: str,
    body: str,
    user_id: str = "default",
) -> NodeAnnotation | None:
    quote = (quote or "").strip()
    body = (body or "").strip()
    if not quote or not body:
        return None
    anno = NodeAnnotation(
        user_id=user_id,
        node_id=int(node_id),
        project_id=int(project_id or 0),
        quote=quote[:MAX_QUOTE],
        body=body[:MAX_BODY],
    )
    session.add(anno)
    session.commit()
    session.refresh(anno)
    logger.info("[批注] node#%s 新增 #%s（%d 字）", node_id, anno.id, len(body))
    return anno


def list_for_node(
    session: Session, node_id: int, user_id: str = "default"
) -> list[NodeAnnotation]:
    return list(
        session.exec(
            select(NodeAnnotation)
            .where(NodeAnnotation.node_id == int(node_id))
            .where(NodeAnnotation.user_id == user_id)
            .order_by(NodeAnnotation.id)
        ).all()
    )


def remove(session: Session, anno_id: int, user_id: str = "default") -> bool:
    anno = session.get(NodeAnnotation, int(anno_id))
    if not anno or anno.user_id != user_id:
        return False
    session.delete(anno)
    session.commit()
    return True


def update(
    session: Session, anno_id: int, body: str, user_id: str = "default"
) -> bool:
    """改一条批注的内容（原文不动）。"""
    anno = session.get(NodeAnnotation, int(anno_id))
    if not anno or anno.user_id != user_id:
        return False
    body = (body or "").strip()
    if not body:
        return False
    anno.body = body[:MAX_BODY]
    session.add(anno)
    session.commit()
    return True


def render_html(items: list[NodeAnnotation], guide: str = "") -> str:
    """批注列表 + 一份给前端做角标的 JSON。

    列表在笔记页，JSON 供 workbench.js 在正文里标出被批注的句子。
    """
    if not items:
        return (
            '<div class="le-anno-empty">读正文时选中一句话，点浮条里的「记一笔」，'
            "批注会一条条收在这里。</div>"
            '<div class="le-anno-data" data-json="[]"></div>'
        )

    guide_key = _key(guide)
    payload = []
    rows = []
    for a in items:
        stale = bool(guide_key) and _key(a.quote) not in guide_key
        payload.append(
            {
                "id": a.id,
                "quote": a.quote,
                "body": a.body,
                "stale": stale,
            }
        )
        quote_html = html.escape(a.quote)
        if len(quote_html) > 120:
            quote_html = quote_html[:120] + "…"
        stale_tag = (
            '<span class="le-anno-stale">原文已改动</span>' if stale else ""
        )
        rows.append(
            f'<div class="le-anno-item" data-anno="{a.id}">'
            f'<div class="le-anno-quote">{quote_html}{stale_tag}</div>'
            f'<div class="le-anno-body">{html.escape(a.body)}</div>'
            f'<div class="le-anno-meta">'
            f'<span>{a.created_at.strftime("%m-%d %H:%M") if a.created_at else ""}</span>'
            f'<button type="button" class="le-anno-del" data-anno-del="{a.id}">删除</button>'
            f"</div></div>"
        )

    data = html.escape(json.dumps(payload, ensure_ascii=False), quote=True)
    return (
        f'<div class="le-anno-head">正文批注 <b>{len(items)}</b> 条</div>'
        + "".join(rows)
        + f'<div class="le-anno-data" data-json="{data}"></div>'
    )
