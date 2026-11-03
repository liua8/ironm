"""场所与器材（spec [2026-10-23] §107）：开头填一次、档案里改、跟管家说也能改，都是记忆里同一份。

不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from ironm_agent.exercises import EQUIPMENT
from ironm_agent.gear import missing, read, sentence
from ironm_agent.memory_store import Change, Item, MemoryBook, now
from ironm_agent.protools.movement import equipment_of
from ironm_agent.training import Plan, PlanItem, Session
from tests.test_live import client as live_client

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
JS = (WEB / "app.js").read_text()
WD = date.today().isoweekday()


def said(content: str, id_: str = "m1") -> Item:
    t = now()
    return Item(id=id_, category="equipment", content=content, evidence=content, origin="said",
                status="active", created=t, updated=t)  # fmt: skip


def test_sentence_is_read_back_by_the_same_rules() -> None:
    assert equipment_of([sentence("gym", [])]) == frozenset(EQUIPMENT)
    bare = sentence("home", [])
    assert "器械" not in bare and equipment_of([bare]) == frozenset({"自重"})  # 不会被认成有器械
    assert equipment_of([sentence("home", ["哑铃", "器械"])]) == frozenset({"自重", "哑铃", "器械"})
    assert equipment_of([sentence("both", ["弹力带"])]) == frozenset(EQUIPMENT)  # 都有：按健身房排
    for place, gear in (
        ("gym", []),
        ("home", []),
        ("home", ["壶铃", "单杠"]),
        ("both", ["弹力带"]),
    ):
        got = read([said(sentence(place, gear))])  # type: ignore[arg-type]
        assert got["known"] and got["place"] == place
        assert got["gear"] == ([] if place == "gym" else gear)


def test_read_what_the_coach_heard_in_chat() -> None:
    assert read([]) == {
        "known": False,
        "place": None,
        "gear": [],
        "custom": [],
        "text": "",
        "form": False,
    }
    got = read([said("家里有一对可调哑铃和弹力带")])
    assert got["place"] == "home" and got["gear"] == ["哑铃", "弹力带"]
    got = read([said("办了健身房的卡", "a"), said("家里有壶铃", "b")])
    assert got["place"] == "both" and got["gear"] == ["壶铃"]


def test_custom_gear_is_kept_and_recognized_when_possible() -> None:
    from ironm_agent.gear import FORM, custom_ok

    s = sentence("home", ["哑铃"], ["跳绳", "划船机", "哑铃", "跳绳", "TRX", "健身器械"])
    assert s == "在家练，家里有哑铃、跳绳、划船机、TRX"  # 同名、重复的只记一次
    assert equipment_of([s]) == frozenset({"自重", "哑铃", "器械"})  # 划船机认成健身器械
    t = now()
    form = Item(id="f", category="equipment", content=s, evidence=FORM, origin="edited",
                status="active", created=t, updated=t)  # fmt: skip
    got = read([form])
    assert got["gear"] == ["哑铃"] and got["custom"] == [
        "跳绳",
        "划船机",
        "TRX",
    ]  # 健身器械不会被自动勾上
    assert custom_ok("没有杠铃") and custom_ok("无") and custom_ok("x" * 13) and custom_ok(" ")
    assert custom_ok("TRX") == "" and custom_ok("可调哑铃凳") == ""


def test_missing_lists_moves_needing_gear_he_lacks() -> None:
    p = Plan(title="t", days_per_week=1, sessions=[Session(day=WD, name="全身", items=[
        PlanItem(exercise="杠铃深蹲", sets=3, reps="8"), PlanItem(exercise="俯卧撑", sets=3, reps="10"),
        PlanItem(exercise="杠铃卧推", sets=3, reps="8")])])  # fmt: skip
    assert missing(p, frozenset({"自重", "哑铃"})) == ["杠铃深蹲", "杠铃卧推"]
    assert missing(p, frozenset(EQUIPMENT)) == [] and missing(None, frozenset()) == []
    assert missing(p, None) == []  # 不知道有什么器械：不提示


def test_put_gear_replaces_the_old_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web

    p = Plan(title="t", days_per_week=1, sessions=[Session(day=WD, name="全身", items=[
        PlanItem(exercise="杠铃深蹲", sets=3, reps="8"), PlanItem(exercise="俯卧撑", sets=3, reps="10")])])  # fmt: skip
    c, _, _ = live_client(monkeypatch, plan=p)
    memory = MemoryBook()
    asyncio.run(memory.apply("42", [Change(kind="insert", item=said("在健身房练"))]))
    c.app.dependency_overrides[web.memory_store] = lambda: memory  # type: ignore[attr-defined]
    assert c.get("/iron/api/gear").json()["place"] == "gym"
    r = c.put("/iron/api/gear", json={"place": "home", "gear": ["哑铃"]}).json()
    assert (
        r["place"] == "home"
        and r["gear"] == ["哑铃"]
        and r["lacking"] == ["杠铃深蹲"]
        and r["form"]
    )
    rows = asyncio.run(memory.items("42", current_only=False))
    old, new = rows[0], rows[1]
    assert old.status == "superseded" and new.status == "active" and new.origin == "edited"
    assert new.supersedes == old.id and new.category == "equipment"
    r = c.put("/iron/api/gear", json={"place": "gym", "gear": []}).json()
    assert r["lacking"] == [] and len(asyncio.run(memory.items("42"))) == 1  # 每次只留一条
    assert c.put("/iron/api/gear", json={"place": "home", "gear": ["飞机"]}).status_code == 422
    bad = c.put("/iron/api/gear", json={"place": "home", "gear": [], "custom": ["没有杠铃"]})
    assert bad.status_code == 422 and "没有的不用写" in bad.json()["detail"]
    r = c.put(
        "/iron/api/gear", json={"place": "home", "gear": [], "custom": ["跳绳", "TRX"]}
    ).json()
    assert (
        r["custom"] == ["跳绳", "TRX"]
        and r["gear"] == []
        and c.get("/iron/api/gear").json()["custom"] == ["跳绳", "TRX"]
    )


def test_page_has_card_and_profile_entry_but_no_picker_at_training() -> None:
    assert "function gearCard" in JS and "gearCard(gear)" in JS and "gearSection()" in JS
    assert "以后再说" in JS and "跟管家说" in JS and 'method: "PUT"' in JS
    live = JS[JS.index("async function startLive") : JS.index("async function startLive") + 1500]
    assert "gear" not in live and "在哪练" not in live  # 开始训练不选场所
