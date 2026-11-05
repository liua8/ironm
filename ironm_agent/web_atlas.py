"""图鉴里的方案库（spec [2026-11-05] §161）：方案库的资料，适合谁、目标、每周几天、在哪练、每次练什么。
打分不在这里，在排行榜的训练计划榜。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends

from ironm_agent.protools.templates import GOALS, LEVELS, PEOPLE, PLACES, templates
from ironm_agent.rank import plan_blurb
from ironm_agent.web_more import _verify

router = APIRouter()
_REF = re.compile(r"〔[^〕]*〕")  # 出处编号只在内部留底，不给用户看


def _plain(text: str) -> str:
    return _REF.sub("", text).strip()


def _plan(t: Any) -> dict[str, Any]:
    sessions = [
        {"name": name, "items": [
            {"move": (s.pick[0] if s.pick else s.free), "sets": s.sets, "reps": s.reps, "note": _plain(s.note)}
            for s in slots
        ]}
        for name, slots in t.sessions.items()
    ]  # fmt: skip
    return {
        "id": t.id,
        "name": t.name,
        "blurb": plan_blurb(t),
        "levels": [LEVELS[x] for x in t.levels],
        "goals": [GOALS[x] for x in t.goals],
        "people": [PEOPLE[x] for x in t.people],
        "place": PLACES.get(t.place, "健身房或在家"),
        "minutes": list(t.minutes),
        "days": sorted(t.weeks),
        "why": _plain(t.why),
        "intensity": _plain(t.intensity),
        "progress": _plain(t.progress),
        "sessions": sessions,
        "blogger": t.source.authors[0] if t.kind == "blogger" and t.source else "",
    }


@router.get("/iron/api/plan-library")
async def plan_library(user_id: str = Depends(_verify())) -> dict[str, Any]:
    return {"plans": [_plan(t) for t in templates()]}
