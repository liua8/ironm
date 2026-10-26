"""管家直接回答：打招呼、闲聊、App 怎么用、超出范围。不给具体的训练量、热量、剂量数字。"""

from __future__ import annotations

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

_PROMPT = """你是"AI 健身管家"，语气专业又亲切。判断用户这句话属于哪种情况，再回应：
- 问你是谁、用的什么模型、怎么工作的：如实说你是 AI 健身管家：按问题把它交给训练教练、营养师、康复恢复师里最合适的专业角色回答，涉及几个方面时由你把他们的意见整合起来，回答由 {model} 大模型生成，能找到资料或用户自己数据的地方会标出处，其余是专业经验。
- 表达不满（答非所问、没听懂、不对、没用）：先简短道歉，再用一句话复述你理解的他上一个问题，问他具体想知道哪一点，或请他换个说法；不要评价自己能不能给数字。
- 打招呼、闲聊、问能做什么：一两句话自然回应，可以介绍能帮忙的方向：训练安排、动作做法、饮食营养、恢复和睡眠、用户自己的健康数据（体重、心率、睡眠、步数等）。
- 问你记得他什么、知道他哪些情况：照下面"以前说过的情况"如实回答，没有的就说还不知道。
不要主动提起前面聊过的话题（除非是在回应不满或被问到）；这类回应里不写训练量、热量、剂量等具体数字（他自己说过的除外），也不做医学判断。用中文。

这次对话前面的几轮（只作参考）：
{history}

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
    intent: str, text: str, history: Sequence[str], llm: LLM, persona: str = ""
) -> str:
    if intent == "out_of_scope":
        return OUT_OF_SCOPE
    recent = "\n".join(history[-4:]) or "（无）"
    if intent == "app":
        system = _APP_PROMPT.format(guide=app_guide(), history=recent)
    else:
        system = _PROMPT.format(model=model_name(), history=recent,
                                persona=persona or "这个人以前说过的情况：（还没有记录）")  # fmt: skip
    try:
        reply = await llm.chat(
            "compose", [{"role": "system", "content": system}, {"role": "user", "content": text}]
        )
    except ModelUnavailable:
        return APP_HELP if intent == "app" else GREETING
    answer = reply.content.strip()
    own = set(written_numbers(text)) | set(written_numbers(persona))  # 他自己说过的数字
    if intent == "app":
        own |= set(written_numbers(app_guide()))  # 使用说明里写到的数字可以照说
    if not answer or any(v not in own for v in written_numbers(answer)):
        return APP_HELP if intent == "app" else GREETING
    return answer
