"""建表（spec [2026-10-23] §183）：同一个进程里一次只建一个，撞上了稍等再试。

各模块第一次用到时"没有这张表就建"（CREATE TABLE IF NOT EXISTS）。新库第一次打开首页，十几个请求同时到，
Postgres 并发建同一张表会报唯一键冲突。这里把建表排成一队：前一个建完后一个再做，IF NOT EXISTS 就不会撞；
别的进程同时在建、撞上了，稍等再试，最多 3 次，还不行照旧抛出。
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable
from typing import Any

RACE = frozenset({"UniqueViolation", "IntegrityError", "DuplicateTable", "DuplicateObject"})
TRIES = 3
_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _lock() -> asyncio.Lock:
    """每个事件循环一把锁（测试里每条用例的事件循环不同）。"""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = _locks[loop] = asyncio.Lock()
    return lock


async def _default(sql: str) -> Any:
    from mirobody.utils.db import execute_query  # 用的时候再取：测试里换掉的照样生效

    return await execute_query(sql, {}, log_sql=False)


async def run_ddl(*statements: str, execute: Callable[[str], Awaitable[Any]] | None = None) -> None:
    """按顺序执行建表语句；空的跳过。"""
    run = execute or _default
    async with _lock():
        for sql in statements:
            if not sql.strip():
                continue
            for attempt in range(TRIES):
                try:
                    await run(sql)
                    break
                except Exception as e:
                    if attempt + 1 < TRIES and type(e).__name__ in RACE:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                    raise
