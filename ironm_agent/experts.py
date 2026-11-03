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

from ironm_agent.actions import ALWAYS, Desk
from ironm_agent.answer_format import assemble, is_slots
from ironm_agent.checks import EXPERIENCE, check_text, cited_ids, merge_echoes, repair, sentences
from ironm_agent.common import ContractModel
from ironm_agent.harness import problem_kinds
from ironm_agent.llm import LLM, parse_json
from ironm_agent.roles import Role, RoleSpec
from ironm_agent.tools import Evidence, Toolbox

_log = logging.getLogger("ironm_agent.experts")

MAX_QUERIES = 3  # 每个 Agent 每轮最多查询几次
MAX_ROUNDS = 5  # 每个 Agent 每轮最多和模型往返几次（含查询）
_FIELDS = ("answer",)  # 管家直接写给用户的回答（单 Agent，§68 起只有这一项）


class Opinion(ContractModel):
    role: Role
    speak: bool
    reason: str = ""  # 不发言的原因
    answer: str = ""  # 直接给用户的回答
    # 改计划、新计划、记训练不再写在这里，由管家调用动作工具交给系统（§120）
    basis: tuple[str, ...] = ()  # 意见里引用到的编号：K 开头为依据库条目，r 开头为健康数据行
    general: bool = False  # 没有资料依据，只给不带具体数字的一般建议

    def body(self) -> str:
        return self.answer


@dataclass(frozen=True)
class Consultation:
    opinion: Opinion
    evidence: Evidence
    status: str  # spoke / silent / failed
    # 运行框架用的明细（spec [2026-10-23] §31）：往返轮数、核对问题类别、是否改写、是否被规则修正、
    # 是否用完查询次数、是否收走工具后才作答、〔经验〕占比、耗时；不含内容
    trace: dict[str, Any] = field(default_factory=dict)


def _user_message(
    text: str,
    history: Sequence[str],
    concerns: Sequence[str],
    personal: str = "",
    memory: str = "",
    *,
    case: str = "",
    note: str = "",
    prefetched: str = "",
) -> str:
    parts = [f"用户的问题：{text}"]
    for extra in (case, personal, memory, note):
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


def problems_of(opinion: Opinion, evidence: Evidence, text: str) -> list[str]:
    """意见不合格的地方：逐句核对出处与数字（与整合后的回答同一套规则）。"""
    if not opinion.speak:
        return []
    if not opinion.body().strip():
        return ["意见是空的"]
    return check_text(
        opinion.body(),
        support=evidence.support,
        entries=evidence.entries,
        question=text,
        calcs=evidence.calcs,
    )


def _repaired(opinion: Opinion, evidence: Evidence, text: str) -> Opinion:
    """repair 回答：对不上的个人数据句删掉，其余对不上出处的句子改标〔经验〕。"""
    fields = {
        f: repair(
            getattr(opinion, f),
            support=evidence.support,
            entries=evidence.entries,
            question=text,
            calcs=evidence.calcs,
        )
        for f in _FIELDS
    }
    body = "\n".join(fields.values())
    if not body.strip():
        return opinion.model_copy(update={"speak": False, "reason": "没能给出意见"})
    return opinion.model_copy(update={**fields, "basis": tuple(cited_ids(body))})


def _salvage(content: str, fields: Sequence[str]) -> dict[str, Any] | None:
    """JSON 坏了时，尽量把文字字段取出来。"""
    out: dict[str, Any] = {}
    for k in fields:
        m = re.search(rf'"{k}"\s*:\s*"((?:[^"\\]|\\.)*)"', content)
        if m:
            try:
                out[k] = json.loads(f'"{m.group(1)}"')
            except json.JSONDecodeError:
                continue
    return out or None


def _parse(role: Role, content: str, question: str = "") -> Opinion | None:
    fields = _FIELDS
    raw = parse_json(content) or _salvage(content, fields)
    if raw is None:
        return None
    if is_slots(raw):  # 按分段写的：由代码拼成正文、按问题类型限长（§38）
        raw = {**raw, "answer": assemble(raw, question)}
    data: dict[str, Any] = {k: raw.get(k) for k in ("general", *fields) if k in raw}
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


def _settled(opinion: Opinion, desk: Desk | None, trace: dict[str, Any]) -> Opinion:
    """提醒过还是说了改却没改：去掉说已经改了、记下了的那几句（§120）。"""
    if desk is None or not opinion.speak or not opinion.answer:
        return opinion
    answer = desk.settle(opinion.answer)
    if desk.unacted:
        trace["unacted"] = True
    return opinion.model_copy(update={"answer": answer}) if answer != opinion.answer else opinion


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
    today: date | None = None,
    trace: dict[str, Any] | None = None,
    *,
    question: str = "",
) -> Opinion:
    trace = trace if trace is not None else {}
    fixes = 0
    rounds = 0
    desk = toolbox.actions
    offered = bool(toolbox.schemas())  # 有工具才提供；装了规程会多出动作工具，所以每轮重新取
    only_actions = False  # 往返到上限后：不再查，只留动作工具，查好的计划、记录还能交上来
    while True:
        rounds += 1
        trace["rounds"] = rounds
        offer = desk.schemas() if only_actions and desk is not None else toolbox.schemas()
        tools = (offer or None) if offered else None
        reply = await llm.chat("expert", messages, tools=tools, json_mode=tools is None)
        # 装了动作类规程的那一轮多给两次往返：交了被退回还能改了再交（§120）
        limit = MAX_ROUNDS + 2 if desk is not None and desk.unlocked - set(ALWAYS) else MAX_ROUNDS
        if reply.tool_calls:
            if rounds > limit + 3:  # 已经不给工具了还要查：放弃，不无限循环
                return Opinion(role=spec.role, speak=False, reason="一直在查询，没能给出意见")
            if rounds > limit:
                trace["forced"] = True
                messages.append(reply.as_message())
                # 排计划要查好几样：到上限时查好的还没交（真实模型回放 11-03），再给两轮只交不查
                grace = desk is not None and rounds <= limit + 2 and bool(desk.schemas())
                for call in reply.tool_calls:
                    if grace and toolbox.is_action(call.name):
                        result = await toolbox.run(call)
                    else:
                        result = ("不要再查了：要交的计划、记录现在用动作工具交，然后按 JSON 回答。" if grace
                                  else "不要再查了，直接按 JSON 回答。")  # fmt: skip
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
                only_actions = grace and rounds < limit + 2
                offered = only_actions  # 只留动作工具；再往后不提供工具，逼它作答
                continue
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                if toolbox.evidence.queries >= MAX_QUERIES and not toolbox.is_action(call.name):
                    trace["exhausted"] = True
                    result = "查询次数已用完。请根据已有依据作答，直接输出 JSON。"
                else:
                    result = await toolbox.run(call)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue
        opinion = _parse(spec.role, reply.content, question)
        if opinion is not None:  # 同一件事写了两遍（普通句子 + 带编号的标记）：先合并再核对
            opinion = opinion.model_copy(
                update={f: merge_echoes(getattr(opinion, f)) for f in _FIELDS}
            )
        if opinion is not None and desk is not None and rounds < limit:  # 提醒后还要留一轮能调工具
            # 刚确认了条件却没交计划、说了改却没改：提醒一次，让它调用工具或改口（§120）
            nudge = desk.followup(opinion.body())
            if nudge is not None:
                trace["nudged"] = True
                offered = bool(toolbox.schemas())
                messages.append({"role": "assistant", "content": reply.content})
                messages.append({"role": "user", "content": nudge})
                continue
        problems = (
            ["输出不是规定格式的 JSON"]
            if opinion is None
            else problems_of(opinion, toolbox.evidence, text)
        )
        if not problems and opinion is not None:
            return _settled(opinion, desk, trace)
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
            return _settled(_repaired(opinion, toolbox.evidence, text), desk, trace)
        fixes += 1
        messages.append({"role": "assistant", "content": reply.content})
        messages.append(
            {
                "role": "user",
                "content": "（系统核对，不是用户说的；用户看不到你上一版和这条。直接改正，回答里不提格式、不道歉）"
                "这些地方要改，改正后只输出 JSON：" + json.dumps(problems, ensure_ascii=False),
            }
        )
