"""共享档案（spec [2026-10-23] §2、§5）：每轮作答前用规则拼一份这个人的档案，被请到的专业角色都拿到同一份。

档案里有基本情况、限制（来自记忆）、今天的身体数据（数值和与他自己平时的差，不定级，§182）、风险提示、指标计算结果；不调用模型。
档案里的数字都带编号（C 开头，与"依据与来源"里的计算同一套），回答引用时照常逐句核对：
C0 是档案的基本情况，C1… 是指标计算（与数据页同一份、同样的编号），最后一个是今天的身体数据。
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from ironm_agent import facts as _facts
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import Recall, until_text
from ironm_agent.metrics import ACTIVITY, GOALS, Metric, Point, Profile, Readings
from ironm_agent.safety.subject import subject_of

LIMIT_CATEGORIES = ("injury", "special", "equipment", "schedule", "diet", "goal", "event")


@dataclass(frozen=True)
class Snapshot:
    """这一轮读到的这个人的数据：档案、每天的健康数据、指标计算（与数据页同一份）。"""

    profile: Profile = field(default_factory=Profile)
    readings: Readings = field(default_factory=Readings)
    metrics: tuple[Metric, ...] = ()
    today: date = field(default_factory=date.today)
    failed: bool = False  # 没读到数据（不影响作答，只是档案里没有数据）


# ---- 今天的身体数据 ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Readiness:
    """今天的身体数据（§182 需求 7）：只给数值和与他自己平时的差，不定级（不写好、一般、差），
    练不练、按几成由管家看这些数和他说的自己判断。"""

    facts: tuple[str, ...] = ()
    sick: bool = False  # 这句话说生病了（安全护栏：回答里不给大重量、高强度、力竭）
    current: bool = False  # 最近 3 天有睡眠或心率记录

    def line(self) -> str:
        return "今天的身体数据：" + ("；".join(self.facts) if self.facts else "没有")


_SICK = re.compile(r"发烧|发热|感冒|生病|拉肚子|腹泻|嗓子疼|咳嗽|流鼻涕|病了")
# 否定或已经好了："没有发烧""不累""感冒好了"
_NEGATION = re.compile(r"(?:没有|没|不是|不|并不|也不|无)\s*$")
_RECOVERED = re.compile(r"^\s*(?:已经)?好了|^\s*好多了|^\s*已经好")


_CLAUSE_OF = re.compile(r"[^，,。！？?；;\n]+")


def _own(text: str, pos: int) -> bool:
    """这个位置所在的分句说的是本人（"我妈感冒了，我今天练什么"里感冒的是妈妈）。"""
    for c in _CLAUSE_OF.finditer(text):
        if c.start() <= pos < c.end():
            return subject_of(c.group(0)) == "self"
    return True


def _said(pattern: re.Pattern[str], text: str) -> bool:
    """这句话里本人说到了这种情况，而且不是否定的、也不是已经好了的。"""
    for m in pattern.finditer(text):
        before, after = text[max(0, m.start() - 3) : m.start()], text[m.end() : m.end() + 5]
        if not _NEGATION.search(before) and not _RECOVERED.search(after) and _own(text, m.start()):
            return True
    return False


said = _said  # 生病记录也用这一套判断（spec [2026-10-23] §46）

def _recent(points: Sequence[Point], today: date, days: int) -> list[float]:
    return [v for d, v in points if 0 <= (today - d).days < days]


def _baseline(points: Sequence[Point], today: date) -> tuple[float, float] | None:
    """本人基线：7 天前往回 60 天的平均与标准差；不到 14 天不算。"""
    old = [v for d, v in points if 7 <= (today - d).days < 67]
    if len(old) < 14:
        return None
    return statistics.fmean(old), statistics.pstdev(old)


def _f(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def _when(d: date, today: date) -> str:
    return "今天" if d == today else f"{d.month} 月 {d.day} 日"


def _vs(now: float, mean: float, unit: str, up: str, down: str, *, places: int = 1, pct: bool = False) -> str:
    """和他自己平时比的差："你平时 55 次/分，高 7 次/分"；pct 时差按百分比。"""
    num = (lambda x: f"{x:.0f}") if places == 0 else _f
    diff = (now - mean) / mean * 100 if pct and mean else now - mean
    size = f"{abs(diff):.0f}" if pct else num(abs(diff))
    if size == "0":
        return f"你平时 {num(mean)}{unit}，和平时一样"
    return f"你平时 {num(mean)}{unit}，{up if diff > 0 else down} {size}{'%' if pct else unit}"


def readiness(r: Readings, text: str, today: date, *, illness: str = "") -> Readiness:
    """今天的身体数据：最近一晚睡眠、最近 3 天的静息心率与心率变异性，各自和他自己平时（7 天前往回 60 天）比，
    带日期（不是今天的写哪天）。只算事实，不定级、不贴"恢复不够、睡得少"这类标签（§182 需求 7）。
    illness：正在进行的生病（事实，§163）；text 只用来认这句话本人说生病了（回答核对的安全护栏）。"""
    facts: list[str] = []
    current = False
    nights = [(d, v) for d, v in sorted(r.sleep_hours) if 0 <= (today - d).days < 3]
    if nights:
        current = True
        d, v = nights[-1]
        line = f"睡眠：最近一晚（{_when(d, today)}）{_f(v)} 小时"
        if len(nights) >= 2:
            line += f"，最近 {len(nights)} 晚平均 {_f(statistics.fmean(x for _, x in nights))} 小时"
        base = _baseline(r.sleep_hours, today)
        if base:
            line += f"，{_vs(v, base[0], ' 小时', '多', '少')}"
        facts.append(line)
    for points, name, unit, pct in (
        (r.resting_hr, "静息心率", " 次/分", False),
        (r.hrv_sdnn, "心率变异性（SDNN）", " 毫秒", True),
        (r.hrv_rmssd, "心率变异性（RMSSD）", " 毫秒", True),
    ):
        recent = [(d, v) for d, v in sorted(points) if 0 <= (today - d).days < 3]
        if not recent:
            continue
        current = True
        now = statistics.fmean(v for _, v in recent)
        last = recent[-1][0]
        line = f"{name}：最近 3 天平均 {now:.0f}{unit}" + (
            "" if last == today else f"（最近一次 {_when(last, today)}）"
        )
        base = _baseline(points, today)
        line += (
            f"，{_vs(now, base[0], unit, '高', '低', places=0, pct=pct)}"
            if base
            else "，你平时的记录还不到 14 天，暂不比较"
        )
        facts.append(line)
    if not current:
        dates = [
            d for pts in (r.sleep_hours, r.resting_hr, r.hrv_sdnn, r.hrv_rmssd) for d, _ in pts
        ]
        latest = max(dates) if dates else None
        facts.append(
            f"最近 3 天没有睡眠、心率记录（最近一次是 {latest.month} 月 {latest.day} 日）"
            if latest
            else "还没有睡眠、心率记录"
        )
    if illness:
        facts.append(f"生病：{illness}")
    return Readiness(tuple(facts), _said(_SICK, text), current)


# ---- 风险提示（数据与记忆，§5）--------------------------------------------------------------


@dataclass(frozen=True)
class Risk:
    key: str  # bp_crisis / bp_high / rhr_high / pregnancy / cardiac / surgery / diabetes / hypertension
    note: str  # 固定提醒：回答开头一句
    block: bool = False  # 问训练、动作、恢复时这一轮不给训练安排

    @property
    def brief(self) -> str:
        """给专业角色看的简短说明（提醒原文已经放在回答开头，免得照抄一遍）。"""
        return RISK_BRIEFS.get(self.key, self.key)


RISK_BRIEFS = {
    "bp_crisis": "最近一次血压很高，已提醒尽快就医：不安排任何运动",
    "bp_high": "最近血压偏高：不安排大重量和憋气发力，加大训练前先请医生评估",
    "rhr_high": "最近静息心率偏高：加大训练前先请医生看看",
    "pregnancy": "孕期：不安排仰卧动作、跳跃和憋气发力",
    "cardiac": "有心脏方面的情况：加大强度前先请心内科医生评估",
    "diabetes": "有糖尿病：留意运动前后的血糖",
    "hypertension": "有高血压：不憋气、不做大重量",
    "surgery": "近期做过手术：恢复训练前先请主治医生确认",
}


def _bp_worst(
    r: Readings, today: date, days: int, sys_cut: float, dia_cut: float
) -> tuple[date, float, float] | None:
    """窗口里达到这一档的读数中最严重的一次（不只看最新一次：三天前 190/115、今天 158/98 也要提醒）。"""
    dia = dict(r.diastolic)
    pairs = [(d, s, dia[d]) for d, s in r.systolic if d in dia and 0 <= (today - d).days < days]
    over = [x for x in pairs if x[1] >= sys_cut or x[2] >= dia_cut]
    return max(over, key=lambda x: (max(x[1] / sys_cut, x[2] / dia_cut), x[0])) if over else None


_MEMORY_RISKS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("pregnancy", re.compile(r"怀孕|孕\s*\d+\s*周|孕期|孕妇|孕中|孕晚|孕早"),
     "孕期运动：避免仰卧动作、跳跃和憋气发力；出现出血、腹痛、头晕、宫缩等立即停止并就医，训练安排先和产检医生确认。"),
    ("cardiac", re.compile(r"心脏病|冠心病|心梗|心肌梗|支架|搭桥|心衰|心律失常|房颤|心肌炎"),
     "你有心脏方面的情况：加大运动强度前先请心内科医生评估；运动中胸闷、胸痛、心慌、头晕立即停止。"),
    ("diabetes", re.compile(r"糖尿病"),
     "你有糖尿病：运动前后留意血糖、随身带糖；用胰岛素或降糖药时别空腹练。"),
    ("hypertension", re.compile(r"高血压"),
     "你有高血压：训练时别憋气、不做大重量，运动强度先请医生评估。"),
    ("surgery", re.compile(r"手术"),
     "你近期做过手术：恢复训练前先请主治医生确认。"),
)  # fmt: skip
SURGERY_DAYS = 90


def _since(item: Item) -> date:
    """术后从第一次记的那天算（更新会新建一条，不重新计时，§148）。"""
    try:
        return date.fromisoformat(str(item.data.get("since") or ""))
    except ValueError:
        return item.created.date()


def risks(r: Readings, memory: Sequence[Item], today: date) -> tuple[Risk, ...]:
    out: list[Risk] = []
    crisis = _bp_worst(r, today, 14, 180, 110)
    high = _bp_worst(r, today, 30, 160, 100)
    if crisis:
        d, s, dia = crisis
        out.append(Risk("bp_crisis", f"你 {d.month} 月 {d.day} 日测的血压是 {s:.0f}/{dia:.0f} mmHg，已经很高：先别运动，尽快就医；如果有胸痛、剧烈头痛、视物模糊、说话不清，立即拨打 120。", block=True))  # fmt: skip
    elif high:
        d, s, dia = high
        out.append(Risk("bp_high", f"你 {d.month} 月 {d.day} 日测的血压是 {s:.0f}/{dia:.0f} mmHg，偏高：加大训练前先找医生评估；训练时别憋气、不做大重量。"))  # fmt: skip
    hr = _recent(r.resting_hr, today, 7)
    if hr and statistics.fmean(hr) > 100:
        out.append(Risk("rhr_high", f"你最近 7 天平均静息心率 {statistics.fmean(hr):.0f} 次/分，偏高：先找医生看看，再加大训练。"))  # fmt: skip
    seen = {x.key for x in out}
    notes = {k: n for k, _, n in _MEMORY_RISKS}
    from ironm_agent.latest import current

    for item in current(memory):  # 结构化的（§148）；同一处以最近说的为准（§158）：伤病、特殊情况带的代码，伤病类型是术后
        if item.status != "active" or not item.data or item.category not in _facts.STRUCTURED:
            continue
        codes = _facts.codes_of(item.data)
        if item.category == "injury" and item.data.get("kind") == "术后":
            codes = [*codes, "surgery"]
        for code in dict.fromkeys(codes):
            if code in seen or code not in notes:
                continue
            if code == "surgery" and (today - _since(item)).days > SURGERY_DAYS:
                continue
            if code == "hypertension" and seen & {"bp_crisis", "bp_high"}:
                continue
            seen.add(code)
            out.append(Risk(code, notes[code]))
    for item in memory:  # 还没补字段的旧记忆：照旧按句子认
        if item.category != "injury" or item.status != "active" or item.data:
            continue
        for key, pattern, note in _MEMORY_RISKS:
            if key in seen or not pattern.search(item.content):
                continue
            if key == "surgery" and (today - item.created.date()).days > SURGERY_DAYS:
                continue
            if key == "hypertension" and seen & {"bp_crisis", "bp_high"}:
                continue
            seen.add(key)
            out.append(Risk(key, note))
    return tuple(out)


# ---- 伤病部位（§4 约束核对用）---------------------------------------------------------------

# 部位（关节编码）、疼痛和体态的说法和结构化字段共用一份（facts.py，§148 补了髋和手肘）
PARTS = _facts.PARTS
_PAIN = _facts.PAIN
NEAR_PAIN = 8  # 部位和疼痛的说法相隔几个字以内才算一起说的
_POSTURE = _facts.POSTURE


def _hurts(part: re.Pattern[str], text: str) -> bool:
    for m in part.finditer(text):
        if not _own(text, m.start()):
            continue
        window = text[max(0, m.start() - NEAR_PAIN) : m.end() + NEAR_PAIN]
        offset = max(0, m.start() - NEAR_PAIN)
        for pain in _PAIN.finditer(window):
            before = text[max(0, offset + pain.start() - 3) : offset + pain.start()]
            if not _NEGATION.search(before):
                return True
    return False


def injured_parts(memory: Sequence[Item], text: str) -> tuple[str, ...]:
    """有伤病的部位：记忆里有效的伤病（读字段，§148；没字段的旧记忆按句子认，只说体态的不算，§108），
    加上这句话里本人说正疼的部位（"深蹲会影响膝盖吗""膝盖不疼""我妈膝盖疼"都不算）。"""
    found = _facts.injured(memory)
    found += [k for k, p in PARTS.items() if _hurts(p, text)]
    return tuple(dict.fromkeys(found))


# ---- 档案 -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseFile:
    basics: str  # 基本情况（一行）
    limits: tuple[str, ...]  # 来自记忆的限制
    readiness: Readiness
    risks: tuple[Risk, ...]
    calcs: dict[str, str]  # 编号 → 说明（含数字；核对与"依据与来源"用）
    calc_lines: tuple[str, ...]  # 给角色看的一行一个计算结果
    injuries: tuple[str, ...]
    profile: Profile
    bmr: float | None
    plan: tuple[str, ...] = ()  # 当前计划与最近的训练记录（§9）
    readiness_id: str = ""
    plan_id: str = ""
    today: date | None = None
    weather: str = ""  # 现在的天气与对训练的影响（spec [2026-10-23] §13；取不到时为空）
    day: tuple[str, ...] = ()  # 今日状态（spec [2026-10-23] §54）：打卡、口头说的状态、生病、说疼
    insights: tuple[tuple[str, str], ...] = ()  # 指标解读（§84）：(编号, 一句话)，依据在 calcs 里
    sore: tuple[str, ...] = ()  # 最近 3 天说过疼的部位（§158）：只给排计划、换动作的工具避开，不当成伤病写进回答

    def text(self, *, calcs: bool = True) -> str:
        lines = [
            "这个人的档案（系统每轮整理，被请到的专业角色看到的都一样；回答要和它一致，用到其中的数字时写上编号）：",
            f"- 基本：{self.basics}〔C0〕",
        ]
        if self.today is not None:
            head = f"- 今天：{self.today.isoformat()}（周{'一二三四五六日'[self.today.weekday()]}）"
            if self.day:  # 今天的状态以这里为准（spec [2026-10-23] §54）
                lines.append(
                    head
                    + "，今天的状态以这里为准（比对话里更早的说法新；他这一句刚说的更新，冲突时按他这一句）："
                )
                lines += [f"  {x}" for x in self.day]
            else:
                lines.append(head)
        if self.weather:
            lines.append(f"- {self.weather}（安排户外运动、饮食和补水时要照顾到）")
        if self.limits:
            lines.append("- 限制与情况（他说过的，作答时要照顾到）：" + "；".join(self.limits))
        ref = f"〔{self.readiness_id}〕" if self.readiness_id else ""
        lines.append(
            f"- {self.readiness.line()}{ref}（代码只算数、不下结论：今天练不练、按几成，由你看这些数和他说的自己判断；"
            "只在安排今天的训练或问恢复时用）"
        )
        if self.insights:  # 读懂指标趋势（§84）：最近和之前比的变化、同期发生的事、已经做的调整（不贴标签，§182）
            lines.append(
                "- 指标解读（代码算的事实：最近 7 天和他自己之前比、同期发生的事，和管家今天已经做的调整；"
                "代码不下结论，好不好由你判断；问到数据、状态、为什么这样调时用，只说可能有关、不说成因果）："
            )
            lines += [f"  [{cid}] {line}" for cid, line in self.insights]
        if self.risks:
            lines.append(
                "- 风险（系统已经在回答开头提醒过，你不用再提，但建议必须符合它）："
                + "；".join(x.brief for x in self.risks)
            )
        if self.plan:
            lines.append(
                f"- 计划与训练记录〔{self.plan_id}〕（他确认过的；回答要照着它说，用到其中的组数次数时写这个编号）："
            )
            lines += [f"  {x}" for x in self.plan]
        if calcs and self.calc_lines:
            lines.append("- 指标计算（与 App 数据页同一份）：")
            lines += [f"  {x}" for x in self.calc_lines]
        return "\n".join(lines)


def _basics(p: Profile, metrics: Sequence[Metric], today: date, target: str = "") -> str:
    parts = []
    if p.sex:
        parts.append("男" if p.sex == "male" else "女")
    age = p.age(today)
    if age is not None:
        parts.append(f"{age} 岁")
    if p.height_cm:
        parts.append(f"身高 {_f(p.height_cm)} 厘米")
    weight = next((m for m in metrics if m.key == "weight" and m.value is not None), None)
    if weight is not None and weight.value is not None:
        parts.append(f"最新体重 {_f(weight.value)} 公斤")
    goal = f"目标{GOALS[p.goal]}" if p.goal else "目标未填写"
    parts.append(goal + (f"；目标体重：{target}" if target else ""))  # 正式的两处拼成一行（§151）
    if p.activity:
        parts.append(f"日常活动：{ACTIVITY[p.activity][0]}")
    return "，".join(parts) if parts else "档案还没有填写"


def build(
    snapshot: Snapshot,
    recall: Recall,
    text: str,
    *,
    plan: Sequence[str] = (),
    illness: str = "",
    day: Sequence[str] = (),
    insights: Sequence[tuple[str, str]] = (),
    target: str = "",
    sore: Sequence[str] = (),
) -> CaseFile:
    """insights：指标解读（§84），每条是 (给角色看的一句话, 追问依据时讲的详细说法)。
    sore：最近 3 天说过疼的部位（§158），和记着的伤病一样避开。"""
    p, today = snapshot.profile, snapshot.today
    metrics = list(snapshot.metrics)
    calcs: dict[str, str] = {}
    lines: list[str] = []
    for i, m in enumerate(metrics, start=1):  # 与 compute_metrics 工具同样的编号
        if m.value is None:
            lines.append(f"- {m.name}：算不出来，{m.text}")
            continue
        cid = f"C{i}"
        calcs[cid] = f"{m.name}：{m.text}。计算：{m.how}。数据：{m.data}。依据：{m.source}"
        lines.append(f"[{cid}] {m.name}：{m.text}")
    basics = _basics(p, metrics, today, target) + (
        "（这次没读到你的档案和健康数据）" if snapshot.failed else ""
    )
    calcs["C0"] = f"档案：{basics}"
    state = readiness(snapshot.readings, text, today, illness=illness)
    if snapshot.failed and not state.current:
        state = Readiness(("这次没读到你的健康数据", *state.facts[1:]), state.sick)
    rid = f"C{len(metrics) + 1}"
    calcs[rid] = state.line()
    limits = tuple(
        f"{x.content}"
        + (
            f"（{_local(x.created).month} 月 {_local(x.created).day} 日说的{until_text(x)}）"
            if x.category == "event"
            else ""
        )
        + ("（已解决）" if x.status == "resolved" else "")
        for x in recall.items
        if x.category in LIMIT_CATEGORIES
    )
    bmr = next((m.value for m in metrics if m.key == "bmr" and m.value is not None), None)
    plan_id = ""
    if plan:
        plan_id = f"C{len(metrics) + 2}"
        calcs[plan_id] = "计划与训练记录：" + "；".join(plan)
    found: list[tuple[str, str]] = []
    for i, (line, detail) in enumerate(insights):
        cid = f"C{len(metrics) + 3 + i}"
        calcs[cid] = f"指标解读：{detail}"
        found.append((cid, line))
    return CaseFile(
        basics=basics,
        limits=limits,
        readiness=state,
        risks=risks(snapshot.readings, recall.items, today),
        calcs=calcs,
        calc_lines=tuple(lines),
        injuries=injured_parts(recall.items, text),
        profile=p,
        bmr=bmr,
        plan=tuple(plan),
        readiness_id=rid,
        plan_id=plan_id,
        today=today,
        day=tuple(day),
        insights=tuple(found),
        sore=tuple(dict.fromkeys(sore)),
    )


def _local(at: datetime) -> date:
    return at.astimezone().date()
