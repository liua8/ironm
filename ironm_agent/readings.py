"""自己记一条、改值、删一条（spec [2026-10-23] §26 需求 4）：测量类指标写进同一份健康记录。

写入用 mirobody 的统一写入入口（统一名称和单位，来源标"手动记录"）；改和删用它自带的更正和撤回，
原记录保留、可追溯。名字的选法经本机实测：体重、体脂率、静息心率用中文名能统一到标准编码（LOINC）；
腰围、睡眠用 mirobody 指标目录里的名字（它的词表认不出中文的腰围）。日志不写数值。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Protocol

_log = logging.getLogger("ironm_agent.readings")

SOURCE = "iron-m 手动记录"


@dataclass(frozen=True)
class Kind:
    title: str
    names: tuple[str, ...]  # 写入用第一个；读最近记录时这些名字都算
    unit: str
    low: float
    high: float
    shown: str  # 给人看的单位


KINDS: dict[str, Kind] = {
    "weight": Kind("体重", ("体重", "bodyMasss", "Body weight"), "kg", 20, 300, "公斤"),
    "body_fat": Kind("体脂率", ("体脂率", "bodyFatPercentages"), "%", 3, 70, "%"),
    "waist": Kind("腰围", ("waistCircumferences",), "cm", 40, 200, "厘米"),
    "resting_hr": Kind("静息心率", ("静息心率", "restingHeartRates"), "/min", 30, 150, "次/分"),
    "sleep": Kind("睡眠时长", ("sleepDuration",), "h", 0.5, 16, "小时"),
    "systolic": Kind("收缩压", ("收缩压", "systolicPressures"), "mm[Hg]", 60, 260, "mmHg"),
    "diastolic": Kind("舒张压", ("舒张压", "diastolicPressures"), "mm[Hg]", 30, 160, "mmHg"),
}


class OutOfRange(ValueError):
    pass


def check(kind: str, value: float) -> Kind:
    k = KINDS[kind]
    if not k.low <= value <= k.high:
        raise OutOfRange(f"{k.title}要在 {k.low:g}–{k.high:g} {k.shown}之间")
    return k


class ReadingStore(Protocol):
    async def add(self, user_id: str, kind: str, value: float, day: date) -> int: ...
    async def recent(self, user_id: str, kind: str, limit: int = 10) -> list[dict[str, Any]]: ...
    async def amend(self, user_id: str, row_id: int, value: float) -> bool: ...
    async def remove(self, user_id: str, row_id: int) -> bool: ...


class ReadingBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[dict[str, Any]]] = {}
        self.next_id = 1

    async def add(self, user_id: str, kind: str, value: float, day: date) -> int:
        k = KINDS[kind]
        self.rows.setdefault(user_id, []).append({"id": self.next_id, "kind": kind, "name": k.names[0],
            "value": value, "unit": k.unit, "day": day.isoformat(), "manual": True, "active": True})  # fmt: skip
        self.next_id += 1
        return self.next_id - 1

    async def recent(self, user_id: str, kind: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = [r for r in self.rows.get(user_id, []) if r["kind"] == kind and r["active"]]
        return sorted(rows, key=lambda r: (r["day"], r["id"]), reverse=True)[:limit]

    def _row(self, user_id: str, row_id: int) -> dict[str, Any] | None:
        return next(
            (r for r in self.rows.get(user_id, []) if r["id"] == row_id and r["active"]), None
        )

    async def amend(self, user_id: str, row_id: int, value: float) -> bool:
        row = self._row(user_id, row_id)
        if row is None:
            return False
        row["active"] = False  # 和 mirobody 一样：原记录保留，另起一条更正后的
        await self.add(user_id, row["kind"], value, date.fromisoformat(row["day"]))
        return True

    async def remove(self, user_id: str, row_id: int) -> bool:
        row = self._row(user_id, row_id)
        if row is None:
            return False
        row["active"] = False
        return True


class MirobodyReadings:
    """线上：写进 mirobody 的健康记录。"""

    async def add(self, user_id: str, kind: str, value: float, day: date) -> int:
        from mirobody.collect import observations
        from mirobody.kernel import series

        k = KINDS[kind]
        tz = await observations.user_tz(str(user_id))
        when = datetime.combine(day, time(12, 0))  # 只知道哪天：记在当天中午（按这个人的时区）
        draft = observations.Draft(name_text=k.names[0], observed_start=when, value_text=f"{value:g}",
                                   unit_text=k.unit, note_text=SOURCE)  # fmt: skip
        prov = observations.Provenance(observations.MODALITY_MANUAL, "api", "api:iron-m",
                                       source_class=series.SOURCE_MANUAL)  # fmt: skip
        report = await observations.ingest(str(user_id), [draft], prov, user_tz=tz)
        inserted = int(report.inserted)
        _log.info("reading added: kind=%s inserted=%d", kind, inserted)
        return inserted

    async def recent(self, user_id: str, kind: str, limit: int = 10) -> list[dict[str, Any]]:
        from mirobody.collect import PostgresHealthQuery

        query = PostgresHealthQuery(reported=True)
        rows: list[dict[str, Any]] = []
        for name in KINDS[kind].names:
            page = await query.records(
                str(user_id), kind="all", keywords=name, limit=limit, offset=0, notes=True
            )
            rows += [r for r in page["rows"] if str(r.get("name") or "").lower() == name.lower()]
        out = {}
        for r in rows:
            out[r["row_id"]] = {
                "id": r["row_id"], "kind": kind, "name": r["name"], "value": r["value"],
                "unit": r.get("unit") or "", "day": str(r.get("observed_start") or "")[:10],
                "manual": r.get("modality") == "manual",
            }  # fmt: skip
        return sorted(out.values(), key=lambda r: (r["day"], r["id"]), reverse=True)[:limit]

    async def amend(self, user_id: str, row_id: int, value: float) -> bool:
        from mirobody.collect import observations

        tz = await observations.user_tz(str(user_id))
        done = (
            await observations.amend(str(user_id), row_id, value_text=f"{value:g}", user_tz=tz)
            is not None
        )
        _log.info("reading amended: done=%s", done)
        return done

    async def remove(self, user_id: str, row_id: int) -> bool:
        from mirobody.collect import observations

        done = bool(await observations.retract(str(user_id), [row_id]) > 0)
        _log.info("reading removed: done=%s", done)
        return done


_default: ReadingStore | None = None


def default_readings() -> ReadingStore:
    global _default
    if _default is None:
        _default = MirobodyReadings()
    return _default
