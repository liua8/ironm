"""主教练：把各专业 Agent 的意见整合成一个回答，并在发出前用规则核对。

- 安全官的提醒不交给模型改写，由系统原样放在回答最后的"安全提醒"里，保证不丢、不改。
- 核对逐句进行（checks.check_text，与专业 Agent 的意见同一套规则）。
- 核对不通过时带着原因改写一次；仍不通过就给出主责角色已经核对过的意见，并提示这次回答受限。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ironm_agent.checks import KB_REF, check_text, cited_ids
from ironm_agent.experts import Consultation, Opinion
from ironm_agent.kb import Entry
from ironm_agent.llm import LLM, ModelUnavailable
from ironm_agent.roles import SPECS, Role

_KB_REF = KB_REF


@dataclass(frozen=True)
class Composed:
    text: str  # 回答正文（不含安全提醒和末尾的资料清单）
    entries: tuple[Entry, ...]  # 正文引用到的依据库条目，按出现顺序
    safety: str  # 安全官的提醒，原样
    degraded: bool
    rewrites: int
    by_model: bool


_PROMPT = """你是健身 App 的主教练。几位专业角色已经分别回答了用户的问题（彼此看不到对方的意见），请把它们整合成一个给用户的回答。

要求：
1. 只使用下面各角色意见里的内容，不新增事实，也不新增数字。几个角色说的是同一件事时合并成一处，口径不同时都保留并说清各自指的时间范围。
2. 主责角色（{primary}）的意见放在前面。
3. 安全官的提醒会由系统单独放在回答最后，你不用写，也不要和它矛盾。
4. 各角色意见里的句子已经标好出处：资料句末尾的〔K03〕、数据句的 <statement>…<cite>[r3]</cite></statement>。整合时这些标记跟着它所属的句子原样保留，不能删，也不能挪到别的句子上；改写一句话时，这句话的数字和标记保持不变。
5. 含数字的句子都必须带着它原来的出处标记。
6. 标了"一般建议"的意见，写成一般建议，不加具体数字。
7. 结构：**结论**、**针对你**、**怎么做**、**注意**；没有内容的部分省略，简单问题可以只写结论和怎么做。
8. 用中文，口语化，像一位专业又亲切的教练，简洁，不要说"根据各角色的意见"这类话。"""


def _payload(text: str, opinions: Sequence[Opinion]) -> str:
    items = []
    for op in opinions:
        item = {
            "角色": SPECS[op.role].name,
            "结论": op.conclusion,
            "针对你": op.for_you,
            "怎么做": op.how,
            "注意": op.caution,
            "不确定": op.uncertain,
            "依据编号": list(op.basis),
        }
        if op.general:
            item["说明"] = "一般建议（没有资料依据）"
        items.append({k: v for k, v in item.items() if v})
    return f"用户的问题：{text}\n\n各角色的意见：\n" + json.dumps(
        items, ensure_ascii=False, indent=1
    )


def review(
    answer: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
) -> list[str]:
    """回答发出前的规则核对，返回问题清单（为空表示通过）。"""
    if not answer.strip():
        return ["回答是空的"]
    return check_text(answer, support=support, entries=entries, question=question)


def _ordered_entries(answer: str, entries: Mapping[str, Entry]) -> tuple[Entry, ...]:
    ids = [r for r in dict.fromkeys(_KB_REF.findall(answer)) if r in entries]
    return tuple(entries[i] for i in ids)


def fallback(opinion: Opinion) -> str:
    """整合失败时：给出主责角色已经核对过的意见。"""
    parts = [f"**结论**\n{opinion.conclusion}"]
    for label, value in (
        ("针对你", opinion.for_you),
        ("怎么做", opinion.how),
        ("注意", opinion.caution),
    ):
        if value:
            parts.append(f"**{label}**\n{value}")
    return "\n\n".join(parts)


async def compose(
    text: str,
    primary: Role,
    consultations: Sequence[Consultation],
    llm: LLM,
) -> Composed:
    spoke = [c for c in consultations if c.opinion.speak]
    safety = next((c.opinion for c in spoke if c.opinion.role is Role.SAFETY), None)
    caution = safety.caution if safety is not None else ""
    others = [c for c in spoke if c.opinion.role is not Role.SAFETY]
    others.sort(key=lambda c: c.opinion.role is not primary)  # 主责在前
    # 参考资料只列安全提醒里真正引用到的
    safety_entries = tuple(
        c.evidence.entries[b]
        for c in spoke
        if c.opinion.role is Role.SAFETY
        for b in cited_ids(caution)
        if b in c.evidence.entries
    )
    if not others:  # 只有安全官发言：提醒就是回答
        return Composed("", safety_entries, caution, False, 0, False)
    opinions = [c.opinion for c in others]
    support = {rid: values for c in others for rid, values in c.evidence.support.items()}
    entries = {eid: e for c in others for eid, e in c.evidence.entries.items()}
    messages = [
        {"role": "system", "content": _PROMPT.format(primary=SPECS[primary].name)},
        {"role": "user", "content": _payload(text, opinions)},
    ]
    for attempt in range(2):
        try:
            reply = await llm.chat("compose", messages)
        except ModelUnavailable:
            break
        answer = reply.content.strip()
        problems = review(answer, support=support, entries=entries, question=text)
        if not problems:
            used = _ordered_entries(answer, entries) + tuple(
                e for e in safety_entries if e.id not in _KB_REF.findall(answer)
            )
            return Composed(answer, used, caution, False, attempt, True)
        messages.append({"role": "assistant", "content": answer})
        messages.append(
            {
                "role": "user",
                "content": "回答没有通过核对，请改正后重写全文：" + "；".join(problems),
            }
        )
    return Composed(fallback(opinions[0]), safety_entries, caution, True, 1, False)
