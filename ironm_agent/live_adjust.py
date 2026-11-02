"""训练中实时调整（spec [2026-10-23] §90）：他在练的时候说"太重了""很累""膝盖有点疼"，由模型决定后面怎么练。

代码只保证算对和安全：只改还没完成的组；重量、次数、秒数在范围内；加重一次不超过这组原来的一成；
说了疼不加重、不加组；换的动作要在动作库里；说的是急症就不改训练、按急症回答。模型失败时不改。
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.live import Live, LiveError, LiveItem, LiveSet, known, new_item
from ironm_agent.llm import LLM, parse_json
from ironm_agent.progression import history
from ironm_agent.training import Plan, WorkoutLog

_log = logging.getLogger("ironm_agent.live")

TIMEOUT_S = 20.0
UP_MAX = 0.10  # 加重一次最多加这组原来重量的一成
# 训练中加重一次最多加一档（§90 需求 6）：下肢 5 公斤，上肢、哑铃、器械 2.5 公斤
STEP_LOWER, STEP_UPPER = 5.0, 2.5
LOWER_PARTS = frozenset({"腿臀"})
MAX_ADD = 3  # 一次最多加几组
MAX_SETS = 20
_HURT = re.compile(r"疼|痛|伤|肿|麻|扭|抽筋|拉到")
QUICK = ("太重了", "太轻了", "很累", "时间不够了", "哪里疼")  # 页面上的快捷说法
FAILED = "这次没调成，你可以直接改后面几组的重量和次数。"

_PROMPT = """你是健身管家 IronM。他正在训练，刚跟你说了一句。下面是这次训练的情况（动作和组都编了号，数是记录器里记的）和他今天的情况。
由你决定后面怎么练，没有固定规则；只能改还没做的组，做完的不动。可以：
- {"kind": "set", "item": 动作号, "set": 组号, "weight_kg": 数, "reps": 数}：改某一组（计时动作用 "seconds"）
- {"kind": "all", "item": 动作号, "weight_kg": 数, "reps": 数}：这个动作还没做的组都改成这样
- {"kind": "drop_sets", "item": 动作号, "count": 几组}：少做几组
- {"kind": "add_sets", "item": 动作号, "count": 几组}：多做几组
- {"kind": "swap", "item": 动作号, "to": "动作库里的动作名"}：后面的组换成别的动作（同一类：蹲换蹲、推换推、拉换拉）
- {"kind": "skip", "item": 动作号}：这个动作今天不练了
不需要改就不改。说疼的：不加重、不加组，先停下这个动作或换成不压痛处的；疼得厉害、肿、麻的，建议今天到此为止、去看医生。说累的：减重量或减组，别练到力竭。说太轻的：先加次数，做到目标次数的上限；次数到上限了还明显轻松（还能多做三个以上）才加重量，只加最小一档（上肢杠铃 2.5 公斤、下肢杠铃 5 公斤、哑铃每只 1–2 公斤），训练中一次只加一档；只做了一组、说不准能不能加时，不改，先问他这组还能再做几个。时间不够的：保留多关节的大动作，减辅助动作。
"say"：一两句话，第一句就说怎么改，再说为什么，像教练站在旁边说；不写编号、不用 markdown。
"end"：建议今天到此为止时写 true。
只输出 JSON：{"say": "…", "changes": [...], "end": false}"""


@dataclass
class Adjusted:
    live: Live
    say: str
    end: bool = False
    urgent: bool = False
    kinds: list[str] = field(default_factory=list)  # 执行了的改动类型（运行记录只记这个）
    dropped: int = 0  # 没执行的改动条数


def _set_text(it: LiveItem, s: LiveSet) -> str:
    if it.timed:
        return f"{s.seconds or '?'} 秒"
    w = f"{s.weight_kg:g} 公斤" if s.weight_kg is not None else "不记重量"
    return f"{w} × {s.reps if s.reps is not None else '?'} 次"


def session_lines(live: Live) -> list[str]:
    """这次训练：每个动作做完的组和还没做的组（编号从 1 开始）。"""
    out = []
    for i, it in enumerate(live.items, start=1):
        done = [f"第{j}组 {_set_text(it, s)}" + (f"（用时 {s.seconds} 秒）" if s.seconds and not it.timed else "")
                for j, s in enumerate(it.sets, start=1) if s.done]  # fmt: skip
        todo = [f"第{j}组 {_set_text(it, s)}" for j, s in enumerate(it.sets, start=1) if not s.done]
        aim = f"（目标：{it.target}）" if it.target else "（没有目标次数）"
        out.append(f"动作{i} {it.exercise}{'（计时）' if it.timed else ''}{aim}：做完 "
                   + ("；".join(done) or "还没有") + "。没做 " + ("；".join(todo) or "没有了"))  # fmt: skip
    return out


def current(live: Live) -> int | None:
    """正在练的动作：第一个还有没完成的组的（下标从 0 开始）。"""
    return next((i for i, it in enumerate(live.items) if any(not s.done for s in it.sets)), None)


def _num(raw: Any, lo: float, hi: float) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw) if lo <= float(raw) <= hi else None


def step_of(exercise: str) -> float:
    """训练中加重的一档：下肢动作 5 公斤，其余 2.5 公斤。"""
    from ironm_agent.exercises import library

    move = next((x for x in library().exercises if x.name == exercise), None)
    return STEP_LOWER if move is not None and move.part in LOWER_PARTS else STEP_UPPER


def _capped(old: float | None, new: float, hurt: bool, step: float = STEP_UPPER) -> float:
    """加重的安全底线：一次最多加一档、也不超过原来的一成；说了疼不加重。"""
    if old is None or old <= 0:
        return new
    if hurt:
        return min(new, old)
    return min(new, old + step, round(old * (1 + UP_MAX) * 2) / 2)  # 按 0.5 公斤取整


def _base(it: LiveItem, s: LiveSet) -> float | None:
    """比较加重用的原重量：这组填的；没填就用这个动作刚做完的最后一组。"""
    if s.weight_kg is not None:
        return s.weight_kg
    done = [x.weight_kg for x in it.sets if x.done and x.weight_kg is not None]
    return done[-1] if done else None


def _edit(it: LiveItem, s: LiveSet, c: dict[str, Any], hurt: bool) -> bool:
    changed = False
    if it.timed:
        sec = _num(c.get("seconds"), 1, 3600)
        if sec is not None:
            s.seconds, changed = round(sec), True
        return changed
    w = _num(c.get("weight_kg"), 0, 500)
    if w is not None:
        s.weight_kg, changed = _capped(_base(it, s), w, hurt, step_of(it.exercise)), True
    r = _num(c.get("reps"), 1, 100)
    if r is not None:
        s.reps, changed = round(r), True
    return changed


def apply(
    live: Live,
    changes: Sequence[Any],
    *,
    hurt: bool,
    plan: Plan | None = None,
    logs: Sequence[WorkoutLog] = (),
    rests: dict[str, int] | None = None,
) -> tuple[Live, list[str], int]:
    """把模型给的改动套到这次训练上（只动没完成的组）。返回（新的训练，执行了的类型，没执行的条数）。"""
    items = [it.model_copy(deep=True) for it in live.items]
    order = list(range(len(items)))  # 动作号 → 现在的位置（换动作会插入新的）
    kinds: list[str] = []
    dropped = 0
    emptied: list[LiveItem] = []  # 这次改动拿掉了全部组的动作
    for c in changes:
        kind = str(c.get("kind") or "") if isinstance(c, dict) else ""
        n = c.get("item") if isinstance(c, dict) else None
        if not isinstance(n, int) or not 1 <= n <= len(order):
            dropped += 1
            continue
        it = items[order[n - 1]]
        todo = [s for s in it.sets if not s.done]
        ok = False
        if kind == "set":
            j = c.get("set")
            if isinstance(j, int) and 1 <= j <= len(it.sets) and not it.sets[j - 1].done:
                ok = _edit(it, it.sets[j - 1], c, hurt)
        elif kind == "all" and todo:
            ok = any([_edit(it, s, c, hurt) for s in todo])
        elif kind == "drop_sets":
            k = c.get("count")
            if isinstance(k, int) and k >= 1 and todo:
                cut = todo[-k:]
                it.sets = [s for s in it.sets if not any(s is x for x in cut)]
                emptied.append(it)
                ok = True
        elif kind == "add_sets" and not hurt:
            k = c.get("count")
            if (
                isinstance(k, int)
                and 1 <= k <= MAX_ADD
                and it.sets
                and len(it.sets) + k <= MAX_SETS
            ):
                last = it.sets[-1]
                it.sets += [LiveSet(weight_kg=last.weight_kg, reps=last.reps,
                                    seconds=None if not it.timed else last.seconds) for _ in range(k)]  # fmt: skip
                ok = True
        elif kind == "skip" and todo:
            it.sets = [s for s in it.sets if s.done]
            emptied.append(it)
            ok = True
        elif kind == "swap" and todo:
            try:
                name = known(str(c.get("to") or ""))
            except LiveError:
                name = ""
            if name and name != it.exercise:
                new = new_item(name, plan, logs, rests or {})
                if new.sets:
                    new.sets = [new.sets[0].model_copy() for _ in todo]
                it.sets = [s for s in it.sets if s.done]
                emptied.append(it)
                pos = order[n - 1] + 1
                items.insert(pos, new)
                order = [p + 1 if p >= pos else p for p in order]
                ok = True
        if ok:
            kinds.append(kind)
        else:
            dropped += 1
    kept = [
        it for it in items if it.sets or not any(it is x for x in emptied)
    ]  # 一组都没做又不练了的，拿掉
    return live.model_copy(update={"items": kept}), kinds, dropped


def context_lines(
    live: Live,
    target: int | None,
    said: str,
    *,
    state: str = "",
    injuries: Sequence[str] = (),
    illness: Sequence[str] = (),
    coach: str = "",
    logs: Sequence[WorkoutLog] = (),
) -> str:
    about = f"动作{target + 1} {live.items[target].exercise}" if target is not None else "整次训练"
    lines = ["这次训练：", *session_lines(live), "", f"他说（关于{about}）：{said}"]
    if state:
        lines.append(f"今天的身体状态：{state}")
    lines += [f"记着的伤病：{x}" for x in injuries]
    lines += [f"在生病：{x}" for x in illness]
    if coach:
        lines.append(f"管家今天的调整：{coach}")
    names = (
        [live.items[target].exercise] if target is not None else [x.exercise for x in live.items]
    )
    for name in names:
        for d, sets in history(name, logs)[:3]:
            done = "；".join(
                f"{s.weight_kg:g}公斤×{s.reps}" if s.weight_kg else f"{s.reps}次" for s in sets
            )
            lines.append(f"{name} {d.month}月{d.day}日做了：{done}")
    return "\n".join(lines)


async def adjust(
    llm: LLM,
    live: Live,
    said: str,
    target: int | None,
    facts: str,
    *,
    plan: Plan | None = None,
    logs: Sequence[WorkoutLog] = (),
    rests: dict[str, int] | None = None,
) -> Adjusted:
    """他说了一句：急症按急症回答；否则让模型决定怎么改，代码按安全底线套上。"""
    from ironm_agent.render import sections_text
    from ironm_agent.safety.emergency import assess
    from ironm_agent.safety.replies import four_section
    from ironm_agent.spoken import URGENT, say, urgent_needs

    hit = assess(said)
    if hit.level != "none":  # 急症：不改训练，建议结束（§86 的做法）
        from ironm_agent.plugin import _replies

        sections = four_section(_replies(), hit)
        spoken = await say(llm, URGENT, "\n".join(f"{x.title}：{x.text}" for x in sections), said,
                           urgent_needs(hit.level, hit.categories))  # fmt: skip
        return Adjusted(live, spoken or sections_text(sections), end=True, urgent=True)
    hurt = bool(_HURT.search(said))
    try:
        reply = await asyncio.wait_for(
            llm.chat(
                "expert",
                [{"role": "system", "content": _PROMPT}, {"role": "user", "content": facts}],
                json_mode=True,
            ),
            TIMEOUT_S,
        )
        raw = parse_json(reply.content)
    except Exception as e:
        _log.warning("live adjust failed: error_type=%s", type(e).__name__)
        raw = None
    if not isinstance(raw, dict):
        return Adjusted(live, FAILED)
    changes = raw.get("changes")
    new, kinds, dropped = apply(live, changes if isinstance(changes, list) else [], hurt=hurt,
                                plan=plan, logs=logs, rests=rests)  # fmt: skip
    from ironm_agent.checks import plain

    text = plain(str(raw.get("say") or "")).strip()[:200] or (
        "先不改，按原来的练。" if not kinds else ""
    )
    return Adjusted(new, text, end=raw.get("end") is True, kinds=kinds, dropped=dropped)
