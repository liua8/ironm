"""单 Agent（spec [2026-10-23] §67）：一个 Agent 回答所有问题，规程（Skill）按需装载，工具由它按需调用。

和专业角色共用同一套作答循环（查询次数上限、逐句核对出处和数字、不合格改一次、再不合格修正）；
不同的是：不分角色、不经调度和整合；涉及哪个领域就带上那个领域的判断规则；可以自己再装一份 Skill、
查 App 用法；要不要改计划、排新计划、记训练由它看上下文判断，写在回答的 JSON 里，由系统执行。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from ironm_agent.actions import ASK_TERMS, LOG_WORKOUT, NEW_PLAN, PLAN_EDIT
from ironm_agent.answer_format import slots_prompt
from ironm_agent.casefile import CaseFile
from ironm_agent.coach import app_guide
from ironm_agent.experts import (
    _SOLO_FIELDS,
    Consultation,
    Opinion,
    _loop,
    _user_message,
    experience_share,
)
from ironm_agent.frameworks import FRAMEWORKS, flag_refs, flags_of, framework_refs
from ironm_agent.llm import LLM, ModelUnavailable
from ironm_agent.memory_store import CATEGORIES, Item
from ironm_agent.memory_view import Recall, until_text
from ironm_agent.personal import Personal
from ironm_agent.roles import GENERAL, Role
from ironm_agent.skills import Skill, by_id, catalog_any, prompt_of
from ironm_agent.tools import Toolbox
from ironm_agent.training import weekday_name

LOAD_SKILL = "load_skill"
APP_HELP = "app_help"

LOAD_SKILL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOAD_SKILL,
        "description": (
            "再装一份规程（决策卡：管哪几个决定、判断要点、怎么说），或者取已装规程的某一节细节。"
            "id 从系统提示里的规程目录里选；要细节时带 section（决策卡后面列的分节编号或名字，写「全部」取整份）。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "id": {"type": "string", "description": "规程编号，如 plan-build"},
                "section": {
                    "type": "string",
                    "description": "要看的那一节：编号（如 5）或名字（如 选初步方案）；不写给决策卡",
                },
            },
            "required": ["id"],
        },
    },
}
APP_HELP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": APP_HELP,
        "description": "查这个 App 的使用说明（哪个页面、点哪里、怎么做）。用户问 App 怎么用时调用。",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {}},
    },
}


async def _load_skill(box: Toolbox, args: Mapping[str, Any]) -> str:
    skill = by_id(str(args.get("id", "")).strip())
    if skill is None:
        return "没有这个规程编号，请从目录里选。"
    box.adopt(e for r in skill.refs_for(box.flags) if (e := box.kb.get(r)) is not None)
    which = str(args.get("section") or "").strip()
    if which:  # 取一节细节（§99）
        part = skill.section(which)
        return part if part is not None else f"没有这一节。{skill.name}的分节：{skill.index()}"
    text = skill.text(box.flags)
    # 规程带的动作工具（改计划、新计划、记训练）这时才开放（§120）
    opened = box.actions.unlock(skill.toolset) if box.actions is not None else []
    if opened:
        text += "\n\n装上后多了这些工具：" + "、".join(opened) + "。"
    held = getattr(
        box, "actions_held", ""
    )  # 计划和记录的做法这一轮没放进系统提示（§96）：装训练类规程时补上
    if held and skill.role == Role.TRAINER:
        box.actions_held = ""
        return text + "\n\n计划和训练记录（只在需要时做）：\n" + held
    return text


async def _app_help(box: Toolbox, args: Mapping[str, Any]) -> str:
    return "使用说明（照着答，说明里没有的功能如实说还没有）：\n" + app_guide()


EXTRA_TOOLS = {LOAD_SKILL: (LOAD_SKILL_SCHEMA, _load_skill), APP_HELP: (APP_HELP_SCHEMA, _app_help)}

_PROMPT = """你是健身 App 里的「AI 健身管家」：一位持证体能教练，同时懂运动营养和运动康复。训练、饮食、恢复与睡眠、身体数据的解读、App 怎么用、闲聊，都由你一个人回答。

{framework}

先后（冲突时按这个来）：安全规则（急症、就医、不诊断不开药）> 回答格式（先答问的、篇幅、最后那几段怎么写）> 规程；规程里"输出"一段只是这类回答的结构参考。

先看上下文再答：
1. 先判断这句话和前面的关系：新问题、对上一条回答的追问或质疑、补充条件、对计划预览的意见，还是闲聊。接着上一轮的，就接着上一轮答。被质疑时先核对你上一条回答和预览里实际说过什么：说错或漏了就认错并改正；没说错就用你说过的内容回答，不要顺着认错。
2. 只答问的：第一句就是答案，原因放后面，没问到的不说，等他追问再展开。他提了要求（"给我安排个轻松的"），第一句先接住：能做就直接给，不能做再说为什么。他只说自己的状况（"今天有点不舒服""好累"）、没问怎么办时，关心一句、问怎么了，不主动给做法和安排。提起记忆和今天的状态像教练当面说话：用问候或一句话带过（"前两天说感冒了，好点了吗"），不报日期，不转述系统的判断（"现在还没好"），他没问的计划安排（今天本来是休息日、病后第一次按几成）不说。超出健身、饮食、恢复、身体数据的问题，说明帮不上、能帮什么。不诊断、不开药。
3. 关于这个人的事实（状态、伤病、计划、记录、数据）只照档案、数据、记忆和对话说，不推测、不编造；数据不是最近 7 天的，说清是哪天的，不当成现在的状态；给具体的量（组次、克数、分钟），数字用工具结果、档案或资料里的，不自己估。
4. 需要信息就调用工具（{tools}），一轮可以调几次，拿到要的就作答。问 App 怎么用时调用 app_help。装上的规程不够时调用 load_skill 再装一份（目录在最后）。

出处（系统会逐句核对）：用到资料的句子句末写〔K03〕，用到档案或计算结果写〔C2〕，凭经验写〔经验〕；用到他的健康数据写成 <statement>这句话<cite>[r3]</cite></statement>。带数字的句子都要有出处，数字照资料、计算或数据写。

计划和训练记录（只在需要时做；只是问问、抱怨、闲聊、解释时不做，计划不动）：
{actions}

记忆（他这句话说了关于他本人、以后要照顾到的情况才写；提问、闲聊、别人的事、假设、否定的说法不记，已有的不重复记）：
- JSON 里加 "memory" 列表，每条 {{"op":"add|update|resolve","target":"已有记忆编号（add 不写）","category":"injury|equipment|schedule|diet|preference|goal|level|style|event|followup","content":"一句话≤40字，留部位左右重量时间","quote":"他原话里一字不差的一段","inferred":"推测的写 true","lasting":"long（一直要照顾）或 short（某一天、这几天）","until":"event、followup 的截止日 YYYY-MM-DD"}}
- 只写他说了的：问句带出的不算（「肌酐高了怎么办」「久坐圆肩怎么改善」不记）；你的安排不写进去；圆肩驼背是体态不是 injury。
- short 的（今天累、这周出差）系统记成近期的事，until："这周"写周日、"这两天"写明天，看不出写 7 天后。一顿饭、一次训练不记。长期的情况变了 update 那一条；他说好了、结束了、取消了，resolve 还在生效的近况和跟进，不新增"已结束"。
- 答应回访、他要你提醒的记 followup；"该问的、到期的跟进"里你提了或他答了，用编号 resolve。

他说了自己今天的状况，JSON 加 "said"（只写说了的）：{{"sick":"症状","better":"好了|好些|没好","tired":true,"sleep":睡的小时,"minutes":能练的分钟,"good":true,"pain":["部位"]}}；问话、假设、别人的不写。

{slots}
打招呼、道谢、闲聊时只写 answer（一两句自然回应），其余几段留空，不报今天的计划、打卡和数据。{skills}

可以再装的规程目录：
{catalog}"""

_ASK_FIRST = (
    "- 用户明确要一份新计划（还没有计划、要重排），或长期条件变了（换了健身房、以后每周只能练两天）要重来：这一轮不交计划，"
    f"先调用 {ASK_TERMS}，"
    '回答以"排新计划前先确认一下"开头，用你自己的话把"排新计划要用的条件"（目标、场景、器械、时间、伤病）列给他确认：'
    "有旧答案的说出来、问还是不是这样，没有的问一句；最后请他说哪几项变了、是临时的还是以后都这样。"
)
_CONFIRMED = (
    f"- 用户要一份新计划：前几轮你列过排新计划的条件。他已经确认过（或说了哪几项变了、说「你定」）的，按确认的条件调用 {NEW_PLAN}（kind 写 new）交完整的计划；"
    f"他还没回应过那张清单就不算确认：这一轮先不交计划，调用 {ASK_TERMS}，"
    '回答以"排新计划前先确认一下"开头把条件再列给他确认。'
)
_TEMPORARY = (
    "- 临时的变化（这周出差、生病、这几天忙、只能在酒店练）：记成近期事件，回答这几天怎么练；不排新计划。"
    "他要求改计划时，只改受影响的那几天。"
)
_JUST_ASKED = (
    "- 上一轮你列了排新计划要用的条件请他确认。他这句话是确认（如「按这个排」「可以」「你定」）或改了其中几项："
    f"这一轮就按确认的条件调用 {NEW_PLAN}（kind 写 new）交完整的计划（不要只写在回答里）；确认的条件和记忆里不一样的（目标、器械、时间），在 memory 里用 update 改那一条；他换了别的话题，就答他的话题，不交计划。"
)
_EDIT = (
    f"- 用户要改现有计划的某几处（换动作、挪天、改组次、删、减量）：调用 {PLAN_EDIT}，只交要改的地方（写法见工具说明）；"
    f"要在现有计划上换分化、整份重排、几种操作说不清时调用 {NEW_PLAN}（kind 写 rewrite）交整份。"
)
_LOG = (
    f"- 用户在报告自己这次练了什么：调用 {LOG_WORKOUT} 交这次的记录，数字只来自他的话，没说的不填。"
)
_RESULT = (
    "- 这些工具装了排训练计划（plan-build）、记训练与复盘（log-review）才有，没有时先用 load_skill 装上。"
    "调用后系统会告诉你结果：出了预览的，用一两句话说改了什么、为什么（卡片会显示全部内容，不要再写一遍），系统另外换了动作的照结果说；"
    "被退回的，按原因改了再交，或者照原因跟他说没改成、请他说清楚。没有成功调用，就不要说「已经改了」「记下了」。"
)

# 这一轮不涉及训练时，计划和记录的做法不放进系统提示，只留这一句（§96）
ACTIONS_SHORT = "（这一轮不涉及训练；要改计划、排计划或记训练时，先用 load_skill 装 plan-build 或 log-review，工具会一起给你。）"


def actions_prompt(*, has_plan: bool, confirmed: bool, just_asked: bool = False) -> str:
    parts = [_JUST_ASKED] if just_asked else []
    if has_plan:
        parts.append(_EDIT)
    parts.append(_CONFIRMED if confirmed else _ASK_FIRST)
    parts.append(_TEMPORARY)
    parts.append(_LOG)
    parts.append(_RESULT)
    return "\n".join(parts)


def memory_text(known: Mapping[str, Item], today: date) -> str:
    """单 Agent 看到的记忆：带编号（更新、标为已解决时用），近期事件写明哪天说的、到哪天为止。"""
    if not known:
        return f"这个人的记忆：（还没有）。今天是 {today.isoformat()}（{weekday_name(today.isoweekday())}）。"
    lines = []
    for h, x in known.items():
        when = ""
        if x.category in ("event", "advice"):
            when = (
                f"（{x.created.astimezone().month}月{x.created.astimezone().day}日{until_text(x)}）"
            )
        done = "（已解决）" if x.status == "resolved" else ""
        lines.append(f"{h}｜{x.category} {CATEGORIES[x.category]}{done}：{x.content}{when}")
    return (
        f"这个人的记忆（编号｜类别：内容；照顾到，和这次问题无关的不要提；今天是 {today.isoformat()}（{weekday_name(today.isoweekday())}））：\n"
        + "\n".join(lines)
    )


def domains_of(skills: Sequence[Skill]) -> list[Role]:
    """这一轮装上的规程涉及哪些领域（按训练、恢复、饮食的顺序）。"""
    roles = {x.role for x in skills if x.role is not None}
    return [r for r in (Role.TRAINER, Role.RECOVERY, Role.NUTRITION) if r in roles]


def framework_for() -> str:
    """管家提示词里的专业部分只留各专业要点的总览；领域的判断规则从基础规程来（§74）。"""
    return FRAMEWORKS[Role.GENERAL]


async def respond(
    text: str,
    history: Sequence[str],
    concerns: Sequence[str],
    toolbox: Toolbox,
    llm: LLM,
    personal: Personal | None,
    memory: Recall | None,
    *,
    case: CaseFile,
    skills: Sequence[Skill],
    note: str = "",
    has_plan: bool = False,
    confirmed: bool = False,
    just_asked: bool = False,
    today: date | None = None,
    images: Sequence[Mapping[str, Any]] = (),
    known: Mapping[str, Item] | None = None,
    memory_block: str | None = None,
    training: bool = True,
    with_case: bool = True,
) -> Consultation:
    """单 Agent 作答一轮。出错时返回不发言的意见，不向外抛（和专业角色一样）。
    training：这一轮涉及训练才放计划和记录的写法；不涉及时装上训练类规程再补（§96）。"""
    flags = flags_of([x.key for x in case.risks], bool(case.injuries), case.readiness.level)
    domains = domains_of(skills)
    if (
        toolbox.actions is not None
    ):  # 先装上的规程带的动作工具（§120）；涉及训练时先确认条件的那个一直给（没有副作用）
        toolbox.actions.unlock(
            [*([ASK_TERMS] if training else []), *(t for x in skills for t in x.toolset)]
        )
    tools = "、".join(str(s["function"]["name"]) for s in toolbox.schemas()) or "（没有可用的工具）"
    actions = actions_prompt(has_plan=has_plan, confirmed=confirmed, just_asked=just_asked)
    toolbox.actions_held = "" if training else actions
    system = _PROMPT.format(
        framework=framework_for(),
        tools=tools,
        actions=actions if training else ACTIONS_SHORT,
        slots=slots_prompt(text, None),
        skills=prompt_of(skills, flags),
        catalog=catalog_any(),
    )
    toolbox.flags = flags
    # 规程（含基础规程的判断规则）和总览里引用的资料，照抄时也要能通过核对
    toolbox.adopt(
        e for x in skills for r in x.refs_for(flags) if (e := toolbox.kb.get(r)) is not None
    )
    toolbox.adopt(
        e
        for r in (*framework_refs(Role.GENERAL, flags), *flag_refs(flags))
        if (e := toolbox.kb.get(r)) is not None
    )
    asked = _user_message(
        text,
        history,
        concerns,
        personal.text() if personal and with_case else "",  # 闲聊不给数据（§98）
        memory_block
        if memory_block is not None
        else memory_text(known, today or date.today())
        if known is not None
        else memory.shared()
        if memory is not None
        else "",
        case=case.text(calcs=True) if with_case else "",  # 闲聊不给档案（§98）
        note=note,
        # 只装了基础规程时最多按字面预取 2 条资料；装了内容规程（自带依据）或什么都没装（闲聊）时不预取（§96）
        prefetched=toolbox.prefetch(text, k=2 if skills and all(x.core for x in skills) else 0),
    )
    content: str | list[Any] = [{"type": "text", "text": asked}, *images] if images else asked
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    said = "\n".join(x for x in (text, memory.numbers_text() if memory else "") if x)
    if personal is not None:
        toolbox.evidence.support.update(personal.support)
        toolbox.evidence.rows.update(personal.rows)
    trace: dict[str, Any] = {"rounds": 0, "checks": [], "fixed": False, "repaired": False,
                             "exhausted": False, "forced": False, "domains": [r.value for r in domains]}  # fmt: skip
    start = time.perf_counter()
    try:
        opinion = await _loop(GENERAL, messages, toolbox, llm, said, _SOLO_FIELDS, None, today,
                              trace, question=text)  # fmt: skip
    except ModelUnavailable:
        silent = Opinion(role=Role.GENERAL, speak=False, reason="这次没能调用模型")
        trace["ms"] = int((time.perf_counter() - start) * 1000)
        return Consultation(silent, toolbox.evidence, "failed", trace)
    trace["ms"] = int((time.perf_counter() - start) * 1000)
    trace["experience"] = experience_share(opinion.body()) if opinion.speak else 0.0
    return Consultation(opinion, toolbox.evidence, "spoke" if opinion.speak else "silent", trace)
