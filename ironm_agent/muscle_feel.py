"""本人说的肌肉感受（spec [2026-10-23] §30）：某块肌肉"还酸""已经不酸了"，恢复判断以本人说的为准。

每块肌肉只用最近说的一次。数据库版的内容用 mirobody 的加密函数加密；日志不写内容。
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Protocol

from ironm_agent.protools.recovery import Feel


class FeelStore(Protocol):
    async def add(self, user_id: str, muscle: str, feel: Feel, day: date) -> None: ...
    async def latest(self, user_id: str) -> dict[str, tuple[Feel, date]]: ...


class FeelBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, list[tuple[str, Feel, date]]] = {}

    async def add(self, user_id: str, muscle: str, feel: Feel, day: date) -> None:
        self.rows.setdefault(user_id, []).append((muscle, feel, day))

    async def latest(self, user_id: str) -> dict[str, tuple[Feel, date]]:
        return {m: (f, d) for m, f, d in self.rows.get(user_id, [])}  # 后说的覆盖先说的


DDL = """
CREATE TABLE IF NOT EXISTS ironm_muscle_feel (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    day        date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgFeel:
    """数据库版：肌肉和感受（"股四头肌|sore"）加密后存。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await execute_query(DDL, {}, log_sql=False)
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
        out: dict[str, tuple[Feel, date]] = {}
        for r in rows:
            muscle, _, feel = str(r["content"]).partition("|")
            if feel in ("sore", "fine"):
                out[muscle] = (feel, r["day"])  # type: ignore[assignment]
        return out


_default: FeelStore | None = None


def default_feel() -> FeelStore:
    global _default
    if _default is None:
        _default = PgFeel()
    return _default
