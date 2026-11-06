"""专业工具的清单：名字、给模型看的说明与参数、哪些角色能用、怎么执行。

工具箱（tools.Toolbox）拿到 ToolContext 后，把本角色能用的工具交给模型；结果里带数字的结论各领一个
C 编号写进这一轮的计算结果，用到的动作库条目记为可以引用的依据。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ironm_agent.body import joint_code
from ironm_agent.exercises import Equipment
from ironm_agent.facts import equipment as equipment_in
from ironm_agent.kb import Entry
from ironm_agent.protools.movement import JOINT_NAMES, equipment_of, substitutes
from ironm_agent.protools.nutrition import ITEMS, Item, nutrition
from ironm_agent.protools.pain import SIGNS, pain_check
from ironm_agent.protools.patterns import WINDOWS, training_patterns
from ironm_agent.protools.plan_check import check_plan
from ironm_agent.protools.result import Finding, Result
from ironm_agent.protools.strength import load_for, one_rep_max
from ironm_agent.protools.templates import GOALS, LEVELS, PLACES, plan_templates
from ironm_agent.protools.templates import catalog as plan_catalog
from ironm_agent.protools.trends import INDICATORS, MAX_DAYS, MIN_DAYS, series, trend
from ironm_agent.training import StoredPlan, WorkoutLog, parse_plan

_log = logging.getLogger("ironm_agent.protools")

type Loader[T] = Callable[[], Awaitable[T]]


@dataclass
class ToolContext:
    """这一轮工具要用到的这个人的情况（只读）。训练记录与计划在用到时才读。"""

    today: date
    goal: str | None = None
    weight_kg: float | None = None  # 最新体重（来自健康数据）
    kcal_target: float | None = None  # 每日热量目标（与数据页同一份计算）
    readings: Any = None  # metrics.Readings；趋势分析用
    injured: tuple[str, ...] = ()  # 有伤病的部位（关节编码 joint.knee、joint.lumbar……）
    equipment: frozenset[Equipment] | None = None  # None 表示不知道
    plan: Loader[StoredPlan | None] | None = None
    workouts: Callable[[date], Awaitable[list[WorkoutLog]]] | None = None
    age: int | None = None  # 选初步方案时分人群（§77）
    profile: Any = None  # metrics.Profile：和标准比时用身高、性别、目标（§84）
    found: tuple[Any, ...] | None = (
        None  # 这一轮算好的事实（§84，对话里已经算好；None 时工具自己算）
    )
    special: frozenset[str] = frozenset()  # 特殊人群（§95）：计划检查按硬规则查
    _cache: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        today: date,
        *,
        goal: str | None,
        weight_kg: float | None,
        readings: Any,
        kcal_target: float | None = None,
        injured: Iterable[str],
        equipment_said: Iterable[str] = (),
        equipment_items: Sequence[Any] | None = None,  # 器械与场地的记忆条目（读字段，§150）
        plan: Loader[StoredPlan | None] | None = None,
        workouts: Callable[[date], Awaitable[list[WorkoutLog]]] | None = None,
        age: int | None = None,
        profile: Any = None,
        found: Sequence[Any] | None = None,
        special: Iterable[str] = (),
    ) -> ToolContext:
        return cls(
            today,
            goal,
            weight_kg,
            kcal_target,
            readings,
            tuple(injured),
            equipment_in(equipment_items)
            if equipment_items is not None
            else equipment_of(equipment_said),
            plan,
            workouts,
            age,
            profile,
            tuple(found) if found is not None else None,
            frozenset(special),
        )

    async def stored_plan(self) -> StoredPlan | None:
        if "plan" not in self._cache:
            self._cache["plan"] = await self.plan() if self.plan else None
        result: StoredPlan | None = self._cache["plan"]
        return result


type Handler = Callable[[ToolContext, Mapping[str, Any]], Awaitable[Result]]


@dataclass(frozen=True)
class ProTool:
    name: str
    roles: frozenset[str]
    description: str
    parameters: dict[str, Any]
    handler: Handler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _obj(properties: dict[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": list(required),
    }


def _num(args: Mapping[str, Any], key: str) -> float | None:
    v = args.get(key)
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def _int(args: Mapping[str, Any], key: str) -> int | None:
    v = _num(args, key)
    return round(v) if v is not None else None


# ---- 执行 -----------------------------------------------------------------------------------


async def _strength(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    weight, reps = _num(args, "weight_kg"), _int(args, "reps")
    target, rir = _int(args, "target_reps"), _int(args, "reps_in_reserve")
    if target is not None:
        return load_for(
            target, rir if rir is not None else 2, max_kg=_num(args, "max_kg"), weight=weight, reps=reps,
            step=_num(args, "step_kg") or 2.5,
        )  # fmt: skip
    if weight is None or reps is None:
        return Result.note(
            "估算最大重量需要 weight_kg 和 reps；推重量需要 target_reps，再加 max_kg 或最近一组的 weight_kg 和 reps。"
        )
    return one_rep_max(weight, reps)


async def _check(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    plan, why = parse_plan(args.get("plan"))
    if plan is None:
        return Result.note(f"{why}，按 plan 的格式写好再检查。")
    stored = await ctx.stored_plan()
    level = str(args.get("level") or "")
    return check_plan(
        plan,
        current=stored.plan if stored else None,
        goal=ctx.goal,
        novice=level == "novice",
        injured=ctx.injured,
        equipment=ctx.equipment,
        available_days=_int(args, "available_days"),
        available_minutes=_int(args, "available_minutes"),
        special=ctx.special,
    )


async def _templates(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    days = _int(args, "days_per_week")
    name = str(args.get("name") or "").strip()
    if days is None and not name:  # 问"有多少计划、有哪些"：列出方案库（§83）
        return plan_catalog()
    if days is None or not 1 <= days <= 7:
        return Result.note("要写每周能练几天（days_per_week，1–7）。")
    level, goal, place = (str(args.get(k) or "") for k in ("level", "goal", "place"))
    goal = goal or str(ctx.goal or "")
    weekdays = [d for d in args.get("weekdays") or [] if isinstance(d, int) and 1 <= d <= 7]
    return plan_templates(
        level=level if level in LEVELS else None,  # type: ignore[arg-type]
        goal=goal if goal in GOALS else None,  # type: ignore[arg-type]
        days=days,
        minutes=_int(args, "minutes"),
        place=place if place in PLACES else None,  # type: ignore[arg-type]
        age=_int(args, "age") or ctx.age,
        equipment=ctx.equipment,
        injured=ctx.injured,
        weekdays=weekdays,
        name=str(args.get("name") or "").strip(),
        special=ctx.special,
    )


def _sources(refs: Iterable[str]) -> str:
    """资料编号 → "名称（机构 年份）"，追问依据时讲得出来。"""
    from ironm_agent.kb import default_kb

    kb = default_kb()
    names = [
        f"{e.title}（{e.publisher.split('（')[0]} {e.year}）" for r in refs if (e := kb.get(r))
    ]
    return "；".join(names)


def _standard(ctx: ToolContext, indicator: str) -> str:
    """趋势工具带上和标准比的一句（§84）。"""
    from ironm_agent.insights import compare

    if ctx.readings is None or ctx.profile is None:
        return ""
    key = {"sleep_hours": "sleep", "systolic": "blood_pressure", "diastolic": "blood_pressure"}.get(
        indicator, indicator
    )
    got = next((r for r in compare(ctx.readings, ctx.profile, ctx.today) if r.key == key), None)
    return f"和标准比：{got.standard}（{_sources(got.refs)}）" if got is not None else ""


async def _explain(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    """综合解读（§84）：各指标和自己比、和标准比；同期发生的事；每条带出处。只给事实，不贴标签（§182）。"""
    from ironm_agent.insights import CONTEXT, compare, observations

    if ctx.readings is None or ctx.profile is None:
        return Result.note("这次读不到健康数据，不能解读，也不能推测为正常。")
    found = ctx.found
    if found is None:
        logs = await ctx.workouts(ctx.today - timedelta(days=28)) if ctx.workouts else []
        found = tuple(observations(ctx.readings, ctx.profile, ctx.today, logs=logs))
    readings = compare(ctx.readings, ctx.profile, ctx.today)
    if not readings and not found:
        return Result.note(
            "还没有心率、睡眠、步数、体重、血压的记录，不能解读；可以连上手表或每天记一次体重。"
        )
    findings = [
        Finding(f"{r.name}（两种比较）", r.line(),
                "和自己比：最近 7 天和之前几周（或本人基线）的平均；和标准比：按年龄、性别的成年人标准",
                "他的健康数据", _sources(r.refs))
        for r in readings
    ]  # fmt: skip
    findings += [
        Finding(f"同期：{s.name}", s.line(), "代码按记录数的，只是同时发生、可能有关，不说成因果",
                s.data, _sources(s.refs))
        for s in found if s.kind in CONTEXT
    ]  # fmt: skip
    notes = [s.line() for s in found if s.kind == "thin"]
    notes.append(
        "回答时：先说数（和他自己比、和标准比），同期发生的事只说可能有关；好不好、要不要调由你看这些数判断。"
    )
    return Result(tuple(findings), tuple(notes))


async def _patterns(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    if ctx.workouts is None:
        return Result.note("这次读不到训练记录。")
    days = _int(args, "days") or 28
    logs = await ctx.workouts(ctx.today - timedelta(days=max(WINDOWS) - 1))
    stored = await ctx.stored_plan()
    return training_patterns(
        logs, ctx.today, days=days, plan=stored.plan if stored else None,
        plan_since=stored.since if stored else None,
    )  # fmt: skip


async def _substitutes(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    name = str(args.get("exercise") or "").strip()
    if not name:
        return Result.note("要写明替代哪个动作。")
    extra = [
        c for x in args.get("avoid_parts") or [] if isinstance(x, str) and (c := joint_code(x))
    ]
    direction = str(args.get("direction") or "any")
    return substitutes(
        name,
        equipment=ctx.equipment,
        injured=tuple(dict.fromkeys([*ctx.injured, *extra])),
        direction=direction if direction in ("easier", "similar", "harder", "any") else "any",  # type: ignore[arg-type]
    )


async def _nutrition(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    said = _num(args, "weight_kg")
    weight, source = (
        (said, "这句话里说的体重") if said is not None else (ctx.weight_kg, "最新的体重记录")
    )
    raw = args.get("items") or ["protein"]
    items: list[Item] = [x for x in ITEMS if x in raw]
    return nutrition(
        weight,
        goal=ctx.goal,
        items=items or ["protein"],
        training_minutes=_int(args, "training_minutes"),
        weight_source=source if weight is not None else "",
        kcal_target=ctx.kcal_target,
    )


async def _pain(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    signs = [str(x) for x in args.get("signs") or [] if isinstance(x, str)]
    return pain_check(_int(args, "score"), signs, part=str(args.get("part") or ""))


async def _trend(ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    indicator = str(args.get("indicator") or "")
    if ctx.readings is None:
        return Result.note("这次没读到健康数据。")
    days = _int(args, "days") or 28
    got = trend(series(ctx.readings, indicator), ctx.today, indicator=indicator, days=days)
    std = _standard(ctx, indicator)
    return Result(got.findings, (*got.notes, std) if std else got.notes, got.entries, got.problems)


# ---- 清单 -----------------------------------------------------------------------------------

_PLAN_ITEM = _obj(
    {
        "exercise": {"type": "string"},
        "sets": {"type": "integer"},
        "reps": {"type": "string"},
        "load": {"type": "string"},
        "note": {"type": "string"},
    },
    ("exercise", "sets", "reps"),
)
_PLAN = _obj(
    {
        "title": {"type": "string"},
        "goal": {"type": "string"},
        "days_per_week": {"type": "integer"},
        "sessions": {
            "type": "array",
            "items": _obj(
                {
                    "day": {"type": "integer", "description": "1 = 周一 … 7 = 周日"},
                    "name": {"type": "string"},
                    "minutes": {"type": "integer"},
                    "items": {"type": "array", "items": _PLAN_ITEM},
                },
                ("day", "name", "items"),
            ),
        },
    },
    ("title", "days_per_week", "sessions"),
)

TOOLS: dict[str, ProTool] = {
    t.name: t
    for t in (
        ProTool(
            "estimate_strength",
            frozenset({"trainer", "general"}),
            "力量计算：给 weight_kg 和 reps 估算最大重量（1RM）；给 target_reps、reps_in_reserve（还剩几次）"
            "和 max_kg（或最近一组的 weight_kg、reps）推出这组该用多重。数字用户说过才能填，不要自己编。",
            _obj(
                {
                    "weight_kg": {"type": "number", "description": "一组用的重量（公斤）"},
                    "reps": {"type": "integer", "description": "这组做了几次"},
                    "target_reps": {"type": "integer", "description": "想做几次"},
                    "reps_in_reserve": {
                        "type": "integer",
                        "description": "做完还剩几次（0–4），默认 2",
                    },
                    "max_kg": {"type": "number", "description": "已知的最大重量"},
                    "step_kg": {
                        "type": "number",
                        "description": "重量最小档位，杠铃 2.5，哑铃常见 1 或 2",
                    },
                }
            ),
            _strength,
        ),
        ProTool(
            "check_plan",
            frozenset({"trainer", "general"}),
            "检查一份训练计划：各肌群每周组数与练几次、新手的天数与组数、同一肌群是否连续两天、"
            "伤病部位的动作、器械是否齐、每次时长，以及和当前计划相比改了什么。写好计划后先检查，有问题就改。",
            _obj(
                {
                    "plan": _PLAN,
                    "level": {"type": "string", "enum": ["novice", "experienced", "unknown"]},
                    "available_days": {
                        "type": "integer",
                        "description": "他每周能练几天（他说过才填）",
                    },
                    "available_minutes": {
                        "type": "integer",
                        "description": "每次能练多少分钟（他说过才填）",
                    },
                },
                ("plan",),
            ),
            _check,
        ),
        ProTool(
            "plan_templates",
            frozenset({"trainer", "general"}),
            "选初步方案：按训练水平、目标、每周天数、每次时长、场地、年龄，从方案库挑出最合适的 1–2 个方案，"
            "按他有的器械和伤病换成具体动作、排好周几，给出能直接改的计划草稿和为什么这样排、怎么进阶。"
            "排新计划时先调它，再照这个人改；他的器械、伤病、年龄系统已经知道，他这几轮说的新条件填进参数。"
            "他点名要某个博主或某套计划时，把他说的名字填进 name。"
            "问有多少训练计划、有哪些计划时，什么都不填，返回方案库的全部方案。",
            _obj(
                {
                    "level": {
                        "type": "string",
                        "enum": list(LEVELS),
                        "description": "none 零基础、lt6m 不到 6 个月、6m-2y 6 个月到 2 年、2y+ 2 年以上",
                    },
                    "goal": {"type": "string", "enum": list(GOALS)},
                    "days_per_week": {"type": "integer", "minimum": 1, "maximum": 7},
                    "minutes": {"type": "integer", "description": "每次能练几分钟（他说过才填）"},
                    "place": {"type": "string", "enum": list(PLACES)},
                    "age": {"type": "integer", "description": "年龄（档案里没有、他说过才填）"},
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 1, "maximum": 7},
                        "description": "他能练的周几，1 是周一（他说过才填）",
                    },
                    "name": {
                        "type": "string",
                        "description": "他点名要的博主或计划名（如“谭成义”），没点名不填",
                    },
                },
            ),
            _templates,
        ),
        ProTool(
            "training_patterns",
            frozenset({"trainer", "recovery", "general"}),
            "汇总这个人最近 14、28 或 56 天的训练：次数、每周平均、常在周几、每次时长、感受、按计划的完成率、"
            "常练和常跳过的动作。记录太少时会说明数据不足。",
            _obj({"days": {"type": "integer", "enum": list(WINDOWS)}}),
            _patterns,
        ),
        ProTool(
            "find_substitutes",
            frozenset({"trainer", "recovery", "general"}),
            "在动作库里找替代动作：按同一动作模式、他有的器械、有伤病的部位，找更容易、相近或更难的动作，并写明为什么。"
            "他的伤病和器械系统已经知道；这句话里新说到的疼痛部位放进 avoid_parts。",
            _obj(
                {
                    "exercise": {"type": "string", "description": "要替代的动作名"},
                    "direction": {"type": "string", "enum": ["easier", "similar", "harder", "any"]},
                    "avoid_parts": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(JOINT_NAMES),
                        },
                    },
                },
                ("exercise",),
            ),
            _substitutes,
        ),
        ProTool(
            "nutrition_calc",
            frozenset({"nutrition", "general"}),
            "营养计算（按他的体重）：protein 每天与每餐蛋白质、carbs 按训练量的碳水（需要 training_minutes）、"
            "creatine 肌酸、caffeine 咖啡因、beta_alanine β-丙氨酸、hydration 运动前补水。热量目标在档案的指标计算里。",
            _obj(
                {
                    "items": {"type": "array", "items": {"type": "string", "enum": list(ITEMS)}},
                    "training_minutes": {
                        "type": "integer",
                        "description": "每天大概练几分钟（他说过才填）",
                    },
                    "weight_kg": {"type": "number", "description": "只在他这句话里说了体重时填"},
                }
            ),
            _nutrition,
        ),
        ProTool(
            "pain_check",
            frozenset({"recovery", "general"}),
            "疼痛判断：按疼痛分数（0–10）和就医信号，给出可以继续、减量改动作，还是停下就医。他没说分数时不要填 score。",
            _obj(
                {
                    "score": {"type": "integer", "description": "疼痛分数 0–10（他说过才填）"},
                    "signs": {"type": "array", "items": {"type": "string", "enum": list(SIGNS)}},
                    "part": {"type": "string", "description": "哪里疼"},
                }
            ),
            _pain,
        ),
        ProTool(
            "explain_trends",
            frozenset({"trainer", "nutrition", "recovery", "general"}),
            "综合解读他的指标：每项和他自己比、和标准比（静息心率、心率变异性、睡眠、步数、血压、体重），"
            "同期发生的事（练的次数、生病、出差），每条带出处；只给数和差、不下结论，怎么看由你判断。"
            '问"我最近怎么样、这些数说明什么、为什么这样调"时用。',
            _obj({}),
            _explain,
        ),
        ProTool(
            "trend_analysis",
            frozenset({"trainer", "nutrition", "recovery", "general"}),
            "按指定的指标和时间范围分析趋势：平均、最高最低、头尾一周的平均、每周变化、变化是否超过日常波动。"
            "按用户问的范围填 days（这周 7、这个月 30、两个月 60、三个月 90、半年 180）。",
            _obj(
                {
                    "indicator": {"type": "string", "enum": list(INDICATORS)},
                    "days": {"type": "integer", "minimum": MIN_DAYS, "maximum": MAX_DAYS},
                },
                ("indicator",),
            ),
            _trend,
        ),
    )
}


def tools_for(role: str) -> list[ProTool]:
    return [t for t in TOOLS.values() if role in t.roles]


def allowed(role: str, name: str) -> bool:
    tool = TOOLS.get(name)
    return tool is not None and role in tool.roles


# 工具结果的编号段：同一层的几位角色同时作答、各自编号，整合时合在一起，所以每个角色用自己的一段，
# 不会撞号；档案里的计算结果用 C0 起的前十几个号（编号最多两位）
CALC_RANGES: dict[str, tuple[int, int]] = {
    "trainer": (20, 51), "nutrition": (52, 67), "recovery": (68, 99), "general": (20, 99),
}  # fmt: skip


def render(
    result: Result,
    *,
    role: str,
    calcs: MutableMapping[str, str],
    entries: MutableMapping[str, Entry],
    library: Mapping[str, Entry],
) -> str:
    """把结果写给模型：带数字的结论各领一个 C 编号（记进这一轮的计算结果，回答引用时核对）。"""
    lines = []
    low, high = CALC_RANGES.get(role, (20, 99))
    free = (n for n in range(low, high + 1) if f"C{n}" not in calcs)
    for f in result.findings:
        n = next(free, None)
        if n is None:  # 这一段的编号用完了：照样给模型看，但不能引用
            lines.append(f"- {f.detail()}")
            continue
        calcs[f"C{n}"] = f.detail()
        lines.append(f"[C{n}] {f.detail()}")
    for ref in result.entries:
        if ref in library:
            entries[ref] = library[ref]
    lines += list(result.notes)
    return "\n".join(lines) or "没有结果。"


async def run(name: str, ctx: ToolContext, args: Mapping[str, Any]) -> Result:
    tool = TOOLS[name]
    try:
        return await tool.handler(ctx, args)
    except Exception as e:  # 工具出错不影响作答：如实告诉模型
        _log.warning("pro tool failed: tool=%s error_type=%s", name, type(e).__name__)
        return Result.note("这次计算没有成功，请不用这个工具作答。")


__all__ = [
    "CALC_RANGES",
    "TOOLS",
    "ProTool",
    "ToolContext",
    "allowed",
    "render",
    "run",
    "tools_for",
]
