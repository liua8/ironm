"""两周快进模拟（spec [2026-10-23] §162）：用假数据看管家怎么调整方案、帮他练。

在本机一个进程里跑：各存储换成内存版（不连数据库、不碰任何真实账号），健康数据逐日生成，模型用真的。
按剧本逐日把时钟拨到那一天，像真用户一样建档、要计划、打卡、说累了、说疼、生病又好了、问进展；
每天先像打开首页一样让管家评估一次。每一步的输入、回答、计划和下次目标的变化记进报告。

    uv run --with time-machine python scripts/simulate.py                   # 三个剧本各跑两周
    uv run --with time-machine python scripts/simulate.py --only B --days 2 # 只跑剧本 B 的前两天（调试）

剧本（§163 验收要多剧本）：A 增肌、健身房，睡得少、膝盖疼、感冒、出差；B 新手减脂、在家，加班漏练、
体重不动、出差没器械；C 有基础、健身房，次数做满看进阶，肩不舒服、只有 30 分钟、想多练一天。
每个剧本一个模拟用户，填好自己的模型（§167），管家后台复查才会跑。

报告写到 evals/sim/reports/（不进仓库）。要调用真实模型，先查余额。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TZ = timezone(timedelta(hours=8))
UID = "sim-user"
START = date(2026, 10, 19)  # 第一天是周一
OUT = ROOT / "evals" / "sim" / "reports"

PROFILE = {"height_cm": 175, "birth": "1998-05-01", "sex": "male", "goal": "muscle", "activity": "moderate"}
# 每个剧本的人和身体数据（体重起点、每天变化；哪几天睡得少、心率高）
SCENES: dict[str, dict[str, Any]] = {
    "A": {"uid": "sim-a", "profile": PROFILE, "kg": 72.0, "per_day": 0.02, "short_sleep": {2: 5.0, 8: 6.0, 9: 6.0},
          "high_hr": (8, 9)},
    "B": {"uid": "sim-b", "profile": {"height_cm": 162, "birth": "1993-03-12", "sex": "female", "goal": "fat_loss",
                                      "activity": "light"},
          "kg": 66.0, "per_day": 0.0, "short_sleep": {3: 5.5, 4: 5.5}, "high_hr": ()},
    "C": {"uid": "sim-c", "profile": {"height_cm": 178, "birth": "1995-08-20", "sex": "male", "goal": "muscle",
                                      "activity": "moderate"},
          "kg": 75.0, "per_day": 0.03, "short_sleep": {}, "high_hr": ()},
}  # fmt: skip
SCENE: dict[str, Any] = SCENES["A"]


def load_env() -> None:
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ---- 假的健康数据 --------------------------------------------------------------------------------


def readings_until(today: date) -> Any:
    """体重从 72.0 公斤慢慢往上（增肌），睡眠 7 小时左右，静息心率 62；剧本里的几天按情况改。"""
    from ironm_agent.metrics import Readings

    rng = random.Random(7)
    days = [START - timedelta(days=27) + timedelta(days=i) for i in range((today - START).days + 28)]
    weight, sleep, hr, steps = [], [], [], []
    short, high = SCENE["short_sleep"], SCENE["high_hr"]
    for d in days:
        n = (d - START).days
        weight.append((d, round(SCENE["kg"] + SCENE["per_day"] * max(n, -27) + rng.uniform(-0.25, 0.25), 1)))
        sleep.append((d, short[n] if n in short else round(7.2 + rng.uniform(-0.4, 0.4), 1)))
        hr.append((d, 72 if n in high else 62 + rng.randint(-2, 2)))
        steps.append((d, 3000 if n in high else 8000 + rng.randint(-1500, 1500)))
    return Readings(weight=tuple(weight), sleep_hours=tuple(sleep), resting_hr=tuple(hr), steps=tuple(steps))


# ---- 把线上存储换成内存版 ------------------------------------------------------------------------

BOOKS = {
    "ironm_agent.coach_state": ("_default", "CoachBook"),
    "ironm_agent.day_state": ("_default", "DayBook"),
    "ironm_agent.goal": ("_default", "GoalBook"),
    "ironm_agent.illness": ("_default", "IllnessBook"),
    "ironm_agent.harness": ("_default", "TraceBook"),
    "ironm_agent.meals": ("_default", "MealBook"),
    "ironm_agent.memory_store": ("_default", "MemoryBook"),
    "ironm_agent.muscle_feel": ("_default", "FeelBook"),
    "ironm_agent.recipes": ("_default", "DietBook"),
    "ironm_agent.readings": ("_default", "ReadingBook"),
    "ironm_agent.session_summary": ("_default", "SummaryBook"),
    "ironm_agent.training": ("_default", "TrainingBook"),
    "ironm_agent.triggers": ("_default", "PainBook"),
    "ironm_agent.user_models": ("_store", "ModelBook"),
    "ironm_agent.diet_adjust": ("_default", "DietBook"),
    "ironm_agent.live": ("_default", "LiveBook"),
    "ironm_agent.checkin_photo": ("_default", "PhotoBook"),
    "ironm_agent.web_search": ("_default", "WebBook"),
}


def install() -> None:
    import importlib

    from ironm_agent import profile as profiles
    from ironm_agent import weather, web
    from ironm_agent.metrics import Profile, compute_all

    for mod, (attr, cls) in BOOKS.items():
        m = importlib.import_module(mod)
        setattr(m, attr, getattr(m, cls)())

    me: dict[str, Profile] = {}

    async def load(user_id: str) -> tuple[Profile, dict[str, str]]:
        return me.get(user_id, Profile()), {}

    async def save(user_id: str, data: Any) -> None:
        got = data.model_dump(exclude_unset=True)
        me[user_id] = replace(me.get(user_id, Profile()), **{k: v for k, v in got.items() if v is not None})

    async def set_goal(user_id: str, goal: str | None) -> None:
        me[user_id] = replace(me.get(user_id, Profile()), goal=goal)  # type: ignore[arg-type]

    profiles.load, profiles.save, profiles.set_goal = load, save, set_goal  # type: ignore[assignment]

    async def snapshot_for(user_id: str, today: date | None = None) -> Any:
        from ironm_agent.casefile import Snapshot

        today = today or date.today()
        readings = readings_until(today)
        profile, _ = await load(user_id)
        adjust = await web.kcal_adjust(user_id)
        return Snapshot(profile, readings, tuple(compute_all(readings, profile, today, adjust)), today)

    async def no_weather(*_: Any) -> None:
        return None

    web.snapshot_for = snapshot_for  # type: ignore[assignment]
    weather.for_user = no_weather  # type: ignore[assignment]


class NoHealth:
    """mirobody 健康数据查询：模拟里没有原始记录（档案里的指标已经由假数据算好）。"""

    async def envelope(self, user_info: Any, **args: Any) -> Any:
        from mirobody.kernel.tools import Envelope

        return Envelope("ok", data=[])


# ---- 模拟用户 -------------------------------------------------------------------------------------

BASE_KG = [("上斜哑铃卧推", 14.0), ("哑铃卧推", 16.0), ("哑铃推举", 12.0), ("哑铃划船", 16.0), ("哑铃臀推", 20.0),
           ("哑铃", 12.0), ("深蹲", 60.0), ("硬拉", 70.0), ("卧推", 50.0), ("划船", 40.0), ("推举", 30.0), ("下拉", 45.0),
           ("腿举", 100.0), ("弯举", 10.0), ("臂屈伸", 10.0), ("飞鸟", 10.0), ("哑铃", 14.0), ("杠铃", 40.0)]  # fmt: skip
NO_WEIGHT = re.compile(r"平板支撑|俯卧撑|卷腹|引体|自重|拉伸|热身|有氧|跑|骑|快走|椭圆|跳|死虫|鸟狗|桥")


@dataclass
class Sim:
    client: Any
    agent: Any
    log: list[dict[str, Any]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    session: str = ""
    day: dict[str, Any] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)  # 每轮的运行记录（走了哪条路、调了哪些工具）

    async def drain(self) -> None:
        """等后台的事做完（管家评估、定下次、记忆提取）。"""
        await self.agent.settle()
        for _ in range(50):
            others = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
            if not others:
                return
            await asyncio.wait(others, timeout=180)

    async def say(self, text: str) -> dict[str, Any]:
        msgs = [{"role": "user", "content": text}]
        self.runs.clear()
        t0 = time.perf_counter()
        blocks = [b async for b in self.agent.generate_response(UID, msgs, session_id=self.session)]
        await self.drain()
        answer = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text").strip()
        cards = [dict(b.get("args") or {}) for b in blocks
                 if b.get("type") == "tool_call" and str(b.get("id", "")).startswith("card-")]  # fmt: skip
        self.history += ["用户：" + text, "教练（要点）：" + answer[:300]]
        turn = {"kind": "chat", "say": text, "answer": answer, "secs": round(time.perf_counter() - t0, 1),
                "cards": [{"kind": c.get("kind"), "draft": c.get("draft")} for c in cards],
                "run": {k: v for r in self.runs[-1:] for k, v in r.items() if not k.startswith("_")}}  # fmt: skip
        self.day["steps"].append(turn)
        print(f"  他：{text}\n  管家（{turn['secs']} 秒）：{answer[:160]}{'…' if len(answer) > 160 else ''}")
        return turn

    async def get(self, path: str) -> Any:
        r = await self.client.get(path)
        return r.json() if r.status_code == 200 else {"status": r.status_code, "detail": r.text[:200]}

    async def post(self, path: str, body: Any = None) -> Any:
        r = await self.client.post(path, json=body or {})
        return r.json() if r.status_code == 200 else {"status": r.status_code, "detail": r.text[:200]}

    async def confirm(self, cards: list[dict[str, Any]], what: str) -> None:
        for c in cards:
            if c.get("draft"):
                got = await self.post(f"/iron/api/drafts/{c['draft']}/confirm")
                await self.drain()
                self.day["steps"].append({"kind": "confirm", "what": what, "card": c.get("kind"),
                                          "ok": "draft" in got})  # fmt: skip
                print(f"  他点了确认（{what}，{c.get('kind')}）")

    async def plan(self) -> Any:
        from ironm_agent.training import default_training

        stored = await default_training().plan(UID)
        return stored.plan if stored is not None else None

    async def open_app(self) -> None:
        """每天第一次打开：管家评估、首页今天、提醒。"""
        coach = await self.get("/iron/api/coach")
        await self.drain()
        coach = await self.get("/iron/api/coach")  # 后台复查跑完了再看一次（§163：今天怎么练由管家定）
        today = await self.get("/iron/api/today")
        self.day["coach"] = [{"title": x.get("title"), "detail": x.get("why") or x.get("detail"),
                              "action": x.get("action"), "key": x.get("key")} for x in coach.get("items", [])]  # fmt: skip
        self.day["coach_changes"] = coach.get("changes", [])
        self.day["today"] = today

    async def accept(self) -> None:
        """他照管家提的确认（改计划、临时调整的预览卡片），看确认后计划怎么变。"""
        coach = await self.get("/iron/api/coach")
        for x in coach.get("pending", []):
            draft = (x.get("value") or {}).get("draft")
            if draft:
                await self.confirm([{"kind": (x.get("value") or {}).get("type"), "draft": draft}],
                                   "管家提的：" + str(x.get("title"))[:40])  # fmt: skip

    async def illness(self) -> list[dict[str, Any]]:
        """生病记录（取证用）：开始、状态、症状、好了的那天。"""
        from ironm_agent.illness import default_illness

        eps = await default_illness().since(UID, START - timedelta(days=30))
        return [{"started": e.started.isoformat(), "status": e.status, "symptoms": e.symptoms, "level": e.level,
                 "ended": e.ended.isoformat() if e.ended else None} for e in eps]  # fmt: skip

    async def workout(self, *, rpe: int, note: str = "", hard: bool = False, light: bool = False,
                      energy: str | None = None, slept: str | None = None, sore: list[str] | None = None) -> None:  # fmt: skip
        """按今天的计划打卡：重量取管家定的下次目标，没有就按经验起始重量；状态好做到次数上限，差的做下限。"""
        from ironm_agent.web_more import decided_targets

        plan = await self.plan()
        session = plan.session_on(date.today()) if plan is not None else None
        if session is None:
            self.day["steps"].append({"kind": "workout", "skipped": "今天计划里没有训练"})
            return
        decided = await decided_targets(UID)
        items = []
        for it in session.items:
            name = it.exercise
            lo, hi = _rep_range(it.reps)
            target = decided.get(name) if isinstance(decided, dict) else None
            kg = _target_kg(target) or _base_kg(name, it)
            if light and kg:
                kg = round(kg * 0.7 / 2.5) * 2.5
            reps = hi if (hard and not light) else lo
            short = 1 if rpe >= 8 and not hard else 0  # 没睡好、吃力：最后一组差一次
            sets = max(1, min(it.sets or 3, 5))
            if NO_WEIGHT.search(name) or kg is None:
                items.append({"exercise": name[:30], "sets": sets, "reps": it.reps or str(reps)})
            else:
                done = [{"reps": reps if i < sets - 1 else max(reps - short, 1), "weight_kg": kg}
                        for i in range(sets)]  # fmt: skip
                items.append({"exercise": name[:30], "sets": sets, "reps": str(reps), "weight_kg": kg,
                              "done_sets": done})  # fmt: skip
        body = {"session": session.name[:16], "items": items, "rpe": rpe, "minutes": 60, "note": note,
                "energy": energy, "slept": slept, "sore": sore or []}  # fmt: skip
        got = await self.post("/iron/api/workouts", body)
        await self.drain()
        after = await decided_targets(UID)
        self.day["steps"].append({"kind": "workout", "session": session.name, "rpe": rpe, "note": note,
                                  "items": [_line(x) for x in items], "ok": "workout" in got,
                                  "targets_after": _targets_lines(after)})  # fmt: skip
        print(f"  打卡：{session.name}（感受 {rpe}）{('备注：' + note) if note else ''}")

    async def rest(self, why: str) -> None:
        got = await self.post("/iron/api/workouts", {"rest": why})
        await self.drain()
        self.day["steps"].append({"kind": "rest", "why": why, "ok": "workout" in got})
        print(f"  打卡：今天没练（{why}）")

    async def proposal(self, trigger: str = "") -> dict[str, Any]:
        got = await self.post("/iron/api/review/proposal" + (f"?trigger={trigger}" if trigger else ""))
        await self.drain()
        step = {"kind": "proposal", "trigger": trigger or "每周复盘", "status": got.get("status"),
                "answer": got.get("answer") or got.get("message") or got.get("detail"),
                "tips": got.get("tips"), "draft": (got.get("draft") or {}).get("id"),
                "ops": (got.get("draft") or {}).get("ops")}  # fmt: skip
        self.day["steps"].append(step)
        print(f"  复盘调整（{step['trigger']}）：{step['status']} {str(step['answer'])[:120]}")
        return got


def _rep_range(reps: str) -> tuple[int, int]:
    nums = [int(x) for x in re.findall(r"\d+", reps or "")]
    if not nums:
        return 10, 10
    return (nums[0], nums[1]) if len(nums) > 1 else (nums[0], nums[0])


def _target_kg(target: Any) -> float | None:
    """管家定的下次目标（progression.Decided）里的重量。"""
    v = getattr(target, "weight_kg", None)
    return float(v) if isinstance(v, int | float) and v else None


def _base_kg(name: str, item: Any) -> float | None:
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(?:公斤|kg)", getattr(item, "load", "") or ""):
        return float(m.group(1))  # 计划里写了重量就按计划
    if NO_WEIGHT.search(name):
        return None
    return next((kg for word, kg in BASE_KG if word in name), 20.0)


def _line(x: dict[str, Any]) -> str:
    if x.get("done_sets"):
        return f"{x['exercise']} " + "、".join(f"{s['weight_kg']:g}×{s['reps']}" for s in x["done_sets"])
    return f"{x['exercise']} {x.get('sets')} 组 × {x.get('reps')}"


def _targets_lines(decided: Any) -> list[str]:
    if not isinstance(decided, dict):
        return []
    out = []
    for name, t in decided.items():
        kg = getattr(t, "weight_kg", None)
        line = f"{name}：下次 {f'{kg:g} 公斤 × ' if kg else ''}{getattr(t, 'reps', '')} 次 × {getattr(t, 'sets', '')} 组"
        out.append(line + (f"（{t.why}）" if getattr(t, "why", "") else ""))
    return out


def plan_lines(plan: Any) -> list[str]:
    if plan is None:
        return []
    out = []
    for s in plan.sessions:
        items = "；".join(f"{x.exercise} {x.sets}×{x.reps}" + (f"（{x.load}）" if x.load else "") for x in s.items)
        out.append(f"{s.name}（周{'一二三四五六日'[s.day - 1] if 1 <= s.day <= 7 else s.day}）：{items}")
    return out


# ---- 两周的剧本 -----------------------------------------------------------------------------------


async def day_script(sim: Sim, n: int) -> None:
    if n == 0:  # 周一：建档、要计划、确认、练第一次
        await sim.client.put("/iron/api/profile", json=PROFILE)
        await sim.open_app()
        first = await sim.say("你好，我想增肌，在健身房练，一周练三次，每次一个小时左右。左膝以前扭伤过，"
                              "现在基本不疼了。练了三个月左右。帮我排个训练计划")  # fmt: skip
        if not first["cards"]:
            first = await sim.say("按这个排")
        await sim.confirm(first["cards"], "训练计划")
        await sim.workout(rpe=7, energy="good", slept="good")
    elif n == 1:  # 周二：练后酸
        await sim.open_app()
        await sim.say("昨天练完腿特别酸，今天下楼都酸，正常吗")
    elif n == 2:  # 周三：只睡了 5 小时
        await sim.open_app()
        await sim.say("昨晚只睡了5个小时，今天还练吗")
        await sim.workout(rpe=8, energy="poor", slept="poor")
    elif n == 3:
        await sim.open_app()
    elif n == 4:  # 周五：练的时候膝盖疼
        await sim.open_app()
        await sim.workout(rpe=7, note="深蹲的时候左膝有点疼", sore=["大腿前"])
    elif n == 5:  # 周六：问这周怎么样
        await sim.open_app()
        await sim.say("这周练下来感觉还行，有哪里要调整吗")
    elif n == 6:  # 周日：看周报
        await sim.open_app()
        sim.day["brief"] = await sim.get("/iron/api/brief")
    elif n == 7:  # 周一：状态好、次数做满，但膝盖又疼 → 看管家怎么一边加重一边护膝（§163：没有规则提醒，管家自己提）
        await sim.open_app()
        await sim.workout(rpe=6, hard=True, note="左膝又有点疼，蹲下去的时候", energy="good", slept="good")
    elif n == 8:  # 周二：感冒
        await sim.open_app()
        await sim.say("感冒了，嗓子疼，有点低烧，37度8")
    elif n == 9:  # 周三：好点了，没练
        await sim.open_app()
        await sim.say("今天好点了，不烧了，还有点咳嗽")
        await sim.rest("sick")
    elif n == 10:  # 周四：咳嗽也好了
        await sim.open_app()
        await sim.say("咳嗽也好了，今天一点症状都没有了，明天能练吗")
    elif n == 11:  # 周五：病后第一次，按管家说的轻一点
        await sim.open_app()
        await sim.workout(rpe=6, light=True, energy="ok", slept="good")
    elif n == 12:  # 周六：下周出差
        await sim.open_app()
        await sim.say("下周一到周三要出差，酒店健身房只有一对哑铃，最重20公斤")
    elif n == 13:  # 周日：问两周的情况，周复盘
        await sim.open_app()
        await sim.say("这两周我练得怎么样？下周怎么安排？")
        sim.day["brief"] = await sim.get("/iron/api/brief")


async def say_and_confirm(sim: Sim, text: str, what: str) -> None:
    got = await sim.say(text)
    await sim.confirm(got["cards"], what)


async def day_script_b(sim: Sim, n: int) -> None:
    """新手减脂、在家（一对 5 公斤哑铃），加班漏练、体重不动、出差没器械。"""
    await sim.open_app()
    if n == 0:
        await sim.client.put("/iron/api/profile", json=SCENE["profile"])
        first = await sim.say("我想减脂，没怎么练过，在家练，有一对 5 公斤的哑铃，一周能练三次，每次 40 分钟左右，"
                              "帮我排个计划")  # fmt: skip
        if not first["cards"]:
            first = await sim.say("可以，就按这个排")
        await sim.confirm(first["cards"], "训练计划")
        await sim.workout(rpe=7, energy="ok", slept="ok")
    elif n == 2:
        await sim.workout(rpe=7)
    elif n == 3:
        await sim.say("这周三晚上要加班，今天练不了了")
        await sim.rest("busy")
    elif n == 4:
        await sim.say("今天只有 20 分钟，昨晚也没睡好，还练吗")
        await sim.workout(rpe=8, energy="poor", slept="poor")
    elif n == 6:
        await sim.say("练了一周，体重一点没动，是不是要再少吃点？")
    elif n == 7:
        await sim.workout(rpe=6, energy="good", slept="good")
    elif n == 8:
        await sim.rest("busy")
    elif n == 9:
        await say_and_confirm(sim, "下周三到周五去上海出差，酒店没有健身房，房间里什么器械都没有", "出差的安排")
    elif n == 11:
        await sim.workout(rpe=7, energy="ok", slept="ok")
    elif n == 13:
        await sim.say("这两周我练得怎么样？体重还是没怎么掉，下周怎么安排？")
        sim.day["brief"] = await sim.get("/iron/api/brief")


async def day_script_c(sim: Sim, n: int) -> None:
    """有基础、健身房，每次都做满次数（看进阶）；卧推时肩不舒服；只有 30 分钟；想多练一天。"""
    await sim.open_app()
    if n == 0:
        await sim.client.put("/iron/api/profile", json=SCENE["profile"])
        first = await sim.say("我练了一年多，想继续增肌，健身房器械都有，一周练三次，每次一个小时，帮我排个计划")
        if not first["cards"]:
            first = await sim.say("按这个排")
        await sim.confirm(first["cards"], "训练计划")
        await sim.workout(rpe=7, hard=True, energy="good", slept="good")
    elif n in (2, 9, 11):
        await sim.workout(rpe=7, hard=True, energy="good", slept="good")
    elif n == 4:
        await sim.workout(rpe=7, hard=True, note="卧推的时候右肩前面有点不舒服，不算疼", energy="good")
    elif n == 6:
        await sim.say("这周每个动作次数都做满了，下周要加重吗？")
    elif n == 7:
        await sim.say("今天只有 30 分钟，怎么练？")
        await sim.workout(rpe=7, hard=True, energy="good", slept="good")
    elif n == 10:
        await sim.say("最近状态特别好，想一周多练一天，可以吗？")
    elif n == 13:
        await sim.say("这两周练得怎么样？下周怎么安排？")
        sim.day["brief"] = await sim.get("/iron/api/brief")


SCRIPTS = {"A": day_script, "B": day_script_b, "C": day_script_c}


async def main(days: int, only: list[str] | None = None) -> list[Path]:
    """每个剧本一个模拟用户，按顺序各跑一遍；报告一个剧本一份。"""
    out = []
    for key in only or list(SCRIPTS):
        out.append(await run_scene(key, days))
    return out


async def seed_model(uid: str) -> None:
    """模拟用户填好自己的模型（§167）：用 .env 里的 DeepSeek 密钥，对话模型和线上默认一样。"""
    from ironm_agent import user_models

    await user_models.default_models().put(uid, user_models.UserModel(
        provider="deepseek", base_url="https://api.deepseek.com", api_key=os.environ["DEEPSEEK_API_KEY"],
        chat_model="deepseek-flash"))  # fmt: skip


async def run_scene(key: str, days: int) -> Path:
    global UID, SCENE
    SCENE, UID = SCENES[key], SCENES[key]["uid"]
    print(f"\n######## 剧本 {key}（{UID}）")
    import logging

    import httpx
    import time_machine
    from fastapi import FastAPI
    from mirobody.server.auth import verify_token

    logging.basicConfig(level=logging.WARNING, format="  [日志] %(name)s %(message)s")
    load_env()
    install()
    from ironm_agent import web
    from ironm_agent.llm import load_models
    from ironm_agent.plugin import IronMAgent

    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: UID
    sim_holder: dict[str, Sim] = {}

    async def history(user_id: str, session_id: str) -> list[str]:
        return list(sim_holder["sim"].history[-12:])

    async def nothing(*_: Any) -> Any:
        return None

    async def empty(*_: Any) -> str:
        return ""

    async def whole(session_id: str) -> list[str]:
        return list(sim_holder["sim"].history)

    from ironm_agent import memory as chat_memory
    from ironm_agent import plugin as plugin_mod

    chat_memory.whole = plugin_mod.whole = whole  # type: ignore[assignment]  # 整段对话原文（模拟里没有 mirobody 的对话库）
    def observe(run: dict[str, Any]) -> None:
        sim_holder["sim"].runs.append(dict(run))

    agent = IronMAgent(health=NoHealth(), models=load_models(), environ=os.environ, history=history,
                       earlier=empty, sources=nothing, weather=nothing, observe=observe)  # fmt: skip
    report: dict[str, Any] = {"scene": key, "start": START.isoformat(), "profile": SCENE["profile"], "days": []}
    await seed_model(UID)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim") as client:
        sim = Sim(client, agent, session=f"{UID}:s1")
        sim_holder["sim"] = sim
        for n in range(days):
            day = START + timedelta(days=n)
            traveller = time_machine.travel(datetime(day.year, day.month, day.day, 19, 0, tzinfo=TZ), tick=True)
            traveller.start()
            try:
                print(f"\n==== 第 {n + 1} 天 {day.isoformat()}（周{'一二三四五六日'[day.weekday()]}）")
                before = plan_lines(await sim.plan())
                sim.day = {"n": n + 1, "date": day.isoformat(), "steps": [], "plan_before": before}
                try:
                    await SCRIPTS[key](sim, n)
                    await sim.accept()  # 管家今天提的改动，他照着确认
                except Exception as e:  # 记下来接着跑
                    sim.day["error"] = f"{type(e).__name__}: {e}"[:300]
                    print("  出错：", sim.day["error"])
                after = plan_lines(await sim.plan())
                sim.day["illness"] = await sim.illness()
                sim.day["plan_after"] = after
                sim.day["plan_changed"] = after != before
                report["days"].append(sim.day)
            finally:
                traveller.stop()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"sim-{key}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    print(f"\n报告：{path}")
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="两周快进模拟（假数据、内存存储、真实模型）")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--only", nargs="*", choices=sorted(SCRIPTS), help="只跑这几个剧本（默认全部）")
    a = p.parse_args()
    asyncio.run(main(a.days, a.only))
