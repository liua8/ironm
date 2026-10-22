"""专业 Agent：先查依据，再回答。同一轮里各 Agent 互不可见。

被请到的 Agent 一定要从自己的专业角度回答这个问题：查到资料或用户数据的地方标出处，
查不到的凭专业经验回答并标〔经验〕。每句按 checks 逐句核对，不合格让模型改一次；
还不合格就 repair（对不上的个人数据句删掉，其余改标〔经验〕），不会因为查不到或核对不过而不说话。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ironm_agent.checks import check_text, cited_ids, repair
from ironm_agent.common import ContractModel
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.personal import Personal
from ironm_agent.roles import Role, RoleSpec
from ironm_agent.tools import Evidence, Toolbox

_log = logging.getLogger("ironm_agent.experts")

MAX_QUERIES = 3  # 每个 Agent 每轮最多查询几次
MAX_ROUNDS = 5  # 每个 Agent 每轮最多和模型往返几次（含查询）
_FIELDS = ("conclusion", "for_you", "how", "caution", "uncertain")


class Opinion(ContractModel):
    role: Role
    speak: bool
    reason: str = ""  # 不发言的原因
    conclusion: str = ""
    for_you: str = ""
    how: str = ""
    caution: str = ""
    uncertain: str = ""
    basis: tuple[str, ...] = ()  # 意见里引用到的编号：K 开头为依据库条目，r 开头为健康数据行
    general: bool = False  # 没有资料依据，只给不带具体数字的一般建议

    def body(self) -> str:
        return "\n".join(getattr(self, f) for f in _FIELDS if getattr(self, f))


@dataclass(frozen=True)
class Consultation:
    opinion: Opinion
    evidence: Evidence
    status: str  # spoke / silent / failed


_PROMPT = """你是健身 App 里的「{name}」，负责：{duty}。
你和其他专业角色同时回答同一个问题，看不到彼此的意见，最后由主教练整合。

做法：
1. 先用工具查依据：{tools}。可以连续查询，最多 3 次。问到 BMI、基础代谢、每天吃多少热量或蛋白质、体重变化、心率和自己基线比怎么样这类问题，先用 compute_metrics。
2. 根据查到的依据作答，每句话写的时候就标好出处：
   - 用到资料的句子，在这一句的句末写〔K03〕（K 编号是查到的资料编号，写这一句的内容真正出自的那份）；
   - 用到指标计算结果（compute_metrics 返回的 C 编号，如 BMI、热量目标）的句子，在这一句的句末写〔C2〕，数字照计算结果写；
   - 用到用户健康数据的句子，写成 <statement>这句话<cite>[r3]</cite></statement>，[ ] 里是这句话用到的数据行编号（r 开头）。
   例：<statement>你近 30 天的静息心率平均 58 次/分<cite>[r3]</cite></statement>，在成年人正常范围的偏低一端〔K20〕。
   - 查不到资料、凭你的专业经验说的句子，在句末写〔经验〕。
3. 你被请来就一定要回答这个问题，从你的专业角度给出实用的建议：依据库里有的就用依据库，没有的就用你的专业知识，不能因为查不到就不回答，也不要说"依据库里没有"这类话。
4. 数字的规矩：标〔K〕〔C〕或数据句里的数字，必须来自那份资料、那个计算结果或那行数据；凭经验给的数字写在标〔经验〕的句子里；不要编造用户的个人数据。
5. 查健康数据时：没有记录就如实说"没有找到记录"，不能推测为正常；不同设备的心率变异性（SDNN 与 RMSSD）是不同指标，不要放在一起比较。
6. 不诊断、不开药。涉及疼痛或不适时，写明出现什么情况要停止并就医。
7. 直接回答用户问的那件事，不说空话套话。只用真正改变建议的个人数据和计算结果（比如按体重算剂量）；问跑前吃什么就别列 BMI，问膝盖疼就别提体重；不要把查到的指标都罗列出来。for_you 只写能让建议更具体的个人信息（比如按这个人的体重算出的量），没有就留空；不要罗列"你的记录里没有什么"，除非用户问的就是这个数据。
8. 用到这个人的体重等数据换算时（例如按 0.3 克/公斤算剂量），把这句话写成 <statement>按你 69.2 公斤算，每天约 21 克〔K10〕<cite>[r3]</cite></statement>，资料编号和数据编号都写上。
9. 用中文，口语化，专业、精炼：每个字段不超过 80 字，只写最关键的一两点，不铺垫、不罗列所有可能。

最后只输出 JSON：
{{"conclusion": "一两句结论", "for_you": "结合这个人的情况（没有可留空）", "how": "具体怎么做", "caution": "注意事项（与这件事相关的风险、什么情况要停止或就医；没有可留空）", "uncertain": "不确定的地方（可留空）"}}"""


def _tool_hint(toolbox: Toolbox) -> str:
    hints = []
    if toolbox.spec.kb_domains:
        hints.append("search_knowledge 查本领域的依据库")
    if toolbox.health is not None:
        hints.append("query_health_indicators 查这个人的健康数据")
    if toolbox.metrics is not None:
        hints.append("compute_metrics 计算这个人的指标（BMI、热量与蛋白质目标、体重趋势等）")
    return "；".join(hints) or "（没有可用的工具）"


def _user_message(
    text: str, history: Sequence[str], concerns: Sequence[str], personal: str = ""
) -> str:
    parts = [f"用户的问题：{text}"]
    if personal:
        parts.append(personal)
    if history:
        parts.append(
            "用户前几句说过的话（只用来理解这次问题里的指代，不要在回答里重提和这次问题无关的旧话题）：\n"
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
    """逐个字段 repair：对不上的个人数据句删掉，其余对不上出处的句子改标〔经验〕。"""
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


def _parse(role: Role, content: str) -> Opinion | None:
    raw = parse_json(content)
    if raw is None:
        return None
    data: dict[str, Any] = {k: raw.get(k) for k in ("general", *_FIELDS) if k in raw}
    data["speak"] = True  # 被请到就要回答，模型说"不发言"也不算
    for k in _FIELDS:
        if k in data and not isinstance(data[k], str):
            data[k] = "" if data[k] is None else str(data[k])
    body = "\n".join(str(data.get(k) or "") for k in _FIELDS)
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
) -> Consultation:
    """请一个专业 Agent 作答。出错时返回不发言的意见，不向外抛。"""
    system = _PROMPT.format(name=spec.name, duty=spec.duty, tools=_tool_hint(toolbox))
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": _user_message(text, history, concerns, personal.text() if personal else ""),
        },
    ]
    if personal is not None:
        toolbox.evidence.support.update(personal.support)
        toolbox.evidence.rows.update(personal.rows)
    try:
        opinion = await _loop(spec, messages, toolbox, llm, text)
    except ModelUnavailable as e:
        _log.warning("expert unavailable: role=%s reason=%s", spec.role.value, e)
        silent = Opinion(role=spec.role, speak=False, reason="这次没能调用模型")
        return Consultation(silent, toolbox.evidence, "failed")
    status = "spoke" if opinion.speak else "silent"
    return Consultation(opinion, toolbox.evidence, status)


async def _loop(
    spec: RoleSpec, messages: list[dict[str, Any]], toolbox: Toolbox, llm: LLM, text: str
) -> Opinion:
    fixes = 0
    rounds = 0
    tools = toolbox.schemas() or None
    while True:
        rounds += 1
        reply = await llm.chat("expert", messages, tools=tools, json_mode=tools is None)
        if reply.tool_calls:
            if rounds > MAX_ROUNDS + 1:  # 已经不给工具了还要查：放弃，不无限循环
                return Opinion(role=spec.role, speak=False, reason="一直在查询，没能给出意见")
            if rounds > MAX_ROUNDS:
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
                    result = "查询次数已用完。请根据已有依据作答，直接输出 JSON。"
                else:
                    result = await toolbox.run(call)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            continue
        opinion = _parse(spec.role, reply.content)
        problems = (
            ["输出不是规定格式的 JSON"]
            if opinion is None
            else problems_of(opinion, toolbox.evidence, text)
        )
        if not problems and opinion is not None:
            return opinion
        if fixes >= 1:
            if opinion is None:
                return Opinion(role=spec.role, speak=False, reason="没能给出规定格式的意见")
            _log.info(
                "expert opinion repaired: role=%s problems=%d", spec.role.value, len(problems)
            )
            return _repaired(opinion, toolbox.evidence, text)
        fixes += 1
        messages.append({"role": "assistant", "content": reply.content})
        messages.append(
            {
                "role": "user",
                "content": "你的意见有问题，请改正后只输出 JSON："
                + json.dumps(problems, ensure_ascii=False),
            }
        )
