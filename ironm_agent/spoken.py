"""该说的话交给模型说，代码只查必须说到的几点（spec [2026-10-23] §86）。

急症、危急指标、拒答、替别人问、生病追问按钮：判定仍由代码做，"怎么说"交给模型；
必须说到的没说到、给了训练安排，或模型调用失败、超时，调用方退回原来的固定回答。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Sequence
from typing import Any

from ironm_agent.checks import plain
from ironm_agent.llm import LLM, TurnLLM, load_models

_log = logging.getLogger("ironm_agent.run")
TIMEOUT_S = 15.0  # 急症要尽快给出：等不到就用固定回答

# 必须说到的点：名字 → 怎么认（没列在这里的按原词找）
NEEDS: dict[str, re.Pattern[str]] = {
    "stop": re.compile(
        r"停止|停下|停掉|先别|别再|不要再|不要继续|暂停|先停|别练|不要练|别运动|不要运动"
    ),
    "call": re.compile(r"120"),
    "doctor": re.compile(r"就医|医院|医生|就诊|急诊|看病"),
    "pharmacist": re.compile(r"医生|药师"),
    "hotline": re.compile(r"12356"),
    "police": re.compile(r"120|110"),
}
# 训练安排：组数、次数、每组几次（急症和危急指标这一轮都不能给）
TRAINING = re.compile(r"\d+\s*组|\d+\s*[x×]\s*\d+|每组\s*\d+|\d+\s*次\s*[x×]")
NO_TRAINING = "no_training"

_SYSTEM = (
    "你是健身管家 IronM，在和用户本人说话。直接写给他看的话：用自然、简短的中文，第一句就是最要紧的事；"
    "不加标题、不编号、不用 markdown，不带资料编号。"
)
URGENT = (
    "他刚说的情况可能需要马上处理。照下面的要点告诉他现在该做什么：停止什么、要不要马上打 120、去哪里看、"
    "可以告诉医生什么。要点里的电话号码照写。不判断病因、不诊断、不给药物和剂量、不安排任何训练。三到六句话。"
)
HELP = (
    "这句话是替别人问的。IronM 只回答本人的问题，不看、不改别人的数据和记忆。用一两句话说明，"
    "可以建议请对方用自己的账号来问；不回答涉及对方身体情况的具体内容。"
)
ILLNESS = (
    "他刚在首页回答了生病追问（好了、好一些、还不舒服）。用一两句话回应他，把今天怎么安排说清楚："
    "照下面系统定好的来，不另作安排；要看医生的照说。"
)


def missing(text: str, needs: Sequence[str]) -> list[str]:
    """回答里没说到的点；给了训练安排时记为 no_training。"""
    out = []
    for n in needs:
        if n == NO_TRAINING:
            if TRAINING.search(text):
                out.append(n)
        elif not (NEEDS[n].search(text) if n in NEEDS else n in text):
            out.append(n)
    return out


def urgent_needs(level: str, categories: Sequence[str]) -> tuple[str, ...]:
    """急症、红旗必须说到的：心理危机说热线和 120/110；其余说停下，急症说 120、红旗说就医。都不能给训练安排。"""
    if "mental_health" in categories:
        return ("hotline", "police", NO_TRAINING)
    return ("stop", "call" if level == "emergency" else "doctor", NO_TRAINING)


RISK_NEEDS = ("stop", "doctor", NO_TRAINING)  # 危急指标：先别运动、尽快就医、不给训练安排
REFUSAL_NEEDS = {
    "diagnosis": ("doctor",),
    "prescription": ("pharmacist",),
    "treatment": ("doctor",),
    "emergency_service": ("call",),
}


async def say(
    llm: LLM,
    task: str,
    material: str,
    question: str,
    needs: Sequence[str] = (),
    *,
    timeout: float = TIMEOUT_S,
) -> str | None:
    """让模型按任务和要点说一段话；说空了、没说到必须的点、调用失败或超时，返回 None（调用方用固定回答）。"""
    user = "\n\n".join(
        x for x in (f"他说：{question}" if question else "",
                    f"要点（意思要传达到）：\n{material}" if material else "") if x
    )  # fmt: skip
    messages = [
        {"role": "system", "content": f"{_SYSTEM}\n\n{task}"},
        {"role": "user", "content": user or "（没有更多内容）"},
    ]
    try:
        reply = await asyncio.wait_for(llm.chat("expert", messages), timeout)
    except Exception as e:
        _log.warning("spoken failed: error_type=%s", type(e).__name__)
        return None
    text = plain(str(reply.content or "")).strip()
    if not text:
        return None
    lack = missing(text, needs)
    if lack:
        _log.info("spoken fell back: missing=%s", ",".join(lack))
        return None
    return text


def default_llm() -> Any:
    """网页接口用的模型（测试里换掉）。"""
    return TurnLLM(load_models(), os.environ)
