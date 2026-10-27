"""动作的结构化标注与替代动作：按同一动作模式、现有器械、伤病部位找更容易、相近或更难的动作。"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.exercises import EQUIPMENT, LIBRARY_BASE, Equipment, Exercise, library
from ironm_agent.protools.result import Result
from ironm_agent.yamlfile import load_yaml

TAGS_PATH = Path(__file__).parent.parent / "exercise_tags.yaml"

type Pattern = Literal[
    "squat", "hinge", "lunge", "bridge", "h_push", "v_push", "h_pull", "v_pull", "shoulder",
    "curl", "extension", "calf", "abduction", "core", "plyo", "cardio", "stretch",
]  # fmt: skip
type Joint = Literal["knee", "back", "shoulder", "wrist", "ankle", "neck"]
type Direction = Literal["easier", "similar", "harder", "any"]

PATTERN_NAMES: dict[str, str] = {
    "squat": "蹲", "hinge": "髋铰链（硬拉类）", "lunge": "单腿", "bridge": "臀桥类",
    "h_push": "水平推", "v_push": "垂直推（推举）", "h_pull": "水平拉（划船）",
    "v_pull": "垂直拉（下拉、引体）", "shoulder": "肩部小肌群", "curl": "弯举", "extension": "臂屈伸",
    "calf": "小腿", "abduction": "髋外展", "core": "核心", "plyo": "跳跃全身", "cardio": "有氧",
    "stretch": "拉伸放松",
}  # fmt: skip
JOINT_NAMES: dict[str, str] = {
    "knee": "膝盖", "back": "腰背", "shoulder": "肩", "wrist": "手腕", "ankle": "脚踝", "neck": "颈部",
}  # fmt: skip
# 同一模式里找不到合适的动作时，到相近的模式里找
RELATED: dict[str, tuple[str, ...]] = {
    "squat": ("lunge", "bridge"), "lunge": ("squat", "bridge"), "hinge": ("bridge",),
    "bridge": ("hinge",), "h_push": ("v_push",), "v_push": ("shoulder", "h_push"),
    "h_pull": ("v_pull",), "v_pull": ("h_pull",), "shoulder": ("v_push",), "extension": ("h_push",),
    "abduction": ("bridge",), "plyo": ("cardio", "squat"),
}  # fmt: skip
# 多关节的主要动作（估算时长时组间休息按大动作算）
COMPOUND: frozenset[str] = frozenset(
    {"squat", "hinge", "lunge", "h_push", "v_push", "h_pull", "v_pull", "plyo"}
)
LEVELS = {"入门": 0, "进阶": 1}


class Tag(ContractModel):
    pattern: Pattern
    groups: tuple[str, ...] = Field(min_length=1)
    muscles: tuple[str, ...] = ()  # 人体图的细分肌肉：主要练到
    assist: tuple[str, ...] = ()  # 辅助练到
    stress: tuple[Joint, ...] = ()
    friendly: tuple[Joint, ...] = ()


class TagFile(ContractModel):
    version: str
    review: str
    tags: dict[str, Tag]


@dataclass(frozen=True)
class Move:
    exercise: Exercise
    tag: Tag
    ref: str  # 动作库条目编号（K9..），引用时写这个

    @property
    def name(self) -> str:
        return self.exercise.name

    @property
    def compound(self) -> bool:
        return self.tag.pattern in COMPOUND


@cache
def moves(path: Path = TAGS_PATH) -> tuple[Move, ...]:
    """动作库里每个动作和它的标注；两边的编号对不上时报错（加了动作要同时补标注）。"""
    tags = TagFile.model_validate(load_yaml(path), strict=False).tags
    lib = library().exercises
    ids = {x.id for x in lib}
    if set(tags) != ids:
        raise ValueError(f"动作标注与动作库对不上：{sorted(set(tags) ^ ids)}")
    return tuple(Move(x, tags[x.id], f"K{LIBRARY_BASE + i}") for i, x in enumerate(lib, start=1))


_BRACKET = re.compile(r"[（(].*?[)）]")
_PREFIXES = (
    "杠铃",
    "哑铃",
    "自重",
    "高脚杯",
    "箱式",
    "单臂",
    "弹力带",
    "保加利亚",
    "罗马尼亚",
    "后撤",
    "凳上",
)


def _base(name: str) -> str:
    base = _BRACKET.sub("", name)
    for p in _PREFIXES:
        base = base.removeprefix(p)
    return base


def find(name: str) -> Move | None:
    """按名字找动作：先全名，再看名字里包含了哪个动作的全名（取最长的），最后按去掉前缀的名字。"""
    text = _BRACKET.sub("", name).strip()
    if not text:
        return None
    all_moves = moves()
    for m in all_moves:
        if m.name == text or _BRACKET.sub("", m.name) == text:
            return m
    contained = [m for m in all_moves if _BRACKET.sub("", m.name) in text]
    if contained:
        return max(contained, key=lambda m: len(_BRACKET.sub("", m.name)))
    for m in all_moves:
        base = _base(m.name)
        if len(base) >= 2 and (base in text or text in base):
            return m
    return None


def equipment_ok(move: Move, available: frozenset[Equipment] | None) -> bool:
    """None 表示不知道他有什么器械：不拦。"""
    return available is None or any(e in available for e in move.exercise.equipment)


def stressed(move: Move, injured: Collection[str]) -> list[str]:
    return [j for j in move.tag.stress if j in injured]


def equipment_of(texts: Iterable[str]) -> frozenset[Equipment] | None:
    """从他说过的器械与场地（记忆）认出有哪些器械；什么都没说过时返回 None（不知道）。"""
    joined = "".join(texts)
    if not joined.strip():
        return None
    if re.search(r"健身房|健身中心|器械都有", joined):
        return frozenset(EQUIPMENT)
    found: set[Equipment] = {"自重"}
    words: dict[Equipment, str] = {
        "哑铃": r"哑铃", "壶铃": r"壶铃", "弹力带": r"弹力带|拉力带|阻力带", "杠铃": r"杠铃",
        "单杠": r"单杠|引体|门框杆", "器械": r"器械|动感单车|单车|跑步机|龙门架|史密斯",
    }  # fmt: skip
    for equipment, pattern in words.items():
        if re.search(pattern, joined):
            found.add(equipment)
    return frozenset(found)


def _reasons(target: Move, m: Move, injured: Collection[str]) -> str:
    out = []
    if m.tag.pattern == target.tag.pattern:
        out.append(f"同为{PATTERN_NAMES[m.tag.pattern]}动作")
    else:
        out.append(f"相近的{PATTERN_NAMES[m.tag.pattern]}动作")
    spared = [JOINT_NAMES[j] for j in injured if j in target.tag.stress and j not in m.tag.stress]
    if spared:
        out.append("不给" + "、".join(spared) + "加负担")
    kind = [JOINT_NAMES[j] for j in m.tag.friendly if j in injured]
    if kind:
        out.append("常用来照顾" + "、".join(kind))
    diff = LEVELS[m.exercise.level] - LEVELS[target.exercise.level]
    out.append({-1: "比原动作容易", 0: "难度相近", 1: "比原动作难"}[diff])
    return "，".join(out)


def ranked(
    target: Move,
    *,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str] = (),
    direction: Direction = "any",
    k: int = 4,
) -> list[Move]:
    """按器械、伤处和难度方向给一个动作排出替代动作（第一个最合适）。"""
    level = LEVELS[target.exercise.level]
    scored: list[tuple[int, int, Move]] = []
    for i, m in enumerate(moves()):
        if m is target or not equipment_ok(m, equipment) or stressed(m, injured):
            continue
        same = m.tag.pattern == target.tag.pattern
        if not same and (
            direction == "similar" or m.tag.pattern not in RELATED.get(target.tag.pattern, ())
        ):
            continue
        diff = LEVELS[m.exercise.level] - level
        if (direction == "easier" and diff > 0) or (direction == "harder" and diff < 0):
            continue
        score = (3 if same else 1) + 2 * len([j for j in m.tag.friendly if j in injured])
        score += (
            1 if (direction == "easier" and diff < 0) or (direction == "harder" and diff > 0) else 0
        )
        scored.append((score, i, m))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [m for _, _, m in scored[:k]]


def substitutes(
    name: str,
    *,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str] = (),
    direction: Direction = "any",
    k: int = 4,
) -> Result:
    target = find(name)
    if target is None:
        return Result.note(
            f"动作库里没有「{name}」，找不到它的替代；可以按动作模式凭经验给，并说明是经验。"
        )
    picked = ranked(target, equipment=equipment, injured=injured, direction=direction, k=k)
    have = "、".join(sorted(equipment)) if equipment is not None else "不知道（没说过）"
    hurt = "、".join(JOINT_NAMES[j] for j in injured) or "无"
    load = (
        "会给" + "、".join(JOINT_NAMES[j] for j in target.tag.stress) + "加负担"
        if target.tag.stress
        else "对关节的负担较小"
    )
    head = (
        f"「{target.name}」〔{target.ref}〕是{PATTERN_NAMES[target.tag.pattern]}动作，{load}。"
        f"条件：器械 {have}；伤病部位 {hurt}。"
    )
    library_says = f"动作库给它的替代〔{target.ref}〕：更容易 {target.exercise.easier}；更难 {target.exercise.harder}"
    if not picked:
        return Result(
            notes=(head, "按这些条件，动作库里没有合适的替代动作。", library_says),
            entries=(target.ref,),
        )
    lines = [
        f"- {m.name}〔{m.ref}〕（{m.exercise.level}；器械：{'、'.join(m.exercise.equipment)}）：{_reasons(target, m, injured)}"
        for m in picked
    ]
    return Result(
        notes=(head, "可以换成：", *lines, library_says),
        entries=(target.ref, *(m.ref for m in picked)),
    )
