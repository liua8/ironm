"""各专业角色的规程（spec [2026-10-23] §8）：按问题和这一轮的情况自动装载最相关的 1–2 份。

规程写在 skills.yaml：做事步骤、判断规则、输出要点、禁忌；规程里的数字带依据库编号，装载时把这些资料
一起交给角色（引用编号能通过核对）。规程只指导怎么作答，本身不作为出处。
讲法规程（如训练教练的"体感讲解"）只管怎么讲，对得上就和讲内容的规程一起装载，不占 1–2 份的名额。
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.roles import EXPERTS, Role
from ironm_agent.yamlfile import load_yaml

SKILLS_PATH = Path(__file__).with_name("skills.yaml")
MAX_SKILLS = 2
type Trigger = Literal["poor", "injury", "plan", "log", "image", "move"]
TRIGGER_BONUS = 2  # 这一轮的情况对得上时加的分（比问题里一个说法对得上更重要）


class Skill(ContractModel):
    id: str = Field(pattern=r"^[a-z]+(-[a-z]+)*$")
    role: Role | None = None
    shared: bool = False  # 三个专业 Agent 都能装载（如数据解读，spec [2026-10-23] §20）
    name: str = Field(min_length=1, max_length=12)
    when: tuple[str, ...] = ()
    on: tuple[Trigger, ...] = ()
    default: bool = False
    style: bool = False  # 讲法规程：管怎么讲、不管讲什么
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
    if any(x.style and x.default for x in data.skills):
        raise ValueError("讲法规程不能当默认规程")
    if any((x.role is None) != x.shared or (x.shared and x.default) for x in data.skills):
        raise ValueError("规程要么属于一个角色，要么是共享的（共享规程不能当默认规程）")
    return data.skills


type Similar = Callable[[str, Sequence[str]], list[float] | None]


def pick(
    role: Role, text: str, triggers: Collection[str] = (), similar: Similar | None = None
) -> list[Skill]:
    """这一轮给这个角色装载的规程：讲内容的取得分最高的 1–2 份；说法都对不上时，用本机向量模型选
    名称和说法最像的一份（similar，spec [2026-10-23] §20），还不行用这个角色的默认规程；
    讲法规程对得上就一起装载，不占名额。"""
    mine = [x for x in skills() if x.role == role or (x.shared and role in EXPERTS)]
    content = [x for x in mine if not x.style]
    scored = sorted(
        ((x.score(text, triggers), i, x) for i, x in enumerate(content)),
        key=lambda t: (-t[0], t[1]),
    )
    chosen = [x for s, _, x in scored if s > 0][:MAX_SKILLS]
    if not chosen and similar is not None and content:
        sims = similar(text, [f"{x.name}：{'、'.join(x.when)}" for x in content])
        if sims:
            chosen = [content[max(range(len(sims)), key=lambda i: sims[i])]]
    if not chosen:
        chosen = [x for x in content if x.default][:1]
    return chosen + [x for x in mine if x.style and x.score(text, triggers) > 0]


def prompt_of(chosen: Sequence[Skill]) -> str:
    if not chosen:
        return ""
    return (
        "\n\n本次装载的规程（照着做；规程里带〔K..〕编号的数字，引用时写这个编号；没有编号的是做事方法，不是出处）：\n"
        + "\n".join(x.text() for x in chosen)
    )
