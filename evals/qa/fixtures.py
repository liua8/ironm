"""问答考题里的人：按 cases.yaml 的 personas 生成档案、每天的健康数据、记忆、计划与训练记录。

健康数据按固定随机种子生成，同一份考题每次生成的数据一样；最后一天（今天）的值就是 base（没有波动），
方便在考题里写出确定的数字（如 BMI 24.5）。生成的数据同时交给两处：
- 指标计算（与数据页同一份计算，纯函数）；
- 假的健康数据查询（EvalHealth）：照 mirobody 查询接口的样子返回目录、最新值、统计、按天或按周的数据，
  每行带引用编号 rid，渲染走 mirobody 自己的代码。
"""

from __future__ import annotations

import random
import statistics
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.memory_store import Item
from ironm_agent.metrics import Point, Profile, Readings

# 数据类别 → mirobody 的指标名、显示名、单位、搜索时能对上的说法
INDICATORS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "weight": ("bodyMasss", "Body weight", "kg", ("体重", "weight", "body mass")),
    "height": ("heights", "Body height", "cm", ("身高", "height")),
    "resting_hr": ("restingHeartRates", "Heart rate --resting", "/min", ("静息心率", "心率", "heart rate", "resting")),
    "hrv_sdnn": ("hrvSDNN", "Heart rate variability SDNN", "ms", ("心率变异", "hrv", "sdnn")),
    "hrv_rmssd": ("hrvRMSSD", "Heart rate variability RMSSD", "ms", ("心率变异", "hrv", "rmssd")),
    "sleep": ("sleepDuration", "Sleep duration", "h", ("睡眠", "睡", "sleep")),
    "steps": ("dailySteps", "Number of steps in 24 hour Measured", "{#}", ("步数", "步", "steps")),
    "systolic": ("systolicPressures", "Systolic blood pressure", "mm[Hg]", ("血压", "收缩压", "blood pressure", "systolic")),
    "diastolic": ("diastolicPressures", "Diastolic blood pressure", "mm[Hg]", ("血压", "舒张压", "blood pressure", "diastolic")),
}  # fmt: skip
DECIMALS = {
    "weight": 1,
    "height": 0,
    "resting_hr": 0,
    "hrv_sdnn": 0,
    "hrv_rmssd": 0,
    "sleep": 1,
    "steps": 0,
}


@dataclass(frozen=True)
class Persona:
    name: str
    desc: str
    profile: Profile
    series: Mapping[str, tuple[Point, ...]]
    memory: tuple[Item, ...] = ()
    plan: Mapping[str, Any] | None = None
    workouts: tuple[Mapping[str, Any], ...] = ()

    def readings(self) -> Readings:
        s = self.series
        return Readings(
            weight=s.get("weight", ()),
            resting_hr=s.get("resting_hr", ()),
            hrv_sdnn=s.get("hrv_sdnn", ()),
            hrv_rmssd=s.get("hrv_rmssd", ()),
            sleep_hours=s.get("sleep", ()),
            steps=s.get("steps", ()),
            systolic=s.get("systolic", ()),
            diastolic=s.get("diastolic", ()),
        )


def _series(owner: str, key: str, spec: Mapping[str, Any], today: date) -> tuple[Point, ...]:
    rng = random.Random(zlib.crc32(f"{owner}:{key}".encode()))
    days, every = int(spec.get("days", 60)), int(spec.get("every", 1))
    base, jitter, slope = (
        float(spec["base"]),
        float(spec.get("jitter", 0)),
        float(spec.get("slope", 0)),
    )
    last = [float(v) for v in spec.get("last", [])]
    places = DECIMALS.get(key, 1)
    out: list[Point] = []
    for ago in range(days - 1, -1, -1):
        noise = rng.gauss(0, jitter)  # 每天都取一次，免得 every 改变了其他天的值
        if ago % every and ago:
            continue
        value = base if ago == 0 else base - slope * ago + noise
        if ago < len(last):
            value = last[len(last) - 1 - ago]
        out.append((today - timedelta(days=ago), round(value, places)))
    return tuple(out)


def _profile(raw: Mapping[str, Any]) -> Profile:
    birth = raw.get("birth")
    return Profile(
        height_cm=raw.get("height_cm"),
        birth=date.fromisoformat(birth) if birth else None,
        sex=raw.get("sex"),
        goal=raw.get("goal"),
        activity=raw.get("activity"),
    )


def _merged(name: str, raw: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    me = dict(raw[name])
    parent = me.pop("extends", None)
    if parent is None:
        return {**me, "memory": list(me.get("memory") or [])}
    base = _merged(parent, raw)
    series = {**base.get("series", {}), **(me.get("series") or {})}
    return {
        "desc": me.get("desc", base.get("desc", "")),
        "profile": {**base.get("profile", {}), **(me.get("profile") or {})},
        "series": {k: v for k, v in series.items() if v is not None},
        "memory": [*base.get("memory", []), *(me.get("memory") or [])],
        "plan": me.get("plan", base.get("plan")),
        "workouts": me.get("workouts", base.get("workouts", [])),
    }


def load_personas(raw: Mapping[str, Mapping[str, Any]], today: date) -> dict[str, Persona]:
    out: dict[str, Persona] = {}
    said = datetime.combine(today - timedelta(days=3), datetime.min.time(), tzinfo=UTC)
    for name in raw:
        m = _merged(name, raw)
        profile = _profile(m.get("profile") or {})
        series: dict[str, tuple[Point, ...]] = {}
        for key, spec in (m.get("series") or {}).items():
            if spec is None:
                continue
            if key == "bp":
                readings = [(today - timedelta(days=int(r["ago"])), r) for r in spec]
                series["systolic"] = tuple(sorted((d, float(r["sys"])) for d, r in readings))
                series["diastolic"] = tuple(sorted((d, float(r["dia"])) for d, r in readings))
            else:
                series[key] = _series(name, key, spec, today)
        if profile.height_cm:
            series["height"] = ((today - timedelta(days=200), float(profile.height_cm)),)
        memory = tuple(
            Item(f"{name}-{i}", cat, content, quote, "said", "active", said, said)
            for i, (cat, content, quote) in enumerate(m.get("memory") or [])
        )
        out[name] = Persona(
            name,
            str(m.get("desc", "")),
            profile,
            series,
            memory,
            m.get("plan"),
            tuple(m.get("workouts") or ()),
        )
    return out


def facts_text(persona: Persona, today: date, ask: str = "") -> str:
    """给评委看的这个人的数据：档案、今天的状态、计划、指标计算结果（与 Agent 看到的同一份）和最近三天的读数。"""
    from ironm_agent.casefile import Snapshot, build
    from ironm_agent.memory_view import Recall
    from ironm_agent.metrics import compute_all

    metrics = compute_all(persona.readings(), persona.profile, today)
    case = build(
        Snapshot(persona.profile, persona.readings(), tuple(metrics), today), Recall(), ask
    )
    lines = [
        f"- 档案：{case.basics}",
        f"- {case.readiness.line()}（系统按最近的睡眠、心率和这句话里说的情况判断）",
        "- 当前计划：" + ("有（见上）" if persona.plan else "没有"),
        *(f"- {m.name}：{m.text}" for m in metrics),
    ]
    labels = {"sleep": "睡眠（小时）", "resting_hr": "静息心率", "hrv_sdnn": "心率变异性 SDNN",
              "hrv_rmssd": "心率变异性 RMSSD", "weight": "体重", "steps": "步数"}  # fmt: skip
    for key, label in labels.items():
        points = persona.series.get(key, ())
        recent = [f"{d.month}/{d.day} {v:g}" for d, v in points if (today - d).days < 3]
        if recent:
            lines.append(f"- 最近三天{label}：" + "，".join(recent))
    dia = dict(persona.series.get("diastolic", ()))
    for d, s in persona.series.get("systolic", ()):
        lines.append(f"- 血压读数 {d.isoformat()}：{s:g}/{dia.get(d, 0):g} mmHg")
    return "\n".join(lines)


# ---- 假的健康数据查询 ----------------------------------------------------------------------


def _fmt(key: str, v: float) -> float | int:
    places = DECIMALS.get(key, 1)
    return round(v) if places == 0 else round(v, places)


@dataclass
class EvalHealth:
    """照 mirobody 健康数据查询接口的样子回答：目录、最新值、统计、按天 / 周 / 月，每行带 rid。"""

    persona: Persona
    asked: list[dict[str, Any]] = field(default_factory=list)
    _next: int = 0

    def _rid(self) -> str:
        self._next += 1
        return f"r{self._next}"

    def _keys(self, indicators: Sequence[str] | None, keywords: Sequence[str] | None) -> list[str]:
        have = [k for k in INDICATORS if self.persona.series.get(k)]
        if indicators:
            wanted = {str(x).lower() for x in indicators}
            return [
                k for k in have if {INDICATORS[k][0].lower(), INDICATORS[k][1].lower()} & wanted
            ]
        if keywords:
            words = [str(w).lower() for w in keywords]
            return [
                k for k in have if any(t in w or w in t for w in words for t in INDICATORS[k][3])
            ]
        return []

    def _catalog(self) -> list[dict[str, Any]]:
        rows = []
        for key, points in self.persona.series.items():
            if not points or key not in INDICATORS:
                continue
            name, display, unit, _ = INDICATORS[key]
            rows.append({
                "indicator": display, "name": name, "kind": "measurement", "count": len(points),
                "unit": unit, "first_date": points[0][0].isoformat(), "last_date": points[-1][0].isoformat(),
            })  # fmt: skip
        return rows

    def _rows(
        self, key: str, view: str, start: date | None, end: date | None
    ) -> list[dict[str, Any]]:
        name, display, unit, _ = INDICATORS[key]
        points = [
            (d, v)
            for d, v in self.persona.series[key]
            if (start is None or d >= start) and (end is None or d <= end)
        ]
        if not points:
            return []
        head = {"indicator": display, "name": name, "unit": unit}
        if view == "latest":
            d, v = points[-1]
            return [{**head, "date": d.isoformat(), "time": f"{d.isoformat()} 08:00:00", "value": str(_fmt(key, v)), "rid": self._rid()}]  # fmt: skip
        values = [v for _, v in points]
        if view == "stats":
            return [{
                **head, "count": len(values), "min": _fmt(key, min(values)), "max": _fmt(key, max(values)),
                "avg": round(statistics.fmean(values), 2), "first": _fmt(key, values[0]), "last": _fmt(key, values[-1]),
                "change": _fmt(key, values[-1] - values[0]), "first_date": points[0][0].isoformat(),
                "last_date": points[-1][0].isoformat(), "rid": self._rid(),
            }]  # fmt: skip
        if view in ("day", "week", "month"):
            groups: dict[date, list[float]] = {}
            for d, v in points:
                bucket = d
                if view == "week":
                    bucket = d - timedelta(days=d.weekday())
                elif view == "month":
                    bucket = d.replace(day=1)
                groups.setdefault(bucket, []).append(v)
            return [
                {**head, "period": b.isoformat(), "avg": round(statistics.fmean(vs), 2), "min": _fmt(key, min(vs)),
                 "max": _fmt(key, max(vs)), "n": len(vs), "rid": self._rid()}
                for b, vs in sorted(groups.items())[-92:]
            ]  # fmt: skip
        return [
            {**head, "date": d.isoformat(), "value": str(_fmt(key, v)), "rid": self._rid()}
            for d, v in reversed(points[-50:])
        ]

    async def envelope(self, user_info: Mapping[str, Any], **args: Any) -> Any:
        from mirobody.kernel.tools import Envelope

        self.asked.append(dict(args))
        keys = self._keys(args.get("indicators"), args.get("keywords"))
        if not keys:
            note = "no indicator matched those terms; this is what this person has on file" if (
                args.get("indicators") or args.get("keywords")) else "this is what this person has on file"  # fmt: skip
            return Envelope("ok", data=self._catalog(), assumptions=(note,))
        start = date.fromisoformat(args["start"]) if args.get("start") else None
        end = date.fromisoformat(args["end"]) if args.get("end") else None
        view = str(args.get("view") or "raw")
        rows = [row for key in keys for row in self._rows(key, view, start, end)]
        return Envelope("ok", data=rows)
