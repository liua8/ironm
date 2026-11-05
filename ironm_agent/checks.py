"""逐句核对出处：专业 Agent 的意见和管家整合后的回答用同一套规则。

- 引用资料的句子在句末写〔K03〕：句子里的数字只能来自这一句引用的资料；
- 引用指标计算结果的句子在句末写〔C2〕：数字只能来自这个计算结果；
- 引用健康数据的句子写成 <statement>…<cite>[r3]</cite></statement>：数字只能来自引用的数据行；
- 没有资料出处、凭专业经验说的句子，在句末写〔经验〕，不核对数字，用户看得到这是经验；
- 没标任何出处的句子不能有数字（用户自己说的数字除外）。

核对不过、改了一次还不过的，不再整条作废，而是 repair：引用个人数据却对不上的那句删掉（不能把人的数据说错），
其余对不上出处的句子去掉错误的出处、改标〔经验〕。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from ironm_agent.kb import Entry
from ironm_agent.numbers import traced, written_numbers

EXPERIENCE = "〔经验〕"
KB_REF = re.compile(r"〔(K\d{2,4})〕")
CALC_REF = re.compile(r"〔(C\d{1,2})〕")
ANY_REF = re.compile(r"〔(?:K\d{2,4}|C\d{1,2}|经验)〕")
_STATEMENT = re.compile(r"<statement>.*?</statement>", re.S)
# 句子的结尾：句号、问号、叹号、分号、换行；紧跟在结尾后面的出处标记仍属于前一句
_SENTENCE = re.compile(r"[^。！？；\n]*(?:[。！？；\n]|$)(?:[ \t]*〔(?:K\d{2,4}|C\d{1,2}|经验)〕)*")
_END = re.compile(r"([。！？；]?)(\s*)$")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE.findall(text) if s.strip()]


def _shown(values: Sequence[float]) -> str:
    return "、".join(f"{v:g}" for v in dict.fromkeys(values))


def _calc_numbers(text: str, calcs: Mapping[str, str]) -> list[float]:
    return [v for c in CALC_REF.findall(text) if c in calcs for v in written_numbers(calcs[c])]


def _statement_problems(seg_text: str, cites: Sequence[str], *, support: Mapping[str, Sequence[float]],
                        entries: Mapping[str, Entry], calcs: Mapping[str, str], own: list[float]) -> list[str]:  # fmt: skip
    bad_rows = [c for c in cites if c not in support]
    if bad_rows:
        return [f"引用了不存在的数据编号：{'、'.join(bad_rows)}"]
    refs = [r for r in KB_REF.findall(seg_text) if r in entries]
    data = [v for c in cites for v in support[c]] + _calc_numbers(seg_text, calcs)
    coefs = [v for r in refs for v in written_numbers(entries[r].as_evidence())]
    loose = [
        v
        for v in written_numbers(ANY_REF.sub("", seg_text))
        if not traced(v, own, data=data, coefs=coefs)
    ]
    return [f"带数据编号的句子里，这些数字在所引的数据行里找不到：{_shown(loose)}"] if loose else []


def _sentence_problems(
    sentence: str,
    *,
    entries: Mapping[str, Entry],
    calcs: Mapping[str, str],
    own: list[float],
    experience: Sequence[float] | None = None,
) -> list[str]:
    if EXPERIENCE in sentence:
        # 专业 Agent 凭经验说的：用户看得到，不核对数字（experience 为 None）；
        # 管家整合时：经验句里的数字必须来自某位专业 Agent 的意见，整合不能自己加数字
        if experience is None:
            return []
        loose = [
            v
            for v in written_numbers(ANY_REF.sub("", sentence))
            if not traced(v, [*experience, *own])
        ]
        return (
            [f"「{sentence.strip()[:30]}…」里的数字 {_shown(loose)} 不在任何专业角色的意见里"]
            if loose
            else []
        )
    refs = [r for r in KB_REF.findall(sentence) if r in entries]
    pool = [v for r in refs for v in written_numbers(entries[r].as_evidence())] + own
    pool += _calc_numbers(sentence, calcs)
    loose = [v for v in written_numbers(ANY_REF.sub("", sentence)) if not traced(v, pool)]
    if not loose:
        return []
    where = (
        f"所引的{'、'.join(refs)}"
        if refs
        else "这一句（没有标出处：用到用户数据要写成 <statement>这句话<cite>[r编号]</cite></statement>，"
        "用到资料要在句末写〔K编号〕，用到指标计算结果写〔C编号〕，凭专业经验说的写〔经验〕）"
    )
    return [f"「{sentence.strip()[:30]}…」里的数字 {_shown(loose)} 在{where}里找不到"]


def check_text(
    text: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
    calcs: Mapping[str, str] | None = None,
    experience: Sequence[float] | None = None,
) -> list[str]:
    """返回问题清单（为空表示通过）。calcs：指标计算结果（C 编号 → 含数字的说明）；
    experience：整合时经验句允许的数字（各专业 Agent 意见里的数字），专业 Agent 自己写意见时为 None。"""
    from mirobody.kernel.citations import parse

    calcs = calcs or {}
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
            problems += _statement_problems(
                seg.text, seg.cites, support=support, entries=entries, calcs=calcs, own=own
            )
            continue
        for sentence in sentences(seg.text):
            problems += _sentence_problems(
                sentence, entries=entries, calcs=calcs, own=own, experience=experience
            )
    for sentence in sentences(_STATEMENT_TAG.sub("", _CITE.sub("", text))):
        wrong = _false_zero(sentence)
        if wrong:
            problems.append(
                f"「{sentence.strip()[:30]}」说可信范围跨过零，但 {wrong} 并不跨零：范围同号就说在上升或在下降"
            )
    return problems


# "可信范围 a 至 b……跨过零"：a、b 同号时说错了（§47）
_RANGE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:至|到|～|~|–|—)\s*(-?\d+(?:\.\d+)?)")
_CROSS = re.compile(r"跨过\s*(?:零|0)")
_CROSS_CLAUSE = re.compile(r"[，,]?[^，,。！？；\n〔<]*跨过\s*(?:零|0)[^，,。！？；\n〔<]*")


def _false_zero(sentence: str) -> str | None:
    """这句说可信范围跨过零，但写的范围不跨零：返回那个范围。"""
    if not _CROSS.search(sentence):
        return None
    ranges = [(float(a), float(b)) for a, b in _RANGE.findall(sentence)]
    if not ranges or any(a * b <= 0 for a, b in ranges):
        return None
    a, b = ranges[0]
    return f"{a:g} 至 {b:g}"


def _drop_false_zero(text: str) -> str:
    """删掉说"跨过零"却和范围不符的分句，其余保留。"""

    def fix(m: re.Match[str]) -> str:
        sentence = m.group(0)
        if _false_zero(_STATEMENT_TAG.sub("", _CITE.sub("", sentence))) is None:
            return sentence
        return _CROSS_CLAUSE.sub("", sentence)

    return _SENTENCE.sub(fix, text)


def _label_experience(sentence: str) -> str:
    """去掉这句话里的出处标记，句末改标〔经验〕。"""
    bare = ANY_REF.sub("", sentence)
    m = _END.search(bare)
    if m is None:
        return bare + EXPERIENCE
    return bare[: m.start()] + m.group(1) + EXPERIENCE + m.group(2)


def repair(
    text: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
    calcs: Mapping[str, str] | None = None,
    experience: Sequence[float] | None = None,
) -> str:
    """改不对的地方：对不上的个人数据句删掉；其余对不上出处的句子改标〔经验〕
    （整合时，改标后数字仍不在任何专业角色意见里的句子删掉）。结果一定通过 check_text。"""
    from mirobody.kernel.citations import parse

    calcs = calcs or {}
    own = written_numbers(question)
    text = _drop_false_zero(text)
    kept: list[str] = []

    def hold(m: re.Match[str]) -> str:
        whole = m.group(0)
        seg = next((s for s in parse(whole) if s.statement), None)
        if seg is None or _statement_problems(
            seg.text, seg.cites, support=support, entries=entries, calcs=calcs, own=own
        ):
            return ""  # 个人数据说不准就不说
        kept.append(whole)
        return _tag(len(kept) - 1)

    body = _STATEMENT.sub(hold, text)
    body = re.sub(r"</?statement>|<cite>.*?</cite>", "", body)  # 不成对的残余标记
    out = []
    for sentence in _SENTENCE.findall(body):
        if not sentence.strip():
            out.append(sentence)  # 换行原样留着，分段的回答修完还是分段（§42）
            continue
        unknown = [r for r in KB_REF.findall(sentence) if r not in entries]
        unknown += [r for r in CALC_REF.findall(sentence) if r not in calcs]
        if unknown or _sentence_problems(
            sentence, entries=entries, calcs=calcs, own=own, experience=experience
        ):
            labeled = _label_experience(sentence)
            if _sentence_problems(
                labeled, entries=entries, calcs=calcs, own=own, experience=experience
            ):
                continue  # 整合时加出来的数字：删掉这句
            out.append(labeled)
        else:
            out.append(sentence)
    repaired = "".join(out)
    for i, whole in enumerate(kept):
        repaired = repaired.replace(_tag(i), whole, 1)
    return repaired.strip()


# 数字后面跟的单位：补出处时要求资料里同一个数后面也是这个单位，免得"3 组"对上资料里不相干的 3（审查 11-05）
_UNIT = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:[–\-~～至到]\s*(\d+(?:\.\d+)?)\s*)?([%％]|[a-zA-Z]{1,4}|[\u4e00-\u9fff]{1,2})"
)
_ABOUT_HIM = re.compile(r"你|您")


def _units(text: str) -> set[tuple[float, str]]:
    out: set[tuple[float, str]] = set()
    for a, b, u in _UNIT.findall(text):  # 范围"3–4 周"：两头都算带这个单位
        out |= {(float(x), u.lower()) for x in (a, b) if x}
    return out


def _source_for(sentence: str, loose: Sequence[float], *, cited: Sequence[str], entries: Mapping[str, Entry],
                calcs: Mapping[str, str], support: Mapping[str, Sequence[float]]) -> str | None:  # fmt: skip
    """这几个数字全都能对上、又不会认错的那一处出处（§165）：回答别处引过的资料优先；
    其次正好一个计算结果；再次这一轮查到的资料里正好一条；最后健康数据里正好一行。都不行返回 None。
    资料和计算要数字连同单位都对得上（"5 克"对"5 克"）；健康数据只补说他自己的句子（有"你"）。"""
    want = {(v, u) for v, u in _units(sentence) if any(abs(v - x) < 1e-9 for x in loose)}
    if {v for v, _ in want} != {float(x) for x in loose}:
        return None  # 有的数没带单位：说不准是哪来的

    def same(text: str) -> bool:
        have = _units(text)
        return all(any(abs(v - hv) < 1e-9 and u[:1] == hu[:1] for hv, hu in have) for v, u in want)

    def kb(ids: Sequence[str]) -> list[str]:
        return [r for r in ids if r in entries and same(entries[r].as_evidence())]

    if hit := kb(cited):
        return f"〔{hit[0]}〕"
    if len(hit := [c for c in calcs if same(calcs[c])]) == 1:
        return f"〔{hit[0]}〕"
    if len(hit := kb([r for r in entries if r not in cited])) == 1:
        return f"〔{hit[0]}〕"
    if _ABOUT_HIM.search(sentence) and len(
        hit := [r for r, vals in support.items() if all(traced(v, list(vals)) for v in loose)]
    ) == 1:
        return f"<cite>[{hit[0]}]</cite>"
    return None


_LEAD = re.compile(r"\s*(?:[-•*]|\d+[.、)])?\s*")


def autocite(
    text: str,
    *,
    support: Mapping[str, Sequence[float]],
    entries: Mapping[str, Entry],
    question: str,
    calcs: Mapping[str, str] | None = None,
) -> str:
    """没写出处、数字却都能在这一轮的资料、计算、健康数据里对上的句子，由代码在句末补上出处（§165），
    省一次退回模型。只补没写任何出处的句子；对不上、或可能认错（几处都对得上）的不动，照旧退回。"""
    calcs = calcs or {}
    own = written_numbers(question)
    cited = [r for r in dict.fromkeys(KB_REF.findall(text)) if r in entries]
    changed = False

    def fix(m: re.Match[str]) -> str:
        nonlocal changed
        sentence = m.group(0)
        if not sentence.strip() or ANY_REF.search(sentence) or "<" in sentence or "⟦" in sentence:
            return sentence
        loose = [v for v in written_numbers(sentence) if not traced(v, own)]
        if not loose:
            return sentence
        mark = _source_for(sentence, loose, cited=cited, entries=entries, calcs=calcs, support=support)
        if mark is None:
            return sentence
        changed = True
        body = sentence.rstrip("\n")
        tail = sentence[len(body) :]
        if mark.startswith("<cite>"):
            lead = _LEAD.match(body)
            n = lead.end() if lead else 0  # 列表的"- "、"1. "留在标记外面
            return f"{body[:n]}<statement>{body[n:]}{mark}</statement>{tail}"
        return body + mark + tail

    held: list[str] = []

    def hold(m: re.Match[str]) -> str:
        held.append(m.group(0))
        return _tag(len(held) - 1)

    body = _SENTENCE.sub(fix, _STATEMENT.sub(hold, text))  # 带数据编号的句子不动
    if not changed:
        return text
    for i, whole in enumerate(held):
        body = body.replace(_tag(i), whole, 1)
    return body


def _tag(i: int) -> str:
    """占位符里不能有数字（会被当成句子里的数字），用字母编号：⟦Sa⟧、⟦Sb⟧ … ⟦Sba⟧。"""
    letters = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letters = "abcdefghijklmnopqrstuvwxyz"[r] + letters
    return f"⟦S{letters}⟧"


def cited_ids(text: str) -> list[str]:
    """文字里引用到的全部依据编号（资料 K、计算 C、数据行 r），按出现顺序。"""
    from mirobody.kernel.citations import parse

    ids = [i.strip("〔〕") for i in ANY_REF.findall(text) if i != EXPERIENCE]
    for seg in parse(text):
        ids.extend(seg.cites)
    return list(dict.fromkeys(ids))


_CITE = re.compile(r"<cite>.*?</cite>", re.S)
_STATEMENT_TAG = re.compile(r"</?statement>")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([，。！？；：、）])")
# 核对时删掉一句后，前后的标点会挨在一起（"提醒一句：，先别…""…上限；。"）：留后面那个句末标点
_LOOSE_PUNCT = re.compile(r"[，、；：,]+([。！？；])|([，、；：])[，、；：,]+|([。！？])[。]+")


_ECHO = re.compile(r"([^。；！？\n<>]*?)<statement>(.*?)(<cite>.*?</cite>)</statement>", re.S)


def merge_echoes(text: str) -> str:
    """模型常把同一件事写两遍：先一句普通的话，后面紧跟一个带数据编号的 <statement> 当作"出处"
    （"空腹血糖 5.1，参考范围 3.9–6.1，在范围内<statement>空腹血糖 5.1，参考范围 3.9–6.1<cite>[r3]</cite></statement>"）。
    前面那半句的数字都在紧跟的标记里时，把前面那半句当作带编号的数据句，去掉重复的标记（spec [2026-10-23] §37）。
    标记里只有编号、句子写在外面（"……参考范围 3.9–6.1<statement><cite>[r3]</cite></statement>"）也照此合并。"""

    def fix(m: re.Match[str]) -> str:
        before, inner, cite = m.group(1), m.group(2), m.group(3)
        said = set(written_numbers(before))
        if not said or (inner.strip() and not said <= set(written_numbers(inner))):
            return m.group(0)
        lead = len(before) - len(before.lstrip())
        return f"{before[:lead]}<statement>{before[lead:].rstrip()}{cite}</statement>"

    return _ECHO.sub(fix, text)


# 其他内部编号（记忆条目〔m20〕、数据行〔r3〕等）也不给用户看
_ANY_MARK = re.compile(r"〔[^〔〕\n]{1,12}〕")


def plain(text: str) -> str:
    """给用户看的正文：去掉出处标记、内部编号和数据引用的标签，只留话本身。"""
    out = _STATEMENT_TAG.sub("", _CITE.sub("", _ANY_MARK.sub("", ANY_REF.sub("", text))))
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out).replace("（）", "").replace("()", "")
    return _LOOSE_PUNCT.sub(lambda m: m.group(1) or m.group(2) or m.group(3), out).strip()
