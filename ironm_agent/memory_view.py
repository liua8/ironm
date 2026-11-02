"""作答时怎么用记忆：L2 按类别分给各专业 Agent，L3 画像是有效记忆直接排成的清单（不经模型改写）。

作答前把这个人的全部有效记忆读进来（一个人通常几十条），不靠关键词检索，避免漏召回；超过 MAX_FACTS 条时
按类别和优先级读取（spec [2026-10-23] §17）。待确认的（系统推断、用户还没确认）和被取代的不用；近期事件过了
EVENT_DAYS 天、训练记录得出的偏好 DATA_DAYS 天没再被数据支持，不再用。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from ironm_agent.memory_store import CATEGORIES, Category, Item, now

EVENT_DAYS = (
    7  # 没写到哪天为止的近期事件，多少天后不再用于回答（spec [2026-10-23] §73，原来 14 天）
)
ADVICE_KEEP = 5  # 给过的建议只带最近几条
DATA_DAYS = 56  # 训练记录得出的偏好多少天没再被数据支持就不用
MAX_FACTS = 60  # 超过这么多条有效记忆时按类别和优先级读取
CATEGORY_CAP: dict[str, int] = {
    "injury": 15, "goal": 5, "style": 5, "equipment": 10, "schedule": 8, "diet": 10,
    "preference": 12, "event": 5, "level": 2,
}  # fmt: skip
KEEP_ORDER: tuple[Category, ...] = (
    "injury", "goal", "level", "style", "equipment", "schedule", "diet", "preference", "event",
)  # fmt: skip
RESOLVED_KEEP = 5  # 记忆多时，已解决的最多留几条

EVERYONE: tuple[Category, ...] = ("preference", "style")
ORDER = tuple(CATEGORIES)


def expired(item: Item, at: datetime | None = None) -> bool:
    at = at or now()
    if item.origin == "data":  # 训练记录得出的偏好：每次还被数据支持时会刷新 updated
        return at - item.updated > timedelta(days=DATA_DAYS)
    if item.category != "event":
        return False
    if item.until is not None:  # 写了到哪天为止的近况，过了那天不再用（spec [2026-10-23] §68）
        return at.astimezone().date() > item.until
    return at - item.created > timedelta(days=EVENT_DAYS)


def _trim(facts: list[Item]) -> list[Item]:
    """记忆太多时：已解决的只留最近几条；每类留最近的若干条；再按优先级取满上限。"""
    if len(facts) <= MAX_FACTS:
        return facts
    newest = sorted(facts, key=lambda x: x.updated, reverse=True)
    resolved = [x for x in newest if x.status == "resolved"][:RESOLVED_KEEP]
    kept: list[Item] = []
    for cat in KEEP_ORDER:
        mine = [x for x in newest if x.category == cat and x.status != "resolved"]
        kept += mine[: CATEGORY_CAP.get(cat, 5)]
    order = {c: i for i, c in enumerate(KEEP_ORDER)}
    kept.sort(key=lambda x: order.get(x.category, len(order)))  # 稳定排序：同类里仍是新的在前
    chosen = (kept + resolved)[:MAX_FACTS]
    return [x for x in facts if x in chosen]


def _day(item: Item) -> str:
    return f"{item.created.month}月{item.created.day}日"


def until_text(item: Item) -> str:
    return f"，到{item.until.month}月{item.until.day}日" if item.until is not None else ""


def _line(item: Item) -> str:
    label = CATEGORIES[item.category]
    if item.status == "resolved":
        label += "（已解决）"
    when = f"（{_day(item)}说的{until_text(item)}）" if item.category == "event" else ""
    return f"- {label}：{item.content}{when}"


@dataclass(frozen=True)
class Recall:
    """这一轮可用的记忆。"""

    items: tuple[Item, ...] = ()
    dropped: int = 0  # 因为超过上限没读的条数（运行记录用）

    @classmethod
    def of(cls, items: Sequence[Item], at: datetime | None = None) -> Recall:
        usable = [x for x in items if x.status in ("active", "resolved") and not expired(x, at)
                  and x.category != "followup"]  # 待跟进只在单 Agent 的四层记忆里用（§73）  # fmt: skip
        advice = [x for x in usable if x.category == "advice"][-ADVICE_KEEP:]
        facts = [x for x in usable if x.category != "advice"]
        kept = _trim(facts)
        kept.sort(key=lambda x: (ORDER.index(x.category), x.created))
        return cls((*kept, *advice), len(facts) - len(kept))

    def without(self, drop: Callable[[Item], bool]) -> Recall:
        """去掉一部分记忆（如没有正在进行的生病时，跟生病有关的事件和建议）。"""
        return replace(self, items=tuple(x for x in self.items if not drop(x)))

    def _facts(self, categories: Sequence[Category]) -> list[Item]:
        return [x for x in self.items if x.category in categories and x.category != "advice"]

    def _advice(self) -> list[Item]:
        return [x for x in self.items if x.category == "advice"]

    def shared(self) -> str:
        """共享档案以外、所有角色都读的记忆：喜好、回答风格、给过的建议（伤病、器械、时间等限制已经写进共享档案）。"""
        facts = self._facts(EVERYONE)
        advice = self._advice()
        parts = []
        if facts:
            parts.append("这个人的喜好与回答风格（照顾到；和这次问题无关的不要提）：\n"
                         + "\n".join(_line(x) for x in facts))  # fmt: skip
        if advice:
            parts.append("之前给他的建议（保持一致；需要改变时说明原因，不必重复）：\n"
                         + "\n".join(f"- {x.content}（{_day(x)}）" for x in advice))  # fmt: skip
        return "\n\n".join(parts)

    def style(self) -> str:
        """管家整合时要照顾的回答风格与喜好。"""
        facts = self._facts(EVERYONE)
        return "\n".join(_line(x) for x in facts)

    def numbers_text(self) -> str:
        """记忆里的说法都是用户自己说的：其中的数字（如哑铃 20 公斤）作答时可以直接用。"""
        return "\n".join(x.content for x in self.items if x.category != "advice")
