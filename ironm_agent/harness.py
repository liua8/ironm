"""运行框架（spec [2026-10-23] §31 第一步）：每轮按环节留下轨迹，用规则发现出错信号并归到环节，
用户的评价和反应记到对应的那一轮；按系统和按个人汇总，让系统知道哪里出错了。

轨迹里只有环节、类别、次数、耗时、角色和 Skill 编号，不写用户原话、回答原文和健康数值；数据库版加密存储，
保留 RETAIN_DAYS 天。记录和汇总失败都不影响回答。
"""

from __future__ import annotations

import json
import logging
import re
import statistics
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any, Literal, Protocol

_log = logging.getLogger("ironm_agent.harness")

RETAIN_DAYS = 180
SLOW_TURN_MS = 20_000
SLOW_EXPERT_MS = 15_000
CLOSE_GAP = 0.2  # 路由前两名的加权分相差不到这么多：分不清该请谁
EXPERIENCE_HIGH = 0.5  # 标〔经验〕的句子过半：知识库缺这块
REPHRASE_SIMILAR = 0.5  # 和上一句的相似度（相邻两字的重合）不低于这个：换个说法再问
ROLE_NAMES = {"trainer": "训练教练", "nutrition": "营养师", "recovery": "康复恢复师"}

type Stage = Literal[
    "safety", "route", "knowledge", "tool", "data", "answer", "compose", "plan", "perf", "outcome"
]
STAGE_NAMES: dict[str, str] = {
    "safety": "安全判断", "route": "路由", "knowledge": "资料", "tool": "工具", "data": "数据",
    "answer": "作答", "compose": "整合", "plan": "计划", "perf": "性能", "outcome": "结果",
}  # fmt: skip

# 每种信号：归到哪个环节、给人看的名字；good 为 True 的是正面反馈（不算出错）
SIGNALS: dict[str, tuple[str, str]] = {
    "route_close": ("route", "前两名分数接近"),
    "route_disagree": ("route", "三路意见不一致"),
    "route_fallback": ("route", "按关键词兜底"),
    "route_missed": ("route", "回答里提到该请却没请的角色"),
    "declined_scope": ("route", "判为超出范围、没请专业角色"),
    "kb_empty": ("knowledge", "查资料查空"),
    "experience_high": ("knowledge", "标〔经验〕的句子过半"),
    "tool_error": ("tool", "工具调用失败"),
    "tool_refused": ("tool", "调用了没有权限的工具"),
    "query_exhausted": ("tool", "查询次数用完"),
    "forced_answer": ("tool", "收走工具后才作答"),
    "health_failed": ("data", "健康数据读取失败"),
    "health_empty": ("data", "查了没有记录"),
    "snapshot_failed": ("data", "没读到档案"),
    "data_not_queried": ("data", "问到指标却没查到数据"),
    "indicator_missing": ("data", "问到的指标没有记录"),
    "expert_silent": ("answer", "专业 Agent 没发言"),
    "expert_failed": ("answer", "专业 Agent 失败"),
    "check_fixed": ("answer", "核对第一次没通过、改写后通过"),
    "check_repaired": ("answer", "改写后仍不通过、被规则修正"),
    "compose_check": ("compose", "整合核对第一次没通过"),
    "compose_repaired": ("compose", "整合被规则修正"),
    "constraint": ("compose", "约束第一次没通过"),
    "constraint_fixed": ("compose", "改写后仍不过关、注明了限制"),
    "compose_fallback": ("compose", "退回主责角色的意见"),
    "preview_invalid": ("plan", "没写出合格的计划或记录"),
    "plan_check": ("plan", "计划检查不通过或只改好一部分"),
    "slow_turn": ("perf", "整轮超过 20 秒"),
    "slow_expert": ("perf", "专业 Agent 超过 15 秒"),
    "budget_hit": ("perf", "用满一轮的模型调用次数"),
    "model_failure": ("perf", "有模型调用失败"),
    "turn_error": ("perf", "整轮出错"),
    "rating_down": ("outcome", "点了没用"),
    "rephrase": ("outcome", "换个说法再问"),
    "user_says_wrong": ("outcome", "说不对、答非所问"),
    "safety_disputed": ("safety", "走了安全流程后用户说不是这么回事"),
    "rating_up": ("outcome", "点了有用"),
}
GOOD = frozenset({"rating_up"})
FEEDBACK = frozenset({"rating_down", "rephrase", "user_says_wrong", "safety_disputed", "rating_up"})

_WRONG = re.compile(
    r"^\s*(不对|不是|错了|你说错|说错了|没回答|答非所问|不是这个意思|我不是问|我问的是|你没懂|没听懂)"
)
IMPORTANT_READINGS = {
    "weight": "体重", "body_fat": "体脂率", "waist": "腰围", "resting_hr": "静息心率",
    "hrv": "心率变异性", "sleep_hours": "睡眠", "steps": "步数",
}  # fmt: skip


# ---- 作答时的记录 ---------------------------------------------------------------------------


def problem_kinds(problems: Iterable[str]) -> list[str]:
    """核对发现的问题按类别归并（问题原文里可能有回答片段，只留类别）。"""
    out: list[str] = []
    for p in problems:
        if "不存在的" in p:
            kind = "bad_ref"
        elif "JSON" in p or "规定格式" in p or "意见是空的" in p or "<statement>" in p:
            kind = "format"
        elif "数据行里找不到" in p:
            kind = "data_number"
        elif "不在任何专业角色的意见里" in p:
            kind = "compose_number"
        elif "数字" in p:
            kind = "number"
        elif any(w in p for w in ("plan", "log", "计划", "训练记录")):
            kind = "plan_format"
        else:
            kind = "other"
        if kind not in out:
            out.append(kind)
    return out


def mentioned_roles(text: str, invited: Iterable[str]) -> list[str]:
    """回答里提到、但这一轮没请到的专业角色（漏请的线索）。"""
    got = set(invited)
    return [k for k, name in ROLE_NAMES.items() if k not in got and name in text]


def missing_readings(readings: Any) -> list[str]:
    """重要指标里哪些没有数据（这个人的数据缺口）。"""
    out = []
    for key, name in IMPORTANT_READINGS.items():
        values = getattr(readings, key, None)
        if key == "hrv":
            values = getattr(readings, "hrv_sdnn", None) or getattr(readings, "hrv_rmssd", None)
        if not values:
            out.append(name)
    return out


def bigram_similarity(a: str, b: str) -> float:
    """两句话相邻两字的重合度（判断是不是换个说法再问；不调用模型）。"""

    def grams(x: str) -> set[str]:
        x = re.sub(r"\W", "", x)
        return {p + q for p, q in pairwise(x)} if len(x) > 1 else set(x)

    ga, gb = grams(a), grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def user_reaction(text: str, previous: str | None) -> str | None:
    """这句话对上一轮回答的反应：说不对、换个说法再问；都不是返回 None。"""
    if _WRONG.search(text):
        return "user_says_wrong"
    if previous and len(text) >= 4 and bigram_similarity(text, previous) >= REPHRASE_SIMILAR:
        return "rephrase"
    return None


# ---- 出错信号 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    kind: str
    role: str = ""  # 出在哪个专业 Agent（与角色无关时为空）
    detail: str = ""  # 类别、工具名之类（不含内容）

    @property
    def stage(self) -> str:
        return SIGNALS[self.kind][0]

    def json(self) -> dict[str, str]:
        return {"kind": self.kind, "stage": self.stage, "role": self.role, "detail": self.detail}


def diagnose(run: Mapping[str, Any]) -> list[Signal]:
    """按这一轮的运行记录和各环节明细，用规则找出错信号。"""
    out: list[Signal] = []
    add = out.append
    route = run.get("route") or {}
    weighted = sorted((route.get("weighted") or {}).values(), reverse=True)
    if len(weighted) >= 2 and weighted[0] > 0 and weighted[0] - weighted[1] < CLOSE_GAP:
        add(Signal("route_close"))
    tops = {
        c: max(s, key=s.get)
        for c, s in (route.get("channels") or {}).items()
        if s and max(s.values()) > 0
    }
    if len(set(tops.values())) > 1:
        add(Signal("route_disagree", detail="/".join(f"{c}:{r}" for c, r in sorted(tops.items()))))
    if run.get("route_by") == "keyword" and route:
        add(Signal("route_fallback"))
    # 判成超出范围：便于发现把训练问题误判成超出范围（spec [2026-10-23] §41）
    if route.get("intent") == "out_of_scope":
        add(Signal("declined_scope"))
    for x in run.get("_experts") or []:
        role = x.get("role", "")
        for m in x.get("mentions") or []:
            add(Signal("route_missed", role, m))
        for call in x.get("calls") or []:
            tool, result = call.get("tool", ""), call.get("result")
            if result == "error":
                add(
                    Signal(
                        "health_failed" if tool == "query_health_indicators" else "tool_error",
                        role,
                        tool,
                    )
                )
            elif result == "refused":
                add(Signal("tool_refused", role, tool))
            elif result == "empty":
                if tool == "query_health_indicators":
                    add(Signal("health_empty", role, tool))
                else:
                    add(Signal("kb_empty", role, tool))
        if x.get("exhausted"):
            add(Signal("query_exhausted", role))
        if x.get("forced"):
            add(Signal("forced_answer", role))
        if (x.get("experience") or 0) >= EXPERIENCE_HIGH and x.get("status") == "spoke":
            add(Signal("experience_high", role))
        if x.get("status") == "silent":
            add(Signal("expert_silent", role))
        elif x.get("status") == "failed":
            add(Signal("expert_failed", role))
        if x.get("repaired"):
            add(Signal("check_repaired", role, ",".join(x.get("checks") or [])))
        elif x.get("fixed"):
            add(Signal("check_fixed", role, ",".join(x.get("checks") or [])))
        if (x.get("ms") or 0) > SLOW_EXPERT_MS:
            add(Signal("slow_expert", role))
    c = run.get("_compose") or {}
    if c.get("repaired"):
        add(Signal("compose_repaired", detail=",".join(c.get("checks") or [])))
    elif c.get("checks"):
        add(Signal("compose_check", detail=",".join(c["checks"])))
    if run.get("constraints"):
        add(Signal("constraint", detail=",".join(run["constraints"])))
    if run.get("constraint_fixed"):
        add(Signal("constraint_fixed"))
    if c.get("degraded"):
        add(Signal("compose_fallback"))
    if run.get("snapshot_failed"):
        add(Signal("snapshot_failed"))
    pre = run.get("prefetch") or {}
    if pre.get("asked") and not pre.get("ok"):
        add(Signal("data_not_queried", detail=str(pre["asked"])))
    elif pre.get("asked") and not pre.get("rows"):
        add(Signal("indicator_missing", detail=str(pre["asked"])))
    if run.get("preview") == "invalid":
        add(Signal("preview_invalid"))
    if run.get("plan_check") in ("failed", "partly"):
        add(Signal("plan_check", detail=run["plan_check"]))
    if (run.get("ms") or 0) > SLOW_TURN_MS and run.get("path") not in ("safety",):
        add(Signal("slow_turn"))
    if run.get("budget_hit"):
        add(Signal("budget_hit"))
    if run.get("model_failures"):
        add(Signal("model_failure", detail=str(run["model_failures"])))
    if run.get("error_type"):
        add(Signal("turn_error", detail=str(run["error_type"])))
    return out


def trace_of(run: Mapping[str, Any]) -> dict[str, Any]:
    """存进轨迹的内容：运行记录（不含原话）加各环节明细。"""
    keep = {k: v for k, v in run.items() if not k.startswith("_")}
    keep["experts"] = run.get("_experts") or []
    keep["compose"] = run.get("_compose") or {}
    keep["missing"] = run.get("_missing") or []
    return keep


# ---- 存储 -----------------------------------------------------------------------------------


@dataclass
class Turn:
    id: str
    user_id: str
    session: str
    at: datetime
    trace: dict[str, Any]
    signals: list[dict[str, str]] = field(default_factory=list)


class TraceStore(Protocol):
    async def add(self, turn: Turn) -> None: ...
    async def last(self, user_id: str, session: str) -> Turn | None: ...
    async def get(self, turn_id: str) -> Turn | None: ...
    async def mark(self, turn_id: str, signal: dict[str, str]) -> None: ...
    async def since(self, start: datetime, user_id: str | None = None) -> list[Turn]: ...


class TraceBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.turns: list[Turn] = []

    async def add(self, turn: Turn) -> None:
        self.turns.append(turn)

    async def last(self, user_id: str, session: str) -> Turn | None:
        mine = [t for t in self.turns if t.user_id == user_id and t.session == session]
        return mine[-1] if mine else None

    async def get(self, turn_id: str) -> Turn | None:
        return next((t for t in self.turns if t.id == turn_id), None)

    async def mark(self, turn_id: str, signal: dict[str, str]) -> None:
        t = await self.get(turn_id)
        if t is not None and signal not in t.signals:
            t.signals.append(signal)

    async def since(self, start: datetime, user_id: str | None = None) -> list[Turn]:
        return [
            t for t in self.turns if t.at >= start and (user_id is None or t.user_id == user_id)
        ]


DDL = """
CREATE TABLE IF NOT EXISTS ironm_turn_trace (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    session    text NOT NULL,
    trace      text NOT NULL,
    signals    text NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ironm_turn_trace_user ON ironm_turn_trace (user_id, created_at);
CREATE INDEX IF NOT EXISTS ironm_turn_trace_time ON ironm_turn_trace (created_at)
"""


class PgTrace:
    """数据库版：轨迹内容用 mirobody 的加密函数加密；信号只有类别，不含内容。"""

    def __init__(self) -> None:
        self._ready = False
        self._purged: date | None = None

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            for stmt in DDL.split(";"):
                if stmt.strip():
                    await execute_query(stmt, {}, log_sql=False)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def add(self, turn: Turn) -> None:
        await self._q(
            "INSERT INTO ironm_turn_trace (id, user_id, session, trace, signals, created_at)"
            " VALUES (:id, :uid, :session, encrypt_content(:trace), :signals, :at)",
            {"id": turn.id, "uid": turn.user_id, "session": turn.session,
             "trace": json.dumps(turn.trace, ensure_ascii=False),
             "signals": json.dumps(turn.signals, ensure_ascii=False), "at": turn.at},
        )  # fmt: skip
        today = turn.at.date()
        if self._purged != today:  # 每天清一次过期的轨迹
            self._purged = today
            await self._q(
                "DELETE FROM ironm_turn_trace WHERE created_at < :cut",
                {"cut": turn.at - timedelta(days=RETAIN_DAYS)},
            )

    @staticmethod
    def _turn(r: Mapping[str, Any]) -> Turn:
        return Turn(str(r["id"]), str(r["user_id"]), str(r["session"]), r["created_at"],
                    json.loads(r["trace"] or "{}"), json.loads(r["signals"] or "[]"))  # fmt: skip

    _COLS = "id, user_id, session, decrypt_content(trace) AS trace, signals, created_at"

    async def last(self, user_id: str, session: str) -> Turn | None:
        rows = await self._q(
            f"SELECT {self._COLS} FROM ironm_turn_trace WHERE user_id = :uid AND session = :session"
            " ORDER BY created_at DESC LIMIT 1",
            {"uid": user_id, "session": session},
        )
        return self._turn(rows[0]) if rows else None

    async def get(self, turn_id: str) -> Turn | None:
        rows = await self._q(
            f"SELECT {self._COLS} FROM ironm_turn_trace WHERE id = :id", {"id": turn_id}
        )
        return self._turn(rows[0]) if rows else None

    async def mark(self, turn_id: str, signal: dict[str, str]) -> None:
        t = await self.get(turn_id)
        if t is None or signal in t.signals:
            return
        await self._q(
            "UPDATE ironm_turn_trace SET signals = :signals WHERE id = :id",
            {"id": turn_id, "signals": json.dumps([*t.signals, signal], ensure_ascii=False)},
        )

    async def since(self, start: datetime, user_id: str | None = None) -> list[Turn]:
        where = "created_at >= :start" + (" AND user_id = :uid" if user_id else "")
        rows = await self._q(
            f"SELECT {self._COLS} FROM ironm_turn_trace WHERE {where} ORDER BY created_at",
            {"start": start, "uid": user_id} if user_id else {"start": start},
        )
        return [self._turn(r) for r in rows]


_default: TraceStore | None = None


def default_traces() -> TraceStore:
    global _default
    if _default is None:
        _default = PgTrace()
    return _default


def new_turn(user_id: str, session: str, run: Mapping[str, Any]) -> Turn:
    signals = [s.json() for s in diagnose(run)]
    return Turn(str(run.get("turn") or uuid.uuid4().hex[:12]), user_id, session,
                datetime.now(UTC), trace_of(run), signals)  # fmt: skip


async def react(
    store: TraceStore, user_id: str, session: str, text: str, previous: str | None
) -> str | None:
    """这句话是对上一轮的反应（说不对、换说法再问）时，记到上一轮上；返回记下的信号。"""
    kind = user_reaction(text, previous)
    if kind is None:
        return None
    last = await store.last(user_id, session)
    if last is None:
        return None
    if kind == "user_says_wrong" and last.trace.get("path") == "safety":
        kind = "safety_disputed"
    await store.mark(last.id, Signal(kind).json())
    return kind


async def rate(store: TraceStore, user_id: str, turn_id: str, rating: int) -> bool:
    """用户给这一轮回答的评价；只能评自己的那一轮。"""
    t = await store.get(turn_id)
    if t is None or t.user_id != user_id:
        return False
    await store.mark(t.id, Signal("rating_up" if rating > 0 else "rating_down").json())
    return True


# ---- 汇总 -----------------------------------------------------------------------------------


def _pct(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return int(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1])


def _per100(n: int, total: int) -> float:
    return round(100 * n / total, 1) if total else 0.0


def _bad(t: Turn) -> list[dict[str, str]]:
    return [s for s in t.signals if s.get("kind") not in GOOD]


def system_summary(turns: Sequence[Turn]) -> dict[str, Any]:
    """系统汇总：按环节、按专业 Agent、按 Skill、按工具。"""
    n = len(turns)
    ms = [
        int(t.trace.get("ms") or 0) for t in turns if t.trace.get("path") not in ("safety", "error")
    ]
    kinds = Counter(s["kind"] for t in turns for s in t.signals)
    stages = Counter(s["stage"] for t in turns for s in _bad(t))
    roles: dict[str, Counter[str]] = defaultdict(Counter)
    role_ms: dict[str, list[int]] = defaultdict(list)
    experience: dict[str, list[float]] = defaultdict(list)
    skills: dict[str, Counter[str]] = defaultdict(Counter)
    tools: dict[str, Counter[str]] = defaultdict(Counter)
    for t in turns:
        unhappy = any(
            s["kind"] in ("rating_down", "rephrase", "user_says_wrong") for s in t.signals
        )
        for x in t.trace.get("experts") or []:
            r = x.get("role", "")
            roles[r]["turns"] += 1
            roles[r][x.get("status", "")] += 1
            role_ms[r].append(int(x.get("ms") or 0))
            if x.get("status") == "spoke":
                experience[r].append(float(x.get("experience") or 0))
            for call in x.get("calls") or []:
                tools[call["tool"]]["calls"] += 1
                tools[call["tool"]][call["result"]] += 1
        for s in _bad(t):
            if s.get("role"):
                roles[s["role"]][s["kind"]] += 1
        for ids in (t.trace.get("skills") or {}).values():
            for sid in ids:
                skills[sid]["loaded"] += 1
                skills[sid]["unhappy"] += int(unhappy)
    paths = Counter(str(t.trace.get("path", "")) for t in turns)
    return {
        "turns": n,
        "paths": {k: _per100(v, n) for k, v in paths.most_common()},
        "ms": {"p50": _pct(ms, 50), "p90": _pct(ms, 90)},
        "stages": [{"stage": k, "name": STAGE_NAMES[k], "count": v, "per100": _per100(v, n)}
                   for k, v in stages.most_common()],
        "signals": [{"kind": k, "stage": SIGNALS[k][0], "name": SIGNALS[k][1], "count": v,
                     "per100": _per100(v, n)} for k, v in kinds.most_common()],
        "roles": {r: {"name": ROLE_NAMES.get(r, r), "turns": c["turns"], "silent": c["silent"],
                      "failed": c["failed"], "check_fixed": c["check_fixed"],
                      "check_repaired": c["check_repaired"], "kb_empty": c["kb_empty"],
                      "experience": round(statistics.fmean(experience[r]), 2) if experience[r] else None,
                      "ms_p50": _pct(role_ms[r], 50)} for r, c in roles.items()},
        "skills": {k: {"loaded": c["loaded"], "unhappy": _per100(c["unhappy"], c["loaded"])}
                   for k, c in sorted(skills.items(), key=lambda kv: -kv[1]["loaded"])},
        "tools": {k: {"calls": c["calls"], "error": c["error"], "empty": c["empty"], "refused": c["refused"]}
                  for k, c in tools.items()},
    }  # fmt: skip


def turn_brief(t: Turn) -> dict[str, Any]:
    """一轮的概要：路径、耗时、请了谁、用了哪些 Skill、三路路由各自的首选、出错信号（不含内容）。"""
    tr = t.trace
    route = tr.get("route") or {}
    tops = {c: max(s, key=s.get) for c, s in (route.get("channels") or {}).items() if s}
    return {
        "id": t.id,
        "user_id": t.user_id,
        "at": t.at.isoformat(),
        "path": tr.get("path"),
        "ms": tr.get("ms"),
        "roles": [ROLE_NAMES.get(r, r) for r in tr.get("roles") or []],
        "skills": tr.get("skills") or {},
        "route_tops": tops,
        "skills_by": tr.get("skills_by") or {},
        "task": tr.get("task"),
        "experts": [
            {
                k: x.get(k)
                for k in (
                    "role",
                    "status",
                    "rounds",
                    "calls",
                    "checks",
                    "fixed",
                    "repaired",
                    "exhausted",
                    "forced",
                    "experience",
                    "ms",
                    "mentions",
                )
            }
            for x in tr.get("experts") or []
        ],
        "signals": [
            {"name": SIGNALS[s["kind"]][1], **s} for s in t.signals if s["kind"] not in GOOD
        ],
        "good": [s["kind"] for s in t.signals if s["kind"] in GOOD],
    }


def person_summary(turns: Sequence[Turn], declined: int = 0) -> dict[str, Any]:
    """个人汇总：系统在这个人身上哪里没帮好。"""
    n = len(turns)
    kinds = Counter(s["kind"] for t in turns for s in t.signals)
    stages = Counter(s["stage"] for t in turns for s in _bad(t))
    roles = Counter(x.get("role", "") for t in turns for x in t.trace.get("experts") or [])
    role_bad = Counter(s["role"] for t in turns for s in _bad(t) if s.get("role"))
    latest = turns[-1].trace.get("missing") if turns else []
    return {
        "turns": n,
        "stages": [
            {"stage": k, "name": STAGE_NAMES[k], "count": v} for k, v in stages.most_common()
        ],
        "signals": [{"kind": k, "name": SIGNALS[k][1], "count": v} for k, v in kinds.most_common()],
        "rating_down": kinds["rating_down"],
        "rating_up": kinds["rating_up"],
        "rephrase": kinds["rephrase"],
        "says_wrong": kinds["user_says_wrong"] + kinds["safety_disputed"],
        "roles": {ROLE_NAMES.get(r, r): v for r, v in roles.most_common()},
        "worst_role": ROLE_NAMES.get(role_bad.most_common(1)[0][0], "") if role_bad else "",
        "missing": latest or [],
        "declined": declined,
    }
