"""改计划用固定操作（spec [2026-10-23] §45）：换动作、挪天、改组次、删、整体减量。

操作由规则（简单句式、每周复盘、首页提醒）或训练教练给出，由代码套到当前计划上：只改指定的地方，
改了什么、没改成的原因、对每周组数的影响都由代码算。不调用模型、不读写存储。
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator

from ironm_agent.exercises import Equipment
from ironm_agent.protools.movement import (
    JOINT_NAMES,
    Move,
    equipment_ok,
    find,
    ranked,
    stressed,
)
from ironm_agent.protools.plan_check import (
    MAJOR,
    SLACK,
    back_to_back,
    estimate_minutes,
    weekly_sets,
)
from ironm_agent.training import WEEKDAYS, Plan, PlanItem, Session, _Model, weekday_name

MAX_ITEMS = 8  # 加动作后一天最多几个（时长超了 fit_time 再减辅助动作）
type OpKind = Literal["remove", "move", "swap", "add", "edit", "reduce"]
ORDER: tuple[OpKind, ...] = (
    "remove",
    "move",
    "swap",
    "add",
    "edit",
    "reduce",
)  # 同一句里几条操作的套用顺序
LIGHT = 0.7  # "轻一点"
LIGHTER = 0.5  # "轻很多"
REVIEW_MAX_DAYS = 2  # 复盘、提醒自动提议的改动每次最多改几天（§18）

_DAY = {c: i for i, c in enumerate(WEEKDAYS, start=1)} | {"天": 7}


def day_of(value: Any) -> int | None:
    """1–7、"周三"、"星期三" 都认；认不出时返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1 <= value <= 7 else None
    text = str(value or "").strip()
    if text.isdigit():
        return day_of(int(text))
    m = re.search(r"(?:周|星期|礼拜)([一二三四五六日天])", text)
    return _DAY[m.group(1)] if m else None


class Op(_Model):
    kind: OpKind
    day: int | None = None  # 哪天（1 是周一）；减量时为空表示整份计划
    exercise: str = Field(default="", max_length=30)  # 换、加、改、删某个动作时写
    to: str = Field(default="", max_length=30)  # 换动作：换成什么
    to_day: int | None = None  # 挪天：挪到哪天
    sets: int | None = Field(default=None, ge=1, le=10)
    reps: str | None = Field(default=None, max_length=20)
    load: str | None = Field(default=None, max_length=40)
    minutes: int | None = Field(default=None, ge=10, le=180)
    ratio: float | None = Field(default=None, gt=0, lt=1)  # 减量的比例
    weight: bool = False  # 减量时连重量一起减（用户明说"重量"）
    why: str = Field(default="", max_length=60)

    @field_validator("day", "to_day", mode="before")
    @classmethod
    def _day(cls, v: Any) -> Any:
        return None if v in (None, "") else day_of(v)

    @field_validator("reps", mode="before")
    @classmethod
    def _reps(cls, v: Any) -> Any:
        return str(v) if isinstance(v, int | float) and not isinstance(v, bool) else v


def parse_ops(raw: Any) -> list[Op] | None:
    """训练教练写的操作列表；不是列表、或有一条不合格时返回 None（交给整份生成）。"""
    if not isinstance(raw, list) or not raw:
        return None
    try:
        return [Op.model_validate(x, strict=False) for x in raw]
    except (ValidationError, TypeError):
        return None


class Conflict(ValueError):
    """同一句话里的操作互相矛盾（删掉周五又改周五、同一天挪去两个地方）：不猜，请用户说清楚。"""


@dataclass
class Applied:
    plan: Plan
    before: Plan
    done: list[Op] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # 每条套上的操作说了什么
    skipped: list[str] = field(default_factory=list)  # "这一条没改：原因"
    notes: list[str] = field(default_factory=list)  # 代码替用户做的修正（换掉不合适的动作、减组）
    touched: set[int] = field(default_factory=set)  # 改到的天

    @property
    def changes(self) -> str:
        return "；".join([*self.lines, *self.notes])


def _same(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ma, mb = find(a), find(b)
    return ma is not None and ma is mb


def _check_conflicts(ops: Sequence[Op]) -> None:
    gone = {o.day for o in ops if o.kind == "remove" and not o.exercise and o.day}
    others = {o.day for o in ops if o.kind in ("swap", "edit", "move") and o.day}
    clash = gone & others
    if clash:
        days = "、".join(weekday_name(d) for d in sorted(clash))
        raise Conflict(f"同一句里既要删掉{days}、又要改{days}的内容")
    sources = [o.day for o in ops if o.kind == "move" and o.day]
    twice = {d for d in sources if sources.count(d) > 1}
    if twice:
        days = "、".join(weekday_name(d) for d in sorted(twice))
        raise Conflict(f"同一句里要把{days}挪到两个不同的日子")


def _session(plan: list[Session], day: int | None) -> Session | None:
    return next((s for s in plan if s.day == day), None)


def _where(sessions: list[Session], op: Op) -> list[tuple[Session, int]]:
    """op 指的是哪几天的哪个动作；没写哪天时找计划里所有这个动作。那天找不到时（这句话里先把那天挪走了），
    按动作名到别的天找。"""

    def hits(day: int | None) -> list[tuple[Session, int]]:
        out = []
        for s in sessions:
            if day is not None and s.day != day:
                continue
            out += [(s, i) for i, x in enumerate(s.items) if _same(op.exercise, x.exercise)]
        return out

    found = hits(op.day)
    if found or op.day is None or any(s.day == op.day for s in sessions):
        return found  # 那天还在却没有这个动作：不跨天去找（§48）
    return hits(None)


def _pick(
    wanted: str,
    old: str,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str],
    taken: Collection[str] = (),
) -> tuple[str, str]:
    """换成的动作要在动作库里、器械他有、不压他的伤处；不合格时用替代动作的首选，并说明原因。
    taken：这一天已经有的动作，替代时跳过（同一天不重复，§48）。"""
    move = find(wanted)
    if move is not None and move.name in taken:
        return "", f"这一天已经有{move.name}了，这一条没改"
    if move is not None and equipment_ok(move, equipment) and not stressed(move, injured):
        return move.name, ""
    base: Move | None = move or find(old)
    if base is None:
        return "", f"动作库里没有「{wanted}」"
    if move is None:
        why = "动作库里没有它"
    elif not equipment_ok(move, equipment):
        why = f"它要用{'、'.join(move.exercise.equipment)}，你没有"
    else:
        why = "对你的" + "、".join(JOINT_NAMES[j] for j in stressed(move, injured)) + "不合适"
    was = find(old)
    if (
        move is not None
        and was is not None
        and was.tag.pattern == move.tag.pattern
        and equipment_ok(was, equipment)
        and not stressed(was, injured)
    ):
        return "", f"你要的{wanted}{why}，原来的{was.name}是同类动作、更适合你，这一条没改"
    alt = [
        m
        for m in ranked(base, equipment=equipment, injured=injured, k=6)
        if m.name != old and m.name not in taken
    ]
    if not alt:
        return "", f"「{wanted}」{why}，也没有比{old}更合适的替代，这一条没改"
    return alt[0].name, f"你要的{wanted}{why}，换成了{alt[0].name}"


def _canon(name: str) -> str:
    m = find(name)
    return m.name if m is not None else name


def _scale(sets: int, ratio: float) -> int:
    return max(1, int(sets * ratio + 0.5))


def apply(
    plan: Plan,
    ops: Sequence[Op],
    *,
    equipment: frozenset[Equipment] | None = None,
    injured: Collection[str] = (),
    blocked: Collection[int] = (),
) -> Applied:
    """按"先删、再挪、再换动作、再改组次、最后减量"的顺序套用；矛盾时抛 Conflict。
    blocked：用户说了没空的日子，不往这些天挪（§48）。"""
    _check_conflicts(ops)
    sessions = [s.model_copy(deep=True) for s in plan.sessions]
    out = Applied(plan, plan)
    for op in sorted(ops, key=lambda o: ORDER.index(o.kind)):
        line, why = _one(sessions, op, equipment, injured, out, blocked)
        if line:
            out.done.append(op)
            out.lines.append(line)
        elif why:
            out.skipped.append(why)
    try:
        out.plan = Plan.model_validate(
            {**plan.model_dump(), "sessions": [s.model_dump() for s in sessions]}
        )
    except ValidationError:
        out.plan, out.done, out.lines = plan, [], []
        out.skipped.append("改完的计划不合格（比如一天都没剩下），这次没改")
    return out


def _one(
    sessions: list[Session],
    op: Op,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str],
    out: Applied,
    blocked: Collection[int] = (),
) -> tuple[str, str]:
    """套一条操作：返回（说明, ""）或（"", 没改的原因）。"""
    day = weekday_name(op.day) if op.day else ""
    if op.kind == "remove":
        s = _session(sessions, op.day)
        if s is None:
            return "", f"{day or '那天'}本来就没有训练"
        if op.exercise:
            idx = [i for i, x in enumerate(s.items) if _same(op.exercise, x.exercise)]
            if not idx:
                return "", f"{day}没有{op.exercise}"
            name = s.items[idx[0]].exercise
            if len(s.items) > 1:
                del s.items[idx[0]]
                out.touched.add(s.day)
                return f"{day}去掉{name}", ""
        if len(sessions) == 1:
            return "", "计划里只剩这一天，不能删"
        sessions.remove(s)
        out.touched.add(s.day)
        return f"删掉{day}「{s.name}」", ""
    if op.kind == "move":
        s, to = _session(sessions, op.day), op.to_day
        if s is None or to is None or to == op.day:
            return "", f"{day or '那天'}没有训练可以挪" if s is None else "没说挪到哪天"
        if to in blocked:  # 他这句话里说了这天没空（§48）
            return "", f"你说{weekday_name(to)}不方便，没挪过去"
        other = _session(sessions, to)
        s.day = to
        out.touched |= {op.day or 0, to}
        if other is not None:
            other.day = op.day or other.day
            return f"{day}「{s.name}」和{weekday_name(to)}「{other.name}」对调", ""
        return f"{day}「{s.name}」挪到{weekday_name(to)}", ""
    if op.kind == "swap":
        hits = _where(sessions, op)
        if not hits or not op.to:
            return "", f"{day}没有{op.exercise}" if not hits else "没说换成什么"
        taken = {_canon(x.exercise) for hs, hi in hits for i, x in enumerate(hs.items) if i != hi}
        name, note = _pick(op.to, op.exercise, equipment, injured, taken)
        if not name:
            return "", note
        was = hits[0][0].items[hits[0][1]].exercise
        for hs, hi in hits:
            hs.items[hi] = hs.items[hi].model_copy(
                update={"exercise": name, "load": op.load or "", "note": ""}
            )
            out.touched.add(hs.day)
        if note:
            out.notes.append(note)
        days = "、".join(dict.fromkeys(weekday_name(hs.day) for hs, _ in hits))
        return f"{days}：{was} → {name}", ""
    if op.kind == "add":  # 给某天加一个动作（把一类动作挪到别的天时用，§48）
        s = _session(sessions, op.day)
        if s is None or not op.exercise:
            return "", f"{day or '那天'}没有训练" if s is None else "没说加什么动作"
        taken = {_canon(x.exercise) for x in s.items}
        name, note = _pick(op.exercise, op.exercise, equipment, injured, taken)
        if not name:
            return "", note
        if len(s.items) >= MAX_ITEMS:
            return "", f"{day}已经有 {len(s.items)} 个动作了，没再加{name}"
        s.items.append(
            PlanItem(exercise=name, sets=op.sets or 3, reps=op.reps or "8–12", load=op.load or "")
        )
        out.touched.add(s.day)
        if note:
            out.notes.append(note)
        return f"{day}加上{name}", ""
    if op.kind == "edit":
        if op.minutes is not None and not op.exercise:
            s = _session(sessions, op.day)
            if s is None:
                return "", f"{day or '那天'}没有训练"
            minutes_was, s.minutes = s.minutes, op.minutes
            out.touched.add(s.day)
            return f"{day}「{s.name}」时长 {minutes_was} → {op.minutes} 分钟", ""
        hits = _where(sessions, op)
        if not hits:
            return "", f"{day}没有{op.exercise or '要改的动作'}"
        update = {k: v for k, v in (("sets", op.sets), ("reps", op.reps), ("load", op.load)) if v}
        if not update:
            return "", "没说改成多少"
        before = hits[0][0].items[hits[0][1]].line()
        if all(getattr(hs.items[hi], k) == v for hs, hi in hits for k, v in update.items()):
            return "", f"{day}{hits[0][0].items[hits[0][1]].exercise}本来就是这样，没有变化"
        for hs, hi in hits:
            hs.items[hi] = hs.items[hi].model_copy(update=update)
            out.touched.add(hs.day)
        days = "、".join(dict.fromkeys(weekday_name(hs.day) for hs, _ in hits))
        return f"{days} {before} → {hits[0][0].items[hits[0][1]].line()}", ""
    # reduce
    ratio = op.ratio or LIGHT
    targets = [s for s in sessions if op.day is None or s.day == op.day]
    if not targets:
        return "", f"{day}没有训练"
    for ts in targets:
        ts.items = [
            x.model_copy(
                update={
                    "sets": _scale(x.sets, ratio),
                    **({"load": (x.load + "，" if x.load else "") + f"重量减到约{_cn(ratio)}"}
                       if op.weight else {}),
                }
            )
            for x in ts.items
        ]  # fmt: skip
        out.touched.add(ts.day)
    where = day or "每次训练"
    return f"{where}减量：组数按{_cn(ratio)}" + ("，重量也减" if op.weight else ""), ""


def _cn(ratio: float) -> str:
    return {LIGHT: "七成", LIGHTER: "一半"}.get(ratio, f"{round(ratio * 100)}%")


# ---- 套用后由代码修：时长超了从最后的辅助动作开始减（§45 需求 4）--------------------------------


def fit_time(applied: Applied, before: Plan | None = None) -> Applied:
    """只修这次改到、而且比改之前更长的那天：估计时长超过这天的时长时，先从最后的辅助动作开始逐个减组
    （每个先减到 2 组），都减到 2 组还超才再往下减、去掉辅助动作；一周里只有它练到某个主要肌群的动作不去掉
    （§48：挪过来的推的动作不能被减没）。原样挪过去的一天本来就超时，不替用户改（只改他要求的地方）。"""
    was = {s.name: estimate_minutes(s) for s in (before or applied.before).sessions}
    sessions = [s.model_copy(deep=True) for s in applied.plan.sessions]

    def groups(ss: list[Session]) -> set[str]:
        return {
            g for g in weekly_sets(applied.plan.model_copy(update={"sessions": ss})) if g in MAJOR
        }

    for s in sessions:
        if s.day not in applied.touched or estimate_minutes(s) <= was.get(s.name, 0):
            continue
        cut: dict[str, str] = {}
        while estimate_minutes(s) > s.minutes * SLACK:
            order = sorted(
                range(len(s.items)),
                key=lambda i: ((m := find(s.items[i].exercise)) is not None and m.compound, -i),
            )
            floor = 2 if any(s.items[i].sets > 2 for i in order) else 1
            i = next((i for i in order if s.items[i].sets > floor), None)
            if i is not None:
                name = s.items[i].exercise
                s.items[i] = s.items[i].model_copy(update={"sets": s.items[i].sets - 1})
                cut[name] = f"{name}减到 {s.items[i].sets} 组"
                continue
            have = groups(sessions)
            i = next(
                (i for i in order if len(s.items) > 1
                 and groups([x if x is not s else x.model_copy(update={"items": s.items[:i] + s.items[i + 1:]})
                             for x in sessions]) >= have),
                None,
            )  # fmt: skip
            if i is None:
                break  # 再减就丢掉整类训练：不减了，由计划检查提示超时
            cut[s.items[i].exercise] = f"去掉{s.items[i].exercise}"
            del s.items[i]
        if cut:
            applied.notes.append(
                f"{weekday_name(s.day)}估计超过 {s.minutes} 分钟，" + "、".join(cut.values())
            )
    applied.plan = applied.plan.model_copy(update={"sessions": sessions})
    return applied


# ---- 预览卡片上的差异（§45 需求 7）------------------------------------------------------------


def rows(old: Plan, new: Plan) -> list[dict[str, str]]:
    """只列有变化的行：项目、改前、改后。"""
    a, b = {s.day: s for s in old.sessions}, {s.day: s for s in new.sessions}
    out = []
    for d in range(1, 8):
        x, y = a.get(d), b.get(d)
        if x is None and y is None:
            continue
        if x is None or y is None:
            out.append({"what": weekday_name(d), "before": x.name if x else "休息",
                        "after": y.name if y else "休息"})  # fmt: skip
            continue
        if x.name != y.name:
            out.append({"what": weekday_name(d), "before": x.name, "after": y.name})
            if [i.exercise for i in x.items] != [i.exercise for i in y.items]:
                continue  # 整天换了内容，一行说清就够
        was = {i.exercise: _short(i) for i in x.items}
        now = {i.exercise: _short(i) for i in y.items}
        for k in was:
            if k not in now:
                out.append({"what": weekday_name(d), "before": was[k], "after": "去掉"})
        for k in now:
            if k not in was:
                out.append({"what": weekday_name(d), "before": "", "after": now[k]})
            elif was[k] != now[k]:
                out.append({"what": weekday_name(d), "before": was[k], "after": now[k]})
        if x.minutes != y.minutes:
            out.append({"what": weekday_name(d), "before": f"{x.minutes} 分钟",
                        "after": f"{y.minutes} 分钟"})  # fmt: skip
    return out


def _short(item: Any) -> str:
    """卡片上一行一个动作：名字和组次，重量说明有变化时才看得出（备注不放，太长）。"""
    return f"{item.exercise} {item.sets}×{item.reps}" + (f"（{item.load}）" if item.load else "")


def impact(old: Plan, new: Plan) -> list[str]:
    """改完对每周组数的影响，和新出现的提示（同一肌群连续两天、一周没练到）。"""
    a, b = weekly_sets(old), weekly_sets(new)
    out = []
    moved = [g for g in dict.fromkeys([*a, *b]) if a.get(g, 0) != b.get(g, 0)]
    if moved:
        out.append("每周组数：" + "、".join(f"{g} {a.get(g, 0)} → {b.get(g, 0)}" for g in moved))
    lost = [g for g in a if g not in b]
    if lost:
        out.append("一周里不再练到：" + "、".join(lost))
    adjacent = [g for g in back_to_back(new) if g not in back_to_back(old)]
    if adjacent:
        out.append("同一肌群连续两天练：" + "、".join(adjacent))
    return out


# ---- 简单句式由规则解析，不调用模型（§45 需求 2）-----------------------------------------------

_D = r"(?:周|星期|礼拜)([一二三四五六日天])"
_MOVE = re.compile(rf"把?{_D}(?:的(?:训练|课))?(?:挪|移|换|调|改)到{_D}")
_REMOVE_DAY = re.compile(rf"把?{_D}(?:的(?:训练|课))?(?:删掉|删了|删除|去掉|取消|不练了?|空出来)")
_REMOVE_ITEM = re.compile(rf"把?{_D}的?([^，。,、]{{2,12}}?)(?:删掉|删了|去掉|不做了?|不要了?)")
_REDUCE = re.compile(
    r"(?:这周|本周|计划|整体|全部|都|每次)?[^，。]{0,6}?"
    r"(?:轻一?点|轻松一?点|减一?点量|减量|少练一?点|轻很多|轻一半|减半|大幅减量)"
)
_MUCH = re.compile(r"轻很多|轻一半|减半|大幅")
_FILLER = re.compile(
    r"[\s，。,.！!、；;]|帮我|麻烦|请|吧|一下|然后|再|并且|还有|和|也|呢|啊|好吗|可以吗"
)
_ONLY_NOW = re.compile(r"今天|今晚|今早|这次|这一次|这一练|现在")
_FOREVER = re.compile(r"以后|每周|固定|一直|长期|之后|往后|计划")


NEW_PLAN = re.compile(
    r"重新排|重排|新排|重新做|重新制定|重做|从头|换个计划|新计划|再排一份"
    r"|(?:换成|改成|改为).{0,6}(?:分化|上下肢|推拉腿|全身练|全身训练)"
)
_SCOPE_HINT = "只想改这一次的话，跟我说「只改今天」。"


_BUSY = re.compile(r"练不了|不能练|不练|没空|没时间|出差|有事|不在家|不在|去不了")
_WEEKEND = re.compile(r"周末")
_NAMED_DAY = re.compile(r"(?:周|星期|礼拜)([一二三四五六日天])")


def blocked_days(text: str) -> set[int]:
    """这句话里说了没空的日子（"这周末出差，周五练不了" → 周五、周六、周日），挪动训练时不往这些天挪（§48）。"""
    out: set[int] = set()
    for clause in re.split(r"[，。,；;！？!?\n]", text):
        if not _BUSY.search(clause):
            continue
        if _WEEKEND.search(clause):
            out |= {6, 7}
        out |= {_DAY[m.group(1)] for m in _NAMED_DAY.finditer(clause)}
    return out


def scope_hint(text: str) -> str:
    """没说是只改这次还是以后都这样时，卡片上提醒一句（§45 需求 9）。"""
    return "" if _FOREVER.search(text) or _ONLY_NOW.search(text) else _SCOPE_HINT


def only_this_time(text: str) -> bool:
    """说的是只改这一次（走今天的版本，不改计划）。"""
    return bool(_ONLY_NOW.search(text)) and not _FOREVER.search(text)


def rule_conflict(text: str) -> str:
    """一句话里删掉某天、又要改那天的内容（"周五不练了，再把周五的弯举加到 4 组"）：返回矛盾说明。"""
    for m in _REMOVE_DAY.finditer(text):
        rest = text.replace(m.group(0), " ")
        day = m.group(1)
        if re.search(rf"(?:周|星期|礼拜){day}", rest):
            name = weekday_name(_DAY[day])
            return f"同一句里既要删掉{name}、又要改{name}的内容"
    return ""


def rule_ops(text: str, plan: Plan) -> list[Op] | None:
    """整句话都能由简单句式说清时返回操作；有一点说不清就返回 None（交给训练教练）。"""
    rest, ops = text, []
    for m in _MOVE.finditer(text):
        ops.append(Op(kind="move", day=_DAY[m.group(1)], to_day=_DAY[m.group(2)], why="你要求的"))
        rest = rest.replace(m.group(0), " ")
    for m in _REMOVE_ITEM.finditer(rest):
        d, name = _DAY[m.group(1)], m.group(2).removeprefix("的")
        s = _session(list(plan.sessions), d)
        if s is not None and any(_same(name, x.exercise) for x in s.items):
            ops.append(Op(kind="remove", day=d, exercise=name, why="你要求的"))
            rest = rest.replace(m.group(0), " ")
    for m in _REMOVE_DAY.finditer(rest):
        ops.append(Op(kind="remove", day=_DAY[m.group(1)], why="你要求的"))
        rest = rest.replace(m.group(0), " ")
    light = _REDUCE.search(rest)
    if light:
        weight = "重量" in text
        ops.append(Op(kind="reduce", ratio=LIGHTER if _MUCH.search(light.group(0)) else LIGHT,
                      weight=weight, why="你要求的"))  # fmt: skip
        rest = rest.replace(light.group(0), " ").replace("重量", " ")
    if not ops or _FILLER.sub("", rest):
        return None
    return ops


# ---- 每周复盘、首页提醒的调整由规则生成（§45 需求 2；最多改两天）-------------------------------


def review_ops(
    actions: Sequence[dict[str, Any]],
    plan: Plan,
    *,
    equipment: frozenset[Equipment] | None,
    injured: Collection[str] = (),
) -> list[Op]:
    """把复盘或提醒给出的动作（种类 + 参数）变成操作；改动最多两天。"""
    ops: list[Op] = []
    for a in actions:
        kind = a.get("kind")
        if kind == "fewer_days":  # 完成不到一半：减到 n 天，从排得最靠后的那天开始删
            keep = int(a.get("days") or plan.days_per_week - 1)
            extra = sorted(plan.sessions, key=lambda s: -s.day)[: max(0, plan.days_per_week - keep)]
            ops += [Op(kind="remove", day=s.day, why=str(a.get("why") or "")) for s in extra]
        elif kind == "lighter":  # 状态差、连续没练：整体按七成
            ops.append(Op(kind="reduce", ratio=LIGHT, why=str(a.get("why") or "")))
        elif kind == "swap_part":  # 同一部位反复疼：把压这个部位的动作换掉
            part = str(a.get("part") or "")
            hurt = [*injured, part]
            for s in plan.sessions:
                for x in s.items:
                    m = find(x.exercise)
                    if m is not None and part in m.tag.stress:
                        alt = ranked(m, equipment=equipment, injured=hurt, k=1)
                        if alt:
                            ops.append(Op(kind="swap", day=s.day, exercise=x.exercise,
                                          to=alt[0].name, why=str(a.get("why") or "")))  # fmt: skip
        elif kind == "variant":  # 平台期：换成相近的变式
            for name in a.get("exercises") or ():
                m = find(str(name))
                alt = (
                    ranked(m, equipment=equipment, injured=injured, direction="similar", k=1)
                    if m
                    else []
                )
                if alt:
                    ops.append(Op(kind="swap", exercise=str(name), to=alt[0].name,
                                  why=str(a.get("why") or "")))  # fmt: skip
    return _within_days(ops, plan, REVIEW_MAX_DAYS)


def _within_days(ops: list[Op], plan: Plan, limit: int) -> list[Op]:
    """整份计划的减量算改了每一天：有别的操作时先保留别的；只剩减量又超过上限时只减前两天。"""
    out: list[Op] = []
    days: set[int] = set()
    for op in ops:
        if op.kind == "reduce" and op.day is None:
            for s in sorted(plan.sessions, key=lambda s: s.day):
                if len(days) >= limit:
                    break
                if s.day not in days:
                    out.append(op.model_copy(update={"day": s.day}))
                    days.add(s.day)
            continue
        hit = (
            {d for d in (op.day, op.to_day) if d is not None}
            if op.day
            else {
                s.day for s in plan.sessions if any(_same(op.exercise, x.exercise) for x in s.items)
            }
        )
        if len(days | hit) > limit:
            continue
        days |= hit
        out.append(op)
    return out


def describe(applied: Applied) -> dict[str, Any]:
    """存进草稿、显示在卡片上的部分：操作、没改成的原因。"""
    return {
        "ops": [o.model_dump(exclude_defaults=True) for o in applied.done],
        "skipped": list(applied.skipped),
    }
