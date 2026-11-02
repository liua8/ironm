"""管家复盘（spec [2026-10-23] §85）：代码只负责算对，调不调、调什么、调多少由模型决定。

每天一次：代码把算好的事实（两种比较、认出的情况和同期发生的事、训练、今天的计划、热量目标）编好号交给模型，
模型决定今天按几成练或休息、改计划、调热量、只提醒或问一句，每条写原因、依据和预期。代码只做三件事：
依据的编号要存在；改计划的操作套得上、检查没有必须改的问题；热量不低于基础代谢和安全下限、危急指标不调训练。
通过的直接生效、记进调整经历、能撤销。模型调用失败时不调整，不退回规则替它决定。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.casefile import risks
from ironm_agent.coach_state import (
    Change,
    Deps,
    Done,
    Inputs,
    Review,
    State,
    _gather,
    evaluate,
)
from ironm_agent.expect import RESULT_WORDS, judge, measure, parse_check, stage_due, stage_facts
from ironm_agent.insights import compare, situations
from ironm_agent.kb import default_kb
from ironm_agent.llm import LLM, TurnLLM, load_models, parse_json
from ironm_agent.metrics import KcalAdjust, safe_floor
from ironm_agent.training import plan_content, weekday_name

_log = logging.getLogger("ironm_agent.review")

TIMEOUT_S = 60.0
# 复盘时常用的资料（模型引用时写编号）；认出的情况和两种比较用到的资料另外加进来
COMMON = ("K03", "K09", "K16", "K18", "K28", "K31", "K37", "K64", "K81", "K82", "K87", "K88")

_PROMPT = """你是健身 App 里的管家，正在给这个人做每天一次的复盘。下面是系统算好的事实（编号 F..，数都是代码算的，照用，不要自己算、不要编）和可以引用的资料（编号 K..）。

请你判断今天要不要调整、调什么、调多少——由你决定，没有固定的规则。可以做这几种（可以做几种，也可以都不做）：
- today：只改今天这一次训练。{"type": "today", "ratio": 0.5 到 0.9（按原来的几成练）} 或 {"type": "today", "rest": true}
- plan：改训练计划（以后每周都按新的练）。{"type": "plan", "ops": [操作]}，操作和改计划时一样：
  {"kind": "swap", "day": 1–7, "exercise": "原动作", "to": "新动作"}、{"kind": "move", "day": 几, "to_day": 几}、
  {"kind": "edit", "day": 几, "exercise": "动作", "sets": 组数, "reps": "次数"}、{"kind": "add", "day": 几, "exercise": "动作", "sets": 组数, "reps": "次数"}、
  {"kind": "remove", "day": 几, "exercise": "动作"}、{"kind": "reduce", "day": 几或不写（整份）, "ratio": 0.5–0.9}
- kcal：调每日热量目标。{"type": "kcal", "delta": 每天多吃（正数）或少吃（负数）多少千卡}
- note：只提醒他一句。{"type": "note", "text": "一句话"}
- ask：拿不准、需要他说清楚时问一句。{"type": "ask", "text": "一句话"}
每一条都要加上：
- "why"：一句话的原因，像当面对他说，不写编号；
- "basis"：用到的事实和资料编号，如 ["F2", "F5", "K18"]，至少有一个 F；
- "expect"：一个能检查的预期，带时间（如"两周后静息心率回到 62 次/分以下"）；note、ask 可以不写。
- "check"：同一个预期写成系统到期能核对的样子（today、plan、kcal 都要写）：
  {"metric": "weight|resting_hr|hrv|sleep|steps|waist|body_fat|completion|e1rm", "op": "<=" 或 ">=", "value": 数, "days": 3–42}；
  e1rm 是某个动作的估算最大重量，加 "exercise": "动作名"；completion 是按计划的完成率（百分数）。
判断时把事实放在一起看：同期发生的事只是"可能有关"，不要当成因果；数据不够或说不准时，宁可不调或问一句。危急的情况系统已经拦下，你不用处理。
事实里有"以前调整的效果"：没达到的不要原样再来一次（换个做法、或者问他）；"还在等结果"的同类调整不要叠加。
事实里有"阶段："开头的几条时，今天满 4 周了，另外写 "stage"：3–5 句阶段小结，像当面对他说——这 4 周练得怎么样、变了什么、调整有没有用、下 4 周的重点；数照事实里的写。

只输出 JSON：{"summary": "一句话：今天看到的最重要的情况（都正常就写都正常）", "adjust": [ ... ], "stage": "只有满 4 周时写"}"""


def facts(
    inp: Inputs, today: date, extra: Sequence[str] = ()
) -> tuple[dict[str, str], tuple[str, ...]]:
    """编好号的事实（F1…）和这些事实用到的资料编号；extra 是以前调整的效果和阶段事实（§89）。"""
    from ironm_agent.illness import active, ago
    from ironm_agent.protools.patterns import training_patterns

    snap = inp.snapshot
    lines: list[str] = []
    refs: list[str] = list(COMMON)
    for r in compare(snap.readings, snap.profile, today):
        lines.append(r.line())
        refs += r.refs
    ill = [f"{ago(e.started, today)}说{e.what()}" for e in active(inp.illness, today)]
    for s in situations(snap.readings, snap.profile, today, logs=inp.logs, illness=ill):
        lines.append(f"认出的情况：{s.line()}")
        refs += s.refs
    if inp.plan is not None:
        lines.append("当前计划：" + "；".join(s.line() for s in inp.plan.sessions))
        session = inp.plan.session_on(today)
        lines.append(f"今天（{weekday_name(today.isoweekday())}）："
                     + (f"按计划练{session.name}" if session is not None else "按计划休息"))  # fmt: skip
    else:
        lines.append("还没有训练计划")
    got = training_patterns(inp.logs, today, days=28, plan=inp.plan, plan_since=inp.since)
    lines += [f.detail() for f in got.findings] or list(got.notes)
    for m in snap.metrics:
        if m.key in ("kcal_target", "protein_target", "bmr") and m.ok:
            lines.append(f"{m.name}：{m.text}")
    if inp.diet is not None:
        lines.append(f"现在的热量调整：每天 {inp.diet.kcal:+d} 千卡（{inp.diet.reason}）")
    lines += [f"生病：{x}" for x in ill]
    said = inp.day.tired() if inp.day is not None else None
    if said is not None:
        lines.append(f"今天他说：{said.text()}")
    lines += extra
    return {f"F{i}": x for i, x in enumerate(lines, start=1)}, tuple(dict.fromkeys(refs))


def _kb_lines(refs: tuple[str, ...]) -> list[str]:
    kb = default_kb()
    out = []
    for r in refs:
        e = kb.get(r)
        if e is not None:
            out.append(f"{r} {e.title}：{e.points[0].text}")
    return out


def _source_text(ids: list[str], fs: dict[str, str]) -> str:
    """依据给人看的说法：用到的事实原文和资料名称（追问依据时讲）。"""
    kb = default_kb()
    parts = [fs[i] for i in ids if i in fs]
    parts += [
        f"{e.title}（{e.publisher.split('（')[0]} {e.year}）" for i in ids if (e := kb.get(i))
    ]
    return "；".join(parts)


def _ids(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else re.findall(r"[FK]\d+", str(raw or ""))
    return [str(x).strip() for x in items if re.fullmatch(r"[FK]\d+", str(x).strip())]


async def run(
    user_id: str, deps: Deps, llm: LLM, *, today: date | None = None, force: bool = False
) -> Review:
    """跑一次复盘（今天已经做过就直接用；force 时重做）。结果存进管家的方案，再重新评估一次。"""
    today = today or date.today()
    state = await deps.store.get(user_id)
    if not force and state is not None and state.review is not None and state.review.day == today:
        return state.review
    inp = await _gather(user_id, deps, today)
    checked, extra, hist = await _outcomes(user_id, deps, inp, today)
    staging = stage_due(state.stage_day if state is not None else None, inp.since, inp.logs, today)
    if staging:
        extra += [f"阶段：{x}" for x in _stage(inp, hist, today)]
    fs, refs = facts(inp, today, extra)
    blocked = any(r.block for r in risks(inp.snapshot.readings, (), today))
    user = "\n".join(
        ["事实：", *(f"[{k}] {v}" for k, v in fs.items()), "", "可以引用的资料：", *_kb_lines(refs)]
    )
    try:
        reply = await asyncio.wait_for(
            llm.chat(
                "expert",
                [{"role": "system", "content": _PROMPT}, {"role": "user", "content": user}],
            ),
            TIMEOUT_S,
        )
        raw = parse_json(reply.content) or {}
    except Exception as e:  # 模型不可用：不调整，不退回规则（§85 需求 5）
        _log.warning("review failed: error_type=%s", type(e).__name__)
        raw = None
    review = Review(day=today, failed=raw is None, checked=checked)
    if raw is not None:
        review.summary = str(raw.get("summary") or "")[:120]
        if staging:
            review.stage = str(raw.get("stage") or "").strip()[:400]
        adjust = raw.get("adjust")
        for a in adjust if isinstance(adjust, list) else []:
            if not isinstance(a, dict):
                continue
            done = await _apply(user_id, deps, inp, a, fs, blocked, today)
            if done is not None:
                review.done.append(done)
    await _save(user_id, deps, review, today)
    _log.info("review done %s", json.dumps({"adjust": len(review.done), "failed": review.failed}))
    return review


def _short(d: date) -> str:
    return f"{d.month}月{d.day}日"


async def _outcomes(
    user_id: str, deps: Deps, inp: Inputs, today: date
) -> tuple[list[str], list[str], list[Change]]:
    """到期的预期先对一遍数据（§89 需求 2）：结果写回那条调整经历。返回（今天核对完的，给模型的事实，
    更新后的调整经历）。撤销了的不核对。"""
    hist = await deps.store.history(user_id, 200)
    declined = {(c.key, c.day) for c in hist if c.kind == "review" and c.change == "declined"}
    live = [c for c in hist if c.kind == "review" and c.change == "added" and c.check
            and (c.key, c.day) not in declined]  # fmt: skip
    checked: list[str] = []
    for i, c in enumerate(hist):
        chk = parse_check(c.check)
        if c not in live or c.result or c.due is None or c.due > today or chk is None:
            continue
        value, how = measure(chk, c.day, c.due, inp.snapshot.readings, inp.logs, inp.plan)
        result = judge(chk, value)
        new = c.model_copy(update={"result": result, "outcome": f"{RESULT_WORDS[result]}（{how}）"})
        await deps.store.update(user_id, new)
        hist[i] = new
        checked.append(f"{_short(c.day)}{c.after}：预期{c.expect or chk.line()}，{new.outcome}")
    lines: list[str] = []
    for c in hist:
        if c.kind != "review" or c.change != "added" or not c.check or (c.key, c.day) in declined:
            continue
        if c.result and c.due is not None and (today - c.due).days <= 56:
            lines.append(f"以前调整的效果：{_short(c.day)}{c.after}（原因：{c.why}）；"
                         f"预期{c.expect}；{c.outcome}")  # fmt: skip
        elif not c.result and c.due is not None and c.due > today:
            lines.append(
                f"还在等结果：{_short(c.day)}{c.after}；预期{c.expect}，{_short(c.due)}核对"
            )
    if checked:
        _log.info("review checked %s", json.dumps({"n": len(checked)}))
    return checked, lines, hist


def _stage(inp: Inputs, hist: Sequence[Change], today: date) -> list[str]:
    """4 周阶段事实（§89 需求 4）：代码算，模型只写小结。"""
    from ironm_agent.expect import STAGE_DAYS
    from ironm_agent.goal import line as goal_line

    declined = {(c.key, c.day) for c in hist if c.kind == "review" and c.change == "declined"}
    one: dict[tuple[str, date], Change] = {}  # 同一条调整重新评估时也会记一次：留带预期的那条
    for c in hist:
        k = (c.key, c.day)
        if (c.kind == "review" and c.change == "added" and c.status == "auto"
                and (today - c.day).days < STAGE_DAYS and k not in declined
                and (k not in one or (c.check and not one[k].check))):  # fmt: skip
            one[k] = c
    adj = sorted(one.values(), key=lambda c: c.at)
    words = [f"{_short(c.day)}{c.after}" + (f"，{c.outcome}" if c.outcome else "，还没到核对的时候")
             for c in adj][:8]  # fmt: skip
    line = goal_line(inp.goal, inp.snapshot) if inp.goal is not None else ""
    return stage_facts(inp.snapshot.readings, inp.logs, today, goal_line=line, adjustments=words)


async def _apply(
    user_id: str,
    deps: Deps,
    inp: Inputs,
    a: dict[str, Any],
    fs: dict[str, str],
    blocked: bool,
    today: date,
) -> Done | None:
    """校验一条调整（只查算得对不对、安全底线），通过就执行；不通过返回 None。"""
    kind = str(a.get("type") or "")
    ids = _ids(a.get("basis"))
    kb = default_kb()
    if not any(i in fs for i in ids) or any(i.startswith("K") and kb.get(i) is None for i in ids):
        _log.info("review item dropped: type=%s reason=basis", kind)
        return None  # 依据的编号对不上：不执行
    if any(i.startswith("F") and i not in fs for i in ids):
        return None
    why = str(a.get("why") or "").strip()[:80]
    basis = _source_text(ids, fs)
    expect = str(a.get("expect") or "").strip()[:80]
    chk = parse_check(a.get("check"))
    if kind in ("today", "plan", "kcal") and chk is None:
        _log.info("review item without check: type=%s", kind)  # 照样执行，只是不核对（§89 需求 1）
    track = (
        {"check": chk.model_dump(), "due": today + timedelta(days=chk.days)}
        if chk is not None
        else {}
    )
    if kind in ("today", "plan") and blocked:
        return None  # 危急指标：不调训练（代码已经拦下、建议就医）
    if kind == "today":
        if a.get("rest") is True:
            return Done(key="review:today", type="today", title="今天休息", why=why, basis=basis,
                        expect=expect, value={"rest": True}, **track)  # fmt: skip
        ratio = a.get("ratio")
        if isinstance(ratio, int | float) and 0 < float(ratio) < 1:
            r = round(float(ratio), 2)
            return Done(key="review:today", type="today", title=f"今天的训练按约{round(r * 10)}成练",
                        why=why, basis=basis, expect=expect, value={"ratio": r}, **track)  # fmt: skip
        return None
    if kind == "plan":
        got = await _plan(user_id, deps, inp, a, why, basis, expect)
        return got.model_copy(update=track) if got is not None else None
    if kind == "kcal":
        got = await _kcal(user_id, deps, inp, a, why, basis, expect, today)
        return got.model_copy(update=track) if got is not None else None
    if kind in ("note", "ask"):
        text = str(a.get("text") or "").strip()[:80]
        if not text:
            return None
        return Done(key=f"review:{kind}", type=kind, title=text, why=why, basis=basis)
    return None


async def _plan(
    user_id: str, deps: Deps, inp: Inputs, a: dict[str, Any], why: str, basis: str, expect: str
) -> Done | None:
    from ironm_agent.plan_ops import Conflict, apply, parse_ops
    from ironm_agent.protools.plan_check import check_plan

    ops = parse_ops(a.get("ops"))
    if inp.plan is None or ops is None:
        return None
    try:
        got = apply(inp.plan, ops)
    except Conflict:
        return None
    if not got.done or check_plan(got.plan, current=inp.plan).problems:
        return None  # 套不上，或改完有必须改的问题：不执行
    content = plan_content(
        got.plan, why or "管家复盘", ops=[o.model_dump(mode="json") for o in got.done]
    )
    draft = await deps.training.add_draft(user_id, "plan", content)
    if await deps.training.confirm(user_id, draft.id) is None:
        return None
    return Done(key="review:plan", type="plan", title="计划已调整：" + "；".join(got.lines)[:100],
                why=why, basis=basis, expect=expect, value={"draft": draft.id})  # fmt: skip


async def _kcal(
    user_id: str,
    deps: Deps,
    inp: Inputs,
    a: dict[str, Any],
    why: str,
    basis: str,
    expect: str,
    today: date,
) -> Done | None:
    delta = a.get("delta")
    by = {m.key: m for m in inp.snapshot.metrics}
    target, bmr = by.get("kcal_target"), by.get("bmr")
    if not isinstance(delta, int | float) or not delta or target is None or target.value is None:
        return None
    if bmr is None or bmr.value is None:
        return None
    floor = safe_floor(bmr.value, inp.snapshot.profile)
    want = round(float(delta))
    new = target.value + want
    note = ""
    if new < floor:  # 安全底线：不低于基础代谢和安全下限，低了按下限执行并写明
        want = round(floor - target.value)
        new = floor
        note = f"（按基础代谢和安全下限，只调到 {round(floor)} 千卡）"
        if want >= 0:
            return None
    before = inp.diet.kcal if inp.diet is not None else 0
    after = before + want
    await deps.diet.apply(user_id, KcalAdjust(kcal=after, since=today, reason=why or "管家复盘"))
    title = f"每日热量目标{'加' if want > 0 else '减'} {abs(want)} 千卡，约 {round(new)} 千卡{note}"
    return Done(key="review:kcal", type="kcal", title=title, why=why, basis=basis, expect=expect,
                value={"before": before, "after": after})  # fmt: skip


async def _save(user_id: str, deps: Deps, review: Review, today: date) -> None:
    """复盘结果存进管家的方案，每条调整记进调整经历；再重新评估，今天的版本按复盘改。"""
    state = await deps.store.get(user_id)
    if state is None:
        state, _ = await evaluate(user_id, deps, reason="管家复盘", today=today)
    at = datetime.now(UTC)
    changes = [Change(id=uuid.uuid4().hex[:16], at=at, day=today, version=state.version, key=d.key,
                      kind="review", change="added", after=d.title, why=d.why, basis=d.basis,
                      status="info" if d.type in ("note", "ask") else "auto",
                      expect=d.expect, check=d.check, due=d.due)
               for d in review.done]  # fmt: skip
    update: dict[str, Any] = {"review": review}
    if review.stage:  # 阶段小结写成了：下一次从今天起算 28 天（§89）
        update.update(stage_day=today, stage_text=review.stage)
    await deps.store.save(user_id, state.model_copy(update=update), changes)
    await evaluate(user_id, deps, reason="管家复盘", today=today)


async def daily(user_id: str, deps: Deps) -> None:
    """每天第一次打开 App 或提问时跑一次（今天做过就不再跑）；出错只记错误类型。"""
    try:
        await run(user_id, deps, TurnLLM(load_models(), os.environ))
    except Exception as e:
        _log.warning("daily review failed: error_type=%s", type(e).__name__)


_BACKGROUND: set[asyncio.Task[None]] = set()


def daily_later(user_id: str, deps: Deps) -> None:
    """在后台跑当天的复盘，不耽误这次请求。"""
    task = asyncio.create_task(daily(user_id, deps))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def undo(user_id: str, deps: Deps, key: str, today: date | None = None) -> Done | None:
    """ "不用这样调"：计划恢复上一版、热量恢复原来的、今天回到原计划；记进调整经历。"""
    today = today or date.today()
    state = await deps.store.get(user_id)
    review = state.review if state is not None else None
    if state is None or review is None or review.day != today:
        return None
    done = next((d for d in review.done if d.key == key and not d.undone), None)
    if done is None or done.type in ("note", "ask"):
        return None
    if done.type == "plan":
        await deps.training.undo(user_id, str(done.value.get("draft")))
    if done.type == "kcal":
        await deps.diet.undo(user_id)
    new = review.model_copy(update={"done": [d.model_copy(update={"undone": True}) if d is done else d
                                            for d in review.done]})  # fmt: skip
    change = Change(id=uuid.uuid4().hex[:16], at=datetime.now(UTC), day=today, version=state.version,
                    key=key, kind="review", change="declined", after=done.title, why=done.why,
                    basis=done.basis, status="auto")  # fmt: skip
    await deps.store.save(user_id, State.model_validate({**state.model_dump(), "review": new.model_dump()}),
                          [change])  # fmt: skip
    await evaluate(user_id, deps, reason="不用这样调", today=today)
    return done
