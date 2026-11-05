"""动作库：从 exercises.yaml 读入并校验（部位、器械只能从固定的几类里选，编号不能重复）。"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.kb import Entry, KnowledgeBase
from ironm_agent.yamlfile import load_yaml

EXERCISES_PATH = Path(__file__).with_name("exercises.yaml")
FEEL_PATH = Path(__file__).with_name("exercise_feel.yaml")

type Part = Literal["腿臀", "胸", "背", "肩", "手臂", "核心", "全身", "有氧", "拉伸放松"]
type Equipment = Literal["自重", "哑铃", "壶铃", "弹力带", "杠铃", "单杠", "器械", "泡沫轴"]
PARTS: tuple[Part, ...] = ("腿臀", "胸", "背", "肩", "手臂", "核心", "全身", "有氧", "拉伸放松")
EQUIPMENT: tuple[Equipment, ...] = (
    "自重",
    "哑铃",
    "壶铃",
    "弹力带",
    "杠铃",
    "单杠",
    "器械",
    "泡沫轴",
)
NOTE = "出现疼痛就停下；有伤病先问医生或康复师。"


class Exercise(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    part: Part
    muscles: str
    equipment: tuple[Equipment, ...] = Field(min_length=1)
    level: Literal["入门", "进阶"]
    steps: tuple[str, ...] = Field(min_length=3)
    cues: tuple[str, ...] = Field(min_length=2)
    mistakes: tuple[str, ...] = Field(min_length=1)
    easier: str
    harder: str
    avoid: str = Field(min_length=1)
    timed: bool = False  # 计时类动作（平板支撑等）：训练记录器记秒数不记次数（§71）
    common: bool = True  # 最常见的动作（§144）；在家替代器械用的冷门动作标 false，图鉴里排在后面


class Library(ContractModel):
    version: str
    review: str
    exercises: tuple[Exercise, ...]


@cache
def library(path: Path = EXERCISES_PATH) -> Library:
    lib = Library.model_validate(load_yaml(path), strict=False)
    ids = [x.id for x in lib.exercises]
    if len(ids) != len(set(ids)):
        raise ValueError("动作编号重复")
    return lib


class Feel(ContractModel):
    cue: str = Field(min_length=4, max_length=60)  # 说给用户听的类比
    replaces: str = Field(min_length=2)  # 它替代的书面说法：只给审定对照，不交给 Agent


class FeelFile(ContractModel):
    version: str
    review: str
    feel: dict[str, tuple[Feel, ...]]


@cache
def feel_cues(path: Path = FEEL_PATH) -> dict[str, tuple[Feel, ...]]:
    """动作库的体感提示（spec [2026-10-23] §8 体感讲解）：每个动作 1–3 条，和动作库的编号对不上时报错。"""
    cues = FeelFile.model_validate(load_yaml(path), strict=False).feel
    ids = {x.id for x in library().exercises}
    if set(cues) != ids:
        raise ValueError(f"体感提示与动作库对不上：{sorted(set(cues) ^ ids)}")
    if any(not 1 <= len(v) <= 3 for v in cues.values()):
        raise ValueError("每个动作的体感提示要有 1–3 条")
    return cues


# 动作库作为依据（spec [2026-10-23] §8）：每个动作一条，编号 K901 起（按 exercises.yaml 的顺序，只往后加），
# 和依据库的资料一样引用、核对，列进"依据与来源"
LIBRARY_BASE = 900


@cache
def library_entries() -> tuple[Entry, ...]:
    out = []
    feel = feel_cues()
    for i, x in enumerate(library().exercises, start=1):
        points = [
            *({"text": f"做法：{s}", "where": "做法"} for s in x.steps),
            {"text": "要点：" + "；".join(x.cues), "where": "要点"},
            {"text": "体感提示：" + "；".join(c.cue for c in feel[x.id]), "where": "体感提示"},
            {"text": "常见错误：" + "；".join(x.mistakes), "where": "常见错误"},
            {"text": f"更容易的替代：{x.easier}；更难的：{x.harder}", "where": "替代"},
            {"text": f"什么情况先别做：{x.avoid}", "where": "什么情况先别做"},
        ]
        out.append(
            Entry.model_validate(
                {
                    "id": f"K{LIBRARY_BASE + i}",
                    "domains": ["library"],
                    "title": x.name,
                    "source": "iron-m 动作库",
                    "publisher": "iron-m",
                    "year": 2026,
                    "level": "library",
                    "population": "一般成年人",
                    "summary": f"{x.part}，主要练{x.muscles}；器械：{'、'.join(x.equipment)}；{x.level}",
                    "points": points,
                    "keywords": [x.name, x.part, *x.equipment],
                    "review": "claude_draft",
                },
                strict=False,
            )
        )
    return tuple(out)


@cache
def library_kb() -> KnowledgeBase:
    return KnowledgeBase(library_entries())


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


def named_in(text: str, k: int = 2) -> list[Entry]:
    """问题里点到名字的动作（"深蹲"能对上各种深蹲），按与问题的相关程度取前几个。"""
    hits = []
    for e in library_entries():
        base = e.title.split("（")[0]
        for p in _PREFIXES:
            base = base.removeprefix(p)
        if e.title in text or (len(base) >= 2 and base in text):
            hits.append(e)
    if len(hits) <= k:
        return hits
    ranked = KnowledgeBase(tuple(hits)).search(text, {"library"}, k=k)
    return ranked or hits[:k]
