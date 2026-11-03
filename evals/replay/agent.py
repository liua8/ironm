"""回放清单里的后台用例（spec [2026-10-23] §138 需求 1）：到期复查（§129）、练完定下次（§132）。

在本进程里用内存存储和一个假的用户编号，按用例准备身体数据、计划和训练记录，用真实模型（或测试里换的假模型）
跑一次，再按用例写的期望用规则判断。不登录、不碰任何账号和数据库。
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ironm_agent.casefile import Snapshot
from ironm_agent.coach_state import CoachBook, Deps
from ironm_agent.diet_adjust import DietBook
from ironm_agent.goal import GoalBook
from ironm_agent.llm import LLM, CallRecord, Reply, Stage
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import LogItem, Plan, SetDone, TrainingBook, WorkoutLog, plan_content
from ironm_agent.triggers import PainBook

USER = "replay-agent"  # 假的用户编号：只在内存里
KINDS = ("checkup", "next")
READINGS = ("resting_hr", "hrv_sdnn", "sleep_hours", "steps", "weight", "systolic", "diastolic")
RECENT_DAYS = 7  # "最近"是这几天，其余算"平时"


@dataclass
class Result:
    """一条后台用例跑下来的结果（报告里的一轮）。"""

    id: str
    say: str  # 这条用例在做什么（报告里当"说法"）
    answer: str = ""  # 管家写的总结或下次目标的说明
    tools: list[str] = field(default_factory=list)  # 模型调用过的工具（含被退回的）
    bad: list[str] = field(default_factory=list)
    secs: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


def _wiggle(i: int) -> float:
    return (i * 7 % 5 - 2) * 0.5  # 平常的日常波动（固定的，同一份用例每次一样）


def readings(spec: Mapping[str, Any], today: date) -> Readings:
    """每项写 {recent: 最近几天的值, usual: 平时的值, days: 共几天, recent_days: 最近算几天, wiggle: 平时的波动}，
    或者 {recent: 今天的值, trend: 每周变多少, days}（按趋势线性变化）。"""
    out: dict[str, Any] = {}
    for key, v in spec.items():
        if key not in READINGS:
            raise ValueError(f"不认识的数据：{key}")
        recent, usual = float(v["recent"]), float(v.get("usual", v["recent"]))
        n, k = int(v.get("days", 30)), int(v.get("recent_days", RECENT_DAYS))
        wig, trend = float(v.get("wiggle", 0.0)), float(v.get("trend", 0.0))
        if trend:  # 按趋势：今天是 recent，往前每周差 trend（如体重每周 -0.6）
            out[key] = tuple(
                (today - timedelta(days=i), round(recent - trend * i / 7, 2)) for i in range(n)
            )
            continue
        out[key] = tuple(
            (today - timedelta(days=i), (recent if i < k else usual + _wiggle(i) * wig))
            for i in range(n)
        )
    return Readings(**out)


def plan_of(spec: Sequence[Mapping[str, Any]], today: date) -> Plan:
    """计划：每次训练写 {day: today/明天这类相对说法或 1–7, name, items}。"""
    sessions = []
    for i, s in enumerate(spec):
        day = s.get("day", "today")
        wd = (
            today.isoweekday()
            if day == "today"
            else ((today.isoweekday() + i) % 7 + 1 if day == "other" else int(day))
        )
        sessions.append(
            {"day": wd, "name": s["name"], "minutes": s.get("minutes", 60), "items": s["items"]}
        )
    return Plan.model_validate(
        {"title": "回放", "days_per_week": len(sessions), "sessions": sessions}
    )


def log_of(spec: Mapping[str, Any], today: date) -> WorkoutLog:
    """训练记录：{back: 几天前, session, rpe, note, items: [{exercise, sets, reps, weight}]}。"""
    items = [LogItem(exercise=it["exercise"],
                     done_sets=[SetDone(reps=int(it["reps"]), weight_kg=it.get("weight"))] * int(it.get("sets", 3)))
             for it in spec.get("items", [])]  # fmt: skip
    return WorkoutLog(day=today - timedelta(days=int(spec.get("back", 0))), session=str(spec.get("session", "")),
                      items=items, rpe=spec.get("rpe"), note=str(spec.get("note", "")))  # fmt: skip


async def deps_for(
    case: Mapping[str, Any], profile: Profile, today: date
) -> tuple[Deps, list[WorkoutLog]]:
    setup = case.get("setup") or {}
    book = TrainingBook()
    if setup.get("plan"):
        d = await book.add_draft(USER, "plan", plan_content(plan_of(setup["plan"], today)))
        await book.confirm(USER, d.id)
    logs = [log_of(x, today) for x in setup.get("logs") or []]
    for log in logs:
        await book.log(USER, log)
    r = readings(setup.get("readings") or {}, today)
    snap = Snapshot(profile, r, tuple(compute_all(r, profile, today)), today)

    async def snapshot(_: str) -> Snapshot:
        return snap

    return Deps(snapshot=snapshot, training=book, pain=PainBook(), goals=GoalBook(), diet=DietBook(),
                store=CoachBook()), logs  # fmt: skip


class Spy:
    """记下模型每次回复里的工具调用和工具结果，原样转给真正的模型。"""

    def __init__(self, llm: LLM) -> None:
        self.llm = llm
        self.calls: list[CallRecord] = llm.calls  # 同一份：调用次数照真正的模型算
        self.tools: list[str] = []
        self.errors: list[str] = []  # 模型调用出的错（种类）：被调用方吞掉也要记成不符合
        self.messages: Sequence[
            Mapping[str, Any]
        ] = ()  # 调用方原地追加的那份对话：跑完再数工具结果

    @property
    def results(self) -> list[str]:
        return [str(m.get("content") or "") for m in self.messages if m.get("role") == "tool"]

    async def chat(
        self,
        stage: Stage,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        json_mode: bool = False,
    ) -> Reply:
        self.messages = messages
        try:
            reply = await self.llm.chat(stage, messages, tools=tools, json_mode=json_mode)
        except BaseException as e:  # 超时被取消（CancelledError）也要记下（复核 11-03）
            self.errors.append(type(e).__name__)
            raise
        self.tools += [c.name for c in reply.tool_calls]
        return reply


async def run_case(
    case: Mapping[str, Any], profile: Profile, llm: LLM, today: date | None = None
) -> Result:
    """跑一条后台用例并判断；出错记成不符合（不往外抛），方便一次跑完整份清单。"""
    today = today or date.today()
    kind = str(case.get("kind"))
    res = Result(id=str(case["id"]), say=f"[{kind}] {case.get('from', '')}")
    if kind not in KINDS:
        res.bad.append(f"不认识的种类：{kind}")
        return res
    spy = Spy(llm)
    start = time.perf_counter()
    try:
        dp, logs = await deps_for(case, profile, today)
        if kind == "checkup":
            await _checkup(case, dp, spy, today, res)
        else:
            await _next(case, dp, spy, logs, today, res)
    except Exception as e:  # 准备或运行出错：这条不符合，接着跑下一条
        res.bad.append(f"运行出错：{type(e).__name__}")
    if spy.errors:  # 复查、定下次自己会吞掉模型的错：照样算不符合，免得"没调"被当成判断对了
        res.bad.append(f"模型调用出错：{'、'.join(dict.fromkeys(spy.errors))}")
    elif not spy.calls and not res.bad:
        res.bad.append("模型没被调用")
    res.secs = time.perf_counter() - start
    res.tools = spy.tools
    return res


async def _checkup(case: Mapping[str, Any], dp: Deps, llm: Spy, today: date, res: Result) -> None:
    from ironm_agent import review

    got = await review.run(USER, dp, llm, today=today, force=True)
    done = [d.type for d in got.done if not d.undone]
    res.answer = got.summary
    res.detail = {"done": done, "titles": [d.title for d in got.done], "failed": got.failed}
    res.bad += judge_checkup(case.get("expect") or {}, done, got.summary, got.failed)


async def _next(case: Mapping[str, Any], dp: Deps, llm: Spy, logs: list[WorkoutLog], today: date,
                res: Result) -> None:  # fmt: skip
    from ironm_agent import next_targets
    from ironm_agent.progression import latest

    if not logs:
        res.bad.append("没有训练记录")
        return
    log = logs[-1]  # 最后一条是"刚记下的这次"
    got = await next_targets.run(USER, dp, llm, log, today=today)
    rejected = sum(1 for m in llm.results if not m.startswith("已存下"))
    moves: dict[str, str] = {}
    whys: dict[str, str] = {}
    book_logs = [x.log for x in await dp.training.workouts(USER, today - timedelta(days=60))]
    stored = await dp.training.plan(USER)
    items = {x.exercise: x for s in (stored.plan.sessions if stored else ()) for x in s.items}
    for name, d in got.items():
        seen = latest(name, book_logs)
        moves[name] = move(d, seen[1] if seen else None, items.get(name))
        whys[name] = d.why
    res.answer = "；".join(f"{k}：{v}" for k, v in whys.items())
    res.detail = {"moves": moves, "rejected": rejected,
                  "decided": {k: v.model_dump(mode="json") for k, v in got.items()}}  # fmt: skip
    res.bad += judge_next(case.get("expect") or {}, moves, whys, rejected)


def move(d: Any, last: float | None, item: Any) -> str:
    """管家定的是哪种：up/down（重量比上次的最重一组高/低）、more（重量不变、组次比计划多）、hold。"""
    w = d.weight_kg
    if w and last and w != last:
        return "up" if w > last else "down"
    if item is not None and (d.sets > item.sets or _top(d.reps) > _top(item.reps)):
        return "more"
    return "hold"


def _top(reps: str) -> int:
    from ironm_agent.progression import rep_range

    r = rep_range(reps)
    return r[1] if r else 0


def _groups(raw: Any) -> list[list[str]]:
    return [[str(w) for w in (g if isinstance(g, list) else [g])] for g in raw or []]


def judge_checkup(
    expect: Mapping[str, Any], done: Sequence[str], summary: str, failed: bool
) -> list[str]:
    """done 写要有的调整种类（today/kcal/propose/note/ask），not_done 写不能有的；
    summary_must / summary_must_not 看总结。复查算失败（模型没就今天做出决定）一律不符合。"""
    bad = []
    for kind in expect.get("done") or []:
        if kind not in done:
            bad.append(f"该有「{kind}」调整，没有（实际 {list(done) or '都没调'}）")
    for kind in expect.get("not_done") or []:
        if kind in done:
            bad.append(f"不该有「{kind}」调整，有了")
    if "any" in expect and bool(done) != bool(expect["any"]):
        bad.append("该调却一样都没调" if expect["any"] else f"不该调，调了 {list(done)}")
    for g in _groups(expect.get("summary_must")):
        if not any(w in summary for w in g):
            bad.append("总结没说到「" + " / ".join(g) + "」")
    bad += [f"总结出现了「{w}」" for w in expect.get("summary_must_not") or [] if w in summary]
    if failed:
        bad.append("复查算失败了（没就今天做出决定）")
    return bad


def judge_next(expect: Mapping[str, Any], moves: Mapping[str, str], whys: Mapping[str, str],
               rejected: int) -> list[str]:  # fmt: skip
    """targets 写每个动作要的结果，可以写一个或几个（任一即可）：up/down/hold（管家定了且是这个方向）、
    rule（没定、照规则）、not_up（没加重：没定或定了不加）；why_must / why_must_not 看那个动作的说明
    （没定时说明为空，why_must 不检查）；rejected 写最多几次被退回。"""
    bad = []
    for name, want in (expect.get("targets") or {}).items():
        allowed = [want] if isinstance(want, str) else list(want)
        got = moves.get(name) or "rule"
        if not any(got == w or (w == "not_up" and got != "up") for w in allowed):
            bad.append(
                f"{name} 应为 {' / '.join(allowed)}，实际 {got if got != 'rule' else '没定（照规则）'}"
            )
    for name, groups in (expect.get("why_must") or {}).items():
        if name not in whys:
            continue
        for g in _groups(groups):
            if not any(w in whys.get(name, "") for w in g):
                bad.append(f"{name} 的说明没说到「" + " / ".join(g) + "」")
    for name, words in (expect.get("why_must_not") or {}).items():
        bad += [f"{name} 的说明出现了「{w}」" for w in words if w in whys.get(name, "")]
    if "rejected" in expect and rejected > int(expect["rejected"]):
        bad.append(f"被退回最多 {expect['rejected']} 次，实际 {rejected} 次")
    return bad
