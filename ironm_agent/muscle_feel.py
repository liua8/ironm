"""本人说的肌肉感受（spec [2026-10-23] §30）：某块肌肉"还酸""已经不酸了"，恢复判断以本人说的为准。

每块肌肉只用最近说的一次。数据库版的内容用 mirobody 的加密函数加密；日志不写内容。
另存每块肌肉在他身上恢复快慢的倍数（§70 修改：按他说的校准），只有肌肉编码和一个数，不含原话。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Protocol

from ironm_agent.body import muscle_codes
from ironm_agent.ddl import run_ddl
from ironm_agent.protools.recovery import Feel

# 打卡时点的"哪里酸"（§105）对应的肌肉：记进同一份肌肉酸痛，人体图和恢复估算照顾到
SORE_MUSCLES: dict[str, tuple[str, ...]] = {
    "胸": ("muscle.pec_major_upper", "muscle.pec_major_lower"),
    "背": ("muscle.lats", "muscle.rhomboids", "muscle.mid_lower_traps"),
    "肩": ("muscle.anterior_delt", "muscle.lateral_delt", "muscle.posterior_delt"),
    "手臂": ("muscle.biceps", "muscle.triceps"),
    "大腿前": ("muscle.quadriceps",),
    "大腿后": ("muscle.hamstrings",),
    "臀": ("muscle.glute_max", "muscle.glute_med"),
    "小腿": ("muscle.gastrocnemius", "muscle.soleus"),
    "核心": ("muscle.rectus_abdominis", "muscle.obliques"),
}


class FeelStore(Protocol):
    async def add(self, user_id: str, muscle: str, feel: Feel, day: date) -> None: ...
    async def latest(self, user_id: str) -> dict[str, tuple[Feel, date]]: ...
    async def rates(self, user_id: str) -> dict[str, float]: ...
    async def set_rate(self, user_id: str, muscle: str, rate: float) -> None: ...


def _coded(said: list[tuple[str, Feel, date]]) -> dict[str, tuple[Feel, date]]:
    """按说的先后，每块肌肉留最后一次；§57 之前存的名字换成编码（被拆开的旧名对拆出来的每一块都算）。"""
    out: dict[str, tuple[Feel, date]] = {}
    for muscle, feel, day in said:
        for code in muscle_codes(muscle):
            out[code] = (feel, day)
    return out


class FeelBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[tuple[str, Feel, date]]] = {}
        self.rate: dict[str, dict[str, float]] = {}

    async def add(self, user_id: str, muscle: str, feel: Feel, day: date) -> None:
        self.rows.setdefault(user_id, []).append((muscle, feel, day))

    async def latest(self, user_id: str) -> dict[str, tuple[Feel, date]]:
        return _coded(self.rows.get(user_id, []))

    async def rates(self, user_id: str) -> dict[str, float]:
        return dict(self.rate.get(user_id, {}))

    async def set_rate(self, user_id: str, muscle: str, rate: float) -> None:
        self.rate.setdefault(user_id, {})[muscle] = rate


DDL = """
CREATE TABLE IF NOT EXISTS ironm_muscle_feel (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    day        date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ironm_recovery_rate (
    user_id    text NOT NULL,
    muscle     text NOT NULL,
    rate       double precision NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, muscle)
)
"""


class PgFeel:
    """数据库版：肌肉和感受（"股四头肌|sore"）加密后存。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(*DDL.split(";"))
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def add(self, user_id: str, muscle: str, feel: Feel, day: date) -> None:
        await self._q(
            "INSERT INTO ironm_muscle_feel (id, user_id, content, day)"
            " VALUES (:id, :uid, encrypt_content(:content), :day)",
            {"id": uuid.uuid4().hex, "uid": user_id, "content": f"{muscle}|{feel}", "day": day},
        )

    async def latest(self, user_id: str) -> dict[str, tuple[Feel, date]]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content, day FROM ironm_muscle_feel"
            " WHERE user_id = :uid ORDER BY created_at",
            {"uid": user_id},
        )
        said: list[tuple[str, Feel, date]] = []
        for r in rows:
            muscle, _, feel = str(r["content"]).partition("|")
            if feel in ("sore", "fine"):
                said.append((muscle, feel, r["day"]))  # type: ignore[arg-type]
        return _coded(said)

    async def rates(self, user_id: str) -> dict[str, float]:
        rows = await self._q(
            "SELECT muscle, rate FROM ironm_recovery_rate WHERE user_id = :uid", {"uid": user_id}
        )
        return {str(r["muscle"]): float(r["rate"]) for r in rows}

    async def set_rate(self, user_id: str, muscle: str, rate: float) -> None:
        await self._q(
            "INSERT INTO ironm_recovery_rate (user_id, muscle, rate) VALUES (:uid, :m, :r)"
            " ON CONFLICT (user_id, muscle) DO UPDATE SET rate = EXCLUDED.rate, updated_at = now()",
            {"uid": user_id, "m": muscle, "r": rate},
        )


_default: FeelStore | None = None


def default_feel() -> FeelStore:
    global _default
    if _default is None:
        _default = PgFeel()
    return _default
