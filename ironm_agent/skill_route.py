"""Skill 按意图装载（spec [2026-10-23] §75）：每轮和读数据同时调一次模型，从规程目录里选 0–3 份，
并给出领域、意图标签、覆盖程度。出错、超时或输出不对时返回 None，由调用方退回按关键词选。

只交给模型这句话和最近两句对话，不给档案和健康数据；运行记录只写选法、标签和覆盖程度，不写原话。
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.roles import Role
from ironm_agent.skills import Skill, by_id, skills

TIMEOUT_S = 4.0
MAX_PICK = 3
FITS = (
    "skill",
    "core",
    "outside",
    "chat",
)  # 有专门的规程 / 只有基础规程 / 不在健身范围 / 打招呼闲聊
_DOMAINS = {"train": Role.TRAINER, "food": Role.NUTRITION, "rest": Role.RECOVERY}

_PROMPT = """你给健身管家挑这一轮要用的规程（做事步骤）。只看用户这句话和前两句对话，判断他想做什么，从目录里选。

规程目录（编号 名字：什么时候用；不用于什么）：
{catalog}

规则：
- 选最贴近他意图的 0–3 份，宁少勿多；说法不一样但意思对得上也要选（"把屁股练翘"是增肌类，"深蹲怎么练"是动作教学）。
- domains：这句话涉及的领域，train 训练（计划、动作、有氧、坚持）、food 饮食（吃什么、热量、补剂）、rest 恢复（伤痛、生病、睡眠、疲劳、身体数据和化验）；可以多个。
- 属于健身、饮食、恢复，但目录里没有专门对得上的：skills 留空，domains 照写，fit 写 core。
- 和健身、饮食、恢复都无关（写文章、理财、编程）：skills、domains 都留空，fit 写 outside。
- 打招呼、道谢、闲聊：都留空，fit 写 chat。
- intent：这句话的意图，不超过 10 个字，不写人名、数字和具体病情（如"增肌训练""深蹲动作""孕期训练"）。
- sources：他在问上一条回答里的数、说法是哪来的（"这个数哪来的""依据是什么"）写 true，否则 false。

只输出 JSON：{{"skills": ["编号"], "domains": ["train|food|rest"], "intent": "…", "fit": "skill|core|outside|chat", "sources": false}}"""


@dataclass(frozen=True)
class Routed:
    skills: tuple[Skill, ...] = ()
    domains: tuple[Role, ...] = ()
    intent: str = ""
    fit: str = "skill"
    dropped: int = 0  # 选了但不在目录里（或是基础、讲法规程）的编号个数
    sources: bool = False  # 他在追问上一条回答的来源（§114：路由判断优先，出错才按关键词）


def catalog() -> str:
    """给路由看的目录：讲内容的规程（基础规程和讲法规程由系统自己带）。"""
    return "\n".join(
        f"- {x.id} {x.name}：{x.use}" + (f"；不用于：{x.not_for}" if x.not_for else "")
        for x in skills()
        if not x.style and not x.core
    )


def parse(raw: object) -> Routed | None:
    """模型的输出 → 路由结果；格式不对返回 None。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("skills"), list):
        return None
    fit = str(raw.get("fit") or "")
    if fit not in FITS:
        return None
    picked: list[Skill] = []
    dropped = 0
    for i in raw["skills"]:
        x = by_id(str(i)) if isinstance(i, str) else None
        if x is None or x.core or x.style or x in picked:
            dropped += 1
            continue
        picked.append(x)
    got = raw.get("domains")
    domains: list[object] = got if isinstance(got, list) else []
    roles = tuple(
        dict.fromkeys(_DOMAINS[d] for d in domains if isinstance(d, str) and d in _DOMAINS)
    )
    if fit in ("outside", "chat"):
        picked, roles = [], ()
    intent = " ".join(str(raw.get("intent") or "").split())[:10]
    return Routed(tuple(picked[:MAX_PICK]), roles, intent, fit, dropped,
                  sources=raw.get("sources") is True)  # fmt: skip


async def route(llm: LLM, text: str, recent: Sequence[str] = ()) -> Routed | None:
    """调一次模型选规程；出错、超时（4 秒）或输出不对返回 None。"""
    asked = "\n".join([*(f"前面：{x}" for x in recent[-2:]), f"这句话：{text}"])
    messages = [
        {"role": "system", "content": _PROMPT.format(catalog=catalog())},
        {"role": "user", "content": asked},
    ]
    try:
        reply = await asyncio.wait_for(llm.chat("route", messages, json_mode=True), TIMEOUT_S)
    except (TimeoutError, ModelUnavailable):
        return None
    return parse(parse_json(reply.content))
