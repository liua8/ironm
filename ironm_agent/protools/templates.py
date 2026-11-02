"""方案库与"选初步方案"（spec [2026-10-23] §77）：按类别先定好的初步方案，挑出最合适的，再按这个人的器械、
伤病把动作位换成动作库里的具体动作，排到一周的哪几天，做成可以直接改的计划草稿。

只算不查、不读写存储；最后的计划仍由 Agent 写、计划检查工具检查、用户确认后才保存。
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from itertools import combinations, pairwise
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ironm_agent.common import ContractModel
from ironm_agent.exercises import Equipment
from ironm_agent.kb import default_kb
from ironm_agent.protools.movement import (
    JOINT_NAMES,
    Move,
    equipment_ok,
    moves,
    ranked,
    stressed,
)
from ironm_agent.protools.plan_check import SLACK, back_to_back, check_plan, estimate_minutes
from ironm_agent.protools.result import Finding, Result
from ironm_agent.training import Plan, PlanItem, Session, weekday_name
from ironm_agent.yamlfile import load_yaml

LIBRARY_PATH = Path(__file__).parent.parent / "plan_library.yaml"

type Level = Literal["none", "lt6m", "6m-2y", "2y+"]
type GoalKey = Literal["health", "fat_loss", "muscle", "strength", "endurance"]
type People = Literal["adult", "older", "youth"]
type Place = Literal["gym", "home"]

LEVELS: dict[str, str] = {
    "none": "零基础", "lt6m": "练了不到 6 个月", "6m-2y": "练了 6 个月到 2 年", "2y+": "练了 2 年以上",
}  # fmt: skip
GOALS: dict[str, str] = {
    "health": "健康体能", "fat_loss": "减脂", "muscle": "增肌", "strength": "力量", "endurance": "耐力",
}  # fmt: skip
PEOPLE: dict[str, str] = {"adult": "成年人", "older": "60 岁以上", "youth": "18 岁以下"}
PLACES: dict[str, str] = {"gym": "健身房", "home": "在家"}
OLDER_AGE = 60
ADULT_AGE = 18
# 没说哪几天能练时的默认排法：训练日尽量隔开
DEFAULT_DAYS: dict[int, tuple[int, ...]] = {
    1: (3,), 2: (1, 4), 3: (1, 3, 5), 4: (1, 2, 4, 5), 5: (1, 2, 3, 5, 6), 6: (1, 2, 3, 4, 5, 6),
    7: (1, 2, 3, 4, 5, 6, 7),
}  # fmt: skip
SHOW = 2  # 最多给几个方案
SHORT = 35  # 每次不超过这么多分钟的方案，算专为时间少排的


class Slot(ContractModel):
    """一个动作位：按顺序挑第一个合适的动作；都不行时找同类替代，再不行用 free（动作库里没有的动作）。"""

    pick: tuple[str, ...] = ()
    free: str = ""
    sets: int = Field(ge=1, le=10)
    reps: str = Field(min_length=1, max_length=20)
    load: str = Field(default="", max_length=40)
    note: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def _some(self) -> Slot:
        if not self.pick and not self.free:
            raise ValueError("动作位要写 pick 或 free")
        return self


class Source(ContractModel):
    """博主方案从哪来（§78）：只提取结构，用自己的话写；二手整理的要写明。"""

    authors: tuple[str, ...] = Field(min_length=1)
    url: str = Field(pattern=r"^https://")
    seen: date  # 查看日期
    secondhand: bool  # 是不是别人整理的（不是博主本人发布）
    note: str = ""


class Template(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: Literal["base", "blogger"] = "base"  # 自己的初步方案 / 博主方案（§78）
    standard: bool = False  # 一般人的标准方案（§79）：一般成年人没点名时默认给
    novice_sets: dict[Level, int] = Field(default_factory=dict)  # 新手每个动作最多几组，不做力竭
    name: str = Field(min_length=1, max_length=24)
    levels: tuple[Level, ...] = Field(min_length=1)
    goals: tuple[GoalKey, ...] = Field(min_length=1)
    people: tuple[People, ...] = Field(min_length=1)
    place: Literal["gym", "home", "any"]
    needs: tuple[Equipment, ...] = ()
    minutes: tuple[int, int]
    weeks: dict[int, tuple[str, ...]]
    days: dict[int, tuple[int, ...]] = Field(default_factory=dict)  # 不按默认排法时，几天练对应周几
    why: str
    intensity: str
    progress: str
    deload: str
    refs: tuple[str, ...] = Field(min_length=1)
    inspired: str = ""
    source: Source | None = None  # 博主方案必填
    aliases: tuple[str, ...] = ()  # 点名用的叫法（博主名、计划名）
    conflicts: tuple[str, ...] = ()  # 和依据不一致的地方
    extras: str = ""  # 附加说明，不放进计划
    sessions: dict[str, tuple[Slot, ...]]

    @model_validator(mode="after")
    def _shape(self) -> Template:
        for n, names in self.weeks.items():
            if not 1 <= n <= 7 or len(names) != n:
                raise ValueError(f"{self.id}：每周 {n} 天要排 {n} 次训练")
            if missing := set(names) - set(self.sessions):
                raise ValueError(f"{self.id}：没有这几次训练 {sorted(missing)}")
        if unused := set(self.sessions) - {x for names in self.weeks.values() for x in names}:
            raise ValueError(f"{self.id}：这几次训练没排进任何一周 {sorted(unused)}")
        for n, days in self.days.items():
            if n not in self.weeks or len(days) != n or len(set(days)) != n:
                raise ValueError(f"{self.id}：每周 {n} 天的排法不对")
        if any(len(s) > 10 or not s for s in self.sessions.values()):
            raise ValueError(f"{self.id}：每次训练 1–10 个动作")
        if (self.kind == "blogger") != (self.source is not None):
            raise ValueError(f"{self.id}：博主方案要写来源，自己的方案不写")
        return self

    def calls(self) -> tuple[str, ...]:
        """点名时认的叫法：方案名、编号、别名、博主。"""
        return (self.name, self.id, *self.aliases, *(self.source.authors if self.source else ()))


class TemplateFile(ContractModel):
    version: str
    review: str
    plans: tuple[Template, ...]


@cache
def _by_name() -> dict[str, Move]:
    return {m.name: m for m in moves()}


@cache
def templates(path: Path = LIBRARY_PATH) -> tuple[Template, ...]:
    """读方案库；编号重复、动作库里没有的动作名、依据库里没有的编号都报错。"""
    plans = TemplateFile.model_validate(load_yaml(path), strict=False).plans
    ids = [t.id for t in plans]
    if len(ids) != len(set(ids)):
        raise ValueError("方案编号重复")
    names, kb = _by_name(), default_kb()
    for t in plans:
        for slot in (s for slots in t.sessions.values() for s in slots):
            if bad := [n for n in slot.pick if n not in names]:
                raise ValueError(f"{t.id}：动作库里没有 {bad}")
        if bad := [r for r in t.refs if kb.get(r) is None]:
            raise ValueError(f"{t.id}：依据库里没有 {bad}")
    return plans


def named(text: str) -> tuple[Template, ...]:
    """他点名要的方案（说了博主名或计划名）。"""
    return tuple(t for t in templates() if text and any(c and c in text for c in t.calls()))


def people_of(age: int | None) -> People:
    if age is None:
        return "adult"
    return "youth" if age < ADULT_AGE else "older" if age >= OLDER_AGE else "adult"


@dataclass(frozen=True)
class Choice:
    template: Template
    days: int  # 用这个方案的哪一个天数版本
    score: int
    gaps: tuple[str, ...]  # 和他的条件不完全对得上的地方


def choose(
    *,
    level: Level | None,
    goal: GoalKey | None,
    days: int,
    minutes: int | None,
    place: Place | None,
    people: People,
    equipment: frozenset[Equipment] | None,
    k: int = SHOW,
    only: Sequence[Template] = (),
) -> list[Choice]:
    """按水平、目标、天数、时长、场地、人群挑方案。人群、水平、必须的器械、场地不对的不选；其余按对得上的多少排。
    only 是他点名要的方案：不按条件筛掉，对不上的写进 gaps；没点名时博主方案排在自己的方案后面（§78）。"""
    out: list[Choice] = []
    for order, t in enumerate(only or templates()):
        gaps: list[str] = []
        score = 0
        misfit = [
            *([f"这个方案是给{'、'.join(PEOPLE[x] for x in t.people)}排的"] if people not in t.people else []),
            *([f"这个方案适合{'、'.join(LEVELS[x] for x in t.levels)}的人"]
              if level is not None and level not in t.levels else []),
            *(["这个方案要在健身房练"] if place == "home" and t.place == "gym" else []),
            *([f"这个方案要有{'、'.join(t.needs)}"] if t.needs and (
                (equipment is None and place == "home")
                or (equipment is not None and not set(t.needs) <= equipment)) else []),
        ]  # fmt: skip
        if misfit and not only:
            continue
        gaps += misfit
        if (
            t.standard
            and not only
            and not misfit
            and days in t.weeks
            and (goal is None or goal in t.goals)
            and (minutes is None or minutes >= t.minutes[0])
        ):
            score += 10  # 一般人的标准方案（§79）
        elif t.kind == "blogger" and not only:
            score -= 3
        n = days if days in t.weeks else min(t.weeks, key=lambda d: (abs(d - days), -d))
        if n == days:
            score += 4
        else:
            gaps.append(f"没有每周 {days} 天的版本，最接近的是每周 {n} 天")
            score -= abs(n - days)
        if goal is not None and goal in t.goals:
            score += 4 if goal == t.goals[0] else 3  # goals 按主次写，主要为这个目标排的排前面
        elif goal is not None:
            gaps.append(f"不是专门为{GOALS[goal]}排的")
            score -= 3
        lo, hi = t.minutes
        if minutes is not None and minutes < lo:
            gaps.append(f"每次大概要 {lo}–{hi} 分钟，比你能练的 {minutes} 分钟长")
            score -= 2
        elif minutes is not None and minutes <= hi:
            score += 1
        elif hi <= SHORT:  # 专为时间少排的：他时间够或没说时，往后放
            score -= 1
            if minutes is not None:
                gaps.append(f"这个方案每次只要 {lo}–{hi} 分钟，你有 {minutes} 分钟")
        if place is not None and t.place == place:
            score += 1  # 专为这个场地排的排前面
        elif place == "gym" and t.place == "home":
            score -= 1
        if level is None and "none" in t.levels:
            score += 1  # 不知道水平时，入门的排前面
        out.append(Choice(t, n, score * 100 - order, tuple(gaps)))
    out.sort(key=lambda c: -c.score)
    return out[:k]


def _pick(
    slot: Slot,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str],
    used: Collection[str],
) -> tuple[Move | None, str]:
    """挑这个动作位的动作：返回动作（free 时是 None）和换动作的原因（没换为空）。"""
    names = _by_name()
    for name in slot.pick:
        m = names[name]
        if m.name not in used and equipment_ok(m, equipment) and not stressed(m, injured):
            return m, ""
    if slot.pick:
        first = names[slot.pick[0]]
        for direction in ("easier", "any"):
            alt = [
                m
                for m in ranked(first, equipment=equipment, injured=injured, direction=direction)
                if m.name not in used
            ]
            if alt:
                return alt[
                    0
                ], f"按你的器械和伤病，「{first.name}」这一位换成同类的「{alt[0].name}」"
    return None, ""


def _tame(text: str) -> str:
    return text.replace("，可做到力竭", "").replace("力竭", "还剩 2 次")


def _session(
    name: str,
    day: int,
    slots: Sequence[Slot],
    equipment: frozenset[Equipment] | None,
    injured: Collection[str],
    cap: int | None = None,
) -> tuple[Session, list[str]]:
    """cap：新手每个动作最多几组，同时去掉力竭（§79）。"""
    items: list[PlanItem] = []
    notes: list[str] = []
    used: list[str] = []
    for slot in slots:
        move, why = _pick(slot, equipment, injured, used)
        if cap is not None:
            slot = slot.model_copy(update={"sets": min(slot.sets, cap), "reps": _tame(slot.reps),
                                           "note": _tame(slot.note)})  # fmt: skip
        if move is not None:
            used.append(move.name)
            note = slot.note
            if equipment is not None and set(move.exercise.equipment) & equipment == {"弹力带"}:
                note = "；".join(x for x in ("用弹力带做", note) if x)  # 名字是器械版，他只有弹力带
            items.append(PlanItem(exercise=move.name, sets=slot.sets, reps=slot.reps,
                                  load=slot.load, note=note))  # fmt: skip
            if why:
                notes.append(why)
        elif slot.free:
            items.append(PlanItem(exercise=slot.free, sets=slot.sets, reps=slot.reps,
                                  load=slot.load, note=slot.note))  # fmt: skip
        else:
            notes.append(f"「{slot.pick[0]}」这一位按你的器械和伤病找不到合适的动作，先空着")
    if not items:
        raise ValueError("这次训练一个动作也排不出来")
    s = Session(day=day, name=name, minutes=10, items=items)
    return s.model_copy(update={"minutes": max(10, min(180, round(estimate_minutes(s))))}), notes


def _fit(session: Session, minutes: int | None) -> tuple[Session, list[str]]:
    """估计时长超过他能练的时间时裁剪：先减辅助动作（排在后面的）的组数，再去掉排在最后的动作。"""
    if minutes is None:
        return session, []
    items = list(session.items)
    cut: list[str] = []

    def need() -> float:
        return estimate_minutes(session.model_copy(update={"items": items}))

    for i in range(len(items) - 1, -1, -1):
        while need() > minutes * SLACK and items[i].sets > 2:
            items[i] = items[i].model_copy(update={"sets": items[i].sets - 1})
            cut.append(f"{items[i].exercise}减到 {items[i].sets} 组")
    while need() > minutes * SLACK and len(items) > 3:
        cut.append(f"去掉{items.pop().exercise}")
    s = session.model_copy(update={"items": items, "minutes": max(10, min(180, round(need())))})
    return s, ([f"{weekday_name(s.day)}按 {minutes} 分钟裁剪：" + "、".join(cut)] if cut else [])


def _gap(days: Sequence[int]) -> int:
    """相邻两次训练之间最少隔几天（跨周也算）。"""
    if len(days) < 2:
        return 7
    ds = sorted(days)
    return min([b - a for a, b in pairwise(ds)] + [ds[0] + 7 - ds[-1]])


def draft(
    t: Template,
    days: int,
    *,
    goal: GoalKey | None,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str] = (),
    weekdays: Sequence[int] = (),
    minutes: int | None = None,
    level: Level | None = None,
) -> tuple[Plan, list[str]]:
    """把方案做成计划草稿。weekdays 是他能练的周几；排法按"同一肌群不连着两天"最少、训练日隔得最开来挑。
    level 是新手时按方案写的组数上限减组、不做力竭（§79）。"""
    names = t.weeks[days]
    cap = t.novice_sets.get(level) if level else None
    default = t.days.get(days, DEFAULT_DAYS[days])
    pool = sorted(set(weekdays)) if len(set(weekdays)) >= days else list(range(1, 8))
    notes: list[str] = []
    if weekdays and len(set(weekdays)) < days:
        notes.append(f"你说能练的日子不到 {days} 天，先按常见排法放，具体哪天可以再挪")
    best: tuple[tuple[int, int, int], Plan, list[str]] | None = None
    for combo in combinations(pool, days):
        sessions, why = [], []
        for name, day in zip(names, combo, strict=True):
            s, n = _session(name, day, t.sessions[name], equipment, injured, cap)
            s, cut = _fit(s, minutes)
            sessions.append(s)
            why += n + cut
        plan = Plan(title=t.name.split(" · ")[0], goal=GOALS[goal] if goal else "",
                    days_per_week=days, sessions=sessions)  # fmt: skip
        key = (len(back_to_back(plan)), -_gap(combo), 0 if combo == default else 1)
        if best is None or key < best[0]:
            best = (key, plan, why)
    assert best is not None
    return best[1], notes + list(dict.fromkeys(best[2]))


def _blogger(t: Template) -> list[str]:
    """博主方案要交代的：从哪来、不是依据、和依据不一致的地方、附加说明（§78）。"""
    if t.source is None:
        return []
    src = t.source
    how = "第三方整理、没有核对博主原发的内容" if src.secondhand else "博主本人公开发布"
    return [
        f"- 博主方案：参考{'、'.join(src.authors)}的公开计划（{src.url}，{how}，{src.seen.isoformat()} 查看"
        + (f"；{src.note}" if src.note else "")
        + "）。这是经验做法、不是依据，不写成依据编号，也不要说成官方计划。",
        *(f"- 和依据不一致：{x}" for x in t.conflicts),
        *([f"- 附加（不放进计划，问到再说）：{t.extras}"] if t.extras else []),
    ]


def catalog() -> Result:
    """方案库一共有哪些（§83）：问"有多少训练计划、有哪些"时用。"""
    plans = templates()
    lines = [
        f"- {t.name}：{_blurb(t)}"
        + ("（一般人的标准方案）" if t.standard else "（博主方案）" if t.kind == "blogger" else "")
        for t in plans
    ]
    return Result.note(
        f"方案库一共 {len(plans)} 份初步方案：",
        *lines,
        "全部计划在 App 的「夯」→ 训练计划榜能看（每周怎么练、为什么这样排、来源）；"
        "他想用哪一份，按他的器械、伤病和时间改好、确认后才保存。"
        "他自己现在用的是哪一份，看档案里的当前计划。",
    )


def _blurb(t: Template) -> str:
    who = (
        "、".join(PEOPLE[p] for p in t.people)
        if t.people != ("adult",)
        else "各种水平"
        if len(t.levels) == len(LEVELS)
        else "、".join(LEVELS[x] for x in t.levels)
    )
    days = "或".join(str(n) for n in sorted(t.weeks))
    goals = "、".join(GOALS[g] for g in t.goals[:2])
    return f"{who}，主要为{goals}，每周 {days} 天"


def as_json(plan: Plan) -> str:
    return json.dumps(plan.model_dump(), ensure_ascii=False, separators=(",", ":"))


def plan_templates(
    *,
    level: Level | None,
    goal: GoalKey | None,
    days: int,
    minutes: int | None,
    place: Place | None,
    age: int | None,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str] = (),
    weekdays: Sequence[int] = (),
    name: str = "",
    special: Collection[str] = (),
) -> Result:
    people = people_of(age)
    said: list[str] = []
    asked = named(name)
    if name and not asked:
        said.append(
            f"方案库里没有「{name}」这个方案，下面是按条件挑的；可以说清是谁的哪套计划，或者照他说的自己排。"
        )
    if place == "home" and equipment is None:
        equipment = frozenset({"自重"})
        said.append("没说过家里有什么器械，先按只有自重排；有哑铃、弹力带告诉我再换。")
    if level is None:
        said.append("不知道训练水平，按入门挑的；问清以后可以再挑。")
    picked = choose(level=level, goal=goal, days=days, minutes=minutes, place=place,
                    people=people, equipment=equipment, only=asked)  # fmt: skip
    cond = "；".join(
        x
        for x in (
            f"水平 {LEVELS[level]}" if level else "水平 不知道",
            f"目标 {GOALS[goal]}" if goal else "目标 不知道",
            f"每周 {days} 天",
            f"每次 {minutes} 分钟" if minutes else "",
            f"场地 {PLACES[place]}" if place else "",
            f"人群 {PEOPLE[people]}",
            "器械 " + ("、".join(sorted(equipment)) if equipment is not None else "不知道"),
            "伤病 " + ("、".join(JOINT_NAMES[j] for j in injured) or "无"),
        )
        if x
    )
    if not picked:
        return Result.note(
            f"条件：{cond}。",
            "方案库里没有合适的初步方案（人群、水平、场地或器械对不上）。按规程自己排，并说明没有现成方案可套。",
            *said,
        )
    findings: list[Finding] = []
    notes = [f"条件：{cond}。", *said]
    entries: list[str] = []
    for i, c in enumerate(picked, start=1):
        t = c.template
        plan, changes = draft(t, c.days, goal=goal, equipment=equipment, injured=injured,
                              weekdays=weekdays, minutes=minutes, level=level)  # fmt: skip
        if level in t.novice_sets:
            changes.insert(
                0, f"按{LEVELS[level]}减到每个动作最多 {t.novice_sets[level]} 组，不做到力竭"
            )
        if t.standard and not asked:
            changes.insert(0, "这是一般人的标准方案：一般成年人没点名时默认用这一份")
        checked = check_plan(plan, goal=goal, novice=level in (None, "none", "lt6m"),
                             injured=injured, equipment=equipment, available_days=days,
                             available_minutes=minutes, special=special)  # fmt: skip
        verdict = next((f.text for f in checked.findings if f.name == "计划检查"), "")
        findings.append(
            Finding(
                f"方案{i}「{t.name}」",
                "；".join(
                    (f"每周 {c.days} 天", *(weekday_name(s.day) + s.name for s in plan.sessions))
                )
                + (f"。和你的条件不完全一样：{'；'.join(c.gaps)}" if c.gaps else ""),
                ("按他点名的方案" if asked else "按水平、目标、天数、时长、场地、人群从方案库挑出")
                + "，再按器械和伤病换成具体动作",
                cond,
                "、".join(t.refs)
                + (f"；博主方案（{'、'.join(t.source.authors)}）" if t.source else "")
                + "；方案库（待审定）",
            )
        )
        notes += [
            f"方案{i}「{t.name}」（{t.id}）",
            f"- 为什么这样排：{t.why}",
            f"- 强度：{t.intensity}",
            f"- 怎么进阶：{t.progress}",
            f"- 什么时候减量：{t.deload}",
            *([f"- 参考：{t.inspired}"] if t.inspired else []),
            *(_blogger(t)),
            *(f"- {x}" for x in changes),
            f"- 计划检查：{verdict}",
            f"- 草稿（照这个人改好后写进 plan）：{as_json(plan)}",
        ]
        entries += [e for e in checked.entries if e not in entries]
    return Result(tuple(findings), tuple(notes), tuple(entries))
