"""主教练：把各专业 Agent 的意见整合成一个回答，并在发出前用规则核对。

- 核对逐句进行（checks.check_text，与专业 Agent 的意见同一套规则）。
- 核对不通过时带着原因改写一次；仍不通过就 repair（对不上的个人数据句删掉，其余改标〔经验〕）。
- 模型不可用时，给出主责角色的意见，并提示这次回答受限。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ironm_agent.checks import CALC_REF, KB_REF, check_text, cited_ids, repair
from ironm_agent.experts import Consultation, Opinion
from ironm_agent.kb import Entry
from ironm_agent.llm import LLM, ModelUnavailable
from ironm_agent.numbers import written_numbers
from ironm_agent.roles import SPECS, Role

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


_PROMPT = """你是健身 App 的主教练。几位专业角色已经分别回答了用户的问题（彼此看不到对方的意见），请把它们整合成一个给用户的回答。

要求：
1. 有效、精炼：第一句直接回答用户问的那件事，接着只给最关键的做法。简单问题不超过 150 字；需要分步骤的问题不超过 300 字、最多 5 个要点。同一个意思只说一次，不铺垫、不罗列所有可能，不用小标题。宁可少说，也不要面面俱到。
2. 只使用各角色意见里的内容，不新增事实，也不新增数字；几个角色说的是同一件事时合并成一处。
3. 主责角色（{primary}）的意见是主体。
4. 风险提醒只保留和这件事直接相关、最重要的一条，放在最后。
5. 个人化：只保留真正改变建议的个人数据（比如按体重算出的剂量）；为了显得个人化而提一句体重之类的不要写；不提和这次问题无关的旧话题，不罗列"你的记录里没有什么"。
6. 出处标记照规则保留（系统展示时会去掉，并把来源放进可展开的"依据与来源"，所以不用在正文里解释出处）：形如 ⟦D1⟧ 的占位符代表一句引用了用户数据的原话，原样放进合适位置，不要改写或自己补写；资料句末尾的〔K03〕、计算结果句末尾的〔C2〕、经验句末尾的〔经验〕跟着它所属的句子保留，不能删、不能挪；改写一句话时它的数字和标记保持不变。含数字的句子都必须带着出处标记或就是占位符。
7. 用中文，口语化，像一位专业又亲切的教练，不要说"根据各角色的意见""依据库"这类话。"""


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


def _payload(text: str, opinions: Sequence[Opinion], shield: Shield) -> str:
    items = []
    for op in opinions:
        item = {
            "角色": SPECS[op.role].name,
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
    return f"用户的问题：{text}\n\n各角色的意见：\n" + json.dumps(
        items, ensure_ascii=False, indent=1
    )


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
) -> Composed:
    others = [c for c in consultations if c.opinion.speak]
    others.sort(key=lambda c: c.opinion.role is not primary)  # 主责在前
    opinions = [c.opinion for c in others]
    support = {rid: values for c in others for rid, values in c.evidence.support.items()}
    entries = {eid: e for c in others for eid, e in c.evidence.entries.items()}
    calcs = {cid: d for c in others for cid, d in c.evidence.calcs.items()}
    rows = {rid: d for c in others for rid, d in c.evidence.rows.items()}
    said = [v for o in opinions for v in written_numbers(o.body())]  # 专业角色意见里出现过的数字
    shield = Shield()
    messages = [
        {"role": "system", "content": _PROMPT.format(primary=SPECS[primary].name)},
        {"role": "user", "content": _payload(text, opinions, shield)},
    ]
    for attempt in range(2):
        try:
            reply = await llm.chat("compose", messages)
        except ModelUnavailable:
            break
        draft = reply.content.strip()
        answer, problems = shield.restore(draft)
        problems += review(
            answer, support=support, entries=entries, question=text, calcs=calcs, experience=said
        )
        if not problems or attempt == 1:
            if problems:  # 改了一次还不过：修正而不是放弃
                answer = repair(
                    answer,
                    support=support,
                    entries=entries,
                    question=text,
                    calcs=calcs,
                    experience=said,
                )
            if answer.strip():
                return _composed(answer, entries, calcs, rows, rewrites=attempt)
            break  # 修完什么都不剩：退回主责角色的意见
        messages.append({"role": "assistant", "content": draft})
        messages.append(
            {
                "role": "user",
                "content": "回答没有通过核对，请改正后重写全文：" + "；".join(problems),
            }
        )
    return _composed(
        fallback(opinions[0]), entries, calcs, rows, rewrites=1, degraded=True, by_model=False
    )
