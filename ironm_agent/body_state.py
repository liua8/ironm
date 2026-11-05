"""他说了自己身体怎样：只按管家交的写（spec [2026-10-23] §163 需求 1，"规则不要"）。

对话里管家调 `record_state`、打卡备注由管家读一遍后交同样的字段，都走这里写进生病记录、今日状态、说疼记录。
代码不再按关键词认生病、认"好了没"、认累和疼，只做两件事：把管家交的字段核对成存得下的样子（轻重是不是那几种、
部位认不认得、数在范围里），再写进去。管家没交就是没说，管家失败就不写。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

_log = logging.getLogger("ironm_agent.body_state")

# 管家交的生病轻重 → 生病记录的级别（§46：颈部以上可以降强度活动，颈部以下、发烧要休息由管家定）
SICK_LEVELS: dict[str, str] = {"发烧": "fever", "颈部以下": "below", "颈部以上": "above", "说不清": "vague"}
BETTER: dict[str, str] = {"好了": "resolved", "好些": "better", "没好": "unwell"}
SIDES = ("左", "右", "两侧")
PAIN_LEVELS = ("轻", "中", "重")

STATE_SCHEMA_PROPS: dict[str, Any] = {
    "sick": {"type": "string", "description": '生病、身体不舒服的症状，他怎么说就怎么写，如"感冒、嗓子疼""肚子疼、拉肚子""发烧 38 度"'},
    "sick_level": {"type": "string", "enum": list(SICK_LEVELS),
                   "description": "写 sick 时一起写：发烧；颈部以下（咳嗽、胸闷、全身酸痛、拉肚子）；颈部以上（流涕、鼻塞、嗓子疼）；说不清"},
    "better": {"type": "string", "enum": list(BETTER), "description": "他说生病好了没有（\"咳嗽也好了\"是好了，不是又病了）"},
    "tired": {"type": "boolean", "description": "说累"},
    "sleep": {"type": "number", "description": "昨晚睡了几小时"},
    "minutes": {"type": "integer", "description": "今天能练多少分钟"},
    "good": {"type": "boolean", "description": "说状态好"},
    "pain": {"type": "array", "description": "练的部位哪里疼（关节）；肚子疼、头疼这类不舒服写进 sick", "items": {
        "type": "object", "additionalProperties": False, "properties": {
            "part": {"type": "string", "enum": ["肩", "手肘", "手腕", "颈椎", "腰", "髋", "膝", "踝"]},
            "side": {"type": "string", "enum": list(SIDES), "description": "他说了左右才写"},
            "exercise": {"type": "string", "description": "在做哪个动作时疼（他说了才写）"},
            "level": {"type": "string", "enum": list(PAIN_LEVELS), "description": "多疼（他说了才写）"},
        }, "required": ["part"]}},
}  # fmt: skip


@dataclass
class Applied:
    """写进去了什么（只有类别和条数，给运行记录和"要不要叫醒管家"用）。"""

    illness: str = ""
    day: int = 0
    pain: list[str] = field(default_factory=list)


def pains_of(raw: Any) -> list[dict[str, str]]:
    """管家交的疼：部位换成关节编码，认不出的不要；左右、动作、轻重不对的空着。"""
    from ironm_agent.facts import PARTS

    out: list[dict[str, str]] = []
    for one in raw if isinstance(raw, list) else []:
        item = one if isinstance(one, Mapping) else {"part": str(one)}
        name = str(item.get("part") or "").strip()
        code = next((k for k, p in PARTS.items() if p.search(name)), None)
        if code is None:
            continue
        side = str(item.get("side") or "")
        level = str(item.get("level") or "")
        out.append({"part": code, "side": side if side in SIDES else "",
                    "exercise": str(item.get("exercise") or "").strip()[:20],
                    "level": level if level in PAIN_LEVELS else ""})  # fmt: skip
    return out


async def apply(
    user_id: str,
    told: Mapping[str, Any],
    *,
    illness: Any,
    days: Any,
    pain: Any,
    memory: Any = None,
    today: date | None = None,
    at: datetime | None = None,
) -> Applied:
    """把管家交的写进去；某一处写不进不影响别处。"""
    from ironm_agent.day_state import Entry
    from ironm_agent.illness import Episode, active, merge, recent
    from ironm_agent.illness import answer as answer_illness

    today = today or date.today()
    at = at or datetime.now(UTC)
    out = Applied()
    sick = str(told.get("sick") or "").strip()[:20]
    better = BETTER.get(str(told.get("better") or "").strip())
    if sick or better:
        try:
            eps = await recent(illness, user_id, today)
            now = active(eps, today)
            changed: Episode | None = None
            if better is not None and now:
                changed, _ = answer_illness(now[0], better, today)  # type: ignore[arg-type]
            elif sick:
                level = SICK_LEVELS.get(str(told.get("sick_level") or ""), "vague")
                changed = merge(eps, [sick], level, today)  # type: ignore[arg-type]
            if changed is not None:
                await illness.save(user_id, changed)
                out.illness = changed.status
        except Exception as e:
            _log.warning("illness save failed: error_type=%s", type(e).__name__)
    entries: list[Any] = []
    if told.get("tired") is True:
        entries.append(Entry(kind="tired", at=at))
    sleep = told.get("sleep")
    if isinstance(sleep, int | float) and not isinstance(sleep, bool) and 0 <= sleep <= 16:
        entries.append(Entry(kind="sleep", at=at, hours=float(sleep) or None))
    minutes = told.get("minutes")
    if isinstance(minutes, int) and not isinstance(minutes, bool) and 5 <= minutes <= 240:
        entries.append(Entry(kind="minutes", at=at, minutes=minutes))
    if told.get("good") is True:
        entries.append(Entry(kind="good", at=at))
    if entries:
        try:
            await days.add(user_id, today, entries)
            out.day = len(entries)
        except Exception as e:
            _log.warning("day state save failed: error_type=%s", type(e).__name__)
    if hurts := pains_of(told.get("pain")):
        try:
            if memory is None or not await memory.paused(user_id):
                for h in hurts:
                    await pain.add(user_id, h["part"], today, side=h["side"], exercise=h["exercise"], level=h["level"])
                out.pain = [h["part"] for h in hurts]
        except Exception as e:
            _log.warning("pain record failed: error_type=%s", type(e).__name__)
    return out


_READ_PROMPT = """你是健身 App 里的「AI 健身管家」。下面是他{where}说的一句话。判断这句话里他有没有说自己身体的状况：哪里疼（在做哪个动作时、左右、多疼）、生病了或病好了、累、没睡好、今天只能练多少分钟、状态很好。
说了就调用 record_state 记下来（只写他这句说了的；"深蹲时左膝有点疼"记膝、左、深蹲、轻）；问话、假设、说别人的不记；没说身体的事就不调用，什么都不用输出。
前面几行只用来看懂他这句在回答什么（"好多了"回的是"感冒好些了吗"就记好些了），前面说过的不再记一遍。"""


async def read_text(user_id: str, text: str, day: date, where: str, deps: Any, llm: Any,
                    context: Sequence[str] = ()) -> Applied | None:  # fmt: skip
    """打卡备注、训练中说的话由管家读一遍（§163 需求 1）：说了疼、病、累就交 record_state，代码照写；
    没说或模型失败就不写，不按关键词猜。"""
    from ironm_agent.actions import RECORD_STATE, RECORD_STATE_SCHEMA

    text = str(text or "").strip()
    if not text:
        return None
    # 对话里接着上一句的（"好多了"回的是"好些了吗"）：管家的问话在回答末尾，取结尾；他的话取开头
    before = "".join(f"前面：{x[:200] if x.startswith('用户') else '…' + x[-200:]}\n" for x in context[-2:])
    messages = [{"role": "system", "content": _READ_PROMPT.format(where=where)},
                {"role": "user", "content": f"{before}{day.month}月{day.day}日{where}：{text[:200]}"}]  # fmt: skip
    try:
        reply = await llm.chat("coach", messages, tools=[RECORD_STATE_SCHEMA])
    except Exception as e:
        _log.warning("checkin note read failed: error_type=%s", type(e).__name__)
        return None
    told: dict[str, Any] = {}
    for call in getattr(reply, "tool_calls", None) or []:
        if call.name == RECORD_STATE and isinstance(call.arguments, Mapping):
            told.update({k: v for k, v in call.arguments.items() if v not in (None, "", [])})
    if not told:
        return Applied()
    return await apply(user_id, told, illness=deps.illness, days=deps.day, pain=deps.pain, memory=deps.memory,
                       today=day)  # fmt: skip
