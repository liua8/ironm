"""主教练直接回答：打招呼、闲聊、App 怎么用、超出范围。不给具体的训练量、热量、剂量数字。"""

from __future__ import annotations

from collections.abc import Sequence

from ironm_agent.llm import LLM, ModelUnavailable
from ironm_agent.numbers import written_numbers

OUT_OF_SCOPE = "这个问题超出了我能帮忙的范围。我可以回答训练安排、动作做法、饮食营养、恢复和睡眠，以及你记录的健康数据（体重、心率、睡眠、步数等）相关的问题。"
APP_HELP = (
    "我是你的健身教练团队：训练规划、动作教练、营养、恢复、数据分析几位专业角色，加上一位安全官。"
    "你可以问训练怎么安排、某个动作怎么做、怎么吃、怎么恢复，也可以问你自己的数据，比如最近的静息心率或体重变化，"
    "回答会注明依据，引用你的数据时可以点开看来源。"
)
GREETING = (
    "你好！我是你的健身教练。想问训练、动作、饮食、恢复，或者你最近的身体数据，都可以直接问我。"
)

_PROMPT = """你是健身 App 的主教练，语气专业又亲切。用户这句话是{kind}。
用一两句话自然地回应；可以介绍你能帮忙的方向：训练安排、动作做法、饮食营养、恢复和睡眠、用户自己的健康数据（体重、心率、睡眠、步数等）。
不要给出具体的训练量、热量、剂量等数字，不要做医学判断。用中文。"""


async def direct(intent: str, text: str, history: Sequence[str], llm: LLM) -> str:
    if intent == "out_of_scope":
        return OUT_OF_SCOPE
    kind = "在问 App 怎么用或你能做什么" if intent == "app" else "打招呼或闲聊"
    try:
        reply = await llm.chat(
            "compose",
            [
                {"role": "system", "content": _PROMPT.format(kind=kind)},
                *({"role": "user", "content": h} for h in history[-4:]),
                {"role": "user", "content": text},
            ],
        )
    except ModelUnavailable:
        return APP_HELP if intent == "app" else GREETING
    answer = reply.content.strip()
    own = set(written_numbers(text))
    if not answer or any(v not in own for v in written_numbers(answer)):
        return APP_HELP if intent == "app" else GREETING
    return answer
