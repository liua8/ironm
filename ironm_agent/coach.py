"""管家直接回答：打招呼、闲聊、App 怎么用、超出范围。不给具体的训练量、热量、剂量数字。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from ironm_agent.llm import LLM, ModelUnavailable, load_models
from ironm_agent.numbers import written_numbers

OUT_OF_SCOPE = "这个问题超出了我能帮忙的范围。我可以回答训练安排、动作做法、饮食营养、恢复和睡眠，以及你记录的健康数据（体重、心率、睡眠、步数等）相关的问题。"
APP_HELP = (
    "我是你的健身教练团队：训练教练、营养师、康复恢复师三位专业角色。"
    "你可以问训练怎么安排、某个动作怎么做、怎么吃、怎么恢复，也可以问你自己的数据，比如最近的静息心率或体重变化，"
    "回答会注明依据，引用你的数据时可以点开看来源。"
)
GREETING = (
    "你好！我是你的健身教练。想问训练、动作、饮食、恢复，或者你最近的身体数据，都可以直接问我。"
)
SORRY = "抱歉，是我没答到你问的。你想知道的是哪一点？直接说，我只回答这一点，不另外给你加安排。"
_COMPLAINT = re.compile(
    r"谁让你|擅自|答非所问|没听懂|听不懂|不对|没用|乱说|瞎说|乱安排|别乱|我问的是|我不是问"
)


def complaint(text: str) -> bool:
    """他在表达不满（spec [2026-10-23] §52）：模型答不出或核对没通过时，回道歉而不是打招呼。"""
    return bool(_COMPLAINT.search(text or ""))


ASK_PREVIEW = (
    "刚才那份计划预览你觉得哪里不行？天数、每次多久、动作、强度还是目标？说一下，我照着改。"
)
ASK_WHICH = "你是指刚才说的哪一点？具体说一下想改哪里或想知道什么，我接着说。"


def _fallback(intent: str, text: str, *, unsure: bool = False, preview: bool = False) -> str:
    if intent == "app":
        return APP_HELP
    if complaint(text):
        return SORRY
    if unsure:  # 路由没把握的承接语（§56）：问他指哪里，不回打招呼
        return ASK_PREVIEW if preview else ASK_WHICH
    return GREETING


_PROMPT = """你是"AI 健身管家"，语气专业又亲切。判断用户这句话属于哪种情况，再回应：
- 问你是谁、用的什么模型、怎么工作的：如实说你是 AI 健身管家：按问题把它交给训练教练、营养师、康复恢复师里最合适的专业角色回答，涉及几个方面时由你把他们的意见整合起来，回答由 {model} 大模型生成，能找到资料或用户自己数据的地方会标出处，其余是专业经验。
- 表达不满（答非所问、没听懂、不对、没用）：先简短道歉，再用一句话复述你理解的他上一个问题，问他具体想知道哪一点，或请他换个说法；不要评价自己能不能给数字。
- 打招呼、闲聊、问能做什么：一两句话自然回应，可以介绍能帮忙的方向：训练安排、动作做法、饮食营养、恢复和睡眠、用户自己的健康数据（体重、心率、睡眠、步数等）。
- 问你记得他什么、知道他哪些情况：照下面"以前说过的情况"如实回答，没有的就说还不知道。
不要主动提起前面聊过的话题（除非是在回应不满或被问到）；这类回应里不写训练量、热量、剂量等具体数字（他自己说过的除外），也不做医学判断。用中文。

这次对话前面的几轮（只作参考）：
{history}

{persona}"""


_FOLLOW_PROMPT = """你是"AI 健身管家"，语气专业又亲切。用户这句话很短（或者不好判断该交给哪位专业角色），要结合上下文接住它：
- 先看上一条回答和下面的"现在的情况"，弄清他这句话是在回应什么；
- 能直接接上的就直接接：比如上一轮给了计划预览，他说"不太行"，先用一句话复述那份预览的要点（几练、每次多久、练什么），再问他哪里不行（天数、每次多久、动作、强度还是目标）；他问"为什么""什么意思"，就用上一条回答里已有的内容解释那一点；
- 需要专业判断的（重排计划、换动作、饮食怎么调），只问清楚他想改哪里，不自己给方案，等他说具体了再由专业角色来；
- 第一句就接他这句话，不要打招呼、不要自我介绍，不要扯回今天打卡、天气等他没问的事；
- 不给新的训练量、重量、热量、克数、时长这类数字（上一条回答、预览和他自己说过的数字可以照说），不做医学判断；用中文，简短，两三句话。

这次对话前面的几轮：
{history}

现在的情况：
{context}

{persona}"""


_APP_PROMPT = """你是"AI 健身管家"。用户在问这个 App 怎么用。照下面的使用说明回答：
- 直接说在哪个页面、点哪里、怎么做，一两步说清楚；他问的事说明里有好几处相关，只挑最相关的说；
- 说明里没有的功能，如实说目前还没有，可以说可以换个什么方式做到；不要编造按钮或功能；
- 不给训练量、热量、剂量这类建议数字（说明里写到的数字可以照说）；用中文，简短。

使用说明：
{guide}

这次对话前面的几轮（只作参考）：
{history}"""

GUIDE_PATH = Path(__file__).with_name("app_guide.md")


@cache
def app_guide() -> str:
    """App 使用说明（spec [2026-10-23] §36）：问 App 怎么用时照着答。"""
    return GUIDE_PATH.read_text(encoding="utf-8")


def model_name() -> str:
    return load_models().stages["compose"].model


async def direct(
    intent: str,
    text: str,
    history: Sequence[str],
    llm: LLM,
    persona: str = "",
    *,
    unsure: bool = False,
    context: Sequence[str] = (),
    preview: bool = False,
) -> str:
    """管家直接回答：闲聊、问 App 用法、超出范围；路由没把握时（unsure）结合上下文接住（spec [2026-10-23] §56）。"""
    if intent == "out_of_scope":
        return OUT_OF_SCOPE
    recent = "\n".join(history[-4:]) or "（无）"
    persona = persona or "这个人以前说过的情况：（还没有记录）"
    if unsure:
        system = _FOLLOW_PROMPT.format(
            history=recent, context="\n".join(context) or "（没有）", persona=persona
        )
    elif intent == "app":
        system = _APP_PROMPT.format(guide=app_guide(), history=recent)
    else:
        system = _PROMPT.format(model=model_name(), history=recent, persona=persona)
    try:
        reply = await llm.chat(
            "compose", [{"role": "system", "content": system}, {"role": "user", "content": text}]
        )
    except ModelUnavailable:
        return _fallback(intent, text, unsure=unsure, preview=preview)
    answer = reply.content.strip()
    own = set(written_numbers(text)) | set(written_numbers(persona))  # 他自己说过的数字
    if intent == "app":
        own |= set(written_numbers(app_guide()))  # 使用说明里写到的数字可以照说
    if unsure:  # 上一条回答、预览和档案里的数字可以照说（§56）
        own |= set(written_numbers(recent)) | set(written_numbers("\n".join(context)))
    if not answer or any(v not in own for v in written_numbers(answer)):
        return _fallback(intent, text, unsure=unsure, preview=preview)
    return answer
