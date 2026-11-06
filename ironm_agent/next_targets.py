"""练完定下次（spec [2026-10-23] §132）：记下一次训练后叫醒管家，定这次练到的动作下次怎么练。

代码把这次的每组次数和重量、感受、备注、同一动作最近两次、计划的组次、今天的状态编成事实交给它，
装上"记训练与复盘"的"练完定下次"一节；它用 `set_next_target` 定（§163 需求 6：不再给规则算的参考）。
代码只校验：动作在当前计划里、加重一次不超过上次重量的一成〔K03〕、减重不超过三成、有重量的不去掉、
没重量的不新加、组数 1–10、次数整串写成"8–12"或"10"（不超过 30）、原因必填。
通过的存进管家的方案，记着依据的哪天、那天记的组和计划的组次；对不上（新记录、同一天再记、改了计划）就照上次。
这次要定的动作，以前定的先清掉：管家这次没调的照上次的重量和次数。一个都没定成时不存；中途失败前存下的照存。
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Sequence
from datetime import date
from typing import Any

from ironm_agent.coach_state import Deps, Inputs, State, _gather, evaluate, loop_lock, state_lock
from ironm_agent.llm import LLM
from ironm_agent.progression import (
    Decided,
    _same,
    check_decided,
    day_mark,
    history,
    latest,
    plan_mark,
)
from ironm_agent.tone import BUDDY
from ironm_agent.training import PlanItem, SetDone, WorkoutLog
from ironm_agent.user_models import pick_quiet

_log = logging.getLogger("ironm_agent.next_targets")

TOOL = "set_next_target"
SECTION = "练完定下次"
TIMEOUT_S = 60.0
MAX_TURNS = 4  # 和模型最多往返几次；到了就停，定了的照存

SCHEMA: dict[str, Any] = {"type": "function", "function": {
    "name": TOOL,
    "description": "定一个动作下次怎么练：重量、每组次数、组数和原因。没调的动作下次照上次的重量和次数。",
    "parameters": {"type": "object", "additionalProperties": False, "properties": {
        "exercise": {"type": "string", "description": "动作名，照事实里写的"},
        "weight_kg": {"type": ["number", "null"], "description": "每组用多重（公斤）；自重、弹力带写 null"},
        "reps": {"type": "string", "description": '每组次数，写成 "8–12" 或 "10"'},
        "sets": {"type": "integer", "description": "组数 1–10"},
        "why": {"type": "string", "description": "一句话原因，像当面对他说"},
    }, "required": ["exercise", "reps", "sets", "why"]}}}  # fmt: skip

_PROMPT = """你是健身 App 里的「AI 健身管家」。现在不是他在问你：他刚记下一次训练，系统叫醒你定这次练到的动作下次怎么练。下面是系统算好的事实，数照用，不要自己编。

{tone}

按规程里「练完定下次」一节判断。要定就调用 `set_next_target`（每个动作一次，可以定几个）；不调的动作下次照上次的重量和次数。
- 只有调用了工具才算定了。结果会告诉你存没存下；没存下的看原因，改了再调或者不调。
- 做完只输出一句话：这次最要紧的一点。

规程：
{skill}"""

_LOCKS: Any = weakref.WeakKeyDictionary()  # 每个人一把：连着打两次卡不并发定两次


def _sets(sets: Sequence[SetDone]) -> str:
    return "、".join(
        f"{x.weight_kg:g} 公斤 × {x.reps}" if x.weight_kg else f"{x.reps} 次" for x in sets
    )


def _short(d: date) -> str:
    return f"{d.month}月{d.day}日"


def due(inp: Inputs, log: WorkoutLog) -> list[PlanItem]:
    """这次记录里该定下次的动作：在当前计划里、记了每组次数、而且这次就是它最近一次记录。"""
    if inp.plan is None or not log.done:
        return []
    out: list[PlanItem] = []
    names: set[str] = set()
    for it in log.items:
        if not it.performed():
            continue
        item = next((x for s in inp.plan.sessions for x in s.items if _same(x.exercise, it.exercise)), None)  # fmt: skip
        if item is None or item.exercise in names:
            continue
        seen = latest(item.exercise, inp.logs)
        if seen is None or seen[0] != log.day:
            continue
        names.add(item.exercise)
        out.append(item)
    return out


def facts(inp: Inputs, log: WorkoutLog, todo: Sequence[PlanItem], today: date) -> list[str]:
    """交给管家的事实：这次的感受和备注、每个动作这次和上次每组做了多少、计划的组次、今天的状态。"""
    bits = [x for x in (f"感受 {log.rpe} 分（1–10）" if log.rpe else "",
                        f"{log.minutes} 分钟" if log.minutes else "",
                        f"备注：{log.note}" if log.note else "") if x]  # fmt: skip
    head = [f"这次（{_short(log.day)}）" + ("，".join(bits) if bits else "没写感受和备注")]
    rows = []
    for item in todo:
        hist = history(item.exercise, inp.logs)[:2]
        done = "；".join(f"{_short(d)} {_sets(sets)}" for d, sets in hist)
        rows.append(f"{item.exercise}：计划 {item.sets} 组 × {item.reps} 次"
                    f"{('，' + item.load) if item.load else ''}；最近两次 {done}")  # fmt: skip
    state = [
        f"今天{e.text()}"
        for e in (inp.day.entries if inp.day is not None and log.day == today else [])
        if e.kind != "minutes"
    ]  # 补记以前的：今天说的累、没睡好和那次无关，不给（审查 11-03）
    from ironm_agent.protools.movement import JOINT_NAMES

    state += [
        f"{_short(d)}说{JOINT_NAMES.get(p, p)}疼" for p, d in inp.pains if (today - d).days <= 7
    ]
    from ironm_agent.illness import active

    state += [f"生病：{e.what()}" for e in active(inp.illness, today)]
    return head + rows + (state or ["今天没说累、生病或哪里疼"])


async def run(
    user_id: str, deps: Deps, llm: LLM, log: WorkoutLog, *, today: date | None = None
) -> dict[str, Decided]:
    """叫醒管家定下次；返回存下的（没定或失败为空）。"""
    today = today or date.today()
    async with loop_lock(_LOCKS, user_id):  # 只在单进程里有效
        return await _run(user_id, deps, llm, log, today)


async def _run(
    user_id: str, deps: Deps, llm: LLM, log: WorkoutLog, today: date
) -> dict[str, Decided]:
    from ironm_agent.illness import recovering_days
    from ironm_agent.skills import by_id

    if not log.done or not any(it.performed() for it in log.items):  # 没练、没记组次：不用读数据
        return {}
    inp = await _gather(user_id, deps, today)
    sick = recovering_days(inp.illness, today)
    if log.day in sick:  # 生病期间的组次不算进下次目标（§46），也不叫醒
        return {}
    inp.logs = [x for x in inp.logs if x.day not in sick]
    todo = due(inp, log)
    skill = by_id("log-review")
    if not todo or skill is None:
        return {}
    by_name = {item.exercise: item for item in todo}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _PROMPT.format(tone=BUDDY, skill=skill.section(SECTION) or skill.text())},
        {
            "role": "user",
            "content": "事实：\n" + "\n".join(f"- {x}" for x in facts(inp, log, todo, today)),
        },
    ]
    got: dict[str, Decided] = {}
    rejected = 0
    try:
        for _ in range(MAX_TURNS):
            reply = await asyncio.wait_for(llm.chat("coach", messages, tools=[SCHEMA]), TIMEOUT_S)
            if not reply.tool_calls:
                break
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                said = _check(call.name, call.arguments, by_name, inp, log, got)
                rejected += not said.startswith("已存下")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": said})
    except (
        Exception
    ) as e:  # 模型不可用：一个都没定成就什么都不存、照上次；已经告诉它存下的照存（§132 需求 4）
        _log.warning("next targets failed: error_type=%s", type(e).__name__)
    await _save(user_id, deps, got, set(by_name), today)
    _log.info(
        "next targets done %s",
        json.dumps({"exercises": len(todo), "decided": len(got), "rejected": rejected}),
    )
    return got


def _check(name: str, args: dict[str, Any], by_name: dict[str, PlanItem],
           inp: Inputs, log: WorkoutLog, got: dict[str, Decided]) -> str:  # fmt: skip
    if name != TOOL:
        return f"这里只有 {TOOL}。"
    wanted = str(args.get("exercise") or "").strip()
    hit = next((k for k in by_name if _same(k, wanted)), None)
    if hit is None:
        return f"没存下：{wanted or '没写动作'}不在这次要定的动作里（{'、'.join(by_name)}）。"
    item = by_name[hit]
    try:
        d = Decided(exercise=hit, sets=args.get("sets"), reps=str(args.get("reps") or "").replace("-", "–"),
                    weight_kg=args.get("weight_kg") or None, why=str(args.get("why") or "")[:120], after=log.day,
                    mark=day_mark(hit, inp.logs, log.day), plan=plan_mark(item))  # fmt: skip
    except (ValueError, TypeError):
        return "没存下：组数要 1–10，次数写成 8–12 或 10，重量不为负。改了再调。"
    seen = latest(hit, inp.logs)
    if problem := check_decided(item, d, seen[1] if seen else None):
        return f"没存下：{problem}。改了再调，或者不调（照上次）。"
    got[hit] = d
    return f"已存下：{hit} 下次 {d.weight_kg:g} 公斤 × {d.reps} 次 × {d.sets} 组" if d.weight_kg else \
        f"已存下：{hit} 下次 {d.reps} 次 × {d.sets} 组"  # fmt: skip


async def _save(
    user_id: str, deps: Deps, got: dict[str, Decided], drop: set[str], today: date
) -> None:
    """存进管家的方案，再重新评估一次：下次目标那一项变了就照常记进调整经历（§132 需求 5）。
    读改存拿着管家方案的锁，免得和同时跑的重新评估互相覆盖（审查 11-03）。
    drop：这次要定的动作，以前定的先清掉（删了按同样的组次重记、这次没调的，照上次；复核 11-03）。"""
    if got and await deps.store.get(user_id) is None:
        await evaluate(user_id, deps, reason="练完定下次", today=today)
    async with state_lock(user_id):
        state = await deps.store.get(user_id)
        if state is None:
            return
        kept = {k: v for k, v in state.targets.items() if k not in drop}
        targets = {**kept, **{k: v.model_dump(mode="json") for k, v in got.items()}}
        if targets == state.targets:
            return
        await deps.store.save(
            user_id, State.model_validate({**state.model_dump(), "targets": targets}), []
        )
    await evaluate(user_id, deps, reason="练完定下次", today=today)


async def after_log(user_id: str, deps: Deps, log: WorkoutLog) -> None:
    """记下一次训练之后在后台跑；出错只记错误类型。"""
    try:
        if (llm := await pick_quiet(user_id)) is None:  # 用他自己的模型；没填就不定下次（§167）
            return
        await run(user_id, deps, llm, log)
    except Exception as e:
        _log.warning("next targets failed: error_type=%s", type(e).__name__)


_BACKGROUND: set[asyncio.Task[None]] = set()


def later(user_id: str, deps: Deps, log: WorkoutLog) -> None:
    """在后台叫醒管家定下次，不耽误这次请求。"""
    task = asyncio.create_task(after_log(user_id, deps, log))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
