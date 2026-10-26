"""回答的分段与长度（spec [2026-10-23] §38）：模型按几段写，代码拼成正文、按问题类型限长。

几段是：答案（第一句直接回答）、理由（一句）、做法（0–3 条）、提醒（只在问到疼痛、受伤、疾病时）、
下一步（今天就能做的一件事）。超长时先删排在后面的做法；答案、理由和提醒不删，不为截短多调一次模型。
模型没按分段写（回的是一段文字）时，照旧用它的文字。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from ironm_agent.checks import plain

type Kind = Literal["fact", "howto", "card", "detail"]
LIMITS: dict[Kind, int] = {"fact": 120, "howto": 220, "card": 90, "detail": 500}
MAX_STEPS: dict[Kind, int] = {"fact": 2, "howto": 3, "card": 1, "detail": 5}
KEYS = ("answer", "reason", "steps", "alert", "next")
_RISKY = re.compile(
    r"疼|痛|伤|肿|麻|晕|胸闷|不舒服|生病|感冒|发烧|血压|孕"
)  # 问到这些才留停止提醒（§42）

_DETAIL = re.compile(r"详细|展开说|具体说说|多说点|说细一点|讲详细")
_HOWTO = re.compile(
    r"怎么(?!样)|如何|安排|计划|推荐|练什么|吃什么|能不能|可以.{0,6}吗|要不要|该不该"
)
_FACT = re.compile(
    r"多少|几(次|天|组|个|公斤|小时)?|是不是|正常吗|高吗|高嘛|低吗|怎么样|算不算|BMI|bmi"
)

SLOTS_PROMPT = """按下面几段写，最后只输出 JSON：
{"answer": "第一句直接回答用户问的那件事（问什么答什么），不超过 40 字",
 "reason": "一句话说为什么，最好用这个人自己的数据；不需要就留空",
 "steps": ["0–%(steps)d 条，只写和问题直接有关、能照做的，每条带具体的量，每条不超过 50 字"],
 "alert": "只在问题本身涉及疼痛、受伤、疾病时写一句什么情况要停下或就医；其余留空",
 "next": "今天就能做的一件事，一句话，不和答案、做法重复；纯知识问题留空"}
每一段里带数字的句子照样在句末写出处标记，答案也不例外，例如 "你的 BMI 是 24.5〔C3〕，属于超重"。
推荐几个动作或几种吃法时最多 %(steps)d 个，每个占一条做法、写怎么做和具体的量；答案里说几个，做法就列几条。
写法：先答案、后理由，不铺垫；问"正常吗、高吗、是不是"时，答案以判断开头（正常 / 偏高 / 偏低 / 没有记录），再给数；没问到的不说（问 BMI 不讲饮食，问早餐不讲训练），用户追问再展开；不预防性地加"如果……就医"；数据风险提醒由系统放在最后，你不用写；全文不超过 %(limit)d 字。"""


_TOPICS = ("血压", "血糖", "孕", "心率", "体温")


def drop_said(notes: str, answer: str) -> str:
    """数据风险提醒放在回答最后；回答里已经讲到同一件事并让他看医生的，不再重复这条提醒。"""
    told = ("医生" in answer) or ("就医" in answer)
    kept = [
        n
        for n in notes.split("\n\n")
        if n.strip() and not (told and any(t in n and t in answer for t in _TOPICS))
    ]
    return "\n\n".join(kept)


def kind_of(text: str, task: str | None = None) -> Kind:
    """这一问按哪种长度回答：要写计划或记录的有卡片；说"详细"的放宽；问数值或判断的最短。"""
    if task in ("plan", "log"):
        return "card"
    if _DETAIL.search(text):
        return "detail"
    if _FACT.search(text) and not _HOWTO.search(text):
        return "fact"
    return "howto"


def limit_of(text: str, task: str | None = None) -> int:
    return LIMITS[kind_of(text, task)]


def slots_prompt(text: str, task: str | None = None) -> str:
    k = kind_of(text, task)
    return SLOTS_PROMPT % {"steps": MAX_STEPS[k], "limit": LIMITS[k]}


def is_slots(raw: Mapping[str, Any]) -> bool:
    """模型回的是不是分段的写法（有答案，且至少还有一段）。"""
    return isinstance(raw.get("answer"), str) and any(k in raw for k in KEYS[1:])


def _size(text: str) -> int:
    return len("".join(plain(text).split()))


def _same(a: str, b: str) -> bool:
    """两句是不是在说同一件事：较短那句的相邻两字有六成以上出现在另一句里。"""
    pa = re.sub(r"[\W_]+", "", plain(a))
    pb = re.sub(r"[\W_]+", "", plain(b))
    short, long_ = sorted((pa, pb), key=len)
    pairs = [short[i : i + 2] for i in range(len(short) - 1)]
    return bool(pairs) and sum(p in long_ for p in pairs) / len(pairs) >= 0.6


def _end(text: str) -> str:
    """句子没有句末标点时补一个句号（看去掉出处标记后的样子，标记照留）。"""
    return text if not text or re.search(r"[。！？!?…]\s*$", plain(text)) else text + "。"


def assemble(raw: Mapping[str, Any], text: str = "", task: str | None = None) -> str:
    """把分段拼成正文：答案和理由一段，做法编号，下一步和提醒各一行；按问题类型截长。"""
    k = kind_of(text, task)
    answer = str(raw.get("answer") or "").strip()
    reason = str(raw.get("reason") or "").strip()
    steps_raw = raw.get("steps") or []
    if isinstance(steps_raw, str):
        steps_raw = [steps_raw]
    steps = [str(x).strip() for x in steps_raw if str(x).strip()][: MAX_STEPS[k]]
    alert = str(raw.get("alert") or "").strip()
    if alert and text and not _RISKY.search(text):
        alert = ""  # 没问到疼痛、伤病、身体不适，就不加"疼就停""就医"（§42）
    nxt = str(raw.get("next") or "").strip()
    if reason and _same(reason, answer):
        reason = ""
    if nxt and any(_same(nxt, x) for x in (answer, *steps)):
        nxt = ""  # 下一步和答案或某条做法说的是一件事，不重复

    answer, reason, nxt, alert = (_end(x) for x in (answer, reason, nxt, alert))

    def build() -> str:
        head = "".join(x for x in (answer, reason) if x)
        body = [f"{i}. {s}" for i, s in enumerate(steps, 1)] if len(steps) > 1 else steps
        return "\n".join(x for x in (head, *body, nxt, alert) if x)

    out = build()
    limit = LIMITS[k]
    if _size(out) > limit and nxt:  # 先删下一步，免得答案说了几个、做法却少列（§42）
        nxt = ""
        out = build()
    if _size(out) > limit and reason:  # 理由只留第一句
        reason = _end(re.split(r"(?<=[。！？!?])", reason, maxsplit=1)[0])
        out = build()
    while _size(out) > limit and steps:  # 再删排在后面的做法
        steps.pop()
        out = build()
    return out
