"""身体状态只由管家写（spec [2026-10-23] §163 需求 1）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ironm_agent.actions import RECORD_STATE
from ironm_agent.body_state import apply, pains_of, read_text
from ironm_agent.day_state import DayBook
from ironm_agent.illness import Episode, IllnessBook
from ironm_agent.memory_store import MemoryBook
from ironm_agent.triggers import PainBook
from tests.fakes import FakeLLM, call, down, jsonr

TODAY = date.today()


@dataclass
class Deps:
    illness: Any
    day: Any
    pain: Any
    memory: Any


def deps() -> Deps:
    return Deps(IllnessBook(), DayBook(), PainBook(), MemoryBook())


def put(d: Deps, told: dict[str, Any]) -> Any:
    return asyncio.run(
        apply("42", told, illness=d.illness, days=d.day, pain=d.pain, memory=d.memory, today=TODAY)
    )


def test_pain_is_kept_with_side_exercise_and_level() -> None:
    d = deps()
    got = put(
        d,
        {
            "pain": [
                {"part": "膝", "side": "左", "exercise": "箱式深蹲", "level": "轻"},
                {"part": "肚子"},
            ]
        },
    )
    assert got.pain == ["joint.knee"]  # 肚子不是练的部位：不记疼，也不改判成生病
    [row] = asyncio.run(d.pain.details("42", TODAY))
    assert (row["part"], row["side"], row["exercise"], row["level"]) == (
        "joint.knee",
        "左",
        "箱式深蹲",
        "轻",
    )
    assert pains_of(["左膝"]) == [
        {"part": "joint.knee", "side": "", "exercise": "", "level": ""}
    ]  # 旧写法照收
    assert pains_of([{"part": "膝", "side": "上面"}])[0]["side"] == ""  # 不认得的左右空着


def test_sick_level_is_what_the_coach_said() -> None:
    for level, want in (
        ("发烧", "fever"),
        ("颈部以下", "below"),
        ("颈部以上", "above"),
        ("说不清", "vague"),
        ("", "vague"),
    ):
        d = deps()
        put(d, {"sick": "嗓子疼", "sick_level": level})
        assert [e.level for e in d.illness.rows["42"].values()] == [want], level


def test_better_moves_the_open_illness_only() -> None:
    d = deps()
    ep = Episode(symptoms=["发烧"], level="fever", started=TODAY - timedelta(days=1))
    asyncio.run(d.illness.save("42", ep))
    assert put(d, {"better": "好些"}).illness == "better"
    assert put(d, {"better": "好了"}).illness == "resolved"
    assert put(d, {"better": "好了"}).illness == ""  # 没有正在进行的生病：不新开、不改


def test_day_state_numbers_must_be_sensible() -> None:
    d = deps()
    got = put(d, {"tired": True, "sleep": 30, "minutes": 2, "good": True})
    assert got.day == 2  # 睡 30 小时、只能练 2 分钟不记


def test_paused_memory_keeps_pain_out() -> None:
    d = deps()
    asyncio.run(d.memory.set_paused("42", True))
    assert put(d, {"pain": [{"part": "腰"}]}).pain == [] and not d.pain.rows.get("42")


def test_a_note_is_read_by_the_coach_not_by_keywords() -> None:
    d = deps()
    said = FakeLLM(
        lambda *_: call(RECORD_STATE, pain=[{"part": "膝", "side": "左", "exercise": "深蹲"}])
    )
    got = asyncio.run(read_text("42", "深蹲的时候左膝有点疼", TODAY, "打卡备注", d, said))
    assert got is not None and got.pain == ["joint.knee"]
    assert said.calls[0].stage == "coach"
    quiet = deps()  # 管家判断没说身体的事：不写（"膝盖酸爽"这类不靠词表猜）
    assert (
        asyncio.run(
            read_text("42", "今天练得很爽", TODAY, "打卡备注", quiet, FakeLLM(lambda *_: jsonr({})))
        ).pain
        == []
    )
    failed = deps()  # 模型失败：什么都不写
    assert asyncio.run(read_text("42", "膝盖疼", TODAY, "打卡备注", failed, FakeLLM(down))) is None
    assert not failed.pain.rows.get("42")
    assert (
        asyncio.run(read_text("42", "  ", TODAY, "打卡备注", failed, FakeLLM(down))) is None
    )  # 没写备注不叫醒
