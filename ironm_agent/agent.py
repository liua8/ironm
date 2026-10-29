"""单 Agent（spec [2026-10-23] §67）：一个 Agent 回答所有问题，规程（Skill）按需装载，工具由它按需调用。

和专业角色共用同一套作答循环（查询次数上限、逐句核对出处和数字、不合格改一次、再不合格修正）；
不同的是：不分角色、不经调度和整合；涉及哪个领域就带上那个领域的判断规则；可以自己再装一份 Skill、
查 App 用法；要不要改计划、排新计划、记训练由它看上下文判断，写在回答的 JSON 里，由系统执行。
"""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping, Sequence
from datetime import date
from typing import Any

from ironm_agent.answer_format import slots_prompt
from ironm_agent.casefile import CaseFile
from ironm_agent.coach import app_guide
from ironm_agent.experts import (
    _SOLO_FIELDS,
    TASKS,
    Consultation,
    Opinion,
    _loop,
    _user_message,
    experience_share,
)
from ironm_agent.frameworks import FRAMEWORKS, domain_rules, flags_of, framework_refs
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
NEW_PLAN = "new_plan"  # 要排新计划、本会话还没确认条件：由系统列出五项请他确认

LOAD_SKILL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": LOAD_SKILL,
        "description": "再装一份规程（做事步骤、判断规则、禁忌）。已经装上的不用再装；id 从系统提示里的规程目录里选。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"id": {"type": "string", "description": "规程编号，如 plan-muscle"}},
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
    box.adopt(e for r in skill.refs if (e := box.kb.get(r)) is not None)
    return skill.text()


async def _app_help(box: Toolbox, args: Mapping[str, Any]) -> str:
    return "使用说明（照着答，说明里没有的功能如实说还没有）：\n" + app_guide()


EXTRA_TOOLS = {LOAD_SKILL: (LOAD_SKILL_SCHEMA, _load_skill), APP_HELP: (APP_HELP_SCHEMA, _app_help)}

_PROMPT = """你是健身 App 里的「AI 健身管家」：一位持证体能教练，同时懂运动营养和运动康复。训练、饮食、恢复与睡眠、身体数据的解读、App 怎么用、闲聊，都由你一个人回答。

{framework}

先看上下文再答：
1. 先判断这句话和前面的关系：新问题、对上一条回答的追问或质疑、补充条件、对计划预览的意见，还是闲聊。接着上一轮的，就接着上一轮答。被质疑时先核对你上一条回答和预览里实际说过什么：说错或漏了就认错并改正；没说错就用你说过的内容回答，不要顺着认错。
2. 只答问的：第一句就是答案，原因放后面，没问到的不说，等他追问再展开。打招呼、闲聊一两句自然回应，不主动报今天的计划、打卡和数据。超出健身、饮食、恢复、身体数据的问题，说明帮不上、能帮什么。不诊断、不开药。
3. 关于这个人的事实（状态、伤病、计划、记录、数据）只照档案、数据、记忆和对话说，不推测、不编造；给具体的量（组次、克数、分钟），数字用工具结果、档案或资料里的，不自己估。
4. 需要信息就调用工具（{tools}），一轮可以调几次，拿到要的就作答。问 App 怎么用时调用 app_help。装上的规程不够时调用 load_skill 再装一份（目录在最后）。

出处（系统会逐句核对）：用到资料的句子句末写〔K03〕，用到档案或计算结果写〔C2〕，凭经验写〔经验〕；用到他的健康数据写成 <statement>这句话<cite>[r3]</cite></statement>。带数字的句子都要有出处，数字照资料、计算或数据写。

计划和训练记录（只在需要时写；只是问问、抱怨、闲聊、解释时不写，计划不动）：
{actions}

记忆（只在需要时写；系统核对后当场记下，下一轮就能用）：
- 他这句话说了关于他本人、以后回答要照顾到的情况（伤病和身体状况、器械和场地、可练时间、饮食、喜好、目标、回答风格、近期发生的事），在 JSON 里加上 "memory" 列表。只是提问、闲聊、别人的事、假设、否定的说法（"没有伤"）不记；档案和记忆里已经有的不重复记。
- 每条：{{"op": "add|update|resolve", "target": "已有记忆的编号（add 不写）", "category": "injury|equipment|schedule|diet|preference|goal|style|event", "content": "一句话，不超过 40 字，照原话保留部位、左右、重量、时间", "quote": "从他这句话里一字不差摘的一段", "inferred": false, "until": "event 要写：到哪天为止（YYYY-MM-DD，含这天）"}}
- inferred：内容是你根据他的话推测的、他没有直接说（比如从"膝盖响"推测是半月板的问题）写 true，系统会先放着等他确认；能不推测就不推测
- until 按今天的日期算："这周"写这周日，"这两天"写明天，"这几天"写 3 天后，"下周"写下周日，说了具体日子照写；实在看不出写 7 天后。例：今天 2026-10-28（周三），他说"这周出差" → {{"op": "add", "category": "event", "content": "这周出差", "quote": "这周出差", "until": "2026-11-01"}}
- 已有记忆的新情况用 update（content 写合并后的完整说法），好了、不再适用用 resolve；临时的变化（这周出差、这几天感冒）记成 event，不改长期的器械、时间和目标。

{slots}
打招呼、道谢、闲聊时只写 answer（一两句自然回应），其余几段留空，不报今天的计划、打卡和数据。{skills}

可以再装的规程目录：
{catalog}"""

_ASK_FIRST = (
    '- 用户明确要一份新计划（还没有计划、要重排），或长期条件变了（换了健身房、以后每周只能练两天）要重来：这一轮先不写计划，在 JSON 里加上 "action": "new_plan"，'
    '回答只写一句过渡（比如"好，先确认一下条件"），系统会列出目标、场景、器械、时间、伤病请他确认。'
)
_CONFIRMED = '- 用户要一份新计划：条件已经确认过了（见前几轮），按确认的条件写完整的 "plan"：'
_TEMPORARY = (
    "- 临时的变化（这周出差、生病、这几天忙、只能在酒店练）：记成近期事件，回答这几天怎么练；不排新计划。"
    "他要求改计划时，只改受影响的那几天。"
)
_JUST_ASKED = (
    "- 上一轮你列了排新计划要用的条件请他确认。他这句话是确认（如「按这个排」「可以」「你定」）或改了其中几项："
    '这一轮就按确认的条件写完整的 "plan"（计划写进 "plan"，不要只写在回答里）；他换了别的话题，就答他的话题，不写计划。'
)


def _body(task: str) -> str:
    """TASKS 里去掉开头那句"这一轮要……"，剩下的格式和要求。"""
    lines = TASKS[task].strip().splitlines()
    return "\n".join(lines[1:])


def actions_prompt(*, has_plan: bool, confirmed: bool, just_asked: bool = False) -> str:
    parts = [_JUST_ASKED] if just_asked else []
    if has_plan:
        parts.append("- 用户要改现有计划的某几处（换动作、挪天、改组次、减量）：\n" + _body("edit"))
    parts.append(_CONFIRMED + "\n" + _body("plan") if confirmed else _ASK_FIRST)
    parts.append(_TEMPORARY)
    parts.append("- 用户在报告自己这次练了什么：\n" + _body("log"))
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


def framework_for(domains: Sequence[Role], flags: Collection[str]) -> str:
    """全能的要点，加上这一轮涉及领域的思考顺序和判断规则（含这个人的少见情况）。"""
    parts = [FRAMEWORKS[Role.GENERAL]]
    for role in domains:
        parts.append(f"【{ {Role.TRAINER: '训练', Role.NUTRITION: '饮食', Role.RECOVERY: '恢复'}[role] }的判断规则】\n"
                     + domain_rules(role, flags))  # fmt: skip
    return "\n\n".join(parts)


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
) -> Consultation:
    """单 Agent 作答一轮。出错时返回不发言的意见，不向外抛（和专业角色一样）。"""
    flags = flags_of([x.key for x in case.risks], bool(case.injuries), case.readiness.level)
    domains = domains_of(skills)
    tools = "、".join(str(s["function"]["name"]) for s in toolbox.schemas()) or "（没有可用的工具）"
    system = _PROMPT.format(
        framework=framework_for(domains, flags),
        tools=tools,
        actions=actions_prompt(has_plan=has_plan, confirmed=confirmed, just_asked=just_asked),
        slots=slots_prompt(text, None),
        skills=prompt_of(skills),
        catalog=catalog_any(),
    )
    toolbox.adopt(e for x in skills for r in x.refs if (e := toolbox.kb.get(r)) is not None)
    for role in (Role.GENERAL, *domains):  # 判断规则里引用的资料，照抄时也要能通过核对
        toolbox.adopt(
            e for r in framework_refs(role, flags) if (e := toolbox.kb.get(r)) is not None
        )
    asked = _user_message(
        text,
        history,
        concerns,
        personal.text() if personal else "",
        memory_text(known, today or date.today())
        if known is not None
        else memory.shared()
        if memory is not None
        else "",
        case=case.text(calcs=True),
        note=note,
        prefetched=toolbox.prefetch(text),
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


def action_of(opinion: Opinion, *, has_plan: bool) -> str:
    """回答里给出的动作：edit（改现有计划）、new_plan（要新计划、先确认条件）、plan（写了完整的新计划）、
    log（记训练）、none。"""
    if opinion.ops and has_plan:
        return "edit"
    if opinion.plan:
        return "plan"
    if opinion.log:
        return "log"
    if opinion.action == NEW_PLAN:
        return NEW_PLAN
    return "none"
