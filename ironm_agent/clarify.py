"""排训练前先问清楚（spec [2026-10-23] §6、§55）。

要一份新计划（还没有计划，或者要重排、要"一份计划"）时，一次列出打算按什么排：目标、场景、器械、时间、伤病，
有旧答案的带上来源和日期，没变就回「按这个排」；本会话确认过就不再问；只改现有计划的某一处时不问。
问今天练什么、还没有计划时，仍按 §6：关键信息缺两项及以上才问。都用固定句式，不调用模型。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ironm_agent.memory import USER
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import EVENT_DAYS, Recall
from ironm_agent.metrics import GOALS, Profile

PLAN_REQUEST = re.compile(
    r"(?:计划|课表|安排|排一?下|排个|排一个|制定|定制|设计).{0,8}(?:训练|练|健身|一周|每周|周)"
    r"|(?:训练|健身|练).{0,6}(?:计划|课表)"
    r"|(?:今天|今晚|明天|晚上|待会)(?:该|要|应该)?(?:练什么|怎么练|练啥|练哪|练点什么)"
    r"|(?:给我|来|要|想要|定|做|排|出|制定|重新定|重新做)[^，。？！?!]{0,8}(?:计划|课表)"
)
# 要的是一份整的计划（不是今天练什么）
_WHOLE = re.compile(r"计划|课表|一周|每周")
# 问的是有多少、有哪些计划（§83），不是要一份：没说"给我排、帮我做、要一份"时不当成要新计划
ASK_ABOUT_PLANS = re.compile(
    r"(?:多少|几个|几份|几套|哪些|什么样的|有什么|都有|还有别的|别的|其他)[^，。？！?!]{0,6}(?:训练)?(?:计划|方案|课表)"
    r"|(?:计划|方案|课表)[^，。？！?!]{0,4}(?:有多少|有几个|有几份|有哪些|都有什么|多不多)"
)
_ASK_FOR_ONE = re.compile(r"给我|帮我|替我|排|做一份|来一份|要一份|制定|定制|设计|换")
# 说的不是训练计划
_NOT_TRAINING = re.compile(r"饮食|食谱|吃|餐|营养|减脂餐|热量|睡眠|作息")
# 要一份新的（§55 需求 3）
REPLAN = re.compile(
    r"重新排|重排|新排|重新做|重新制定|重做|从头|换个计划|新计划|再排一份|重新定"
    r"|(?:来|给我|要|想要|做|排|出|制定)(?:一份|一个|个|份)[^，。？！?!]{0,8}(?:计划|课表)"
    r"|来一份新的|新的一份|更好的.{0,6}计划"
)
# 点到具体的天、动作、组次、时长：改现有计划的一处
_SPECIFIC = re.compile(
    r"周[一二三四五六日天]|星期|礼拜|这周|本周|下周|深蹲|硬拉|卧推|划船|引体|推举|弓步|臀桥|骑车|跑步"
    r"|\d+\s*(?:组|次|分钟|公斤)|换掉|删掉|去掉|挪|少练|多练|加一练|减量|轻一?点|动作"
)
# 按现有计划问今天、明天练什么：不是要新计划
_WHICH_DAY = re.compile(
    r"(?:今天|今晚|明天|晚上|待会|这次)(?:该|要|应该)?(?:练什么|怎么练|练啥|练哪|练点什么)"
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
_HURT = re.compile(r"疼|痛|伤|膝|腰|肩|好了|恢复")
DEFAULTS = re.compile(
    r"你定|随便|都行|你看着|你来定|默认|无所谓|不知道|直接给|直接排|看着办|都可以|你安排"
)
NO_CHANGE = re.compile(r"按这个排|按这个来|没变|都没变|不变|照旧|就这样|没问题|对的?|是的")
MARK = "也可以直接说「你定」"  # 追问的标志：本会话已经问过就不再问
HEAD = "排新计划前先确认一下"  # 确认五项的开头（之前的回答只留开头一段，标志放开头才找得到）
CONFIRM = "都没变就回「按这个排」"
DEFAULT_PLAN = "每周 3 天、每次 45 分钟、徒手加哑铃"
DEFAULT_NOTE = f"用户让你来定：按默认值（{DEFAULT_PLAN}，目标按综合健康）来排，并在回答里说明用了默认值、以后可以随时改。"
ANSWERED_NOTE = f"用户刚回答了教练的追问（见前几轮对话）：按他说的来排，没说到的按默认值（{DEFAULT_PLAN}），并说明哪些用了默认值。"
CONFIRMED_NOTE = (
    "上一轮你列了排新计划要用的条件请他确认（见前几轮对话）。先看他这句是不是在回应那张清单（确认、改了几项、「你定」）："
    "是的话，列出的条件里他说变了的按新的排，其余照列出的排；只说「你定」时，有旧答案的照旧，没有的按默认值（"
    + DEFAULT_PLAN + "）；计划说明第一句写这份计划按他的目标怎么排，他说了的变化在回答里复述一句。"
    "他问的是别的事（比如问身体、问吃什么），就只答他问的，这一轮不写计划（§108）。"
)

_QUESTIONS = {
    "schedule": "你一周能练几天、每次大概多久？",
    "equipment": "在家还是健身房，手边有什么器械？",
    "goal": "主要想增肌、减脂，还是提升体能？",
}
_PLACES = (("健身房", "健身房"), ("家", "在家"), ("宿舍", "宿舍"), ("酒店", "酒店"),
           ("办公室", "办公室"), ("操场", "户外"), ("公园", "户外"), ("户外", "户外"))  # fmt: skip


@dataclass(frozen=True)
class Decision:
    plan: bool = False  # 这一轮是要排训练（含回答追问的那一轮），一定请训练教练
    ask: str = ""  # 要追问时的固定句子
    note: str = ""  # 不追问时交给训练教练的说明（如按默认值排）
    missing: tuple[str, ...] = ()
    origin: str = ""  # 回答追问时：用户当初问的是什么（据此决定要不要出计划预览）
    new: bool = False  # 要的是一份新计划（不是改现有计划的某一处）


def asked(history: Sequence[str]) -> str | None:
    """上一条回答是不是追问；是的话返回用户当初问的那句话。"""
    coach = [i for i, x in enumerate(history) if not x.startswith(USER)]
    if not coach or not _is_ask(history[coach[-1]]):
        return None
    before = [x[len(USER) :] for x in history[: coach[-1]] if x.startswith(USER)]
    return before[-1] if before else ""


def _is_ask(line: str) -> bool:
    return MARK in line or HEAD in line


def wants_new(text: str, *, has_plan: bool) -> bool:
    """要的是一份整的新训练计划（§55 需求 3）：没有计划时要计划；已有计划时说了重排、要"一份计划"，
    或者只说要计划、没点到具体的天、动作、组次、时长。"""
    if not PLAN_REQUEST.search(text) or not _WHOLE.search(text):
        return False
    if ASK_ABOUT_PLANS.search(text) and not _ASK_FOR_ONE.search(text):
        return False  # "你们有多少训练计划"：问的是方案库（§83）
    if _NOT_TRAINING.search(text) and not re.search(r"训练|练|健身", text):
        return False
    if _WHICH_DAY.search(text) and not REPLAN.search(text) and not re.search(r"计划|课表", text):
        return False  # "今天练什么，一周三练"：问的是今天，"一周"是在说时间
    if not has_plan or REPLAN.search(text):
        return True
    return not (_SPECIFIC.search(text) or _WHICH_DAY.search(text))


def replies(text: str) -> bool:
    """路由不可用时的兜底：这句话像是在回答追问（模型可用时由路由判断，§108）。"""
    return _answers(text)


def _answers(text: str) -> bool:
    """这句话像是在回答追问（"你定""按这个排""一周三练，在家有哑铃""现在只有 30 分钟"），
    而不是换了个话题（"早餐吃什么"）。"""
    return bool(
        DEFAULTS.search(text)
        or NO_CHANGE.search(text)
        or _SCHEDULE.search(text)
        or _EQUIPMENT.search(text)
        or _GOAL.search(text)
        or _HURT.search(text)
    )


def _md(d: date) -> str:
    return f"{d.month}月{d.day}日"


def _said(items: Sequence[Item]) -> str:
    """几条记忆连起来，带上最早那条是哪天说的。"""
    first = min(x.created for x in items)
    return "；".join(x.content for x in items) + f"（{_md(first.date())}你说的）"


_ONE_DAY = re.compile(r"今天|今晚|今早|今日|今儿")
_THIS_WEEK = re.compile(r"这周|本周|这个星期|这礼拜")
_NEXT_WEEK = re.compile(r"下周|下个星期|下礼拜")


def _until(x: Item) -> date:
    """临时情况到哪天为止：说了今天的只算那天，说了这周、下周的到那周日，其余按两周。"""
    start = x.created.date()
    if _ONE_DAY.search(x.content):
        return start
    sunday = start + timedelta(days=6 - start.weekday())
    if _NEXT_WEEK.search(x.content):
        return sunday + timedelta(days=7)
    if _THIS_WEEK.search(x.content):
        return sunday
    return start + timedelta(days=EVENT_DAYS)


def _span(start: date, end: date) -> str:
    return f"{_md(start)}当天" if end == start else f"{_md(start)}起，到{_md(end)}"


def conditions(
    recall: Recall,
    profile: Profile,
    *,
    target: str = "",
    plan_line: str = "",
    today: date | None = None,
    checked_today: bool = False,
) -> list[str]:
    """排新计划前要确认的五项（§55 需求 1、2、6、7）：有旧答案的带上来源和日期，没有的只问一句。

    target：目标表里的目标（"2027年10月26日前体重到 65 公斤，现在 67 公斤（10月26日设的）"）；
    plan_line：当前计划的时间安排（"现在的计划每周 4 练：周一、周二、周四、周六"）。
    """
    active = [x for x in recall.items if x.status != "resolved"]

    def of(cat: str) -> list[Item]:
        return [x for x in active if x.category == cat]

    out = []
    goals = of("goal")
    if target:
        out.append(f"①目标：{target}")
    elif goals:
        out.append(f"①目标：{_said(goals)}")
    elif profile.goal:
        out.append(
            f"①目标：档案里写的是{GOALS[profile.goal]}，有具体的数和日期吗（比如几月前减到多少公斤）？"
        )
    else:
        out.append("①目标：主要想增肌、减脂，还是提升体能？有具体的数和日期更好。")
    gear = of("equipment")
    places = [x for x in gear if any(k in x.content for k, _ in _PLACES)]
    if places:
        names = list(dict.fromkeys(n for x in places for k, n in _PLACES if k in x.content))
        out.append(
            f"②场景：{'、'.join(names)}（{_md(min(x.created for x in places).date())}你说的）"
        )
    else:
        out.append("②场景：在家、健身房，还是户外？")
    out.append(
        f"③器械：{_said(gear)}" if gear else "③器械：手边有什么器械（比如哑铃多重），还是徒手？"
    )
    times = of("schedule")
    if times:
        out.append(f"④时间：{_said(times)}" + (f"；{plan_line}" if plan_line else ""))
    elif plan_line:
        out.append(f"④时间：{plan_line}")
    else:
        out.append("④时间：一周能练几天、每次大概多久、哪几天有空？")
    hurts = of("injury")
    if hurts:
        out.append(f"⑤伤病：{_said(hurts)}，现在怎么样？")
    else:
        out.append("⑤伤病：有没有旧伤、正在恢复或者哪里不能练？")
    # 临时的和上面五项长期的分开写，带起止日期；已经过了的不写（§55 需求 7）
    temp = [(x, _until(x)) for x in of("event")]
    temp = [(x, end) for x, end in temp if today is None or end >= today]
    if temp:
        spans = [f"{x.content}（{_span(x.created.date(), end)}）" for x, end in temp]
        out.append("这两周的临时条件（到期就不再用）：" + "；".join(spans))
    if today is not None:
        tomorrow = today + timedelta(days=1)
        out.append(
            f"今天已经打过卡，新计划从明天（{_md(tomorrow)}）开始。"
            if checked_today
            else f"新计划今天开始还是明天（{_md(tomorrow)}）开始？不说就从今天开始。"
        )
    return out


def confirm_ask(lines: Sequence[str]) -> str:
    return (
        f"{HEAD}，我打算按这些排：\n"
        + "\n".join(lines)
        + f"\n\n{CONFIRM}，有变的说哪几项（是这两周临时的还是以后都这样也说一声）；{MARK}。"
    )


def decide(
    text: str,
    history: Sequence[str],
    recall: Recall,
    profile: Profile,
    *,
    has_plan: bool = False,
    target: str = "",
    plan_line: str = "",
    today: date | None = None,
    checked_today: bool = False,
) -> Decision:
    """has_plan：已经有确认过的计划。target、plan_line、today、checked_today 见 conditions。"""
    origin = asked(history)
    if origin is not None and _answers(text):
        last = next(x for x in reversed(history) if not x.startswith(USER))
        if HEAD in last:  # 回答五项确认（§55）：没变的照列出的排，变了的按新的
            return Decision(plan=True, note=CONFIRMED_NOTE, origin=origin, new=True)
        note = DEFAULT_NOTE if DEFAULTS.search(text) else ANSWERED_NOTE
        return Decision(plan=True, note=note, origin=origin)
    if not PLAN_REQUEST.search(text):
        return Decision()
    new = wants_new(text, has_plan=has_plan)
    if DEFAULTS.search(text):
        return Decision(plan=True, note=DEFAULT_NOTE, new=new)
    if any(_is_ask(x) for x in history):
        return Decision(plan=True, new=new)  # 本会话问过了，不再问
    if new:  # §55：要新计划，五项都确认
        lines = conditions(recall, profile, target=target, plan_line=plan_line, today=today,
                           checked_today=checked_today)  # fmt: skip
        return Decision(plan=True, ask=confirm_ask(lines), missing=("confirm",), new=True)
    if has_plan:
        return Decision(plan=True)  # 改现有计划的一处，或按计划问今天练什么
    # 没有计划，问今天练什么（§6）：缺两项及以上才问
    said = "\n".join([text, *(x[len(USER) :] for x in history if x.startswith(USER))])
    have = {
        c for c in ("schedule", "equipment", "goal") if any(x.category == c for x in recall.items)
    }
    if profile.goal:
        have.add("goal")
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
