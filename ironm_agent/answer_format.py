"""回答的分段与长度（spec [2026-10-23] §38）：模型按几段写，代码拼成正文、按问题类型限长。

几段是：答案（第一句直接回答）、理由（一句）、做法（0–3 条）、提醒（只在问到疼痛、受伤、疾病时）、
下一步（一般不写）。超长时先删排在后面的做法；答案、理由和提醒不删，不为截短多调一次模型。
§82：做法 3 条以上才编号，1–2 条接在答案后面写成句子；答案里已经让他就医、别运动的不再加提醒；
提醒和下一步不同时出现——不套"结论 + 清单 + 叮嘱 + 就医"的固定模板。
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
NUMBERED = 3  # 做法这么多条以上才编号（§82）
_RISKY = re.compile(
    r"疼|痛|伤|肿|麻|晕|胸闷|不舒服|生病|感冒|发烧|血压|孕"
)  # 问到这些才留停止提醒（§42）
# 问的是身体状态（§82 修改）：做法最多 2 条、不编号，写成句子
_BODY_STATE = re.compile(
    r"不舒服|难受|累|没睡好|熬夜|生病|感冒|发烧|嗓子|咳|拉肚子|头疼|头晕|疼|痛|酸|能不能练|还能练|能练吗|还练吗"
)
BODY_STEPS = 2
# 他在问或提要求（§82）：只说自己的状况、没问怎么办时，问身体状态的回答不给做法和下一步
_ASKING = re.compile(
    r"[？?吗嘛呢]|怎么|如何|什么|啥|哪|能不能|可不可以|要不要|该不该|还练|安排|推荐|给我|帮我|建议|练点|动一动|锻炼"
)
_TOLD = re.compile(
    r"就医|看医生|去医院|别练|不要运动|不宜运动|先休息|别运动|停下"
)  # 答案里已经说了（§82）

_DETAIL = re.compile(r"详细|展开说|具体说说|多说点|说细一点|讲详细")
_HOWTO = re.compile(
    r"怎么(?!样)|如何|安排|计划|推荐|练什么|吃什么|能不能|可以.{0,6}吗|要不要|该不该"
)
_FACT = re.compile(
    r"多少|几(次|天|组|个|公斤|小时)?|是不是|正常吗|高吗|高嘛|低吗|怎么样|算不算|算.{0,4}吗|BMI|bmi"
)

SLOTS_PROMPT = """按下面几段写，最后只输出 JSON：
{"answer": "第一句直接回答用户问的那件事（问什么答什么），不超过 40 字",
 "reason": "一句话说为什么，最好用这个人自己的数据；不需要就留空",
 "steps": ["0–%(steps)d 条，只写和问题直接有关、能照做的，每条带具体的量，每条不超过 50 字；两三句话能说清的就写进答案，这里留空"],
 "alert": "只在他说的情况本身有风险时写一句什么情况要停下或就医；答案里已经说了就留空；其余留空",
 "next": "一般留空；只在他问怎么做、今天还有一件该做的事前面没写到时写一句"}
每一段里带数字的句子照样在句末写出处标记，答案也不例外，例如 "你的 BMI 是 24.5〔C3〕，属于超重"。
推荐几个动作或几种吃法时最多 %(steps)d 个，每个占一条做法、写怎么做和具体的量；答案里说几个，做法就列几条。
写法：像教练当面说话，先答案、后理由，不铺垫；他提了要求（比如要一个轻松的安排）先接住，能做就给，不能做再说为什么；问"正常吗、高吗、是不是"时，答案以判断开头（正常 / 偏高 / 偏低 / 没有记录），再给数；没问到的不说（问 BMI 不讲饮食，问早餐不讲训练），用户追问再展开；不预防性地加"如果……就医"；数据风险提醒由系统放在最后，你不用写；全文不超过 %(limit)d 字。"""


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
    if task in ("plan", "edit", "log"):
        return "card"
    if _DETAIL.search(text):
        return "detail"
    if _FACT.search(text) and not _HOWTO.search(text):
        return "fact"
    return "howto"


def slots_prompt(text: str, task: str | None = None) -> str:
    k = kind_of(text, task)
    if k != "detail" and _BODY_STATE.search(text) and not _ASKING.search(text):  # 只说了状况（§82）
        return SLOTS_PROMPT % {"steps": 0, "limit": LIMITS[k]} + (
            "\n他只说了自己的状况、没问怎么办：answer 写一句关心、问他怎么了（哪里不舒服），"
            "不给做法和安排，steps、next、alert 都留空。"
        )
    if k != "detail" and _BODY_STATE.search(text):  # 问身体状态：最多 2 条，写进答案里也行（§82）
        return SLOTS_PROMPT % {"steps": BODY_STEPS, "limit": LIMITS[k]} + (
            "\n他问的是身体状态（不舒服、累、疼、能不能练）：像当面说话一样两三句说完，不分条列清单。"
        )
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
    body_state = bool(text) and bool(_BODY_STATE.search(text)) and k != "detail"
    cap = min(MAX_STEPS[k], BODY_STEPS) if body_state else MAX_STEPS[k]
    if body_state and not _ASKING.search(text):
        cap = 0  # 只说了"今天有点不舒服"：关心一句、问怎么了，不主动给做法（§82）
        raw = {**raw, "next": ""}
    steps = [str(x).strip() for x in steps_raw if str(x).strip()][:cap]
    alert = str(raw.get("alert") or "").strip()
    if alert and text and not _RISKY.search(text):
        alert = ""  # 没问到疼痛、伤病、身体不适，就不加"疼就停""就医"（§42）
    nxt = str(raw.get("next") or "").strip()
    if alert and _TOLD.search(plain(answer + reason)):
        alert = ""  # 答案或理由里已经让他就医、别运动了，不再说一遍（§82）
    if alert and nxt:
        nxt = ""  # 提醒和下一步不同时出现，免得结尾叮嘱两句（§82）
    if reason and _same(reason, answer):
        reason = ""
    if nxt and any(_same(nxt, x) for x in (answer, *steps)):
        nxt = ""  # 下一步和答案或某条做法说的是一件事，不重复

    answer, reason, nxt, alert = (_end(x) for x in (answer, reason, nxt, alert))

    def build() -> str:
        if len(steps) >= NUMBERED and not body_state:
            head = "".join(x for x in (answer, reason) if x)
            body = [f"{i}. {s}" for i, s in enumerate(steps, 1)]
        else:  # 1–2 条做法接在答案后面写成句子，不编号（§82）
            head = "".join(x for x in (answer, reason, *(_end(s) for s in steps)) if x)
            body = []
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
