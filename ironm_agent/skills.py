"""各专业角色的规程（spec [2026-10-23] §8）：按问题和这一轮的情况自动装载最相关的 1–2 份。

规程写在 skills.yaml：做事步骤、判断规则、输出要点、禁忌；规程里的数字带依据库编号，装载时把这些资料
一起交给角色（引用编号能通过核对）。规程只指导怎么作答，本身不作为出处。
讲法规程（style）只管怎么讲，对得上就和讲内容的规程一起装载，不占名额（§88 起没有讲法规程了）。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.roles import Role
from ironm_agent.yamlfile import load_yaml

SKILLS_PATH = Path(__file__).with_name("skills.yaml")
SKILLS_DIR = Path(__file__).with_name("skills")  # 一份一个文件夹的新规程（spec [2026-10-23] §76）
type Trigger = Literal["poor", "injury", "plan", "log", "image", "move", "lab", "metric", "new"]
TRIGGER_BONUS = 2  # 这一轮的情况对得上时加的分（比问题里一个说法对得上更重要）


class Example(ContractModel):
    q: str = Field(min_length=1)
    a: str = Field(min_length=1)


_REF = re.compile(r"〔(K\d{2,4})〕")


class Skill(ContractModel):
    id: str = Field(pattern=r"^[a-z]+(-[a-z]+)*$")
    role: Role | None = None
    shared: bool = False  # 三个专业 Agent 都能装载（如数据解读，spec [2026-10-23] §20）
    name: str = Field(min_length=1, max_length=12)
    use: str = Field(min_length=4, max_length=60)  # 什么时候用（spec [2026-10-23] §22）
    not_for: str = Field(default="", max_length=90)  # 什么时候不用、该用哪个
    when: tuple[str, ...] = ()
    on: tuple[Trigger, ...] = ()
    default: bool = False
    style: bool = False  # 讲法规程：管怎么讲、不管讲什么
    steps: tuple[str, ...] = ()  # 做事步骤（基础规程没有，其余必须有）
    rules: tuple[str, ...] = ()
    output: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    refs: tuple[str, ...] = ()
    # 基础规程（spec [2026-10-23] §74）：一个领域的思考顺序、判断规则、示例、工具，原来三个角色提示词里的内容；
    # special 是少见情况的规则（有伤、孕期、血压……），只在这个人有这类情况时带上
    core: bool = False
    order: str = ""
    examples: tuple[Example, ...] = ()
    tools: str = ""
    special: tuple[tuple[str, str], ...] = ()  # (情况, 规则)，按 YAML 里的顺序
    # 文件夹规程（§76）：SKILL.md 的正文（完整流程）和它用到的工具、MCP
    body: str = ""
    toolset: tuple[str, ...] = ()

    def extras(self, flags: Collection[str] = ()) -> list[str]:
        """这个人有的少见情况对应的规则（按 special 里的顺序）。"""
        return [v for k, v in self.special if k in flags]

    def refs_for(self, flags: Collection[str] = ()) -> tuple[str, ...]:
        """装上这份规程时可以引用的依据：写明的 refs，加上基础规程正文里出现的编号。"""
        found = _REF.findall(self.text(flags)) if self.core or self.body else []
        return tuple(dict.fromkeys([*self.refs, *found]))

    def score(self, text: str, triggers: Collection[str]) -> int:
        return sum(1 for w in self.when if w in text) + TRIGGER_BONUS * sum(
            1 for t in self.on if t in triggers
        )

    def text(self, flags: Collection[str] = ()) -> str:
        if self.body:
            uses = f"\n（这份规程用到的工具：{'、'.join(self.toolset)}）" if self.toolset else ""
            return f"【{self.name}】\n{self.body.strip()}{uses}"
        parts = [f"【{self.name}】"]
        if self.core:
            parts.append(f"- 思考顺序：{self.order}")
            parts += [f"- 判断：{x}" for x in self.rules]
            parts += [f"- 示例：问：{e.q} 答：{e.a}" for e in self.examples]
            parts.append(f"- 工具：{self.tools}")
            parts += [f"- 这个人的特殊情况：{x}" for x in self.extras(flags)]
            return "\n".join(parts)
        for label, lines in (("做法", self.steps), ("判断", self.rules), ("输出", self.output),
                             ("禁忌", self.avoid)):  # fmt: skip
            parts += [f"- {label}：{x}" for x in lines]
        return "\n".join(parts)


class SkillFile(ContractModel):
    version: str
    review: str
    skills: tuple[Skill, ...] = Field(min_length=1)


def folder_skills(root: Path = SKILLS_DIR) -> list[dict[str, object]]:
    """skills/编号/SKILL.md：开头 --- 之间是字段（YAML），后面是正文；tools 写的是用到的工具。"""
    from ironm_agent.yamlfile import load_yaml_text  # 和 skills.yaml 同一个读法（on 不会读成 true）

    out: list[dict[str, object]] = []
    for md in sorted(root.glob("*/SKILL.md")) if root.is_dir() else []:
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(f"{md.parent.name}/SKILL.md 开头要有 --- 字段 ---")
        head, _, body = text[4:].partition("\n---\n")
        meta = load_yaml_text(head) or {}
        if not isinstance(meta, dict) or meta.get("id") != md.parent.name:
            raise ValueError(f"{md.parent.name}/SKILL.md 的 id 要和文件夹名一样")
        if "tools" in meta:
            meta["toolset"] = meta.pop("tools")
        meta["body"] = body.strip()
        out.append(meta)
    return out


@cache
def skills(path: Path = SKILLS_PATH, root: Path = SKILLS_DIR) -> tuple[Skill, ...]:
    raw = load_yaml(path)
    if isinstance(raw, dict) and isinstance(raw.get("skills"), list):
        raw["skills"] = [*raw["skills"], *folder_skills(root)]
    rows = raw.get("skills") if isinstance(raw, dict) else None
    for x in rows if isinstance(rows, list) else []:
        if not isinstance(x, dict):
            continue
        if "domain" in x:  # YAML 里叫 domain（训练 / 饮食 / 恢复，§74），代码里沿用 role
            x["role"] = x.pop("domain")
        if isinstance(x.get("special"), dict):  # 规程要能当集合的元素：special 存成有序的二元组
            x["special"] = [[k, v] for k, v in x["special"].items()]
    data = SkillFile.model_validate(raw, strict=False)
    ids = [x.id for x in data.skills]
    if len(ids) != len(set(ids)):
        raise ValueError("规程编号重复")
    if any(x.style and x.default for x in data.skills):
        raise ValueError("讲法规程不能当默认规程")
    if any((x.role is None) != x.shared or (x.shared and x.default) for x in data.skills):
        raise ValueError("规程要么属于一个角色，要么是共享的（共享规程不能当默认规程）")
    if any(not x.core and not x.steps and not x.body for x in data.skills):
        raise ValueError("规程要有做事步骤或正文（基础规程除外）")
    if any(x.core and (x.role is None or not x.order or not x.rules) for x in data.skills):
        raise ValueError("基础规程要属于一个领域，并写明思考顺序和判断规则")
    names = {x.name for x in data.skills}
    for x in data.skills:
        unknown = [n for n in re.findall(r"「([^」]+)」", x.not_for) if n not in names]
        if unknown:
            raise ValueError(f"{x.id} 的 not_for 点到的规程不存在：{unknown}")
    return data.skills






def prompt_of(chosen: Sequence[Skill], flags: Collection[str] = ()) -> str:
    if not chosen:
        return ""
    return (
        "\n\n本次装载的规程（照着做；规程里带〔K..〕编号的数字，引用时写这个编号；没有编号的是做事方法，不是出处）：\n"
        + "\n".join(x.text(flags) for x in chosen)
    )


def core_of(role: Role) -> Skill | None:
    """这个领域的基础规程（§74）。"""
    return next((x for x in skills() if x.core and x.role == role), None)


def with_cores(chosen: Sequence[Skill], domains: Collection[Role] = ()) -> list[Skill]:
    """装了某个领域的规程（或路由说涉及这个领域，§75），就带上这个领域的基础规程（§74 需求 2），
    基础规程排在前面，按训练、恢复、饮食。"""
    have = {x.role for x in chosen if x.role is not None} | set(domains)
    cores = [c for r in (Role.TRAINER, Role.RECOVERY, Role.NUTRITION) if r in have
             and (c := core_of(r)) is not None and c not in chosen]  # fmt: skip
    return [*cores, *chosen]


# ---- 路由选 Skill（spec [2026-10-23] §21）------------------------------------------------------

RULE_TRIGGERS: frozenset[str] = frozenset(
    {"poor", "plan", "log", "image", "injury", "lab", "metric", "new"}
)  # 路由看不到的系统情况；lab / metric：问题点到了化验指标 / 每天测的指标（spec [2026-10-23] §37）




# ---- 单 Agent（spec [2026-10-23] §67 需求 2）：不按角色分，按这句话和情况跨领域选 ---------------------

MAX_ANY = 3


def by_id(skill_id: str) -> Skill | None:
    return next((x for x in skills() if x.id == skill_id), None)


def pick_any(
    text: str,
    triggers: Collection[str] = (),
    drop: Collection[str] = (),
    k: int = MAX_ANY,
) -> list[Skill]:
    """路由出错时退回的选法：所有领域里得分最高的 1–k 份（这一轮情况要求的排前面）；都对不上时不硬装，
    由它看目录自己装（§67）。drop：这一轮不装的情况。"""
    content = [x for x in skills() if not x.style and not x.core and not set(x.on) & set(drop)]
    required = [x for x in content if any(t in RULE_TRIGGERS and t in triggers for t in x.on)]
    scored = sorted(
        ((x.score(text, triggers), i, x) for i, x in enumerate(content)),
        key=lambda t: (-t[0], t[1]),
    )
    chosen = list(dict.fromkeys([*required, *(x for s, _, x in scored if s > 0)]))[:k]
    style = [x for x in skills() if x.style and x.score(text, triggers) > 0]
    return with_cores(chosen) + style


def catalog_any() -> str:
    """单 Agent 看的全部规程目录：编号、名字、什么时候用（讲法类不列）。"""
    return "\n".join(f"- {x.id} {x.name}：{x.use}" for x in skills() if not x.style)


def pick_routed(
    routed: Sequence[Skill],
    domains: Collection[Role],
    text: str,
    triggers: Collection[str] = (),
    drop: Collection[str] = (),
    k: int = MAX_ANY,
) -> list[Skill]:
    """按意图路由选的（§75）：先放这一轮情况要求的，再放路由选的，最多 k 份；带上涉及领域的基础规程；
    讲法规程对得上就一起装。drop：这一轮不装的情况。"""
    content = [x for x in skills() if not x.style and not x.core and not set(x.on) & set(drop)]
    required = [x for x in content if any(t in RULE_TRIGGERS and t in triggers for t in x.on)]
    allowed = set(content)
    chosen = list(dict.fromkeys([*required, *(x for x in routed if x in allowed)]))[:k]
    style = [x for x in skills() if x.style and x.score(text, triggers) > 0]
    return with_cores(chosen, domains) + style
