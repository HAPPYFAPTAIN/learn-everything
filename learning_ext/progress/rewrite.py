"""对话式改内容：定位到正文里的某一段，只改这一段，写回数据库。

为什么不做"整节重写"：整节重写慢、贵，而且会把本来对的部分一起改坏。
用户的问题通常就一句「这个例子不合适」「这段看不懂」，只需要动那一段。

定位靠用户选中的文字去匹配原始正文里的段落块。匹配不上就如实拒绝，
绝不猜位置——改错段比不改更糟。
"""

from __future__ import annotations

import logging
import re
import threading

from ktem.db.engine import engine
from sqlmodel import Session

from learning_ext.db.models import KnowledgeNode
from learning_ext.llm import chat

logger = logging.getLogger(__name__)

# 后台备课线程也在写同一个 sqlite，写之前统一拿这把锁
_WRITE_LOCK = threading.Lock()

# 每个节点只留最近一次的改写前正文，用于「撤销」
_UNDO: dict[int, str] = {}

PRESETS: dict[str, str] = {
    "rewrite": "保留原意，把这段重写得更清楚、更顺口，长度和原文相当。",
    "simplify": "把这段讲得更浅：少用术语，遇到概念先打个比方，句子更短。",
    "example": "给这段补一个具体、贴近日常的例子（电商、记账、点外卖这类都行），原论点不要改。",
    "tighten": "删掉重复和铺垫，压到原文六成左右，信息量不减。",
    "expand": "把这段讲透：补上「为什么」和「具体怎么做」，可以写到原文的 1.6 倍。",
}

ACTION_LABELS = {
    "rewrite": "重写这段",
    "simplify": "讲浅一点",
    "example": "加个例子",
    "tighten": "精简",
    "expand": "展开讲",
    "custom": "按要求改",
    "undo": "撤销",
}

_SYSTEM = (
    "你是一位中文教材编辑，负责按作者的要求润色讲义里的某一段。"
    "你的输出会被直接拼回原文，所以只能给改写结果本身，不能有任何解释、前言、"
    "或者把结果包在代码块里。"
)


def _key(s: str) -> str:
    """压成只含中文/字母/数字的串，用来做跨 markdown 的宽松匹配。

    界面上的文字是渲染后的（没有 **、`、> 这些符号），直接比对会永远匹配不上。
    """
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", s or "")


def _split_blocks(text: str) -> list[tuple[int, int]]:
    """按空行切段，代码块内部的空行不算分界。

    标题行必须单独成段：讲义里常见「正文下一行直接跟 ### 小标题」的写法，
    只按空行切会把标题并进正文段，改写时连标题一起被模型吃掉。
    """
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    fence = False
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        end = offset + len(line)
        if stripped.startswith("```"):
            fence = not fence
        if not fence and re.match(r"^#{1,6}\s", stripped):
            if start is not None:
                blocks.append((start, offset))
                start = None
            blocks.append((offset, end))
            offset = end + 1
            continue
        if not fence and not stripped:
            if start is not None:
                blocks.append((start, offset))
                start = None
        elif start is None:
            start = offset
        offset = end + 1
    if start is not None:
        blocks.append((start, len(text)))
    return blocks


def locate(text: str, snippet: str) -> tuple[int, int] | None:
    """把界面上选中的文字映射回原文里的字符区间。

    只在段落边界上找，而且绝不让区间跨过「选中内容里没有的标题」——
    一旦跨段，改写就会把后面无关的内容一起替换掉（实测会吞掉下一节标题）。
    """
    if not text or not snippet:
        return None
    blocks = _split_blocks(text)
    if not blocks:
        return None
    keys = [_key(text[a:b]) for a, b in blocks]
    is_head = [text[a:b].lstrip().startswith("#") for a, b in blocks]
    target = _key(snippet)
    if not target:
        return None

    # 1. 单段完整包含：取最紧的那一段
    hits = [i for i, k in enumerate(keys) if k and target in k]
    if hits:
        i = min(hits, key=lambda x: len(keys[x]))
        return blocks[i]

    # 2. 跨段（用户选了好几段）：从每段起向后拼，碰到不相关的标题就停
    for i in range(len(blocks)):
        if not keys[i]:
            continue
        acc = ""
        for j in range(i, min(i + 8, len(blocks))):
            if is_head[j] and keys[j] not in target:
                break
            acc += keys[j]
            if target in acc:
                return (blocks[i][0], blocks[j][1])
            if len(acc) > len(target) * 1.5 + 160:
                break

    # 3. 兜底：界面文字和原文有出入时，用前半段找单段
    half = target[: max(24, len(target) // 2)]
    hits = [i for i, k in enumerate(keys) if k and half in k]
    if hits:
        i = min(hits, key=lambda x: len(keys[x]))
        return blocks[i]
    return None


def _context(text: str, start: int, end: int, limit: int = 700) -> str:
    """给模型一点上下文：最近的上文标题 + 前后一小段。"""
    before = text[max(0, start - limit) : start]
    heading = ""
    for line in reversed(before.split("\n")):
        if line.lstrip().startswith("#"):
            heading = line.strip()
            break
    after = text[end : end + 300]
    parts = []
    if heading:
        parts.append(f"所在小节：{heading}")
    if before.strip():
        parts.append("上文：…" + before.strip()[-400:])
    if after.strip():
        parts.append("下文：" + after.strip()[:200] + "…")
    return "\n".join(parts)


def _clean_out(raw: str, original: str) -> str:
    out = (raw or "").strip()
    # 模型偶尔会把整段包在代码块里
    fence = re.fullmatch(r"```[a-zA-Z]*\n(.*?)\n```", out, re.S)
    if fence and not original.strip().startswith("```"):
        out = fence.group(1).strip()
    # 去掉「改写后：」这类前缀
    out = re.sub(r"^(改写后|修改后|新版|结果)[：:]\s*", "", out)
    return out.strip()


def rewrite(node_id: int, snippet: str, action: str = "rewrite", instruction: str = "") -> dict:
    """改写命中的那一段并落库。

    返回 {"ok": bool, "message": str, "guide": str}，guide 是更新后的整节正文。
    """
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return {"ok": False, "message": "先选一节课程。", "guide": ""}

    if action == "undo":
        return undo(nid)

    with Session(engine) as session:
        node = session.get(KnowledgeNode, nid)
        if not node:
            return {"ok": False, "message": "这一节已经不存在了。", "guide": ""}
        text = node.description or ""
    if len(_key(text)) < 50:
        return {"ok": False, "message": "这一节还没有正文，等它写出来再改。", "guide": ""}

    span = locate(text, snippet)
    if not span:
        return {
            "ok": False,
            "message": "没定位到你选的那段文字。可能它刚被改过——刷新一下再试。",
            "guide": text,
        }
    start, end = span
    block = text[start:end]
    # 兜底：命中区间开头若是标题行（老内容里标题和正文可能贴在一起），
    # 标题留在原地，只改正文。用户选中的就是标题时除外。
    while True:
        lead = re.match(r"\s*(#{1,6}[^\n]*\n)", block)
        if not lead:
            break
        hk = _key(lead.group(1))
        if hk and hk in _key(snippet):
            break
        start += lead.end()
        block = text[start:end]
    ask = (instruction or "").strip() or PRESETS.get(action, PRESETS["rewrite"])

    prompt = (
        "下面是讲义里需要改写的那一段，以及它的上下文。\n\n"
        f"作者的要求：{ask}\n\n"
        "要求：\n"
        "1. 只输出改写后的这一段，不要解释，不要用代码块包裹整段（除非原文就是代码）。\n"
        "2. 保留原有的 markdown 结构：标题层级、列表符号、加粗、表格都对上。\n"
        "3. 不新增小标题，不改动其他段落，不加「改写后」之类的字样。\n"
        "4. 语言用朴素的中文，别写成套话。\n\n"
        "【需要改写的一段】\n"
        f"{block}\n\n"
        "【上下文，仅供理解】\n"
        f"{_context(text, start, end)}"
    )
    try:
        raw = chat(prompt, system=_SYSTEM, temperature=0.4, max_tokens=2500)
    except Exception as exc:  # noqa: BLE001
        logger.exception("改写调用失败 node#%s", nid)
        return {"ok": False, "message": f"改写失败：{type(exc).__name__}: {exc}", "guide": text}

    new_block = _clean_out(str(raw), block)
    if len(_key(new_block)) < 10:
        return {"ok": False, "message": "模型这次没给出有效内容，再试一次。", "guide": text}
    if len(new_block) > max(1200, len(block) * 4):
        return {"ok": False, "message": "改写结果异常长，已经放弃这次修改。", "guide": text}

    # 保住段落两端的空白：结尾的换行丢了，下一行标题会跟正文粘成「产品。### 标题」，
    # 之后 markdown 认不出标题，再改一次就会把整节结构弄坏。
    lead_ws = block[: len(block) - len(block.lstrip())]
    trail_ws = block[len(block.rstrip()) :]
    new_block = lead_ws + new_block.strip() + trail_ws

    updated = text[:start] + new_block + text[end:]
    _UNDO[nid] = text
    if not _save(nid, updated):
        return {"ok": False, "message": "写入失败，内容没变。", "guide": text}
    logger.info("[改写] node#%s %s 段长 %d→%d", nid, action, len(block), len(new_block))
    return {
        "ok": True,
        "message": f"✅ 已按「{ACTION_LABELS.get(action, '改写')}」更新这一段，可以撤销。",
        "guide": updated,
    }


def undo(node_id: int) -> dict:
    try:
        nid = int(node_id)
    except (TypeError, ValueError):
        return {"ok": False, "message": "没有可撤销的修改。", "guide": ""}
    old = _UNDO.pop(nid, None)
    if old is None:
        return {"ok": False, "message": "这一节没有可撤销的修改。", "guide": ""}
    if not _save(nid, old):
        return {"ok": False, "message": "撤销写入失败。", "guide": old}
    logger.info("[改写] node#%s 已撤销", nid)
    return {"ok": True, "message": "↩️ 已退回修改前的内容。", "guide": old}


def can_undo(node_id) -> bool:
    try:
        return int(node_id) in _UNDO
    except (TypeError, ValueError):
        return False


def _save(node_id: int, text: str) -> bool:
    try:
        with _WRITE_LOCK:
            with Session(engine) as session:
                node = session.get(KnowledgeNode, node_id)
                if not node:
                    return False
                node.description = text
                session.add(node)
                session.commit()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("改写落库失败 node#%s", node_id)
        return False
