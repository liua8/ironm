"""专业 Agent：先查依据，再回答。同一轮里各 Agent 互不可见。

被请到的 Agent 一定要从自己的专业角度回答这个问题：查到资料或用户数据的地方标出处，
查不到的凭专业经验回答并标〔经验〕。每句按 checks 逐句核对，不合格让模型改一次；
还不合格就 repair（对不上的个人数据句删掉，其余改标〔经验〕），不会因为查不到或核对不过而不说话。
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from ironm_agent.answer_format import assemble, is_slots
from ironm_agent.checks import EXPERIENCE, check_text, cited_ids, merge_echoes, repair, sentences
from ironm_agent.common import ContractModel
from ironm_agent.harness import problem_kinds
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.plan_ops import parse_ops
from ironm_agent.roles import Role, RoleSpec
from ironm_agent.tools import Evidence, Toolbox
from ironm_agent.training import parse_log, parse_plan

_log = logging.getLogger("ironm_agent.experts")

MAX_QUERIES = 3  # 每个 Agent 每轮最多查询几次
MAX_ROUNDS = 5  # 每个 Agent 每轮最多和模型往返几次（含查询）
_FIELDS = ("conclusion", "for_you", "how", "caution", "uncertain")
_SOLO_FIELDS = ("answer",)  # 只请到一位（或单 Agent 对照组）时，它直接写给用户的回答


class Opinion(ContractModel):
    role: Role
    speak: bool
    reason: str = ""  # 不发言的原因
    conclusion: str = ""
    for_you: str = ""
    how: str = ""
    caution: str = ""
    uncertain: str = ""
    answer: str = ""  # 直接给用户的回答（solo 模式），有它时就不再整合
    plan: dict[str, Any] | None = None  # 训练教练写的计划（要写计划的那一轮），系统校验后做成预览
    log: dict[str, Any] | None = None  # 训练教练整理的训练记录（要记训练的那一轮）
    ops: list[dict[str, Any]] | None = None  # 改计划时只写要改的地方（§45），由代码套到当前计划上
    basis: tuple[str, ...] = ()  # 意见里引用到的编号：K 开头为依据库条目，r 开头为健康数据行
    general: bool = False  # 没有资料依据，只给不带具体数字的一般建议
    action: str = (
        ""  # 单 Agent 说明要做的事（如 new_plan：要排新计划、先确认条件，spec [2026-10-23] §67）
    )
    memory: list[dict[str, Any]] | None = None  # 单 Agent 这一轮要记的（§68），由代码核对后写入

    def body(self) -> str:
        if self.answer:
            return self.answer
        return "\n".join(getattr(self, f) for f in _FIELDS if getattr(self, f))


@dataclass(frozen=True)
class Consultation:
    opinion: Opinion
    evidence: Evidence
    status: str  # spoke / silent / failed
    # 运行框架用的明细（spec [2026-10-23] §31）：往返轮数、核对问题类别、是否改写、是否被规则修正、
    # 是否用完查询次数、是否收走工具后才作答、〔经验〕占比、耗时；不含内容
    trace: dict[str, Any] = field(default_factory=dict)


_PROMPT = """你是健身 App 里的「{name}」，负责：{duty}。
{team}

{framework}

回答方式：
1. 先给结论，再用一句话说理由，再给做法；只答问的，没问到的不说。
2. 关于这个人的事实（状态、伤病、计划、记录、数据）只照档案、数据和他这句话说，不推测、不编造；档案里有和问题相关的数据时，结论用上一条。
3. 给具体的量（组次、克数、分钟），不说"适量、多注意、循序渐进"。
4. 你被请来就要回答：资料里没有就凭专业经验答；不诊断、不开药。
先看档案和系统查好的资料，不够再用工具查（{tools}），最多 3 次，拿到要的就作答。

出处（系统会逐句核对）：用到资料的句子句末写〔K03〕，用到档案或计算结果写〔C2〕，凭经验写〔经验〕；用到他的健康数据写成 <statement>这句话<cite>[r3]</cite></statement>。带数字的句子都要有出处，数字照资料、计算或数据写；按他的体重换算时资料编号和数据编号都写上。
{tail}"""


# 这一轮要写计划或整理训练记录时（spec [2026-10-23] §9），交给训练教练的额外要求；写在 JSON 里，由系统做成预览卡片
TASKS = {
    "plan": """

这一轮要写一份每周训练计划（新排，或者按用户的要求改档案里的当前计划）：
- 在 JSON 里加上 "plan"，写完整的新计划（改计划时没改的部分照抄当前计划，不是只写改动）：
  {"title": "计划名（不超过 12 个字）", "goal": "目标", "days_per_week": 每周几练, "sessions": [{"day": 1 到 7（1 是周一）, "name": "这一次练什么（如下肢）", "minutes": 大概多少分钟, "items": [{"exercise": "动作名", "sets": 组数, "reps": "次数（如 8–12）", "load": "重量或强度说明，可空", "note": "要点或限制，可空"}]}]}
- 每次最多 6 个动作，热身和放松不写成动作；load、note 各不超过 15 个字；
- 动作、组次、时长都要符合档案：他的器械、可练时间、伤病（有伤病的动作在 note 里写明限制或换掉）、今天的身体状态；
- 再加上 "changes"：一句话说清这份计划是怎么排的、改了什么（如"周三从上肢推改成练背，推的动作挪到周一"）；
- 给用户的文字只写一两句话：这份计划的思路和改了什么，不要把整份计划再写一遍（系统会把 plan 显示成预览卡片，用户确认后才保存）。""",
    "edit": """

这一轮要按用户的要求改档案里的当前计划。只写要改的地方，由系统套到当前计划上：
- 在 JSON 里加上 "ops"：操作列表，每条是下面六种之一（day 写 1 到 7，1 是周一；exercise 写当前计划里的动作名）：
  {"kind": "swap", "day": 哪天, "exercise": "原动作", "to": "换成的动作", "why": "原因"}
  {"kind": "move", "day": 哪天, "to_day": 挪到哪天, "why": "原因"}
  {"kind": "add", "day": 哪天, "exercise": "加的动作", "sets": 组数, "reps": "次数", "why": "原因"}
  {"kind": "edit", "day": 哪天, "exercise": "动作", "sets": 组数, "reps": "次数", "load": "重量说明", "why": "原因"}（只写要改的字段；改这天的时长写 {"kind": "edit", "day": 哪天, "minutes": 分钟}）
  {"kind": "remove", "day": 哪天, "exercise": "动作（删整天时不写）", "why": "原因"}
  {"kind": "reduce", "day": 哪天（整份计划都减时不写）, "ratio": 0.7 或 0.5, "why": "原因"}
- 要把某天改成练另一天正在练的内容（如周三练推、周五练拉，"周三改成练背"）：用 move 把这两天对调（{"kind": "move", "day": 3, "to_day": 5}），两类训练都保留、组数不变，这是首选；
- 要把某天改成练计划里没有的内容：用 swap 把那天的动作逐个换成要练的动作，原来那类动作要保留就用 add 加到别的训练日（一周里原来练到的胸、背、腿、臀、肩不能全丢掉）；删一个动作用 remove（写 exercise）；edit 只改组次、重量、时长，不能用来删动作或加动作；每条操作的 exercise 必须是那天现有的动作；
- swap 的 to、add 的 exercise 写你实际要换成的具体动作名（他没有杠铃就写哑铃版的动作名，不要照抄用户说的"杠铃深蹲"）；给用户的文字和操作说的要是同一个动作；
- 用户没提到的地方一律不动；换成的动作要符合他的器械和伤病，不合适时系统会换成替代动作；
- 用户的几条要求互相矛盾时（如删掉一天又改那天的动作），照原话把每条都写成操作，不要自己取舍，系统会请他说清楚；
- 用户要的是重新排一份、或者换分化方式（如全身改成上下肢）、用这六种说不清时，不写 ops，改写完整的 "plan"（格式见下）：
  {"title": "计划名（不超过 12 个字）", "goal": "目标", "days_per_week": 每周几练, "sessions": [{"day": 1 到 7, "name": "这一次练什么", "minutes": 大概多少分钟, "items": [{"exercise": "动作名", "sets": 组数, "reps": "次数", "load": "", "note": ""}]}]}
- 给用户的文字只写一两句话：改了什么、为什么（系统会把改动显示成预览卡片，用户确认后才保存）。""",
    "log": """

这一轮要把用户说的这次训练整理成一条记录：
- 在 JSON 里加上 "log"：{"day": "日期（默认今天，YYYY-MM-DD）", "session": "按计划练的是哪一次（档案里当前计划的那次的名字，没有就空）", "items": [{"exercise": "动作名", "sets": 组数或 null, "reps": "次数", "weight_kg": 重量（公斤）或 null, "done_sets": [{"reps": 这一组的次数, "weight_kg": 这一组的重量或 null}]（用户说了每组不同的重量或次数时才写，否则空列表）}], "done": 是否练完, "rpe": 感受（1–10，用户说了才写）或 null, "minutes": 时长或 null, "note": "备注（如“有点累”），可空"}；
- 记录里的数字只能来自用户这句话，用户没说的就写 null，不要猜；
- 给用户的文字只写一两句话：简单反馈这次训练（按档案和计划说下一次怎么练），不要把记录再写一遍（系统会显示成预览卡片，用户确认后才记下）。""",
}

_WRITE = """你是健身 App 里的「训练教练」。你刚才已经回答了用户，但没有按格式写出{what}。请照你的回答和这个人的档案，把{what}写成 JSON。{rules}

只输出 JSON。"""


async def write_task(
    llm: LLM, task: str, text: str, answer: str, case: str, current: str = ""
) -> dict[str, Any] | None:
    """训练教练回答了、却没写出合格的计划或记录时，单独请它补写一次（只要 JSON，不要文字）。"""
    what = "计划（plan）" if task == "plan" else "训练记录（log）"
    rules = TASKS.get(task, "").replace("给用户的文字只写一两句话", "不用写给用户的文字")
    parts = [f"用户的话：{text}", f"你的回答：{answer}", case]
    if current:
        parts.append(f"当前计划（JSON）：{current}")
    try:
        reply = await llm.chat(
            "expert",
            [
                {"role": "system", "content": _WRITE.format(what=what, rules=rules)},
                {"role": "user", "content": "\n\n".join(x for x in parts if x)},
            ],
            json_mode=True,
        )
    except ModelUnavailable:
        return None
    raw = parse_json(reply.content) or {}
    found = raw.get(task)
    if not isinstance(found, dict):
        return None
    if task == "plan" and isinstance(raw.get("changes"), str):
        found = {**found, "changes": raw["changes"]}
    return found


def _user_message(
    text: str,
    history: Sequence[str],
    concerns: Sequence[str],
    personal: str = "",
    memory: str = "",
    *,
    case: str = "",
    relay: str = "",
    note: str = "",
    prefetched: str = "",
) -> str:
    parts = [f"用户的问题：{text}"]
    for extra in (case, personal, memory, relay, note):
        if extra:
            parts.append(extra)
    if prefetched:
        parts.append("系统按问题先查好的资料（可以直接引用编号，不够再查）：\n" + prefetched)
    if history:
        parts.append(
            "这次对话前面的几轮（只用来理解这次问题里的指代，不要在回答里重提和这次问题无关的旧话题）：\n"
            + "\n".join(history)
        )
    if concerns:
        names = {"discomfort": "身体不适", "special": "特殊人群"}
        parts.append("注意：这句话涉及" + "、".join(names.get(c, c) for c in concerns))
    return "\n\n".join(parts)


def problems_of(
    opinion: Opinion,
    evidence: Evidence,
    text: str,
    task: str | None = None,
    today: date | None = None,
) -> list[str]:
    """意见不合格的地方：逐句核对出处与数字（与整合后的回答同一套规则）；要写计划或记录时，格式也要对。"""
    if not opinion.speak:
        return []
    if not opinion.body().strip():
        return ["意见是空的"]
    shape: list[str] = []
    if task == "plan":
        _, why = parse_plan(opinion.plan)
        shape = [why or ""] if opinion.plan is not None else ["这一轮要写出 plan（完整的每周计划）"]
    elif task == "edit":
        if opinion.ops is not None and parse_ops(opinion.ops) is not None:
            shape = []
        elif opinion.plan is not None:
            shape = [parse_plan(opinion.plan)[1] or ""]
        else:
            shape = ["这一轮要写出 ops（要改的地方），或者完整的 plan"]
    elif task == "log":
        _, why = parse_log(opinion.log, today or date.today())
        shape = [why or ""] if opinion.log is not None else ["这一轮要写出 log（这次训练的记录）"]
    return [x for x in shape if x] + check_text(
        opinion.body(),
        support=evidence.support,
        entries=evidence.entries,
        question=text,
        calcs=evidence.calcs,
    )


def _repaired(
    opinion: Opinion, evidence: Evidence, text: str, names: Sequence[str] = _FIELDS
) -> Opinion:
    """逐个字段 repair：对不上的个人数据句删掉，其余对不上出处的句子改标〔经验〕。"""
    fields = {
        f: repair(
            getattr(opinion, f),
            support=evidence.support,
            entries=evidence.entries,
            question=text,
            calcs=evidence.calcs,
        )
        for f in names
    }
    body = "\n".join(fields.values())
    if not body.strip():
        return opinion.model_copy(update={"speak": False, "reason": "没能给出意见"})
    return opinion.model_copy(update={**fields, "basis": tuple(cited_ids(body))})


def _salvage(content: str, fields: Sequence[str]) -> dict[str, Any] | None:
    """JSON 坏了（常见于计划太长被截断）时，尽量把文字字段取出来，计划和记录就不要了。"""
    out: dict[str, Any] = {}
    for k in fields:
        m = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
        if m:
            try:
                out[k] = json.loads(f'"{m.group(1)}"')
            except json.JSONDecodeError:
                continue
    return out or None


def _parse(
    role: Role,
    content: str,
    fields: Sequence[str] = _FIELDS,
    question: str = "",
    task: str | None = None,
) -> Opinion | None:
    raw = parse_json(content) or _salvage(content, fields)
    if raw is None:
        return None
    if fields == _SOLO_FIELDS and is_slots(
        raw
    ):  # 按分段写的：由代码拼成正文、按问题类型限长（§38）
        raw = {**raw, "answer": assemble(raw, question, task)}
    data: dict[str, Any] = {k: raw.get(k) for k in ("general", *fields) if k in raw}
    for k in ("plan", "log"):
        if isinstance(raw.get(k), dict):
            data[k] = raw[k]
    if isinstance(raw.get("ops"), list):
        data["ops"] = [x for x in raw["ops"] if isinstance(x, dict)]
    if isinstance(raw.get("action"), str):
        data["action"] = raw["action"].strip()[:20]
    if isinstance(raw.get("memory"), list):
        data["memory"] = [x for x in raw["memory"] if isinstance(x, dict)]
    if isinstance(data.get("plan"), dict) and isinstance(raw.get("changes"), str):
        data["plan"] = {**data["plan"], "changes": raw["changes"]}  # 改了什么，跟着计划走
    data["speak"] = True  # 被请到就要回答，模型说"不发言"也不算
    for k in fields:
        if k in data and not isinstance(data[k], str):
            data[k] = "" if data[k] is None else str(data[k])
    body = "\n".join(str(data.get(k) or "") for k in fields)
    data["basis"] = tuple(cited_ids(body))
    try:
        return Opinion.model_validate({"role": role, **data}, strict=False)
    except ValidationError:
        return None


def experience_share(text: str) -> float:
    """标〔经验〕的句子占比（运行框架用：过半说明知识库缺这块）。"""
    all_ = sentences(text)
    return round(sum(EXPERIENCE in x for x in all_) / len(all_), 2) if all_ else 0.0


async def _loop(
    spec: RoleSpec,
    messages: list[dict[str, Any]],
    toolbox: Toolbox,
    llm: LLM,
    text: str,
    fields: Sequence[str] = _FIELDS,
    task: str | None = None,
    today: date | None = None,
    trace: dict[str, Any] | None = None,
    *,
    question: str = "",
) -> Opinion:
    trace = trace if trace is not None else {}
    fixes = 0
    rounds = 0
    memo: list[dict[str, Any]] | None = None  # 第一次写的记忆：改写时模型常常漏掉，沿用
    # 改计划只写操作：动作合不合适由代码校验，不用再查（§45，一次改计划最多调用 2 次模型）
    tools = None if task == "edit" else (toolbox.schemas() or None)
    while True:
        rounds += 1
        trace["rounds"] = rounds
        reply = await llm.chat("expert", messages, tools=tools, json_mode=tools is None)
        if reply.tool_calls:
            if rounds > MAX_ROUNDS + 1:  # 已经不给工具了还要查：放弃，不无限循环
                return Opinion(role=spec.role, speak=False, reason="一直在查询，没能给出意见")
            if rounds > MAX_ROUNDS:
                trace["forced"] = True
                messages.append(reply.as_message())
                for call in reply.tool_calls:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": "不要再查了，直接按 JSON 回答。",
                        }
                    )
                tools = None  # 不再提供工具，逼它作答
                continue
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                if toolbox.evidence.queries >= MAX_QUERIES:
                    trace["exhausted"] = True
                    result = "查询次数已用完。请根据已有依据作答，直接输出 JSON。"
                else:
                    result = await toolbox.run(call)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue
        opinion = _parse(spec.role, reply.content, fields, question, task)
        if opinion is not None:  # 同一件事写了两遍（普通句子 + 带编号的标记）：先合并再核对
            opinion = opinion.model_copy(
                update={f: merge_echoes(getattr(opinion, f)) for f in _FIELDS + _SOLO_FIELDS}
            )
            memo = opinion.memory if opinion.memory is not None else memo
            opinion = opinion.model_copy(update={"memory": memo})
        problems = (
            ["输出不是规定格式的 JSON"]
            if opinion is None
            else problems_of(opinion, toolbox.evidence, text, task, today)
        )
        if not problems and opinion is not None:
            return opinion
        if fixes == 0:
            trace["checks"] = problem_kinds(problems)  # 只留类别，问题原文里可能有回答片段
            trace["fixed"] = True
        if fixes >= 1:
            if opinion is None:
                return Opinion(role=spec.role, speak=False, reason="没能给出规定格式的意见")
            trace["repaired"] = True
            _log.info(
                "expert opinion repaired: role=%s problems=%d", spec.role.value, len(problems)
            )
            return _repaired(opinion, toolbox.evidence, text, fields)
        fixes += 1
        messages.append({"role": "assistant", "content": reply.content})
        messages.append(
            {
                "role": "user",
                "content": "你的意见有问题，请改正后只输出 JSON："
                + json.dumps(problems, ensure_ascii=False),
            }
        )
