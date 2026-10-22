"""动作库：从 exercises.yaml 读入并校验（部位、器械只能从固定的几类里选，编号不能重复）。"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.yamlfile import load_yaml

EXERCISES_PATH = Path(__file__).with_name("exercises.yaml")

type Part = Literal["腿臀", "胸", "背", "肩", "手臂", "核心", "全身", "有氧"]
type Equipment = Literal["自重", "哑铃", "壶铃", "弹力带", "杠铃", "单杠", "器械"]
PARTS: tuple[Part, ...] = ("腿臀", "胸", "背", "肩", "手臂", "核心", "全身", "有氧")
EQUIPMENT: tuple[Equipment, ...] = ("自重", "哑铃", "壶铃", "弹力带", "杠铃", "单杠", "器械")
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
