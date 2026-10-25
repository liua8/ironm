"""专业 Agent：先查依据，再回答。同一轮里各 Agent 互不可见。

被请到的 Agent 一定要从自己的专业角度回答这个问题：查到资料或用户数据的地方标出处，
查不到的凭专业经验回答并标〔经验〕。每句按 checks 逐句核对，不合格让模型改一次；
还不合格就 repair（对不上的个人数据句删掉，其余改标〔经验〕），不会因为查不到或核对不过而不说话。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import ValidationError

from ironm_agent.casefile import CaseFile
from ironm_agent.checks import EXPERIENCE, check_text, cited_ids, repair, sentences
from ironm_agent.common import ContractModel
from ironm_agent.frameworks import framework, framework_refs
from ironm_agent.harness import problem_kinds
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.memory_view import Recall
from ironm_agent.personal import Personal
from ironm_agent.protools import registry as pro
from ironm_agent.roles import Role, RoleSpec
from ironm_agent.skills import Skill, prompt_of
from ironm_agent.tools import METRIC_ROLES, Evidence, Toolbox
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
    basis: tuple[str, ...] = ()  # 意见里引用到的编号：K 开头为依据库条目，r 开头为健康数据行
    general: bool = False  # 没有资料依据，只给不带具体数字的一般建议

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

做法：
1. 先看这个人的档案和系统已经查好的资料；不够再用工具查：{tools}。可以连续查询，最多 3 次。问到 BMI、基础代谢、每天吃多少热量或蛋白质、体重变化、心率和自己基线比怎么样这类问题，直接用档案里的指标计算结果（没有档案时用 compute_metrics）。
2. 根据依据作答，每句话写的时候就标好出处：
   - 用到资料的句子，在这一句的句末写〔K03〕（K 编号是资料编号，写这一句的内容真正出自的那份）；
   - 用到档案或指标计算结果（C 编号，如 BMI、热量目标、今天的身体状态）的句子，在这一句的句末写〔C2〕，数字照档案写；
   - 用到用户健康数据的句子，写成 <statement>这句话<cite>[r3]</cite></statement>，[ ] 里是这句话用到的数据行编号（r 开头）。
   例：<statement>你近 30 天的静息心率平均 58 次/分<cite>[r3]</cite></statement>，在成年人正常范围的偏低一端〔K20〕。
   - 查不到资料、凭你的专业经验说的句子，在句末写〔经验〕。
3. 你被请来就一定要回答这个问题，从你的专业角度给出实用的建议：依据库里有的就用依据库，没有的就用你的专业知识，不能因为查不到就不回答，也不要说"依据库里没有"这类话。
4. 数字的规矩：标〔K〕〔C〕或数据句里的数字，必须来自那份资料、那个计算结果或那行数据；凭经验给的数字写在标〔经验〕的句子里；不要编造用户的个人数据。
5. 查健康数据时：没有记录就如实说"没有找到记录"，不能推测为正常；不同设备的心率变异性（SDNN 与 RMSSD）是不同指标，不要放在一起比较。
6. 不诊断、不开药。涉及疼痛或不适时，写明出现什么情况要停止并就医。
7. 专业的回答方式：
   - 先给结论，再用一句话说理由（用到他的情况或依据），再给做法；
   - 关于这个人的事实（今天的状态、伤病、计划、训练记录、数据）只照档案、数据和他这句话说，不推测、不改写：档案写"状态好"就不能说"状态差"；档案里没有的计划、组次、伤病不能说有；他这句话说的情况以这句话为准；
   - 给具体能执行的量（组数次数、克数、分钟），不用"适量""多注意""循序渐进"这类空话；
   - 信息不够时按最常见的情况答，并说明按什么情况答的；拿不准的地方说出来，不装作确定。
8. 直接回答用户问的那件事，不说空话套话。只用真正改变建议的个人数据和计算结果（比如按体重算剂量）；问跑前吃什么就别列 BMI，问膝盖疼就别提体重；不要把查到的指标都罗列出来。for_you 只写能让建议更具体的个人信息（比如按这个人的体重算出的量），没有就留空；不要罗列"你的记录里没有什么"，除非用户问的就是这个数据。
9. 用到这个人的体重等数据换算时（例如按 0.3 克/公斤算剂量），把这句话写成 <statement>按你 69.2 公斤算，每天约 21 克〔K10〕<cite>[r3]</cite></statement>，资料编号和数据编号都写上。
{tail}"""

_OPINION_TAIL = """10. 用中文，口语化，专业、精炼：每个字段不超过 80 字，只写最关键的一两点，不铺垫、不罗列所有可能。

最后只输出 JSON：
{"conclusion": "一两句结论", "for_you": "结合这个人的情况（没有可留空）", "how": "具体怎么做", "caution": "注意事项（与这件事相关的风险、什么情况要停止或就医；没有可留空）", "uncertain": "不确定的地方（可留空）"}"""

# 只请到一位时（或单 Agent 对照组），由它直接写给用户的回答，不再整合（spec [2026-10-23] §7）
_SOLO_TAIL = """10. 你是这次唯一作答的角色，直接写给用户的回答：第一句直接回答用户问的那件事，接着只给最关键的做法；没问到的事（比如问 BMI 时的饮食建议）不要加。简单问题不超过 150 字；需要分步骤的不超过 300 字、最多 5 个要点。同一个意思只说一次，不铺垫、不罗列所有可能，不用小标题。风险提醒只留和这件事最相关的一条，放在最后。出处标记照上面的规矩写在句末（系统展示时会去掉，并把来源放进可展开的"依据与来源"，所以不用在正文里解释出处）。用中文，口语化，像一位专业又亲切的教练。

最后只输出 JSON：{"answer": "给用户的回答"}"""


def _tool_hint(toolbox: Toolbox) -> str:
    hints = []
    if toolbox.spec.kb_domains:
        hints.append("search_knowledge 查本领域的依据库")
    if toolbox.health is not None:
        hints.append("query_health_indicators 查这个人的健康数据")
    if toolbox.metrics is not None:
        hints.append("compute_metrics 计算这个人的指标（BMI、热量与蛋白质目标、体重趋势等）")
    if toolbox.context is not None:
        names = [t.name for t in pro.tools_for(toolbox.spec.role.value)]
        if names:
            hints.append("专业工具 " + "、".join(names) + "（结果带 C 编号，用法见上面的思考顺序）")
    return "；".join(hints) or "（没有可用的工具）"


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


_ALONE = "你和其他专业角色同时回答同一个问题，看不到彼此的意见，最后由管家整合。"
_RELAYED = "你在前面同事给出结论之后作答：你的建议要和他们的结论一致（冲突时以安全和恢复为准），不用重复他们说过的。"
_SOLO = "这一轮只请了你一位，你写的就是给用户的回答。"


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


def _parse(role: Role, content: str, fields: Sequence[str] = _FIELDS) -> Opinion | None:
    raw = parse_json(content) or _salvage(content, fields)
    if raw is None:
        return None
    data: dict[str, Any] = {k: raw.get(k) for k in ("general", *fields) if k in raw}
    for k in ("plan", "log"):
        if isinstance(raw.get(k), dict):
            data[k] = raw[k]
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


async def consult(
    spec: RoleSpec,
    text: str,
    history: Sequence[str],
    concerns: Sequence[str],
    toolbox: Toolbox,
    llm: LLM,
    personal: Personal | None = None,
    memory: Recall | None = None,
    *,
    solo: bool = False,
    case: CaseFile | None = None,
    relay: str = "",
    note: str = "",
    task: str | None = None,
    today: date | None = None,
    skills: Sequence[Skill] = (),
    images: Sequence[Mapping[str, Any]] = (),
) -> Consultation:
    """请一个专业 Agent 作答。出错时返回不发言的意见，不向外抛。

    memory：这个人的长期记忆；有共享档案（case）时，伤病、器械等限制已经在档案里，这里只给喜好、
    回答风格和给过的建议，没有档案时给这个角色该看的那几类。记忆里用户自己说过的数字（如哑铃 20 公斤）
    和这次问题里的数字一样，作答时可以直接用。
    solo：这一轮只请到它一位，由它直接写给用户的回答（不再整合）。
    relay：前一层同事的结论（分层接力）；note：系统交代的话（如按默认值排）。
    task：这一轮要写计划（plan）或整理训练记录（log），只交给训练教练；写出的计划或记录由系统校验后做成预览。
    images：用户这一轮附的图片（给模型看的图片段），只交给主责角色。
    """
    team = _SOLO if solo else (_RELAYED if relay else _ALONE)
    system = _PROMPT.format(
        name=spec.name,
        duty=spec.duty,
        team=team,
        framework=framework(spec.role),
        tools=_tool_hint(toolbox),
        tail=(_SOLO_TAIL if solo else _OPINION_TAIL)
        + TASKS.get(task or "", "")
        + prompt_of(skills),
    )
    toolbox.adopt(e for x in skills for r in x.refs if (e := toolbox.kb.get(r)) is not None)
    # 提示词里的判断规则引用到的资料，回答照抄时也要能通过核对（spec [2026-10-23] §15）
    toolbox.adopt(e for r in framework_refs(spec.role) if (e := toolbox.kb.get(r)) is not None)
    if memory is None:
        remembered = ""
    else:
        remembered = memory.shared() if case is not None else memory.for_role(spec.role)
    calcs = spec.role.value in METRIC_ROLES
    asked = _user_message(
        text,
        history,
        concerns,
        personal.text() if personal else "",
        remembered,
        case=case.text(calcs=calcs) if case is not None else "",
        relay=relay,
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
                             "exhausted": False, "forced": False}  # fmt: skip
    start = time.perf_counter()
    try:
        fields = _SOLO_FIELDS if solo else _FIELDS
        opinion = await _loop(spec, messages, toolbox, llm, said, fields, task, today, trace)
    except ModelUnavailable as e:
        _log.warning("expert unavailable: role=%s reason=%s", spec.role.value, e)
        silent = Opinion(role=spec.role, speak=False, reason="这次没能调用模型")
        trace["ms"] = int((time.perf_counter() - start) * 1000)
        return Consultation(silent, toolbox.evidence, "failed", trace)
    trace["ms"] = int((time.perf_counter() - start) * 1000)
    trace["experience"] = experience_share(opinion.body()) if opinion.speak else 0.0
    status = "spoke" if opinion.speak else "silent"
    return Consultation(opinion, toolbox.evidence, status, trace)


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
) -> Opinion:
    trace = trace if trace is not None else {}
    fixes = 0
    rounds = 0
    tools = toolbox.schemas() or None
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
        opinion = _parse(spec.role, reply.content, fields)
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
