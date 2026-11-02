"""管家整合：请到多位专业角色时，把它们的意见整合成一个回答，并在发出前用规则核对。

- 核对逐句进行（checks.check_text，与专业 Agent 的意见同一套规则）。
- 核对不通过时带着原因改写一次；仍不通过就 repair（对不上的个人数据句删掉，其余改标〔经验〕）。
- 模型不可用时，给出主责角色的意见，并提示这次回答受限。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from ironm_agent.checks import (
    CALC_REF,
    KB_REF,
    check_text,
    cited_ids,
    plain,
    repair,
)
from ironm_agent.constraints import Violation, fixes
from ironm_agent.experts import Consultation
from ironm_agent.harness import problem_kinds
from ironm_agent.kb import Entry
from ironm_agent.llm import LLM, ModelUnavailable
from ironm_agent.memory_view import Recall
from ironm_agent.numbers import written_numbers

_KB_REF = KB_REF


@dataclass(frozen=True)
class Composed:
    text: str  # 回答正文，带出处标记（内部核对用；展示时去掉，出处放进"依据与来源"）
    entries: tuple[Entry, ...]  # 正文引用到的依据库条目，按出现顺序
    degraded: bool
    rewrites: int
    by_model: bool
    calcs: tuple[tuple[str, str], ...] = ()  # 正文引用到的指标计算（C 编号，说明）
    rows: tuple[tuple[str, str], ...] = ()  # 正文引用到的健康数据（rid，说明）
    violations: tuple[str, ...] = ()  # 约束核对第一次发现的问题类别（spec [2026-10-23] §4）
    fixed: bool = False  # 改写后仍不过关，末尾补了固定的限制
    checks: tuple[str, ...] = ()  # 核对第一次发现的问题类别（运行框架用，spec [2026-10-23] §31）
    repaired: bool = False  # 改写后仍不通过，被规则修正


type Constraints = Callable[[str], list[Violation]]


_REVISE = """你是"AI 健身管家"。下面这条回答有不符合这个人情况的地方，请只改这些地方，其余照原样保留。
要求：
1. 按"要改的地方"修正：优先写明怎么做才安全（控制深度或幅度、轻重量、换成哪个具体的替代动作），确实不适合才说先别做；不要把用户想练的东西一概禁掉，不新增别的内容，改完前后说法要一致。
2. 出处标记照规则保留：形如 ⟦D1⟧ 的占位符原样放回；句末的〔K03〕〔C2〕〔经验〕跟着所属的句子保留；不新增数字。
3. 原回答里讲动作用的类比和体感描述（如"想象腋下夹着一张纸"）原样保留，不改回解剖术语。
4. 只输出改好的回答全文。"""


_STATEMENT = re.compile(r"<statement>.*?</statement>", re.S)
_HOLDER = re.compile(r"⟦D(\d+)⟧")


class Shield:
    """把引用了用户数据的整句（<statement>…</statement>）换成占位符 ⟦D1⟧ 交给模型，整合后再换回原话。

    模型改写时容易把这类句子的标记弄坏（网页上就点不开了），占位符让这些句子一个字都不被改动。
    """

    def __init__(self) -> None:
        self.originals: list[str] = []

    def hide(self, text: str) -> str:
        def swap(m: re.Match[str]) -> str:
            self.originals.append(m.group(0))
            return f"⟦D{len(self.originals)}⟧"

        return _STATEMENT.sub(swap, text)

    def restore(self, text: str) -> tuple[str, list[str]]:
        problems: list[str] = []

        def back(m: re.Match[str]) -> str:
            i = int(m.group(1))
            if 1 <= i <= len(self.originals):
                return self.originals[i - 1]
            problems.append(f"不存在的占位符 ⟦D{i}⟧")
            return ""

        return _HOLDER.sub(back, text), problems


def review(
    answer: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
    calcs: Mapping[str, str] | None = None,
    experience: Sequence[float] | None = None,
) -> list[str]:
    """回答发出前的规则核对，返回问题清单（为空表示通过）。"""
    if not answer.strip():
        return ["回答是空的"]
    return check_text(
        answer,
        support=support,
        entries=entries,
        question=question,
        calcs=calcs,
        experience=experience,
    )


def _ordered_entries(answer: str, entries: Mapping[str, Entry]) -> tuple[Entry, ...]:
    ids = [r for r in dict.fromkeys(_KB_REF.findall(answer)) if r in entries]
    return tuple(entries[i] for i in ids)


def _composed(
    answer: str,
    entries: Mapping[str, Entry],
    calcs: Mapping[str, str],
    rows: Mapping[str, str],
    *,
    rewrites: int,
    degraded: bool = False,
    by_model: bool = True,
) -> Composed:
    used_calcs = tuple((c, calcs[c]) for c in dict.fromkeys(CALC_REF.findall(answer)) if c in calcs)
    used_rows = tuple((r, rows[r]) for r in cited_ids(answer) if r in rows)
    return Composed(
        answer,
        _ordered_entries(answer, entries),
        degraded,
        rewrites,
        by_model,
        used_calcs,
        used_rows,
    )


def solo(consultation: Consultation) -> Composed:
    """只请到一位时，它直接写的回答就是最终回答（已经逐句核对过），不再整合。"""
    ev = consultation.evidence
    return _composed(consultation.opinion.answer, ev.entries, ev.calcs, ev.rows, rewrites=0)


def _settle(
    composed: Composed,
    constraints: Constraints | None,
    found: Sequence[Violation],
    annotate: Callable[[str], str] | None = None,
) -> Composed:
    """记下第一次发现的约束问题；改写后仍不过关时，在不过关的动作后面注明限制，
    还不行就在末尾补一句固定的限制（都不调用模型）。"""
    still = constraints(plain(composed.text)) if constraints else []
    if still and annotate is not None:
        composed = replace(composed, text=annotate(composed.text), fixed=True)
        still = constraints(plain(composed.text)) if constraints else []
    if still:
        composed = replace(
            composed, text=composed.text.rstrip() + "\n\n" + fixes(still), fixed=True
        )
    return replace(composed, violations=tuple(dict.fromkeys(v.kind for v in found)))


async def revise(
    consultation: Consultation,
    text: str,
    llm: LLM,
    *,
    constraints: Constraints | None,
    memory: Recall | None = None,
    annotate: Callable[[str], str] | None = None,
) -> Composed:
    """只请到一位时的约束核对：不过关就改写一次；仍不过关就注明限制。"""
    composed = solo(consultation)
    found = constraints(plain(composed.text)) if constraints else []
    if not found:
        return composed
    ev = consultation.evidence
    question = "\n".join(x for x in (text, memory.numbers_text() if memory else "") if x)
    said = written_numbers(consultation.opinion.body())
    shield = Shield()
    messages = [
        {"role": "system", "content": _REVISE},
        {
            "role": "user",
            "content": f"用户的问题：{text}\n\n回答：\n{shield.hide(composed.text)}\n\n要改的地方："
            + "；".join(v.detail for v in found),
        },
    ]
    try:
        reply = await llm.chat("compose", messages)
    except ModelUnavailable:
        return _settle(composed, constraints, found, annotate)
    answer, problems = shield.restore(reply.content.strip())
    problems += review(answer, support=ev.support, entries=ev.entries, question=question,
                       calcs=ev.calcs, experience=said)  # fmt: skip
    if problems:
        answer = repair(answer, support=ev.support, entries=ev.entries, question=question,
                        calcs=ev.calcs, experience=said)  # fmt: skip
    if answer.strip():
        composed = _composed(answer, ev.entries, ev.calcs, ev.rows, rewrites=1)
        composed = replace(composed, checks=tuple(problem_kinds(problems)), repaired=bool(problems))
    return _settle(composed, constraints, found, annotate)
