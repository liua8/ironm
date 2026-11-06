"""管家复盘（spec [2026-10-23] §85、§129）：代码只负责算对，调不调、调什么、调多少由管家按规程决定。

每天一次叫醒管家做"到期复查"：代码把算好的事实（两种比较、同期发生的事、训练、今天的计划、热量目标）
编好号交给它，装上该复查的规程（今天练不练每次都装，饮食方案满 14 天没调热量才装，排训练计划满 4 周才装），
它用工具调：今天按几成练或休息、调热量、提改计划、提醒或问一句，每条写原因、依据和预期。代码只做三件事：
依据的编号要存在；改计划的操作套得上、检查没有必须改的问题；热量不低于基础代谢和安全下限、危急指标不调训练。
今天、热量通过的直接生效、记进调整经历、能撤销；改计划存成预览，他同意才保存（§129 需求 3）。
模型调用失败时不调整，不退回规则替它决定。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.actions import ADJUST_TODAY, KCAL_CHANGE, PLAN_EDIT, TEMP_CHANGE
from ironm_agent.casefile import risks
from ironm_agent.coach_state import (
    NOT_REFUSED,
    REFUSE_DAYS,
    Change,
    Deps,
    Done,
    Inputs,
    Refusal,
    Review,
    State,
    _gather,
    alive,
    carry,
    evaluate,
    expiry,
    hanging_lines,
    refusals,
    state_lock,
)
from ironm_agent.expect import RESULT_WORDS, judge, measure, parse_check, stage_due, stage_facts
from ironm_agent.insights import compare
from ironm_agent.kb import default_kb
from ironm_agent.llm import LLM, parse_json
from ironm_agent.metrics import KcalAdjust, safe_floor
from ironm_agent.training import DRAFT_HOURS, REST_WORDS, plan_content, week_start, weekday_name
from ironm_agent.user_models import pick_quiet

_log = logging.getLogger("ironm_agent.review")

TIMEOUT_S = 60.0
# 复盘时常用的资料（模型引用时写编号）；两种比较用到的资料另外加进来
COMMON = ("K03", "K09", "K16", "K18", "K28", "K31", "K37", "K64", "K81", "K82", "K87", "K88")

_PROMPT = """你是健身 App 里的「AI 健身管家」。现在不是他在问你，是系统每天叫醒你做一次到期复查：下面是系统算好的事实（编号 F..，数都是代码算的，照用，不要自己算、不要编）和可以引用的资料（编号 K..）。

按装上的规程里「到期复查」一节判断今天要不要调、调什么、调多少；没有固定的规则，由你决定。要调就调用工具（{tools}），可以调几样，也可以都不调：
- 每次调用都写 why（一句话原因，像当面对他说，不写编号）、basis（用到的事实和资料编号，至少一个 F）、expect（给人看的预期，带时间）、check（系统到期能核对的预期：{{"metric": "weight|resting_hr|hrv|sleep|steps|waist|body_fat|completion|e1rm", "op": "<=" 或 ">=", "value": 数, "days": 3–42}}，e1rm 加 "exercise"；提醒和问一句可以不写预期）。
- 只有调用了工具才算调了：总结里写"今天按七成练""热量少吃 200"不会生效。
- 结果会告诉你生效了没有；没生效的看原因，改了再调或者不调。
- 把事实放在一起看：同期发生的事只是"可能有关"，不当成因果；数据不够或说不准时，宁可不调或问一句。危急的情况系统已经拦下，你不用处理。
- 事实里有"以前调整的效果"：没达到的不要原样再来一次（换个做法、或者问他）；"还在等结果"的同类调整不要叠加。
{stage}
做完只输出 JSON：{{"summary": "一句话：今天看到的最重要的情况（都正常就写都正常）"{stage_field}}}

装上的规程（到期复查）：
{skills}"""

_STAGE = '事实里有"阶段："开头的几条：今天满 4 周了，另外写 stage：3–5 句阶段小结，像当面对他说——这 4 周练得怎么样、变了什么、调整有没有用、下 4 周的重点；数照事实里的写。'
MAX_TURNS = 6  # 和模型最多往返几次（含调工具）；到了就不再给工具，请它作答
# 总结里说到要调（按几成练、休息、减量、调热量）：没调用工具就提醒一次；前面几个字是否定的不算
_SAYS_ADJUST = re.compile(
    r"按\s*[一二三四五六七八九\d到至~～—–-]+\s*成|[降减]到\s*[一二三四五六七八九\d]+\s*成|[五六七八九]成练"
    r"|练\s*\d{2}\s*%|按\s*0\.\d|休息一天|今天休息(?!日)|减量|少吃|多吃|[上下]调\s*\d+|减\s*\d+\s*千卡|调到|调整为"
)
# 只认紧贴在前面的明确否定："不用减量""先不调"；"睡眠不足今天按七成练"里的"不"是在说原因，不算（复核 11-03）
_NEGATED = re.compile(
    r"(?:不用|不必|不要|无需|不需要|没必要|暂时不|先不|别|不)\s*$|(?:不用|不必|不要|无需|不需要|没必要|暂时不|先不).{0,2}$"
)


def says_adjust(text: str) -> bool:
    """总结里是不是说了要调（"不用减量""暂时不需要调整为"这类否定的不算）。"""
    return any(
        not _NEGATED.search(text[max(0, m.start() - 6) : m.start()])
        for m in _SAYS_ADJUST.finditer(text)
    )


NUDGE = (
    "（系统核对）你的总结里说到要调整，但这一轮没有调用工具，所以什么都没生效。要调就调用对应的工具"
    "（今天按几成练或休息、调热量……）；本来就不打算调的，照原样输出 JSON。"
)
DIET_DAYS = 14  # 距上次调热量满几天才复查饮食（同 §18）

_WHY = {"type": "string", "description": "一句话原因，像当面对他说，不写编号"}
_BASIS = {
    "type": "array",
    "items": {"type": "string"},
    "description": "用到的事实和资料编号，至少一个 F",
}
_EXPECT = {"type": "string", "description": '给人看的预期，带时间，如"两周后静息心率回到 62 以下"'}
_CHECK = {
    "type": "object",
    "description": "系统到期能核对的预期 {metric, op, value, days, exercise?}",
}


def _tool(
    name: str, description: str, props: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "additionalProperties": False,
        "properties": {**props, "why": _WHY, "basis": _BASIS, "expect": _EXPECT, "check": _CHECK},
        "required": [*required, "why", "basis"]}}}  # fmt: skip


NOTE = "coach_note"
CHECKUP = "checkup"  # 复查存的计划预览在草稿里的来源标记
TOOLS: dict[str, dict[str, Any]] = {
    ADJUST_TODAY: _tool(ADJUST_TODAY, "只改今天这一次：按几成练（ratio 0.5–0.9）或休息（rest）。原计划不变，他能说不用这样调。",
                        {"ratio": {"type": "number"}, "rest": {"type": "boolean"}}, []),
    KCAL_CHANGE: _tool(KCAL_CHANGE, "调每日热量目标：每天多吃（正数）或少吃（负数）多少千卡。不低于基础代谢和安全下限。",
                       {"delta": {"type": "integer"}}, ["delta"]),
    PLAN_EDIT: _tool(PLAN_EDIT, "提改计划（以后都这样）：交操作（swap/move/add/edit/remove/reduce，同对话里改计划）。系统套用、检查后存成预览，他同意才保存。",
                     {"ops": {"type": "array", "items": {"type": "object"}}}, ["ops"]),
    TEMP_CHANGE: _tool(TEMP_CHANGE, "提临时调整（这几天这样练，到期回到原计划，如减量一周、病后一周、出差几天）：start、end（YYYY-MM-DD，最长 28 天）、ops（同改计划）。存成预览，他确认才生效。",
                       {"start": {"type": "string"}, "end": {"type": "string"},
                        "ops": {"type": "array", "items": {"type": "object"}}}, ["start", "end", "ops"]),
    NOTE: _tool(NOTE, "只提醒他一句（kind 写 note），或者拿不准时问他一句（kind 写 ask）。",
                {"kind": {"type": "string", "enum": ["note", "ask"]}, "text": {"type": "string"}}, ["kind", "text"]),
}  # fmt: skip
_TYPE = {ADJUST_TODAY: "today", KCAL_CHANGE: "kcal", PLAN_EDIT: "plan", TEMP_CHANGE: "temp"}
# 每类调整是哪一件事（§182：同一件事新的替换旧的、说了不用 14 天内不再提）
_KEY = {"today": "review:today", "kcal": "review:kcal", "plan": "review:propose", "temp": "review:temp",
        "note": "review:note", "ask": "review:ask"}  # fmt: skip
_LOCKS: dict[str, asyncio.Lock] = {}  # 每个人一把：同一天的复查不并发跑两次


def facts(
    inp: Inputs, today: date, extra: Sequence[str] = ()
) -> tuple[dict[str, str], tuple[str, ...]]:
    """编好号的事实（F1…）和这些事实用到的资料编号；extra 是以前调整的效果和阶段事实（§89）。"""
    from ironm_agent.illness import active, ago
    from ironm_agent.protools.movement import JOINT_NAMES
    from ironm_agent.protools.patterns import training_patterns

    snap = inp.snapshot
    lines: list[str] = []
    refs: list[str] = list(COMMON)
    for r in compare(snap.readings, snap.profile, today):
        lines.append(r.line())
        refs += r.refs
    ill = [f"{ago(e.started, today)}说{e.what()}" for e in active(inp.illness, today)]
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
    if (o := inp.seen) is not None:  # 按记录估的实际消耗（§118），调不调热量由管家定（§163 需求 6）
        lines.append(f"按记录估的实际消耗：每天约 {o.tdee} 千卡（最近 {o.days} 天平均每天吃 {o.intake} 千卡，"
                     f"体重每周 {o.kg_per_week:+.2f} 公斤，称了 {o.weighins} 次）")  # fmt: skip
    lines += [f"生病：{x}" for x in ill]
    for e in inp.illness:  # 好了的也给：病后第一次怎么练由管家定（§163）
        if not e.active and e.ended is not None and (today - e.ended).days <= 14:
            lines.append(f"生病经过：{ago(e.started, today)}说{e.what()}，{ago(e.ended, today)}好了")
    for e in (inp.day.entries if inp.day is not None else []):  # 今天说的累、睡了几小时、只有几分钟、状态好
        lines.append(f"今天他说：{e.text()}")
    for p in getattr(inp, "pain_details", None) or []:  # 近两周说疼：哪处、左右、在做哪个动作（§163）
        bits = [x for x in (p.get("side"), p.get("exercise") and f"做{p['exercise']}时", p.get("level")) if x]
        lines.append(f"说疼：{ago(p['day'], today)} {JOINT_NAMES.get(p['part'], p['part'])}" + (f"（{'，'.join(bits)}）" if bits else ""))
    lines += [f"临时调整（他确认过的）：{t.line()}" for t in inp.temps if t.end >= today]
    edits = list(getattr(inp.day, "edits", None) or []) if inp.day is not None else []
    if edits:  # 今天已经改过（对话里管家或他自己在计划页改的）：再按几成练会叠上去
        lines.append("今天已经改过（只改今天）：" + "；".join(e.line or f"{e.kind} {e.exercise}".strip() for e in edits))
    for log in inp.logs:  # 打卡勾的没练原因（他自己填的）
        if not log.done and log.rest and (today - log.day).days <= 7:
            lines.append(f"{ago(log.day, today)}没练：{REST_WORDS.get(log.rest, log.rest)}")
    if inp.advice is not None and inp.advice.reasons:  # 天气：户外练不练由管家定
        lines.append(f"今天的天气：{inp.advice.name}（{'；'.join(inp.advice.reasons)}）")
    from ironm_agent.memory_layers import unconfirmed_lines

    lines += [f"很久没确认的记忆：{x}" for x in unconfirmed_lines(inp.memory, today)]  # 问不问由管家定（§182）
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


RETRY_AFTER = timedelta(minutes=10)  # 失败后自动再试的间隔：模型一直不可用时不至于每次打开都调一次


async def run(
    user_id: str, deps: Deps, llm: LLM, *, today: date | None = None, force: bool = False,
    retry: bool = False,
) -> Review:  # fmt: skip
    """跑一次复盘（今天已经做过就直接用；force 时重做）。结果存进管家的方案，再重新评估一次。"""
    today = today or date.today()
    async with _LOCKS.setdefault(
        user_id, asyncio.Lock()
    ):  # 打开对话和第一次提问同时触发：只跑一次（审查 11-03）。只在单进程里有效，多进程要换数据库锁
        try:
            return await _run(user_id, deps, llm, today=today, force=force, retry=retry)
        except Exception as e:  # 还没调模型就出错（读数据、计划）：记成失败，首页显示"管家出错了"、能重试（复核 11-05）
            _log.warning("review setup failed: error_type=%s", type(e).__name__)
            failed = Review(day=today, failed=True, failed_at=datetime.now(UTC))
            try:  # 早上已经生效的照留着（和模型出错时一样）：没就今天做出决定才算失败（复核 11-05）
                state = await deps.store.get(user_id)
                earlier = state.review if state is not None and state.review is not None and state.review.day == today else None
                if earlier is not None:
                    told = earlier.today() is not None
                    failed = earlier.model_copy(update={"failed": not told, "failed_at": None if told else failed.failed_at})
                await _save(user_id, deps, failed, today)
            except Exception as e2:
                _log.warning("review failure not saved: error_type=%s", type(e2).__name__)
            return failed


async def _run(user_id: str, deps: Deps, llm: LLM, *, today: date, force: bool, retry: bool = False) -> Review:
    state = await deps.store.get(user_id)
    earlier = state.review if state is not None and state.review is not None and state.review.day == today else None
    if not force and earlier is not None:  # 失败的过一会儿再试；他点了重试就马上试（复核 11-05）
        waited = earlier.failed_at is None or datetime.now(UTC) - earlier.failed_at >= RETRY_AFTER
        if not earlier.failed or not (retry or waited):
            return earlier
    inp = await _gather(user_id, deps, today)
    stored = await deps.training.plan(user_id)  # 提改计划的底稿：和 inp.plan 同时取（复核 11-03）
    base = stored.id if stored is not None else ""
    root = stored.line_id if stored is not None else ""
    checked, extra, hist = await _outcomes(user_id, deps, inp, today)
    staging = stage_due(state.stage_day if state is not None else None, inp.since, inp.logs, today)
    last_week = state.week_day if state is not None else None
    weekly = inp.plan is not None and (last_week is None or week_start(last_week) < week_start(today))
    if weekly:  # 这周第一次复查：看一眼这周和上周（§163，取代规则的每周复盘和提醒）
        extra += _week_facts(inp, today)
    if staging:
        extra += [f"阶段：{x}" for x in _stage(inp, hist, today)]
    kept = list(earlier.done) if earlier is not None else []  # 失败的那次已经生效的也留着（复核 11-05）
    extra += [f"今天已经定过：{d.title}（要改就再调一次，同一项以这次为准）" for d in kept if not d.undone]
    extra += [f"今天他撤销了：{d.title}（别再这样调）" for d in kept if d.undone]
    # 前几天提的、还挂着的建议和 14 天内他拒绝过的（§182）：再提同一件事会替换旧的；拒绝过的系统不再执行
    refused_now = refusals(state, today)
    mine = {d.key for d in kept}
    hanging = [d for d in await alive(user_id, deps.training, carry(state, today)) if d.key not in mine]
    extra += hanging_lines(hanging, refused_now, today, skip={d.key for d in kept if d.undone})
    fs, refs = facts(inp, today, extra)
    blocked = any(r.block for r in risks(inp.snapshot.readings, inp.memory, today))
    skills = _due_skills(inp, today, staging or weekly)
    allowed = {NOTE, *(t for x in skills for t in x.toolset if t in TOOLS)}
    schemas = [TOOLS[n] for n in TOOLS if n in allowed]
    system = _PROMPT.format(
        tools="、".join(n for n in TOOLS if n in allowed),
        stage=_STAGE if staging else "",
        stage_field=', "stage": "阶段小结"' if staging else "",
        skills="\n\n".join(x.section("到期复查") or x.text() for x in skills),
    )
    user = "\n".join(
        ["事实：", *(f"[{k}] {v}" for k, v in fs.items()), "", "可以引用的资料：", *_kb_lines(refs)]
    )
    review = Review(day=today, checked=checked, weekly=weekly)
    if earlier is not None:  # 同一天重看：早上定的照留着，同一项以这次为准（复核 11-05）
        review = Review(day=today, checked=[*earlier.checked, *(x for x in checked if x not in earlier.checked)],
                        weekly=weekly or earlier.weekly, done=list(kept), stage=earlier.stage,
                        summary=earlier.summary)  # fmt: skip
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw: dict[str, Any] | None = None
    nudged = False
    try:
        for turn in range(MAX_TURNS + 1):
            offer = schemas if turn < MAX_TURNS else None  # 到了往返上限：不再给工具，请它作答
            reply = await asyncio.wait_for(
                llm.chat("coach", messages, tools=offer or None, json_mode=not offer), TIMEOUT_S
            )
            if not reply.tool_calls or not offer:  # 没给工具的那一轮还要调：不执行，按它写的作答
                raw = parse_json(reply.content) or {}
                said = str(raw.get("summary") or "")
                if (
                    offer
                    and turn < MAX_TURNS - 1
                    and not nudged
                    and review.done == kept
                    and says_adjust(said)
                ):
                    nudged = True  # 总结里说了要调、却没调用工具：提醒一次（真实模型 11-03）
                    messages.append({"role": "assistant", "content": reply.content})
                    messages.append({"role": "user", "content": NUDGE})
                    continue
                break
            messages.append(reply.as_message())
            for call in reply.tool_calls:
                said = await _call(
                    base,
                    user_id,
                    deps,
                    inp,
                    call.name,
                    call.arguments,
                    allowed,
                    fs,
                    blocked,
                    today,
                    review,
                    root,
                    refused_now,
                )
                messages.append({"role": "tool", "tool_call_id": call.id, "content": said})
    except Exception as e:  # 模型不可用：不调整，不退回规则（§85 需求 5）；已经生效的照记，能撤销
        _log.warning("review failed: error_type=%s", type(e).__name__)
        review.failed = review.today() is None  # 没就今天做出决定：显示"管家出错了"，能重试
        if review.failed:
            review.failed_at = datetime.now(UTC)
    if raw is not None:
        review.summary = str(raw.get("summary") or "")[:120]
        if staging:
            review.stage = str(raw.get("stage") or "").strip()[:400]
    await _save(user_id, deps, review, today)
    _log.info("review done %s", json.dumps({"adjust": len(review.done), "failed": review.failed}))
    return review


def _week_facts(inp: Inputs, today: date) -> list[str]:
    """每周复查的事实：上周和这周到今天，计划练几次、练了几次（生病的日子不算应练）。"""
    from ironm_agent.illness import sick_days
    from ironm_agent.training import week_of

    sick = sick_days(inp.illness, today)
    out = []
    for label, day in (("上周", week_start(today) - timedelta(days=1)), ("这周到今天", today)):
        w = week_of(inp.plan, inp.logs, day, inp.since, sick)
        out.append(f"{label}：计划 {w.planned} 次，该练 {w.due} 次，练了 {w.done} 次")
    return out


def _due_skills(inp: Inputs, today: date, staging: bool) -> list[Any]:
    """今天该复查哪几份规程（§129 需求 1）：今天练不练每次都查；满 14 天没调热量查饮食；满 4 周查计划。"""
    from ironm_agent.skills import by_id

    want = ["readiness-adjust"]
    if inp.diet is None or (today - inp.diet.since).days >= DIET_DAYS:
        want.append("diet-plan")
    if staging and inp.plan is not None:
        want.append("plan-build")
    return [x for x in (by_id(i) for i in want) if x is not None]


async def _call(
    base: str,
    user_id: str, deps: Deps, inp: Inputs, name: str, args: dict[str, Any], allowed: set[str],
    fs: dict[str, str], blocked: bool, today: date, review: Review, root: str = "",
    refused_now: dict[str, Refusal] | None = None,
) -> str:  # fmt: skip
    """执行一次复查里的工具调用：校验沿用 §85 的 _apply；同一项调两次以后一次为准；他 14 天内拒绝过的同一件事
    不执行（§182）。日志只记工具名和结果。"""
    if name not in allowed:
        _log.info("review tool: tool=%s result=locked", name)
        return f"今天的复查没有 {name}（没到复查它的时候），不调这一项。"
    kind = str(args.get("kind") or "note") if name == NOTE else _TYPE[name]
    no = (refused_now or {}).get(_KEY.get(kind, ""))
    if no is not None and _KEY.get(kind) not in NOT_REFUSED:
        _log.info("review tool: tool=%s result=refused", name)
        n = (today - no.day).days
        return (f"没执行：他{'今天' if n == 0 else f' {n} 天前'}拒绝过「{no.title}」，同一件事 {REFUSE_DAYS} 天内不再提；"
                "别的可以照常调，或者不调。")  # fmt: skip
    a = {**args, "type": kind, "_base": base, "_root": root}
    first = (
        next((d for d in review.done if d.key == "review:kcal" and not d.undone), None) if kind == "kcal" else None
    )
    if first is not None:  # 同一轮第二次调热量：先撤掉第一次，撤销时才回得到原样（审查 11-03）
        await deps.diet.undo(user_id)
    try:
        done = await _apply(user_id, deps, inp, a, fs, blocked, today)
    except Exception:
        done = None
        if first is not None:  # 写库出错：第一次补回去，记录和库保持一致（复核 11-03）
            await deps.diet.apply(
                user_id,
                KcalAdjust(int(first.value.get("after") or 0), today, first.why or "管家复盘"),
            )
        raise
    if done is None and first is not None:  # 第二次没通过：第一次照旧
        await deps.diet.apply(
            user_id, KcalAdjust(int(first.value.get("after") or 0), today, first.why or "管家复盘")
        )
    if done is not None:  # 出现日期和到期日（§182）：带预览的已经按预览的有效期写好
        done = done.model_copy(update={"appeared": today, "expires": done.expires or expiry(today)})
    if done is None:
        _log.info("review tool: tool=%s result=rejected", name)
        return ("没执行：依据要写事实编号（至少一个 F，资料编号要存在）；危急情况不调训练；"
                "改计划的操作要套得上、检查要过；热量要写多少千卡。按原因改了再调，或者不调。")  # fmt: skip
    old = next((d for d in review.done if d.key == done.key), None)
    if old is not None:  # 同一项以后一次为准；前一次提的计划预览作废
        review.done.remove(old)
        if old.type == "propose":
            await deps.training.cancel(user_id, str(old.value.get("draft")))
    review.done.append(done)
    _log.info("review tool: tool=%s result=ok", name)
    if done.type == "propose":
        return f"已存成计划预览，等他确认：{done.title}"
    return f"已生效：{done.title}"


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
            and c.status != "confirm" and (c.key, c.day) not in declined]  # fmt: skip  # 提的改计划没执行，不核对
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
        if (c.kind != "review" or c.change != "added" or not c.check or c.status == "confirm"
                or (c.key, c.day) in declined):  # fmt: skip
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
    if kind in ("today", "plan", "temp") and blocked:
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
        got = await _plan(user_id, deps, inp, a, why, basis, expect, today)
        return got.model_copy(update=track) if got is not None else None
    if kind == "temp":
        got = await _temp(user_id, deps, inp, a, why, basis, expect, today)
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
    user_id: str, deps: Deps, inp: Inputs, a: dict[str, Any], why: str, basis: str, expect: str,
    today: date | None = None,
) -> Done | None:  # fmt: skip
    from ironm_agent.plan_ops import Conflict, apply, parse_ops
    from ironm_agent.protools.plan_check import check_plan

    ops = parse_ops(a.get("ops"))
    if inp.plan is None or ops is None:
        return None
    try:
        got = apply(inp.plan, ops)
    except Conflict:
        return None
    from ironm_agent.special import flags, is_special

    special = flags(
        inp.snapshot.profile, risks(inp.snapshot.readings, inp.memory, date.today()), date.today()
    )
    # 特殊人群的硬规则（§95）：原计划本来就有的不挡（否则连减量都改不了），只挡这次改出来的
    had = {p for p in check_plan(inp.plan, special=special).problems if is_special(p)}
    left = [p for p in check_plan(got.plan, current=inp.plan, special=special).problems
            if not (is_special(p) and p in had)]  # fmt: skip
    if not got.done or left:
        return None  # 套不上，或改完有必须改的问题：不执行
    content = plan_content(
        got.plan, why or "管家复盘", ops=[o.model_dump(mode="json") for o in got.done]
    )
    content = {
        **content,
        "source": CHECKUP,
        "base": str(a.get("_base") or ""),
    }  # 计划后来改过就不再给这份预览
    draft = await deps.training.add_draft(
        user_id, "plan", content
    )  # 存成预览，他同意才保存（§129）
    day = today or date.today()
    last = day + timedelta(days=-(-DRAFT_HOURS // 24))  # 预览还能确认的最后一天（24 小时：到明天）
    return Done(key="review:propose", type="propose", title="建议这样改计划：" + "；".join(got.lines)[:100],
                why=why, basis=basis, expect=expect, value={"draft": draft.id},
                expires=expiry(day, last))  # fmt: skip


async def _temp(
    user_id: str, deps: Deps, inp: Inputs, a: dict[str, Any], why: str, basis: str, expect: str, today: date
) -> Done | None:
    """提临时调整（§163）：日期和操作核对、套得上、检查过，存成临时调整预览，他确认才生效。"""
    from ironm_agent import plan_layers
    from ironm_agent.plan_ops import Conflict, apply, parse_ops
    from ironm_agent.protools.plan_check import check_plan
    from ironm_agent.special import flags, is_special

    ops = parse_ops(a.get("ops"))
    try:
        start, end = date.fromisoformat(str(a.get("start") or "")), date.fromisoformat(str(a.get("end") or ""))
    except ValueError:
        return None
    if inp.plan is None or ops is None or start < today or end < start or (end - start).days >= plan_layers.MAX_DAYS:
        return None
    base = plan_layers.stacked(inp.plan, inp.temps, start, end)  # 和重叠的临时调整叠起来再检查（复核 11-05）
    try:
        got = apply(inp.plan, ops)
        layered = apply(base, ops).plan
    except Conflict:
        return None
    special = flags(inp.snapshot.profile, risks(inp.snapshot.readings, inp.memory, today), today)
    had = {p for p in check_plan(base, special=special).problems if is_special(p)}
    left = [p for p in check_plan(layered, current=base, special=special).problems
            if not (is_special(p) and p in had)]  # fmt: skip
    if not got.done or left:
        return None
    content = {**plan_layers.content(start, end, why, got, got.lines, str(a.get("_root") or "")), "source": CHECKUP,
               "base": str(a.get("_base") or "")}  # fmt: skip
    draft = await deps.training.add_draft(user_id, "temp", content)
    span = f"{start.month}月{start.day}日" + (f"到{end.month}月{end.day}日" if end != start else "")
    return Done(key="review:temp", type="propose", title=f"建议{span}临时这样练：" + "；".join(got.lines)[:90],
                why=why, basis=basis, expect=expect, value={"draft": draft.id, "temp": True},
                expires=expiry(today, start))  # 过了开始日期预览就作废（§163）  # fmt: skip


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
    """管家定的热量调整（§163 需求 6）：调多少由它定，代码只守上下限（同对话里调热量，diet_adjust._apply）：
    单次不超过 ±300、累计不超过原目标 ±500、不低于基础代谢和安全下限、被下限推成反方向的不调；
    18 岁以下、孕期不减。超了按上下限执行并写明。"""
    from ironm_agent.diet_adjust import MAX_STEP, MAX_TOTAL
    from ironm_agent.diet_adjust import _apply as within_limits
    from ironm_agent.special import MINOR, PREGNANCY, flags

    delta = a.get("delta")
    by = {m.key: m for m in inp.snapshot.metrics}
    target, bmr = by.get("kcal_target"), by.get("bmr")
    if not isinstance(delta, int | float) or isinstance(delta, bool) or not delta:
        return None
    if target is None or target.value is None or bmr is None or bmr.value is None:
        return None
    want = round(float(delta))
    special = flags(inp.snapshot.profile, risks(inp.snapshot.readings, inp.memory, today), today)
    if want < 0 and special & {MINOR, PREGNANCY}:  # 特殊人群硬规则：不减热量（§90）
        return None
    prop, _ = within_limits(want, why, basis, target.value, bmr.value, inp.snapshot.profile, inp.diet)
    if prop is None:
        return None
    before = inp.diet.kcal if inp.diet is not None else 0
    note = ""
    if prop.after == round(safe_floor(bmr.value, inp.snapshot.profile)) and prop.delta != want:
        note = f"（按基础代谢和安全下限，只调到 {prop.after} 千卡）"
    elif abs(prop.total) == MAX_TOTAL and prop.delta != want:
        note = f"（累计最多调 {MAX_TOTAL} 千卡，只调到 {prop.after} 千卡）"
    elif abs(want) > MAX_STEP:
        note = f"（一次最多调 {MAX_STEP} 千卡）"
    await deps.diet.apply(user_id, KcalAdjust(kcal=prop.total, since=today, reason=why or "管家复盘"))
    title = f"每日热量目标{'加' if prop.delta > 0 else '减'} {abs(prop.delta)} 千卡，约 {prop.after} 千卡{note}"
    return Done(key="review:kcal", type="kcal", title=title, why=why, basis=basis, expect=expect,
                value={"before": before, "after": prop.total})  # fmt: skip


async def _save(user_id: str, deps: Deps, review: Review, today: date) -> None:
    """复盘结果存进管家的方案，每条调整记进调整经历；再重新评估，今天的版本按复盘改。"""
    if await deps.store.get(user_id) is None:
        await evaluate(user_id, deps, reason="管家复盘", today=today)
    async with state_lock(user_id):  # 读改存之间不让别的写进来（§132 审查）
        await _save_locked(user_id, deps, review, today)
    await evaluate(user_id, deps, reason="管家复盘", today=today)


async def _save_locked(user_id: str, deps: Deps, review: Review, today: date) -> None:
    state = await deps.store.get(user_id)
    if state is None:
        return
    at = datetime.now(UTC)
    prev = state.review.done if state.review is not None and state.review.day == today else []
    changes = [Change(id=uuid.uuid4().hex[:16], at=at, day=today, version=state.version, key=d.key,
                      kind="review", change="added", after=d.title, why=d.why, basis=d.basis,
                      status="info" if d.type in ("note", "ask") else "confirm" if d.type == "propose" else "auto",
                      expect=d.expect, check=d.check, due=d.due)
               for d in review.done if not d.undone and d not in prev]  # fmt: skip  # 早上记过的、撤销了的不再记（复核 11-05）
    # 前几天提的、还挂着的建议（§182）：今天又提了同一件事的，新的替换旧的（旧的预览作废）
    mine = {d.key: d for d in review.done}
    carried = []
    for d in carry(state, today):
        new = mine.get(d.key)
        if new is None:
            carried.append(d)
        elif d.type == "propose" and d.value.get("draft") and d.value.get("draft") != new.value.get("draft"):
            try:
                await deps.training.cancel(user_id, str(d.value["draft"]))
            except Exception as e:
                _log.info("replaced draft not cancelled: error_type=%s", type(e).__name__)
    update: dict[str, Any] = {"review": review, "carried": carried, "refused": refusals(state, today)}
    if review.stage:  # 阶段小结写成了：下一次从今天起算 28 天（§89）
        update.update(stage_day=today, stage_text=review.stage)
    if review.weekly and not review.failed:  # 这周看过了（失败的下次再看）
        update.update(week_day=today)
    await deps.store.save(user_id, state.model_copy(update=update), changes)


async def daily(user_id: str, deps: Deps) -> None:
    """每天第一次打开 App 或提问时跑一次（今天做过就不再跑）；出错只记错误类型。"""
    try:
        if (llm := await pick_quiet(user_id)) is None:  # 用他自己的模型；没填今天就不看（§167）
            return
        await run(user_id, deps, llm)
    except Exception as e:
        _log.warning("daily review failed: error_type=%s", type(e).__name__)


_BACKGROUND: set[asyncio.Task[None]] = set()


def rerun_later(user_id: str, deps: Deps, reason: str) -> None:
    """他说了身体或安排上的事、首页点了"累了""只有几分钟"、回答了"好些了吗"：叫醒管家重看今天（§163 需求 3）。
    今天做过也重做；在后台跑，出错只记错误类型。"""

    async def go() -> None:
        try:
            if (llm := await pick_quiet(user_id)) is None:  # 没填自己的模型就不重看（§167）
                return
            await run(user_id, deps, llm, force=True)
        except Exception as e:
            _log.warning("review rerun failed: error_type=%s reason=%s", type(e).__name__, reason[:20])

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def retry_later(user_id: str, deps: Deps) -> None:
    """首页"管家出错了"点重试：失败的马上再试一次；已经看成了的不重跑（点两下也只跑一次）。"""

    async def go() -> None:
        try:
            if (llm := await pick_quiet(user_id)) is None:
                return
            await run(user_id, deps, llm, retry=True)
        except Exception as e:
            _log.warning("review retry failed: error_type=%s", type(e).__name__)

    task = asyncio.create_task(go())
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


def daily_later(user_id: str, deps: Deps) -> None:
    """在后台跑当天的复盘，不耽误这次请求。"""
    task = asyncio.create_task(daily(user_id, deps))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)


async def undo(
    user_id: str, deps: Deps, key: str, today: date | None = None, *, refuse: bool = True
) -> Done | None:
    """ "不用这样调"：计划恢复上一版、热量恢复原来的、今天回到原计划；记进调整经历。前几天提的、还挂着的也能撤。
    refuse：是他说的不用，同一件事 14 天内不再提（§182）；计划后来改过、预览过时了由系统收起的不算。"""
    today = today or date.today()
    async with state_lock(user_id):
        done = await _undo(user_id, deps, key, today, refuse)
    if done is not None:
        await evaluate(user_id, deps, reason="不用这样调", today=today)
    return done


async def _undo(user_id: str, deps: Deps, key: str, today: date, refuse: bool = True) -> Done | None:
    state = await deps.store.get(user_id)
    if state is None:
        return None
    review = state.review if state.review is not None and state.review.day == today else None
    done = next((d for d in review.done if d.key == key and not d.undone), None) if review is not None else None
    if done is None:  # 前几天提的、还挂着的（§182）
        done = next((d for d in carry(state, today) if d.key == key), None)
    if done is None or done.type in ("note", "ask"):
        return None
    if done.type == "plan":
        await deps.training.undo(user_id, str(done.value.get("draft")))
    if done.type == "propose":  # 还没确认的作废；他已经确认了的恢复上一版（审查 11-03）
        draft = await deps.training.draft(user_id, str(done.value.get("draft")))
        if draft is None or draft.state not in ("pending", "confirmed"):
            return None
        if draft.state == "pending":
            await deps.training.cancel(user_id, draft.id)
        elif await deps.training.undo(user_id, draft.id) is None:
            return None
    if done.type == "kcal":
        await deps.diet.undo(user_id)
    await _declined(user_id, deps, state, review, done, today, refuse)
    return done


async def _declined(
    user_id: str, deps: Deps, state: State, review: Review | None, done: Done, today: date, refuse: bool
) -> None:
    """记下这条不要了：今天提的标成撤销，前几天提的从挂着的里拿掉；他说的不用记进 refused（§182）。"""
    update: dict[str, Any] = {}
    if review is not None and any(d is done for d in review.done):
        update["review"] = review.model_copy(update={"done": [d.model_copy(update={"undone": True}) if d is done else d
                                                              for d in review.done]})  # fmt: skip
    else:  # 前几天提的：把挂着的接好（更早那次复盘的已经接进来了，不再留着它，免得再接一次）
        update["carried"] = [d for d in carry(state, today) if d.key != done.key]
        update["review"] = review
    refused_now = refusals(state, today)
    if refuse and done.key not in NOT_REFUSED:
        refused_now[done.key] = Refusal(title=done.title, day=today)
    update["refused"] = refused_now
    change = Change(id=uuid.uuid4().hex[:16], at=datetime.now(UTC), day=today, version=state.version,
                    key=done.key, kind="review", change="declined", after=done.title, why=done.why,
                    basis=done.basis, status="auto")  # fmt: skip
    await deps.store.save(user_id, state.model_copy(update=update), [change])
    _log.info("review declined %s", json.dumps({"type": done.type, "refused": refuse}))


async def declined_draft(user_id: str, deps: Deps, draft_id: str, today: date | None = None) -> bool:
    """他在预览卡片上点了取消：管家提的这条算他说了不用（§182），同一件事 14 天内不再提。预览已经作废，这里只记。"""
    today = today or date.today()
    async with state_lock(user_id):
        state = await deps.store.get(user_id)
        if state is None:
            return False
        review = state.review if state.review is not None and state.review.day == today else None
        live = [*(d for d in (review.done if review is not None else []) if not d.undone), *carry(state, today)]
        done = next((d for d in live if d.type == "propose" and str(d.value.get("draft")) == draft_id), None)
        if done is None:
            return False
        await _declined(user_id, deps, state, review, done, today, True)
    await evaluate(user_id, deps, reason="不用这样调", today=today)
    return True
