"""打卡照片（spec [2026-10-23] §117）：练完打卡随手拍的一张，挂在那条训练记录上，在轨迹里按天看。

照片用 mirobody 的加密函数加密存在 iron-m 自己的表里，只按登录的人取；不交给模型；日志不记图片。
"""

from __future__ import annotations

import base64
from typing import Any, Protocol

from ironm_agent.ddl import run_ddl


class PhotoStore(Protocol):
    async def put(self, user_id: str, workout_id: str, data: bytes, mime: str) -> None: ...
    async def get(self, user_id: str, workout_id: str) -> tuple[bytes, str] | None: ...
    async def drop(self, user_id: str, workout_id: str) -> None: ...
    async def having(self, user_id: str, workout_ids: list[str]) -> set[str]: ...


class PhotoBook:
    """内存版（测试与自测用）。"""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], tuple[bytes, str]] = {}

    async def put(self, user_id: str, workout_id: str, data: bytes, mime: str) -> None:
        self.rows[(user_id, workout_id)] = (data, mime)

    async def get(self, user_id: str, workout_id: str) -> tuple[bytes, str] | None:
        return self.rows.get((user_id, workout_id))

    async def drop(self, user_id: str, workout_id: str) -> None:
        self.rows.pop((user_id, workout_id), None)

    async def having(self, user_id: str, workout_ids: list[str]) -> set[str]:
        return {w for (u, w) in self.rows if u == user_id and w in workout_ids}


DDL = """
CREATE TABLE IF NOT EXISTS ironm_checkin_photo (
    user_id    text NOT NULL,
    workout_id text NOT NULL,
    photo      text NOT NULL,
    photo_mime text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, workout_id)
)
"""


class PgPhotos:
    """数据库版：照片（base64）用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL)
            self._ready = True
        rows = await execute_query(sql, params or {}, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def put(self, user_id: str, workout_id: str, data: bytes, mime: str) -> None:
        await self._q(
            "INSERT INTO ironm_checkin_photo (user_id, workout_id, photo, photo_mime) VALUES "
            "(:uid, :wid, encrypt_content(:photo), :mime) ON CONFLICT (user_id, workout_id) "
            "DO UPDATE SET photo = EXCLUDED.photo, photo_mime = EXCLUDED.photo_mime, created_at = now()",
            {"uid": user_id, "wid": workout_id, "mime": mime,
             "photo": base64.b64encode(data).decode()},
        )  # fmt: skip

    async def get(self, user_id: str, workout_id: str) -> tuple[bytes, str] | None:
        rows = await self._q(
            "SELECT decrypt_content(photo) AS photo, photo_mime FROM ironm_checkin_photo "
            "WHERE user_id = :uid AND workout_id = :wid",
            {"uid": user_id, "wid": workout_id},
        )
        if not rows or not rows[0].get("photo"):
            return None
        return base64.b64decode(rows[0]["photo"]), str(rows[0].get("photo_mime") or "image/jpeg")

    async def drop(self, user_id: str, workout_id: str) -> None:
        await self._q(
            "DELETE FROM ironm_checkin_photo WHERE user_id = :uid AND workout_id = :wid",
            {"uid": user_id, "wid": workout_id},
        )

    async def having(self, user_id: str, workout_ids: list[str]) -> set[str]:
        if not workout_ids:
            return set()
        rows = await self._q(
            "SELECT workout_id FROM ironm_checkin_photo "
            "WHERE user_id = :uid AND workout_id = ANY(:ids)",
            {"uid": user_id, "ids": workout_ids},
        )
        return {str(r["workout_id"]) for r in rows}


_default: PhotoStore | None = None


def default_photos() -> PhotoStore:
    global _default
    if _default is None:
        _default = PgPhotos()
    return _default
