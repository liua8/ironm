"""作答时怎么用记忆：L2 按类别分给各专业 Agent，L3 画像是有效记忆直接排成的清单（不经模型改写）。

作答前把这个人的全部有效记忆读进来（一个人通常几十条），不靠关键词检索，避免漏召回。
待确认的（系统推断、用户还没确认）和被取代的不用；近期事件过了 EVENT_DAYS 天不再用。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ironm_agent.memory_store import CATEGORIES, Category, Item, now
from ironm_agent.roles import Role

EVENT_DAYS = 14  # 近期事件多少天后不再用于回答
ADVICE_KEEP = 5  # 给过的建议只带最近几条

ROLE_CATEGORIES: dict[Role, tuple[Category, ...]] = {
    Role.PLANNER: ("injury", "equipment", "schedule", "goal", "event"),
    Role.EXERCISE: ("injury", "equipment"),
    Role.NUTRITION: ("diet", "goal"),
    Role.RECOVERY: ("injury", "event", "schedule"),
    Role.DATA: ("goal",),
}
EVERYONE: tuple[Category, ...] = ("preference", "style")
ORDER = tuple(CATEGORIES)


def expired(item: Item, at: datetime | None = None) -> bool:
    return item.category == "event" and (at or now()) - item.created > timedelta(days=EVENT_DAYS)


def _day(item: Item) -> str:
    return f"{item.created.month}月{item.created.day}日"


def _line(item: Item) -> str:
    label = CATEGORIES[item.category]
    if item.status == "resolved":
        label += "（已解决）"
    when = f"（{_day(item)}说的）" if item.category == "event" else ""
    return f"- {label}：{item.content}{when}"


@dataclass(frozen=True)
class Recall:
    """这一轮可用的记忆。"""

    items: tuple[Item, ...] = ()

    @classmethod
    def of(cls, items: Sequence[Item], at: datetime | None = None) -> Recall:
        usable = [x for x in items if x.status in ("active", "resolved") and not expired(x, at)]
        advice = [x for x in usable if x.category == "advice"][-ADVICE_KEEP:]
        facts = [x for x in usable if x.category != "advice"]
        facts.sort(key=lambda x: (ORDER.index(x.category), x.created))
        return cls((*facts, *advice))

    def _facts(self, categories: Sequence[Category]) -> list[Item]:
        return [x for x in self.items if x.category in categories and x.category != "advice"]

    def _advice(self) -> list[Item]:
        return [x for x in self.items if x.category == "advice"]

    def for_role(self, role: Role) -> str:
        """给一位专业 Agent 的记忆（L2）：它这一领域的类别，加上所有人都读的喜好、回答风格和给过的建议。"""
        facts = self._facts((*ROLE_CATEGORIES.get(role, ()), *EVERYONE))
        advice = self._advice()
        parts = []
        if facts:
            parts.append("这个人以前说过的情况（作答时要照顾到；和这次问题无关的不要提）：\n"
                         + "\n".join(_line(x) for x in facts))  # fmt: skip
        if advice:
            parts.append("之前给他的建议（保持一致；需要改变时说明原因，不必重复）：\n"
                         + "\n".join(f"- {x.content}（{_day(x)}）" for x in advice))  # fmt: skip
        return "\n\n".join(parts)

    def categories_for(self, role: Role) -> list[Category]:
        """这位专业 Agent 拿到了哪几类记忆（写日志用，只有类别，不含内容）。"""
        shown = (*ROLE_CATEGORIES.get(role, ()), *EVERYONE, "advice")
        return [c for c in ORDER if c in shown and any(x.category == c for x in self.items)]

    def persona(self) -> str:
        """画像（L3）：全部有效记忆按类别排成清单，主教练调度和直接回答时用。"""
        facts = self._facts(ORDER)
        if not facts:
            return ""
        return "这个人以前说过的情况：\n" + "\n".join(_line(x) for x in facts)

    def style(self) -> str:
        """主教练整合时要照顾的回答风格与喜好。"""
        facts = self._facts(EVERYONE)
        return "\n".join(_line(x) for x in facts)

    def numbers_text(self) -> str:
        """记忆里的说法都是用户自己说的：其中的数字（如哑铃 20 公斤）作答时可以直接用。"""
        return "\n".join(x.content for x in self.items if x.category != "advice")
