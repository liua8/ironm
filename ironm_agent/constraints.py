"""约束核对（spec [2026-10-23] §4）：回答发出前，除了数字和出处，再用规则核对内容约束。

- 伤病与动作：有伤病的部位，回答不能直接安排会加重它的动作，除非写明了限制（控制深度或幅度、换成替代动作、
  先别做）：写在这个分句或紧跟的分句里，或者回答里有一句总的说明（提到这个部位并写明限制，如"膝盖有伤，
  所有蹲类动作只蹲到不疼的深度"），后面列的动作都算照顾到了；
- 今天状态差或生病：不安排大重量、高强度间歇、冲刺、力竭；
- 血压偏高、孕期：不安排大重量和憋气发力；孕期不安排仰卧和跳跃；
- 热量下限：建议的每日摄入不低于基础代谢，也不低于 1200 千卡（女）/ 1500 千卡（男）；
- 减重速度：不建议每周减重超过 1 公斤。

不过关时交给模型改写一次（把每个不过关的分句都告诉它）；仍不过关时，在不过关的动作后面直接注明限制
（如"开合跳（膝盖有伤先别做）"，annotate），不调用模型。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ironm_agent.casefile import CaseFile
from ironm_agent.training import Plan

# 分句里出现这些词，说明已经写了限制或是在说"别做"（注明的限制里不用逗号，免得被拆成两个分句）
BASE_OK = ("不", "别", "避免", "暂停", "先停", "替代", "代替", "换成", "改成", "改为", "换为", "替换",
           "而不是", "禁止", "停止", "慎", "限制", "控制", "取消", "减少", "免", "跳过", "绕开", "避开")  # fmt: skip
MAX_SHOWN = 4  # 每类最多列出几个不过关的分句
MAX_NOTES = 20  # 每类最多注明几处
_CLAUSE = re.compile(r"[^，,。！？；;\n]+")
_SENTENCE = re.compile(r"[^。！？；;\n]+")
_SENTENCE_END = re.compile(r"[。！？；;\n]")
NEAR = 4  # "不、别"这类词紧跟在动作后面几个字以内才算（"深蹲先别做"）
_GENERIC = re.compile(r"动作|训练|运动|练|蹲|重量|强度")
_JUMP = r"(?<!心)跳(?![过出])"


@dataclass(frozen=True)
class Rule:
    kind: str
    risky: re.Pattern[str]
    ok: tuple[str, ...]  # 在 BASE_OK 之外，还算写了限制的词
    why: str
    fix: str  # 实在注明不了时补在末尾的一句
    note: str = "（先别做）"  # 改写后仍不过关时，注在动作后面的限制
    jump_note: str = ""  # 跳跃类动作用的限制（膝盖、脚踝）
    covers: re.Pattern[str] | None = (
        None  # 一句话提到这个部位或情况并写明限制，就算整条回答都照顾到了
    )

    def note_for(self, matched: str) -> str:
        return self.jump_note if self.jump_note and "跳" in matched else self.note

    def specific(self, text: str) -> bool:
        return any(w in text for w in self.ok)

    def allowed(self, clause: str, hit: re.Match[str] | None = None) -> bool:
        """这个分句写了限制：具体的写法（深度、幅度、不疼…）在哪都算；"不、别、避免"这类泛泛的词，
        只在说到这个动作之前、或紧跟在它后面（"先别做深蹲""深蹲先别做"）才算。"""
        if self.specific(clause):
            return True
        if hit is None:
            return any(w in clause for w in BASE_OK)
        after = clause[hit.end() :]
        if after.startswith(
            ("（", "(")
        ):  # 紧跟在动作后面的括号里写了限制（注明的限制就是这样写的）
            inside = re.split(r"[）)]", after[1:], maxsplit=1)[0]
            if any(w in inside for w in BASE_OK):
                return True
        for w in BASE_OK:
            for m in re.finditer(re.escape(w), clause):
                if m.start() < hit.start() or hit.end() <= m.start() <= hit.end() + NEAR:
                    return True
        return False

    def covered(self, text: str, matched: str) -> bool:
        """有没有一句总的说明照顾到这类动作：提到这个部位或情况、写明了限制，并且说的是同一类动作
        （跳跃要专门提到跳；"先别做跳跃"不算说过深蹲怎么做）。"""
        if self.covers is None:
            return False
        jump = "跳" in matched
        for x in _SENTENCE.findall(text):
            if not (self.covers.search(x) and self.allowed(x)):
                continue
            if jump and "跳" in x:
                return True
            others = [m for m in self.risky.findall(x) if "跳" not in m]
            if not jump and (others or (_GENERIC.search(x) and "跳" not in x)):
                return True
        return False

    def bad(self, text: str) -> list[tuple[int, int, str]]:
        """没写明限制的地方：(开始位置, 结束位置, 命中的说法)，位置是在整段文字里的。
        本分句写了限制、紧跟的分句里有具体的写法、或者有一句总的说明，就算写明。"""
        out = []
        for c in _CLAUSE.finditer(text):
            clause = c.group(0)
            after = _CLAUSE.search(text, c.end())
            same_sentence = after is not None and not _SENTENCE_END.search(
                text, c.end(), after.start()
            )
            following = after.group(0) if after is not None and same_sentence else ""
            for hit in self.risky.finditer(clause):
                if self.allowed(clause, hit) or self.specific(following):
                    continue
                if self.covered(text, hit.group(0)):
                    continue
                out.append((c.start() + hit.start(), c.start() + hit.end(), hit.group(0)))
        return out


INJURY_RULES: dict[str, Rule] = {
    "knee": Rule("knee", re.compile(rf"{_JUMP}|深蹲|弓步|箭步|分腿蹲"),
                 ("箱", "深度", "幅度", "不疼", "无痛", "半蹲", "浅蹲", "坐到", "椅子"),
                 "他膝盖有伤",
                 "你膝盖有伤：深蹲、弓步只做到不疼的深度（可以用箱子控制），先别做跳跃动作；疼痛加重就停下。",
                 "（膝盖有伤：只做到不疼的深度）", "（膝盖有伤：跳跃先别做）", re.compile(r"膝")),
    "back": Rule("back", re.compile(r"硬拉|杠铃深蹲|壶铃摇摆|仰卧起坐|早安式|俯身划船|负重转体"),
                 ("轻", "小重量", "空杆", "徒手", "不疼", "幅度", "医生", "康复"),
                 "他腰有伤",
                 "你腰有伤：硬拉、深蹲这类动作先用轻重量、只做不疼的幅度，最好先请医生或康复师评估；疼痛加重就停下。",
                 "（腰有伤：先用轻重量、只做不疼的幅度）", "", re.compile(r"腰|椎间盘|背部")),
    "shoulder": Rule("shoulder", re.compile(r"推举|肩推|过头|引体|臂屈伸|双杠|颈后|卧推"),
                     ("窄握", "地板", "幅度", "不疼", "轻", "小重量"),
                     "他肩膀有伤",
                     "你肩膀不舒服：推举、引体、臂屈伸先别做，卧推换成窄握或地板卧推、只做不疼的幅度；疼痛加重就停下。",
                     "（肩膀有伤：只做不疼的幅度、疼就先别做）", "", re.compile(r"肩")),
    "wrist": Rule("wrist", re.compile(r"俯卧撑|平板支撑|卧推"), ("握拳", "把手", "前臂", "手肘", "不疼"),
                  "他手腕有伤",
                  "你手腕不舒服：俯卧撑和平板支撑改成握拳、用把手或手肘撑，只做不疼的范围。",
                  "（手腕有伤：改成握拳或用把手、只做不疼的范围）", "", re.compile(r"手腕|腕")),
    "ankle": Rule("ankle", re.compile(rf"{_JUMP}|跑步|慢跑|冲刺"), ("不疼",),
                  "他脚踝有伤",
                  "你脚踝有伤：先别做跑跳动作，换成骑车这类低冲击的有氧。",
                  "（脚踝有伤先别做）", "（脚踝有伤：跑跳先别做）", re.compile(r"脚踝|踝|跟腱")),
    "neck": Rule("neck", re.compile(r"颈后|倒立"), (), "他颈部不舒服",
                 "你脖子不舒服：先别做颈后推举、颈后下拉和倒立。", "（脖子不舒服先别做）", "",
                 re.compile(r"颈|脖子")),
}  # fmt: skip
INTENSITY = Rule(
    "readiness",
    re.compile(
        r"大重量|高强度间歇|HIIT|冲刺|力竭|极限|最大重量|冲重量|冲击 ?PR|测(?:试)? ?1RM|间歇跑"
    ),
    # "等"既是"等恢复了再练"也是"深蹲、硬拉等"：只认"等状态、等恢复"这类写法
    ("下次", "恢复后", "状态好", "改天", "明天", "等状态", "等恢复", "等睡", "等你"),
    "他今天状态差或生病",
    "今天状态不好：别做大重量、高强度间歇和力竭训练，改成轻松版或休息。",
    "（今天状态不好：先别做）",
)
BLOOD = Rule(
    "blood_pressure",
    re.compile(r"大重量|憋气|屏气|力竭|极限重量|最大重量|测(?:试)? ?1RM|倒立"),
    ("呼气", "呼吸", "医生", "评估", "许可"),
    "他血压偏高",
    "血压偏高：别做大重量和憋气发力，加大训练前先找医生评估。",
    "（血压偏高：先别做）",
    "",
    re.compile(r"血压"),
)
PREGNANCY = Rule(
    "pregnancy",
    re.compile(rf"仰卧起坐|卷腹|平躺|仰卧|{_JUMP}|憋气|屏气|大重量|卧推"),
    ("侧卧", "上斜", "坐姿"),
    "她在孕期",
    "孕期：避免仰卧动作（改成侧卧或上斜）、跳跃和憋气发力；出现出血、腹痛、头晕等立即停止并就医。",
    "（孕期先别做）",
    "",
    re.compile(r"孕"),
)
_BP_RISKS = frozenset({"bp_crisis", "bp_high", "hypertension"})

_KCAL = re.compile(r"(\d{3,4})(?:\s*[-–~至到]\s*(\d{3,4}))?\s*(?:千卡|大卡|kcal|卡路里)")
_DAILY = re.compile(r"每天|每日|一天|全天|日摄入|热量目标|目标热量|总热量|总摄入")
_NOT_INTAKE = re.compile(
    r"消耗|燃烧|基础代谢|少吃|缺口|赤字|差额|减少|多吃|盈余|超出|高出|低于|以上|不要|别|不低于"
)
_RATE = re.compile(
    r"(?:每周|一周|每星期|一星期)(?:能|可以|要|争取|目标)?(?:减|瘦|掉|降)(?:重|脂|体重)?"
    r"(?:约|大约|大概|差不多)?\s*"
    r"(\d+(?:\.\d+)?)\s*(?:[-–~至到]\s*(\d+(?:\.\d+)?))?\s*(公斤|千克|kg|斤)"
)
RATE_FIX = "每周减重控制在 0.5–1 公斤以内更容易保持，也更少掉肌肉。"


@dataclass(frozen=True)
class Violation:
    kind: str
    detail: str  # 给模型的改写说明
    fix: str  # 改写后仍不过关时补在回答末尾的一句


@dataclass(frozen=True)
class Context:
    injuries: tuple[str, ...] = ()
    poor: bool = False  # 今天状态差或生病
    risks: frozenset[str] = frozenset()
    floor: int = 1200  # 每日摄入下限

    @classmethod
    def of(cls, case: CaseFile) -> Context:
        sex_floor = 1500 if case.profile.sex == "male" else 1200
        floor = max(sex_floor, round(case.bmr)) if case.bmr else sex_floor
        return cls(
            injuries=case.injuries,
            poor=case.readiness.level == "poor" or case.readiness.sick,
            risks=frozenset(x.key for x in case.risks),
            floor=floor,
        )


def _clause_at(text: str, pos: int) -> str:
    for c in _CLAUSE.finditer(text):
        if c.start() <= pos < c.end():
            return c.group(0).strip()
    return ""


def _rule(text: str, rule: Rule) -> Violation | None:
    bad = rule.bad(text)
    if not bad:
        return None
    where = "、".join(f"「{_clause_at(text, a)[:24]}」里的“{m}”" for a, _, m in bad[:MAX_SHOWN])
    detail = (
        f"{rule.why}，{where}没有写明限制：写明怎么做才安全（控制深度或幅度、轻重量、换成哪个替代动作），"
        "确实不适合才说先别做；也可以在前面用一句话总的说明（提到这个部位或情况并写明限制）。前后说法要一致"
    )
    return Violation(rule.kind, detail, rule.fix)


def _calories(text: str, floor: int) -> Violation | None:
    for clause in _CLAUSE.findall(text):
        if not _DAILY.search(clause) or _NOT_INTAKE.search(clause):
            continue
        for m in _KCAL.finditer(clause):
            low = min(int(v) for v in m.groups() if v)
            if 800 <= low < floor:
                return Violation(
                    "calories",
                    f"「{clause.strip()[:24]}」建议每天吃 {low} 千卡，低于这个人的下限 {floor} 千卡（基础代谢与安全下限）",
                    f"每天吃的热量不要低于 {floor} 千卡（基础代谢和安全下限），太低会掉肌肉、影响健康。",
                )
    return None


_RATE_OK = re.compile(r"太快|不要|别|不建议|避免|超过|以内|不宜")


def _rate(text: str) -> Violation | None:
    for clause in _CLAUSE.findall(text):
        if _RATE_OK.search(clause):
            continue
        for m in _RATE.finditer(clause):
            high = float(m.group(2) or m.group(1))
            kg = high / 2 if m.group(3) == "斤" else high
            if kg > 1:
                return Violation(
                    "weight_rate", f"「{m.group(0)}」每周减重超过 1 公斤，太快", RATE_FIX
                )
    return None


def _rules(ctx: Context) -> list[Rule]:
    rules = [INJURY_RULES[k] for k in ctx.injuries if k in INJURY_RULES]
    if ctx.poor:
        rules.append(INTENSITY)
    if ctx.risks & _BP_RISKS:
        rules.append(BLOOD)
    if "pregnancy" in ctx.risks:
        rules.append(PREGNANCY)
    return rules


def check(text: str, ctx: Context) -> list[Violation]:
    """回答（给用户看的正文）违反了哪些约束；为空表示通过。"""
    found = [v for rule in _rules(ctx) if (v := _rule(text, rule))]
    found += [v for v in (_calories(text, ctx.floor), _rate(text)) if v]
    return found


def annotate(text: str, ctx: Context) -> str:
    """改写后仍不过关时：在不过关的动作、热量、减重速度后面直接注明限制（不调用模型）。

    伤病、孕期、血压这类，注明的那句话本身就是总的说明，后面同类的动作不再重复注明；
    今天状态差这类，每一处都注明。
    """
    out = text
    for rule in _rules(ctx):
        for _ in range(
            MAX_NOTES
        ):  # 每注明一处，重新看还有没有没照顾到的（注明的话本身可能就是总的说明）
            bad = rule.bad(out)
            if not bad:
                break
            _, end, matched = bad[0]
            out = out[:end] + rule.note_for(matched) + out[end:]

    def fix(m: re.Match[str]) -> str:
        clause = m.group(0)
        if _DAILY.search(clause) and not _NOT_INTAKE.search(clause):
            for k in _KCAL.finditer(clause):
                if 800 <= min(int(v) for v in k.groups() if v) < ctx.floor:
                    note = f"（太低了：每天不要低于 {ctx.floor} 千卡）"
                    return clause[: k.end()] + note + clause[k.end() :]
        rate = _RATE.search(clause)
        if rate and _rate(rate.group(0)):
            return (
                clause[: rate.end()] + "（太快了：每周 0.5–1 公斤以内更稳）" + clause[rate.end() :]
            )
        return clause

    return _CLAUSE.sub(fix, out)


def annotate_plan(plan: Plan, ctx: Context) -> Plan:
    """计划里每个动作单独核对：有伤病、孕期、血压偏高时，没写限制的动作在备注里注明（限制写在前面，
    备注再长也不会被截掉）。今天状态差是当天的事，不写进长期的周计划。"""
    rules = [r for r in _rules(ctx) if r is not INTENSITY]
    sessions = []
    for s in plan.sessions:
        items = []
        for x in s.items:
            line = " ".join(v for v in (x.exercise, x.load, x.note) if v)
            notes = [
                rule.note_for(m).strip("（）") for rule in rules for _, _, m in rule.bad(line)[:1]
            ]
            if notes:
                note = "；".join(n for n in dict.fromkeys([*notes, x.note]) if n)
                x = x.model_copy(update={"note": note[:80]})
            items.append(x)
        sessions.append(s.model_copy(update={"items": items}))
    return plan.model_copy(update={"sessions": sessions})


def fixes(violations: Sequence[Violation]) -> str:
    """改写后仍不过关时补在回答末尾的话（固定文字，去重）。"""
    return "".join(dict.fromkeys(v.fix for v in violations))
