"""同一件事以最近的为准（spec [2026-10-23] §113）：读记忆时按"同一件事"分组，每组只认最近记的那条，
更早的当作被替换、不再用（最近那条是"好了、结束了"时，就说明这件事过去了）。只在读的时候判断，不改存储，
所以已经存着的旧条目也照这条规则读。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ironm_agent.memory_store import Item

# 说"在哪练"的话（在家练、去健身房练、办了健身房的卡、两边都练）；"家里有壶铃"说的是器械，不算
_PLACE = re.compile(
    r"[在去](?:健身房|健身中心)|在(?:家里?|酒店|宿舍)(?:练|锻炼|健身|[，,])|办了?.{0,3}健身房|健身房的?卡|都练"
)
_WEEKDAY = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天])")
_AMOUNTS = (("蛋白", r"蛋白"), ("热量", r"千卡|热量|卡路里"), ("碳水", r"碳水"), ("脂肪", r"脂肪"),
            ("喝水", r"喝水|饮水"))  # fmt: skip
_HURT = re.compile(r"疼|痛|伤|酸|肿|麻")
_PUNCT = re.compile(r"[\s\W_]+", re.U)
_ONE = frozenset({"goal", "level"})  # 只有一条：目标、训练水平


def _same_text(category: str, text: str) -> frozenset[str]:
    return frozenset({f"{category}:{_PUNCT.sub('', text)}"})


def keys(item: Item) -> frozenset[str]:
    """这条记忆说的是哪件（几件）事；两条有相同的 key 就是同一件事。"""
    from ironm_agent.casefile import PARTS
    from ironm_agent.memory_extract import _EVENT_KINDS

    c, text = item.category, item.content
    if c in _ONE:
        return frozenset({c})
    if c in ("event", "followup"):  # 近况和待跟进算一类：出差了、说好的回来前提醒，同一件事
        got = {f"近况:{i}" for i, k in enumerate(_EVENT_KINDS) if k.search(text)}
        if _HURT.search(text):
            got |= {f"近况:{p}" for p, rx in PARTS.items() if rx.search(text)}
        return frozenset(got) or _same_text(c, text)
    if c == "injury":
        parts = {f"伤病:{p}" for p, rx in PARTS.items() if rx.search(text)}
        return frozenset(parts) or _same_text(c, text)
    if c == "equipment":
        return frozenset({"在哪练"}) if _PLACE.search(text) else _same_text(c, text)
    if c == "advice":
        got = {
            f"建议:{name}"
            for name, rx in _AMOUNTS
            if re.search(rx, text) and re.search(r"\d", text)
        }
        got |= {f"建议:周{d}" for d in _WEEKDAY.findall(text)}
        return frozenset(got) or _same_text(c, text)
    return _same_text(c, text)


def shadowed(items: Iterable[Item]) -> set[str]:
    """被同一件事更近的一条替换掉的记忆编号（被取代的不算在内）。"""
    rows = sorted((x for x in items if x.status != "superseded"), key=lambda x: x.created)
    newest: dict[str, Item] = {}
    for x in rows:
        for k in keys(x):
            newest[k] = x
    return {x.id for x in rows if any(newest[k] is not x for k in keys(x))}


def current(items: Iterable[Item]) -> list[Item]:
    """去掉被替换的（顺序不变）。"""
    items = list(items)
    gone = shadowed(items)
    return [x for x in items if x.id not in gone]
