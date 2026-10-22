"""逐句核对：专业 Agent 的意见和主教练整合后的回答用同一套规则。

- 引用资料的句子在句末写〔K03〕：句子里的数字只能来自这一句引用的资料；
- 引用健康数据的句子写成 <statement>…<cite>[r3]</cite></statement>：数字只能来自引用的数据行；
- 没有标出处的句子不能有数字（用户自己说的数字除外）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from ironm_agent.kb import Entry
from ironm_agent.numbers import traced, written_numbers

KB_REF = re.compile(r"〔(K\d{2,3})〕")
CALC_REF = re.compile(r"〔(C\d{1,2})〕")
ANY_REF = re.compile(r"〔(?:K\d{2,3}|C\d{1,2})〕")
# 句子的结尾：句号、问号、叹号、分号、换行；紧跟在结尾后面的〔K..〕仍属于前一句
_SENTENCE = re.compile(r"[^。！？；\n]*(?:[。！？；\n]|$)(?:[ \t]*〔(?:K\d{2,3}|C\d{1,2})〕)*")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.findall(text) if s.strip()]


def _shown(values: Sequence[float]) -> str:
    return "、".join(f"{v:g}" for v in dict.fromkeys(values))


def check_text(
    text: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
    calcs: Mapping[str, str] | None = None,
) -> list[str]:
    """返回问题清单（为空表示通过）。calcs：指标计算结果（C 编号 → 含数字的说明）。"""
    calcs = calcs or {}
    from mirobody.kernel.citations import parse

    problems: list[str] = []
    if text.count("<statement>") != text.count("</statement>"):
        problems.append("<statement> 标记没有成对")
    unknown = [r for r in dict.fromkeys(KB_REF.findall(text)) if r not in entries]
    unknown += [r for r in dict.fromkeys(CALC_REF.findall(text)) if r not in calcs]
    if unknown:
        problems.append(f"引用了不存在的资料或计算编号：{'、'.join(unknown)}")
    own = written_numbers(question)
    for seg in parse(text):
        if seg.statement:
            bad_rows = [c for c in seg.cites if c not in support]
            if bad_rows:
                problems.append(f"引用了不存在的数据编号：{'、'.join(bad_rows)}")
                continue
            refs = [r for r in KB_REF.findall(seg.text) if r in entries]
            data = [v for c in seg.cites for v in support[c]]
            data += [
                v
                for c in CALC_REF.findall(seg.text)
                if c in calcs
                for v in written_numbers(calcs[c])
            ]
            coefs = [v for r in refs for v in written_numbers(entries[r].as_evidence())]
            loose = [
                v
                for v in written_numbers(ANY_REF.sub("", seg.text))
                if not traced(v, own, data=data, coefs=coefs)
            ]
            if loose:
                problems.append(
                    f"带数据编号的句子里，这些数字在所引的数据行里找不到：{_shown(loose)}"
                )
            continue
        for sentence in sentences(seg.text):
            refs = [r for r in KB_REF.findall(sentence) if r in entries]
            pool = [v for r in refs for v in written_numbers(entries[r].as_evidence())] + own
            pool += [
                v
                for c in CALC_REF.findall(sentence)
                if c in calcs
                for v in written_numbers(calcs[c])
            ]
            loose = [v for v in written_numbers(ANY_REF.sub("", sentence)) if not traced(v, pool)]
            if loose:
                where = (
                    f"所引的{'、'.join(refs)}"
                    if refs
                    else "这一句（没有标出处：用到用户数据要写成 <statement>这句话<cite>[r编号]</cite></statement>，"
                    "用到资料要在句末写〔K编号〕，用到指标计算结果要在句末写〔C编号〕）"
                )
                problems.append(
                    f"「{sentence.strip()[:30]}…」里的数字 {_shown(loose)} 在{where}里找不到"
                )
    return problems


def cited_ids(text: str) -> list[str]:
    """文字里引用到的全部依据编号（资料 K、数据行 r），按出现顺序。"""
    from mirobody.kernel.citations import parse

    ids = ANY_REF.findall(text)
    ids = [i.strip("〔〕") for i in ids]
    for seg in parse(text):
        ids.extend(seg.cites)
    return list(dict.fromkeys(ids))
