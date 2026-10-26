"""管家整合：请到多位专业角色时，把它们的意见整合成一个回答，并在发出前用规则核对。

- 核对逐句进行（checks.check_text，与专业 Agent 的意见同一套规则）。
- 核对不通过时带着原因改写一次；仍不通过就 repair（对不上的个人数据句删掉，其余改标〔经验〕）。
- 模型不可用时，给出主责角色的意见，并提示这次回答受限。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from ironm_agent.answer_format import assemble, is_slots, slots_prompt
from ironm_agent.checks import (
    CALC_REF,
    KB_REF,
    check_text,
    cited_ids,
    merge_echoes,
    plain,
    repair,
    sentences,
)
from ironm_agent.constraints import Violation, fixes
from ironm_agent.experts import Consultation, Opinion
from ironm_agent.harness import problem_kinds
from ironm_agent.kb import Entry
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.memory_view import Recall
from ironm_agent.numbers import written_numbers
from ironm_agent.roles import Role, spec_of

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


_PROMPT = """你是"AI 健身管家"。几位专业角色已经分别回答了用户的问题（彼此看不到对方的意见），请把它们整合成一个给用户的回答。

要求：
1. 有效、精炼（spec [2026-10-23] §38）：第一句就是用户问的那件事的答案，理由一句放在后面；只答问的，没问到的不说，用户追问再展开；同一个意思只说一次，不铺垫、不罗列所有可能。宁可少说，也不要面面俱到。
2. 只使用各角色意见里的内容，不新增事实，也不新增数字；几个角色说的是同一件事时合并成一处。
3. 主责角色（{primary}）的意见是主体；问题涉及几个方面（比如又问练又问吃）时，做法第 1 条来自主责角色，第 2 条来自另一位角色，各写最关键的一条。
4. 停下或就医的提醒只在问题本身涉及疼痛、受伤、疾病时保留一条；数据风险提醒由系统放在最后，不用写；不预防性地加"如果……就医"。
5. 个人化：只保留真正改变建议的个人数据（比如按体重算出的剂量）；为了显得个人化而提一句体重之类的不要写；不提和这次问题无关的旧话题，不罗列"你的记录里没有什么"。
6. 出处标记照规则保留（系统展示时会去掉，并把来源放进可展开的"依据与来源"，所以不用在正文里解释出处）：形如 ⟦D1⟧ 的占位符代表一句引用了用户数据的原话，原样放进合适位置，不要改写或自己补写；资料句末尾的〔K03〕、计算结果句末尾的〔C2〕、经验句末尾的〔经验〕跟着它所属的句子保留，不能删、不能挪；改写一句话时它的数字和标记保持不变。含数字的句子都必须带着出处标记或就是占位符。
7. 用中文，口语化，像一位专业又亲切的教练，不要说"根据各角色的意见""依据库"这类话。讲动作用大白话：训练教练讲动作用的类比和体感描述（如"想象腋下夹着一张纸，别让它掉下来"）原样保留，不要改回解剖术语；其他角色写了解剖术语（如肩胛后缩、外旋、伸髋、肩袖、等长收缩）时，换成身体部位和动作的大白话（如"两块肩胛骨往中间夹"），实在换不了的，紧跟一句大白话说明它是什么。
8. 意见有冲突时按"安全 > 恢复 > 训练、营养"取舍：恢复认为今天该休息或减量时，训练安排给减量版；只写取舍后的一种说法，不要把两种都写出来。{style}"""

_REVISE = """你是"AI 健身管家"。下面这条回答有不符合这个人情况的地方，请只改这些地方，其余照原样保留。
要求：
1. 按"要改的地方"修正：优先写明怎么做才安全（控制深度或幅度、轻重量、换成哪个具体的替代动作），确实不适合才说先别做；不要把用户想练的东西一概禁掉，不新增别的内容，改完前后说法要一致。
2. 出处标记照规则保留：形如 ⟦D1⟧ 的占位符原样放回；句末的〔K03〕〔C2〕〔经验〕跟着所属的句子保留；不新增数字。
3. 原回答里讲动作用的类比和体感描述（如"想象腋下夹着一张纸"）原样保留，不改回解剖术语。
4. 只输出改好的回答全文。"""


# 几位角色一起作答时，每位至少留一条做法（spec [2026-10-23] §42）：模型漏了就从那位的意见里补第一句
_ROLE_STEPS = (
    '\nsteps 每条写成 {{"role": "角色名", "text": "做法"}}；被请到的每位角色（{names}）至少一条。'
)


def _steps_per_role(items: Any, opinions: Sequence[Opinion]) -> list[str]:
    names = [spec_of(o.role).name for o in opinions]
    got: list[tuple[str, str]] = []
    for it in items if isinstance(items, list) else ([items] if items else []):
        if isinstance(it, Mapping):
            role, text = str(it.get("role") or ""), str(it.get("text") or "").strip()
        else:
            role, text = "", str(it).strip()
        if text:
            got.append((role, text))
    if not any(r in names for r, _ in got):
        return [t for _, t in got]  # 模型没写角色名，照原样用
    covered = {r for r, _ in got}
    for name, op in zip(names, opinions, strict=True):
        if name in covered:
            continue
        first = next(
            (s.strip() for s in sentences(op.how or op.conclusion)
             if s.strip() and s.count("<statement>") == s.count("</statement>")),
            "",
        )  # fmt: skip
        if first:
            got.append((name, first))
    lead = [next(t for r, t in got if r == n) for n in names if any(r == n for r, _ in got)]
    return lead + [t for _, t in got if t not in lead]


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


def _payload(text: str, opinions: Sequence[Opinion], shield: Shield, state: str = "") -> str:
    items = []
    for op in opinions:
        item = {
            "角色": spec_of(op.role).name,
            "结论": shield.hide(op.conclusion),
            "针对你": shield.hide(op.for_you),
            "怎么做": shield.hide(op.how),
            "注意": shield.hide(op.caution),
            "不确定": shield.hide(op.uncertain),
            "依据编号": list(op.basis),
        }
        if op.general:
            item["说明"] = "一般建议（没有资料依据）"
        items.append({k: v for k, v in item.items() if v})
    head = f"用户的问题：{text}" + (f"\n这个人{state}" if state else "")
    return f"{head}\n\n各角色的意见：\n" + json.dumps(items, ensure_ascii=False, indent=1)


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


def fallback(opinion: Opinion) -> str:
    """整合失败时：给出主责角色已经核对过的意见。"""
    return "\n\n".join(
        x for x in (opinion.conclusion, opinion.for_you, opinion.how, opinion.caution) if x
    )


async def compose(
    text: str,
    primary: Role,
    consultations: Sequence[Consultation],
    llm: LLM,
    memory: Recall | None = None,
    *,
    constraints: Constraints | None = None,
    annotate: Callable[[str], str] | None = None,
    state: str = "",
    task: str | None = None,
) -> Composed:
    """constraints：约束核对（不过关的地方和数字问题一起交给改写）；state：这个人今天的身体状态（取舍用）。"""
    others = [c for c in consultations if c.opinion.speak]
    others.sort(key=lambda c: c.opinion.role is not primary)  # 主责在前
    opinions = [c.opinion for c in others]
    support = {rid: values for c in others for rid, values in c.evidence.support.items()}
    entries = {eid: e for c in others for eid, e in c.evidence.entries.items()}
    calcs = {cid: d for c in others for cid, d in c.evidence.calcs.items()}
    rows = {rid: d for c in others for rid, d in c.evidence.rows.items()}
    said = [v for o in opinions for v in written_numbers(o.body())]  # 专业角色意见里出现过的数字
    shield = Shield()
    style = memory.style() if memory else ""
    hint = f"\n9. 这个人说过的回答偏好与喜好（照做）：\n{style}" if style else ""
    # 记忆里用户自己说过的数字（如哑铃 20 公斤）和这次问题里的数字一样，可以直接用
    question = "\n".join(x for x in (text, memory.numbers_text() if memory else "") if x)
    messages = [
        {
            "role": "system",
            "content": _PROMPT.format(primary=spec_of(primary).name, style=hint)
            + "\n\n"
            + slots_prompt(text, task)
            + _ROLE_STEPS.format(names="、".join(spec_of(o.role).name for o in opinions)),
        },
        {"role": "user", "content": _payload(text, opinions, shield, state)},
    ]
    found: list[Violation] = []
    checks: list[str] = []
    for attempt in range(2):
        try:
            reply = await llm.chat("compose", messages, json_mode=True)
        except ModelUnavailable:
            break
        draft = re.sub(r"〔D(\d+)〕", r"⟦D\1⟧", reply.content.strip())  # 模型把占位符写成了出处括号
        raw = parse_json(draft)
        if isinstance(raw, dict) and is_slots(raw):  # 按分段写的由代码拼成正文、限长（§38）
            raw = {**raw, "steps": _steps_per_role(raw.get("steps"), opinions)}
            draft = assemble(raw, text, task)
        answer, problems = shield.restore(draft)
        answer = merge_echoes(answer)
        problems += review(
            answer,
            support=support,
            entries=entries,
            question=question,
            calcs=calcs,
            experience=said,
        )
        violations = constraints(plain(answer)) if constraints and answer.strip() else []
        if attempt == 0:
            found = violations
            checks = problem_kinds(problems)
        problems += [v.detail for v in violations]
        repaired = bool(problems) and attempt == 1
        if not problems or attempt == 1:
            if problems:  # 改了一次还不过：修正而不是放弃
                answer = repair(
                    answer,
                    support=support,
                    entries=entries,
                    question=question,
                    calcs=calcs,
                    experience=said,
                )
            if answer.strip():
                done = _composed(answer, entries, calcs, rows, rewrites=attempt)
                done = replace(done, checks=tuple(checks), repaired=repaired)
                return _settle(done, constraints, found, annotate)
            break  # 修完什么都不剩：退回主责角色的意见
        messages.append({"role": "assistant", "content": draft})
        messages.append(
            {
                "role": "user",
                "content": "回答没有通过核对，请改正后按同样的 JSON 重写：" + "；".join(problems),
            }
        )
    degraded = _composed(
        fallback(opinions[0]), entries, calcs, rows, rewrites=1, degraded=True, by_model=False
    )
    return _settle(replace(degraded, checks=tuple(checks)), constraints, found, annotate)
