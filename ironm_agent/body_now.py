"""同一处身体以最近的说法为准（spec [2026-10-23] §158）：伤病记在记忆表，说疼记在说疼记录里，读的时候合。

- 某处的伤病说好了（已结束），那一天及以前那一处的说疼记录不再算（反复疼的提醒、每天检查、档案"今天"一段）；
- 好了之后又说疼的照常算；最近 3 天说过疼的部位，排计划、换动作时和记着的伤病一样避开。
不改存储、不调用模型。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

SORE_DAYS = 3  # 最近几天说过疼的部位也避开


def _parts(item: Any) -> list[str]:
    from ironm_agent.facts import parts_in

    data = getattr(item, "data", None) or {}
    return list(data.get("parts") or []) or parts_in(item.content)


def healed_on(items: Sequence[Any]) -> dict[str, date]:
    """说好了的部位 → 哪天说的（同一处还有在疼的伤病就不算好了）。"""
    from ironm_agent.latest import current

    live = [x for x in current([x for x in items if x.status != "superseded"]) if x.category == "injury"]
    hurt = {p for x in live if x.status in ("active", "pending") for p in _parts(x)}
    out: dict[str, date] = {}
    for x in live:
        if x.status != "resolved":
            continue
        day = x.updated.astimezone().date()
        for p in _parts(x):
            if p not in hurt and day > out.get(p, date.min):
                out[p] = day
    return out


def fresh(pains: Sequence[tuple[str, date]], items: Sequence[Any]) -> list[tuple[str, date]]:
    """去掉说好了那天及以前、那一处的说疼记录。"""
    healed = healed_on(items)
    return [(p, d) for p, d in pains if p not in healed or d > healed[p]]


def sore(pains: Sequence[tuple[str, date]], items: Sequence[Any], today: date) -> list[str]:
    """最近 SORE_DAYS 天说过疼（好了之后说的）的部位。"""
    return list(dict.fromkeys(p for p, d in fresh(pains, items) if 0 <= (today - d).days < SORE_DAYS))
