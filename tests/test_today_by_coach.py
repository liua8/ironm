"""今天的版本只由管家定（spec [2026-10-23] §163 需求 3）。不连数据库、不调用真实模型。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ironm_agent.coach_state import Done, Inputs, Review, today_version
from ironm_agent.day_state import DayState, Entry
from ironm_agent.illness import Episode
from tests.test_coach import TODAY, plan_today, snap


def done(**value: Any) -> Review:
    return Review(day=TODAY, done=[Done(key="review:today", type="today", title="今天", why="这周练多了",
                                        basis="F3", value=value)])  # fmt: skip


def version(review: Review | None, **kw: Any) -> Any:
    return today_version(
        Inputs(snapshot=snap(sleep=4.0), plan=plan_today(), review=review, **kw), TODAY
    )


def test_only_the_coach_changes_today() -> None:
    assert version(None).status == "reviewing"
    assert version(Review(day=TODAY, failed=True)).status == "coach_error"
    plain = version(Review(day=TODAY, summary="照计划练"))
    assert (
        plain.status == "ok" and not plain.changed and plain.today["items"][0]["sets"] == 4
    )  # 睡 4 小时也不减半
    rest = version(done(rest=True))
    assert rest.status == "review_rest" and "这周练多了" in rest.title
    ratio = version(done(ratio=0.5))
    assert (
        ratio.changed and ratio.today["items"][0]["sets"] == 2 and ratio.reasons == ("这周练多了",)
    )


def test_illness_tiredness_and_weather_no_longer_change_today_by_rule() -> None:
    from ironm_agent.weather import Advice

    sick = [Episode(symptoms=["发烧"], level="fever", started=TODAY)]
    tired = DayState(
        day=TODAY,
        entries=[
            Entry(kind="tired", at=datetime.now(UTC)),
            Entry(kind="minutes", at=datetime.now(UTC), minutes=20),
        ],
    )
    v = version(Review(day=TODAY), illness=sick, day=tired, advice=Advice("avoid", ("气温 38℃",)))
    assert v.status == "ok" and not v.changed and v.today["items"][0]["sets"] == 4


def test_edits_for_today_still_apply() -> None:
    from ironm_agent.training import PlanEdit

    edit = PlanEdit(kind="remove", exercise="罗马尼亚硬拉")
    v = version(Review(day=TODAY), day=DayState(day=TODAY, edits=[edit]))
    assert [x["exercise"] for x in v.original["items"]] == ["杠铃深蹲"] and v.changed


def test_saying_something_about_the_body_wakes_the_coach(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import plugin, review

    calls: list[str] = []
    monkeypatch.setattr(review, "rerun_later", lambda uid, deps, reason: calls.append(reason))
    monkeypatch.setattr(review, "daily_later", lambda *a: calls.append("daily"))
    plugin.wake_review("42", None, "说了今天的状态", True)
    plugin.wake_review("42", None, "确认方案", True)
    plugin.wake_review("42", None, "每天第一次提问", False)
    assert calls == ["说了今天的状态", "daily"]


def test_the_review_sees_the_facts_it_now_decides_on() -> None:
    from ironm_agent.review import facts
    from ironm_agent.weather import Advice

    ill = [Episode(symptoms=["发烧"], level="fever", started=TODAY - timedelta(days=4), status="resolved",
                   ended=TODAY - timedelta(days=1))]  # fmt: skip
    day = DayState(day=TODAY, entries=[Entry(kind="minutes", at=datetime.now(UTC), minutes=20)])
    pains = [
        {
            "part": "joint.knee",
            "day": TODAY - timedelta(days=2),
            "side": "左",
            "exercise": "箱式深蹲",
            "level": "轻",
        }
    ]
    inp = Inputs(snapshot=snap(), plan=plan_today(), illness=ill, day=day, pain_details=pains,
                 advice=Advice("indoor", ("小雨",)))  # fmt: skip
    text = "\n".join(facts(inp, TODAY)[0].values())
    assert "生病经过：4 天前说发烧，昨天好了" in text
    assert (
        "20 分钟" in text
        and "说疼：前天 膝盖（左，做箱式深蹲时，轻）" in text
        and "今天的天气" in text
    )
