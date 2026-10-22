"""每轮开始先读这个人最新的基本数据（体重、身高），交给所有专业 Agent，让建议能按本人算。

读到的每一行都带 mirobody 的引用编号，Agent 引用时用 <statement>…<cite>[r3]</cite></statement>。
读不到时不影响作答，只是建议不能按本人换算。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ironm_agent.tools import row_numbers

_log = logging.getLogger("ironm_agent.personal")

BASICS = ("bodyMasss", "heights")


@dataclass(frozen=True)
class Personal:
    lines: tuple[str, ...] = ()  # 给 Agent 看的几行，每行末尾带 [r编号]
    support: dict[str, list[float]] = field(default_factory=dict)

    def text(self) -> str:
        if not self.lines:
            return ""
        return (
            "这个人最新的基本数据（引用时写成 <statement>…<cite>[r编号]</cite></statement>）：\n"
            + "\n".join(self.lines)
        )


async def personal_basics(health: Any, user_id: str, session_id: str) -> Personal:
    try:
        envelope = await health.envelope(
            {"user_id": user_id, "session_id": session_id}, indicators=list(BASICS), view="latest"
        )
    except Exception as e:
        _log.warning("basics unavailable: error_type=%s", type(e).__name__)
        return Personal()
    if getattr(envelope, "status", "ok") == "error":
        return Personal()
    lines: list[str] = []
    support: dict[str, list[float]] = {}
    for row in getattr(envelope, "data", None) or []:
        if not isinstance(row, Mapping) or not isinstance(row.get("rid"), str):
            continue
        rid = row["rid"]
        name = row.get("indicator") or row.get("name") or ""
        value = row.get("value") or row.get("value_canonical") or ""
        unit = row.get("unit") or row.get("unit_canonical") or ""
        date = row.get("date") or row.get("time") or ""
        lines.append(f"- {name}：{value} {unit}（{date}）[{rid}]".replace("  ", " "))
        support[rid] = row_numbers(row)
    return Personal(tuple(lines), support)
