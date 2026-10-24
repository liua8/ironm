"""今天的版本（spec [2026-10-23] §18 需求 3）：按今天的状态、天气、可用时间，用规则把计划里今天那次改一改。

不调用模型；每一处改动都写明为什么。原计划不变，用户可以按今天的版本练并打卡。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ironm_agent.protools.movement import find
from ironm_agent.protools.plan_check import estimate_minutes
from ironm_agent.training import PlanItem, Session

_OUTDOOR = re.compile(r"跑|快走|户外|徒步|爬山|骑行|跳绳")
INDOOR = "原地踏步或室内单车"
TIRED_NOTE = "今天状态差：减轻重量，不练到力竭"


@dataclass(frozen=True)
class TodayVersion:
    session: Session
    changes: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return bool(self.changes)


@dataclass
class _Draft:
    items: list[PlanItem]
    changes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _note(item: PlanItem, extra: str) -> str:
    return "；".join(x for x in (item.note, extra) if x)[:80]


def build(
    session: Session,
    *,
    tired: bool = False,
    tired_why: str = "",
    indoor: bool = False,
    indoor_why: str = "",
    minutes: int | None = None,
    scale: float | None = None,
    scale_why: str = "",
) -> TodayVersion:
    """tired：今天状态差或生病；indoor：天气不宜户外；minutes：今天只有多少分钟；
    scale：中断后回来，按原量的几成练（需求 5 用）。"""
    d = _Draft(list(session.items))
    if scale is not None and scale < 1:
        d.items = [x.model_copy(update={"sets": max(1, round(x.sets * scale))}) for x in d.items]
        d.changes.append(f"每个动作的组数按原来的约 {round(scale * 10)} 成")
        d.reasons.append(scale_why)
    if tired:
        d.items = [
            x.model_copy(update={"sets": max(1, x.sets // 2), "note": _note(x, TIRED_NOTE)})
            for x in d.items
        ]
        d.changes.append("组数减半（至少 1 组），减轻重量、不练到力竭")
        d.reasons.append(tired_why or "今天状态差")
    if indoor:
        swapped = []
        for i, x in enumerate(d.items):
            if _OUTDOOR.search(x.exercise):
                swapped.append(x.exercise)
                d.items[i] = x.model_copy(
                    update={"exercise": INDOOR, "note": _note(x, f"原来是{x.exercise}")}
                )
        if swapped:
            d.changes.append(f"户外的{'、'.join(swapped)}换成{INDOOR}")
            d.reasons.append(indoor_why or "天气不宜户外")
    if minutes is not None:
        trimmed = _fit(d, session, minutes)
        if trimmed:
            d.changes.append(trimmed)
            d.reasons.append(f"今天只有 {minutes} 分钟")
    out = session.model_copy(update={"items": d.items})
    if minutes is not None:
        out = out.model_copy(update={"minutes": max(10, min(session.minutes, minutes))})
    return TodayVersion(out, tuple(d.changes), tuple(dict.fromkeys(r for r in d.reasons if r)))


def _fit(d: _Draft, session: Session, minutes: int) -> str:
    """按估算时长删减：先去掉辅助动作（从后往前），还放不下再给后面的动作减组。"""
    removed: list[str] = []
    cut = 0

    def need() -> float:
        return estimate_minutes(session.model_copy(update={"items": d.items}))

    while need() > minutes and len(d.items) > 1:
        idx = next(
            (i for i in range(len(d.items) - 1, -1, -1)
             if (m := find(d.items[i].exercise)) is None or not m.compound),
            None,
        )  # fmt: skip
        if idx is None:
            break
        removed.append(d.items.pop(idx).exercise)
    i = len(d.items) - 1
    while need() > minutes and any(x.sets > 1 for x in d.items):
        if d.items[i].sets > 1:
            d.items[i] = d.items[i].model_copy(update={"sets": d.items[i].sets - 1})
            cut += 1
        i = i - 1 if i > 0 else len(d.items) - 1
    parts = []
    if removed:
        parts.append(f"去掉{'、'.join(removed)}")
    if cut:
        parts.append(f"主项一共少做 {cut} 组")
    return "，".join(parts)
