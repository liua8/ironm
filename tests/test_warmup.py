"""计划页的热身和估算消耗（spec [2026-10-23] §116）：代码按这天的动作生成，不调用模型。不连数据库。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from ironm_agent.casefile import Snapshot
from ironm_agent.kb import KnowledgeBase
from ironm_agent.metrics import Profile, Readings
from ironm_agent.training import PlanItem, Session
from ironm_agent.warmup import burn, warmup
from tests.test_plan_edit import JS, WD, client


def day(*names: str, minutes: int = 45) -> Session:
    return Session(day=1, name="练", minutes=minutes,
                   items=[PlanItem(exercise=n, sets=3, reps="10") for n in names])  # fmt: skip


def test_warmup_follows_the_moves_of_the_day() -> None:
    w = warmup(day("杠铃深蹲", "哑铃卧推", "单臂哑铃划船"))
    assert w.steps[0].startswith("全身低强度 5 分钟：原地踏步、开合跳或快走")
    assert "徒手深蹲、弓步各 8 次" in w.steps[1] and "肩胛前伸后缩" in w.steps[1]
    assert "猫牛式" in w.steps[1]
    assert w.steps[2] == "杠铃深蹲先做 2 组热身：正式重量的一半做 8 次、七成做 3–5 次"
    assert w.minutes == 9
    push = warmup(day("侧平举", "俯卧撑"))  # 只练推；第一个多关节动作是自重的
    assert "徒手深蹲" not in push.steps[1] and "肩胛前伸后缩" in push.steps[1]
    assert push.steps[2] == "俯卧撑先做 1 组，次数减半"
    machine = warmup(day("腿举", "坐姿腿弯举"))
    assert "骑单车、椭圆机或快走" in machine.steps[0]


def test_days_without_big_moves_or_unknown_moves() -> None:
    small = warmup(day("侧平举", "平板支撑"))  # 没有多关节动作：不写热身组
    assert len(small.steps) == 2 and small.minutes == 7
    core = warmup(day("平板支撑"))  # 只练核心：不写活动部位
    assert len(core.steps) == 1 and core.minutes == 5
    unknown = warmup(day("骑车"))  # 动作库找不到：不算进分类
    assert len(unknown.steps) == 1 and unknown.steps[0].startswith("全身低强度")
    easy = warmup(day("快走", "跪姿髋屈肌拉伸"))  # 只有有氧、拉伸：从慢速开始
    assert easy.steps == ("从慢速开始 5 分钟，到微微出汗、还能说整句话",) and easy.minutes == 5
    for w in (small, core, unknown):
        assert all("〔" not in s for s in w.steps)  # 页面上不出现编号


def test_burn_is_a_rounded_range_and_needs_weight() -> None:
    b = burn(45, 70)
    assert b is not None and (b.low, b.high) == (180, 320)  # 3.5×70×0.75=183.75；6×70×0.75=315
    assert "3.5" in b.how and "6.0" in b.how and "70 公斤" in b.how and "〔" not in b.how
    assert "不加进饮食页" in b.how
    assert burn(45, None) is None and burn(45, 0) is None


def test_kb_has_the_compendium_entry() -> None:
    e = next(x for x in KnowledgeBase.load().entries if x.id == "K117")
    assert e.year == 2024 and "Compendium" in e.source and e.review == "claude_draft"
    assert any("02054" in p.text and "3.5" in p.text for p in e.points)
    assert any("02050" in p.text and "6.0" in p.text for p in e.points)


def test_week_gives_warmup_and_burn_on_training_days(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web

    async def snap(_: str, today: date | None = None) -> Snapshot:
        return Snapshot(Profile(goal="muscle"), Readings(weight=((date(2026, 1, 1), 80.0), (date.today(), 70.0))),
                        (), date.today())  # fmt: skip

    c, _, _ = client(monkeypatch)
    monkeypatch.setattr(web, "snapshot_for", snap)
    days = c.get("/iron/api/week").json()["days"]
    today = next(d for d in days if d["today"])
    assert today["warmup"]["steps"][-1].startswith("杠铃深蹲先做 2 组") and today["warmup"]["basis"]
    assert (today["burn"]["low"], today["burn"]["high"]) == (180, 320)  # 最近一次体重 70，45 分钟
    rest = [d for d in days if d["session"] is None]
    assert rest and all(d["warmup"] is None and d["burn"] is None for d in rest)

    async def none(*_: Any, **__: Any) -> Snapshot:
        raise RuntimeError("读不到")

    monkeypatch.setattr(web, "snapshot_for", none)
    today = next(d for d in c.get("/iron/api/week").json()["days"] if d["today"])
    assert today["burn"] is None and today["warmup"] is not None  # 读不到体重：不估，热身照给
    assert today["session"]["day"] == WD


def test_plan_page_shows_both() -> None:
    assert "记了体重才能估消耗" in JS and "（估算）" in JS and "warmupCard(c.warmup)" in JS
