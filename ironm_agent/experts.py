"""专业 Agent：先查依据，再写意见。同一轮里各 Agent 互不可见。

意见里每句话在写的时候就标好出处（资料〔K03〕、数据 <statement>…<cite>[r3]</cite></statement>），
按 checks.check_text 逐句核对；不合格时让模型改一次，仍不合格则这个 Agent 不发言。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from ironm_agent.checks import check_text, cited_ids
from ironm_agent.common import ContractModel
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
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
1. 先用工具查依据：{tools}。可以连续查询，最多 3 次。
2. 根据查到的依据作答，每句话写的时候就标好出处：
   - 用到资料的句子，在这一句的句末写〔K03〕（K 编号是查到的资料编号，写这一句的内容真正出自的那份）；
   - 用到用户健康数据的句子，写成 <statement>这句话<cite>[r3]</cite></statement>，[ ] 里是这句话用到的数据行编号（r 开头）。
   例：<statement>你近 30 天的静息心率平均 58 次/分<cite>[r3]</cite></statement>，在成年人正常范围的偏低一端〔K20〕。
3. 回答里的数字（次数、组数、克数、分钟、心率、步数等）只能出现在标了出处的句子里，并且来自那份资料或那行数据；用户自己说的数字可以直接用。依据里没有的数字一律不写。不要提到你没有查到的用户数据。
4. 依据答不了这个问题时，speak 写 false，reason 写原因；依据不全时，可以给不带具体数字的一般建议，并把 general 写 true。
5. 查健康数据时：没有记录就如实说"没有找到记录"，不能推测为正常；不同设备的心率变异性（SDNN 与 RMSSD）是不同指标，不要放在一起比较。
6. 不诊断、不开药。涉及疼痛或不适时，写明出现什么情况要停止并就医。
7. 用中文，口语化，专业、简洁。{extra}

最后只输出 JSON：
{{"speak": true, "reason": "", "conclusion": "一两句结论", "for_you": "结合这个人的情况（没有可留空）", "how": "具体怎么做", "caution": "注意事项", "uncertain": "不确定的地方（可留空）", "general": false}}"""

_SAFETY_EXTRA = "\n你是安全官：只负责风险和界限。conclusion 用一句话说这件事最主要的风险，caution 写清楚注意什么、出现什么情况要停止并就医；不给训练或饮食方案，不评论用户的数据（你看不到），也不要说依据库里查到或没查到什么。这句话没有值得特别提醒的风险时，speak 写 false。"


def _tool_hint(toolbox: Toolbox) -> str:
    hints = []
    if toolbox.spec.kb_domains:
        hints.append("search_knowledge 查本领域的依据库")
    if toolbox.health is not None:
        hints.append("query_health_indicators 查这个人的健康数据")
    return "；".join(hints) or "（没有可用的工具）"


def _user_message(text: str, history: Sequence[str], concerns: Sequence[str]) -> str:
    parts = [f"用户的问题：{text}"]
    if history:
        parts.append("最近的对话（用于理解指代）：\n" + "\n".join(history[-6:]))
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
        opinion.body(), support=evidence.support, entries=evidence.entries, question=text
    )


def _parse(role: Role, content: str) -> Opinion | None:
    raw = parse_json(content)
    if raw is None:
        return None
    data: dict[str, Any] = {
        k: raw.get(k) for k in ("speak", "reason", "general", *_FIELDS) if k in raw
    }
    for k in ("reason", *_FIELDS):
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
) -> Consultation:
    """请一个专业 Agent 作答。出错时返回不发言的意见，不向外抛。"""
    extra = _SAFETY_EXTRA if spec.role is Role.SAFETY else ""
    system = _PROMPT.format(name=spec.name, duty=spec.duty, tools=_tool_hint(toolbox), extra=extra)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": _user_message(text, history, concerns)},
    ]
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
            if rounds > MAX_ROUNDS:
                return Opinion(role=spec.role, speak=False, reason="查询太多次，没有给出意见")
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
            reason = "；".join(problems)
            _log.info(
                "expert opinion rejected: role=%s problems=%d", spec.role.value, len(problems)
            )
            return Opinion(role=spec.role, speak=False, reason=f"意见没有通过核对（{reason}）")
        fixes += 1
        messages.append({"role": "assistant", "content": reply.content})
        messages.append(
            {
                "role": "user",
                "content": "你的意见有问题，请改正后只输出 JSON："
                + json.dumps(problems, ensure_ascii=False),
            }
        )
