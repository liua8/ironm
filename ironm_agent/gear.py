"""场所与器材（spec [2026-10-23] §107）：开头填一次、档案里改、跟管家说也能改，都是记忆里同一份"器械与场地"。

表单填的写成一句话存进记忆；读的时候和排计划、换动作一样用 equipment_of 认器械。不读写存储。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Literal

from ironm_agent.exercises import Equipment
from ironm_agent.memory_store import Item
from ironm_agent.protools.movement import equipment_of, equipment_ok, find
from ironm_agent.training import Plan

type Place = Literal["gym", "home", "both"]
PLACES: dict[Place, str] = {"gym": "健身房", "home": "家里", "both": "都有"}
# 家里可能有的（自重不用选；"只有自重"就是一样都不选）
GEAR: tuple[Equipment, ...] = ("哑铃", "壶铃", "弹力带", "杠铃", "单杠", "器械")
GEAR_NAMES: dict[Equipment, str] = {"器械": "健身器械"}
_GYM = re.compile(r"健身房|健身中心|器械都有")
FORM = "档案里填的"  # 表单存的记忆写在"原话"里的标记
_HOME = re.compile(r"家里|在家|家中|宿舍|小区")


MAX_CUSTOM = 8
_NOT = re.compile(r"没有|无|不")
_SPLIT = "、"


def custom_ok(name: str) -> str:
    """一样自己加的器材：可以就返回整理好的名字，不行返回为什么。"""
    n = re.sub(r"[、，,；;。\s]+", "", name)
    if not n or len(n) > 12:
        return "每样器材写 1 到 12 个字"
    if _NOT.search(n):
        return "写有的器材就行，没有的不用写"
    return ""


def clean_custom(names: Sequence[str]) -> list[str]:
    """去掉标点、和勾选项同名的、重复的。"""
    taken = {GEAR_NAMES.get(g, g) for g in GEAR} | set(GEAR)
    out: list[str] = []
    for name in names:
        n = re.sub(r"[、，,；;。\s]+", "", name)
        if n and n not in taken and n not in out:
            out.append(n)
    return out[:MAX_CUSTOM]


def sentence(place: Place, gear: Sequence[Equipment], custom: Sequence[str] = ()) -> str:
    """存进记忆的那句话。没有的器械不写出来：写"没有器械"会被认成有器械。"""
    have = [GEAR_NAMES.get(g, g) for g in GEAR if g in gear] + clean_custom(custom)
    home = f"家里有{_SPLIT.join(have)}" if have else "家里只有自重，不用工具"
    if place == "gym":
        return "在健身房练，器械都有"
    if place == "home":
        return f"在家练，{home}"
    return f"健身房和家里都练；{home}"


def current(items: Sequence[Item]) -> list[Item]:
    from ironm_agent.latest import current as latest

    return [x for x in latest(items) if x.category == "equipment" and x.status == "active"]


def read(items: Sequence[Item]) -> dict[str, Any]:
    """现在记的场所与器材：known（记过没有）、place、gear（家里有的）、text（记的原话，给他看）。"""
    mine = current(items)
    if not mine:
        return {"known": False, "place": None, "gear": [], "custom": [], "text": "", "form": False}
    texts = [x.content for x in mine]
    joined = "；".join(texts)
    gym, home = bool(_GYM.search(joined)), bool(_HOME.search(joined))
    place: Place | None = "both" if gym and home else "gym" if gym else "home" if home else None
    # 家里有什么：只看说家里的那几句（健身房那句会被认成"器械都有"）
    home_texts = [t for t in texts if not _GYM.search(t) or _HOME.search(t)]
    found = equipment_of([_GYM.sub("", t) for t in home_texts]) or frozenset()
    form = len(mine) == 1 and mine[0].evidence == FORM  # 就是档案里填的那一条：页面不再重复原话
    gear = [g for g in GEAR if g in found]
    custom: list[str] = []
    if (
        form
    ):  # 表单写的那句"家里有 A、B、C"：按原样分出勾的和自己加的（划船机不会让"健身器械"被勾上）
        names = joined.split("家里有", 1)[1].split(_SPLIT) if "家里有" in joined else []
        gear = [g for g in GEAR if GEAR_NAMES.get(g, g) in names]
        custom = clean_custom(names)
    return {"known": True, "place": place, "gear": gear, "custom": custom,
            "text": joined, "form": form}  # fmt: skip


def missing(plan: Plan | None, equipment: frozenset[Equipment] | None) -> list[str]:
    """计划里要用他没有的器械的动作（去重，按出现先后）。"""
    if plan is None or equipment is None:
        return []
    out: list[str] = []
    for s in plan.sessions:
        for x in s.items:
            m = find(x.exercise)
            if m is not None and not equipment_ok(m, equipment) and x.exercise not in out:
                out.append(x.exercise)
    return out
