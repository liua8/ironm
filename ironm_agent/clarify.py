"""信息不够先追问（spec [2026-10-23] §6）：要排训练计划或今天的训练时，关键信息缺两项及以上就先问一句。

三项关键信息：每周能练几天、每次多久；在哪练、有什么器械；目标。来源依次是档案与记忆、这句话、本会话前几轮
用户说的话。追问用固定句式，不调用模型，也不请专业角色；同一件事只追问一次；用户说"你定"就按默认值排。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ironm_agent.memory import USER
from ironm_agent.memory_view import Recall
from ironm_agent.metrics import Profile

PLAN_REQUEST = re.compile(
    r"(?:计划|课表|安排|排一?下|排个|排一个|制定|定制|设计).{0,8}(?:训练|练|健身|一周|每周|周)"
    r"|(?:训练|健身|练).{0,6}(?:计划|课表)"
    r"|(?:今天|今晚|明天|晚上|待会)(?:该|要|应该)?(?:练什么|怎么练|练啥|练哪|练点什么)"
)
_SCHEDULE = re.compile(
    r"(?:\d+|[一两二三四五六七])\s*(?:天|次|练)|(?:\d+|[一两二三四五六七半])\s*(?:个)?(?:多)?(?:小时|分钟)"
    r"|每天|工作日|周末|早上|中午|晚上|下班"
)
_EQUIPMENT = re.compile(
    r"家|健身房|器械|哑铃|杠铃|壶铃|弹力带|徒手|自重|单杠|跑步机|操场|公园|宿舍|酒店|办公室|瑜伽垫"
)
_GOAL = re.compile(
    r"增肌|减脂|减肥|瘦|力量|耐力|马拉松|半马|全马|体能|健康|塑形|增重|长肌肉|减重|减肚子|体态|练大"
)
DEFAULTS = re.compile(
    r"你定|随便|都行|你看着|你来定|默认|无所谓|不知道|直接给|直接排|看着办|都可以|你安排"
)
MARK = "也可以直接说「你定」"  # 追问的标志：本会话已经问过就不再问
DEFAULT_PLAN = "每周 3 天、每次 45 分钟、徒手加哑铃"
DEFAULT_NOTE = f"用户让你来定：按默认值（{DEFAULT_PLAN}，目标按综合健康）来排，并在回答里说明用了默认值、以后可以随时改。"
ANSWERED_NOTE = f"用户刚回答了教练的追问（见前几轮对话）：按他说的来排，没说到的按默认值（{DEFAULT_PLAN}），并说明哪些用了默认值。"

_QUESTIONS = {
    "schedule": "你一周能练几天、每次大概多久？",
    "equipment": "在家还是健身房，手边有什么器械？",
    "goal": "主要想增肌、减脂，还是提升体能？",
}


@dataclass(frozen=True)
class Decision:
    plan: bool = False  # 这一轮是要排训练（含回答追问的那一轮），一定请训练教练
    ask: str = ""  # 要追问时的固定句子
    note: str = ""  # 不追问时交给训练教练的说明（如按默认值排）
    missing: tuple[str, ...] = ()
    origin: str = ""  # 回答追问时：用户当初问的是什么（据此决定要不要出计划预览）


def asked(history: Sequence[str]) -> str | None:
    """上一条回答是不是追问；是的话返回用户当初问的那句话。"""
    coach = [i for i, x in enumerate(history) if not x.startswith(USER)]
    if not coach or MARK not in history[coach[-1]]:
        return None
    before = [x[len(USER) :] for x in history[: coach[-1]] if x.startswith(USER)]
    return before[-1] if before else ""


def _answers(text: str) -> bool:
    """这句话像是在回答追问（"你定""一周三练，在家有哑铃""想增肌"），而不是换了个话题（"早餐吃什么"）。"""
    return bool(
        DEFAULTS.search(text)
        or _SCHEDULE.search(text)
        or _EQUIPMENT.search(text)
        or _GOAL.search(text)
    )


def decide(
    text: str, history: Sequence[str], recall: Recall, profile: Profile, *, has_plan: bool = False
) -> Decision:
    """has_plan：已经有确认过的计划，每周几练、每次多久、用什么器械都在计划里，不再追问这些。"""
    origin = asked(history)
    if origin is not None and _answers(text):
        note = DEFAULT_NOTE if DEFAULTS.search(text) else ANSWERED_NOTE
        return Decision(plan=True, note=note, origin=origin)
    if not PLAN_REQUEST.search(text):
        return Decision()
    if DEFAULTS.search(text):
        return Decision(plan=True, note=DEFAULT_NOTE)
    if any(MARK in x for x in history):
        return Decision(plan=True)  # 同一件事只追问一次
    said = "\n".join([text, *(x[len(USER) :] for x in history if x.startswith(USER))])
    have = {
        c for c in ("schedule", "equipment", "goal") if any(x.category == c for x in recall.items)
    }
    if profile.goal:
        have.add("goal")
    if has_plan:
        have |= {"schedule", "equipment"}
    for key, pattern in (("schedule", _SCHEDULE), ("equipment", _EQUIPMENT), ("goal", _GOAL)):
        if pattern.search(said):
            have.add(key)
    missing = tuple(k for k in ("schedule", "equipment", "goal") if k not in have)
    if len(missing) < 2:
        return Decision(plan=True, missing=missing)
    asks = [_QUESTIONS[k] for k in missing[:2]]
    numbered = "".join(f"{'①②'[i]}{q}" for i, q in enumerate(asks))
    return Decision(
        plan=True,
        ask=f"先确认两件事，好给你排得准：{numbered}{MARK}，我先按{DEFAULT_PLAN}来排。",
        missing=missing,
    )
