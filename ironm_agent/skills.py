"""各专业角色的规程（spec [2026-10-23] §8）：按问题和这一轮的情况自动装载最相关的 1–2 份。

规程写在 skills.yaml：做事步骤、判断规则、输出要点、禁忌；规程里的数字带依据库编号，装载时把这些资料
一起交给角色（引用编号能通过核对）。规程只指导怎么作答，本身不作为出处。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.roles import Role
from ironm_agent.yamlfile import load_yaml

SKILLS_PATH = Path(__file__).with_name("skills.yaml")
MAX_SKILLS = 2
type Trigger = Literal["poor", "injury", "plan", "log", "image"]
TRIGGER_BONUS = 2  # 这一轮的情况对得上时加的分（比问题里一个说法对得上更重要）


class Skill(ContractModel):
    id: str = Field(pattern=r"^[a-z]+(-[a-z]+)*$")
    role: Role
    name: str = Field(min_length=1, max_length=12)
    when: tuple[str, ...] = ()
    on: tuple[Trigger, ...] = ()
    default: bool = False
    steps: tuple[str, ...] = Field(min_length=1)
    rules: tuple[str, ...] = ()
    output: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()

    def score(self, text: str, triggers: Collection[str]) -> int:
        return sum(1 for w in self.when if w in text) + TRIGGER_BONUS * sum(
            1 for t in self.on if t in triggers
        )

    def text(self) -> str:
        parts = [f"【{self.name}】"]
        for label, lines in (("做法", self.steps), ("判断", self.rules), ("输出", self.output),
                             ("禁忌", self.avoid)):  # fmt: skip
            parts += [f"- {label}：{x}" for x in lines]
        return "\n".join(parts)


class SkillFile(ContractModel):
    version: str
    review: str
    skills: tuple[Skill, ...] = Field(min_length=1)


@cache
def skills(path: Path = SKILLS_PATH) -> tuple[Skill, ...]:
    data = SkillFile.model_validate(load_yaml(path), strict=False)
    ids = [x.id for x in data.skills]
    if len(ids) != len(set(ids)):
        raise ValueError("规程编号重复")
    return data.skills


def pick(role: Role, text: str, triggers: Collection[str] = ()) -> list[Skill]:
    """这一轮给这个角色装载的规程：得分最高的 1–2 份；都对不上时用这个角色的默认规程。"""
    mine = [x for x in skills() if x.role == role]
    scored = sorted(
        ((x.score(text, triggers), i, x) for i, x in enumerate(mine)), key=lambda t: (-t[0], t[1])
    )
    chosen = [x for s, _, x in scored if s > 0][:MAX_SKILLS]
    if not chosen:
        chosen = [x for x in mine if x.default][:1]
    return chosen


def prompt_of(chosen: Sequence[Skill]) -> str:
    if not chosen:
        return ""
    return (
        "\n\n本次装载的规程（照着做；规程里带〔K..〕编号的数字，引用时写这个编号；没有编号的是做事方法，不是出处）：\n"
        + "\n".join(x.text() for x in chosen)
    )
