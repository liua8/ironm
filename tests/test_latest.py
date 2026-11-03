"""所有状态按时间（spec [2026-10-23] §113）：同一件事以最近的为准，旧的被替换；问记录不算说病。

用排查时看到的真实情形（改写过，不含账号信息）。不连数据库、不调用模型。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from ironm_agent.illness import detect
from ironm_agent.latest import current, shadowed
from ironm_agent.memory_layers import layers
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import Recall
from ironm_agent.timeline import build

TODAY = date(2026, 11, 2)
T0 = datetime(2026, 10, 29, 9, tzinfo=UTC)


def item(id_: str, category: str, content: str, minutes: int, status: str = "active",
         until: date | None = None) -> Item:  # fmt: skip
    at = T0 + timedelta(minutes=minutes)
    return Item(id_, category, content, content, "said", status, at, at, None, until)  # type: ignore[arg-type]


def test_newer_word_on_the_same_recent_thing_wins() -> None:
    trip = item(
        "trip", "followup", "出差回来前一天跟教练说一声", 0, until=TODAY + timedelta(days=3)
    )
    over = item("over", "event", "出差取消，周二不再外出", 1, status="resolved")
    sick = item("sick", "event", "从昨天起身体不舒服，今天还没好", 1500, until=TODAY)
    well = item("well", "followup", "体温已记录，身体恢复", 1600, status="resolved")
    busy = item("busy", "event", "这周加班很忙", 1700)
    assert shadowed([trip, over, sick, well, busy]) == {"trip", "sick"}  # 忙是另一件事，不受影响
    knee = item("kn", "event", "今天左膝有点疼", 100)
    knee_ok = item("ko", "event", "膝盖不疼了", 200, status="resolved")
    assert shadowed([knee, knee_ok, busy]) == {"kn"}  # 同一个部位疼：最近说不疼了
    new_sick = item("new", "event", "今天有点不舒服", 1800)
    assert shadowed([sick, well, new_sick]) == {"sick", "well"}  # 又说不舒服：最近的是"不舒服"


def test_profile_things_by_their_key() -> None:
    knee = item("knee", "injury", "左膝有旧伤，深蹲蹲深了会疼", 0)
    knee_ok = item("ok", "injury", "左膝不疼了", 10, status="resolved")
    shoulder = item("sh", "injury", "右肩一抬就疼", 5)
    assert shadowed([knee, knee_ok, shoulder]) == {"knee"}  # 不同部位互不影响
    goals = [item("g1", "goal", "想增肌", 0), item("g2", "goal", "目标减脂", 10)]
    assert shadowed(goals) == {"g1"}
    gym = item("gym", "equipment", "在健身房练，有哑铃、跑步机", 0)
    home = item("home", "equipment", "在家练，只有哑铃", 10)
    kettle = item("kb", "equipment", "家里有壶铃", 20)
    assert shadowed([gym, home, kettle]) == {"gym"}  # "家里有壶铃"是器械，不是换地方
    assert shadowed([item("a", "equipment", "办了健身房的卡", 0), kettle]) == set()
    same = [item("d1", "diet", "乳糖不耐受", 0), item("d2", "diet", "乳糖不耐受", 10),
            item("d3", "diet", "不吃香菜", 20)]  # fmt: skip
    assert shadowed(same) == {"d1"}


def test_advice_by_amount_and_weekday() -> None:
    old = item("p1", "advice", "每天少吃约200千卡，蛋白质按111–138克吃", 0)
    new = item("p2", "advice", "每天蛋白质108–134克，分3–4餐", 10)
    thu_old = item("t1", "advice", "周四高脚杯深蹲加1组", 0)
    thu_new = item("t2", "advice", "周四加俯身哑铃反向飞鸟2组", 10)
    knee = item("k", "advice", "深蹲降到不疼的深度", 5)
    assert shadowed([old, new, thu_old, thu_new, knee]) == {"p1", "t1"}


def test_every_reader_follows_the_rule() -> None:
    trip = item(
        "trip", "followup", "出差回来前一天跟教练说一声", 0, until=TODAY + timedelta(days=3)
    )
    over = item("over", "event", "出差取消，周二不再外出", 1, status="resolved")
    sick = item("sick", "event", "从昨天起身体不舒服，今天还没好", 1500, until=TODAY)
    well = item("well", "event", "身体恢复", 1600, status="resolved")
    items = [trip, over, sick, well]
    assert [x.id for x in current(items)] == ["over", "well"]
    at = datetime(2026, 11, 2, 12, tzinfo=UTC)
    assert "sick" not in {x.id for x in Recall.of(items, at).items}
    lay = layers(items, TODAY)
    shown = "\n".join([*lay.episodes, *lay.asks, *lay.profile])
    assert "身体不舒服" not in shown and "出差回来前一天" not in shown
    line = next(x for x in build(TODAY, 14, memory=items) if "身体不舒服" in x)
    assert "后来说法变了" in line and "到11月2日" not in line  # 时间线照样列出当时说过


def test_asking_for_records_is_not_saying_you_are_sick() -> None:
    for asked in ("我的生病记录", "我的病史", "看看我生病的记录"):
        assert detect(asked) is None, asked
    for said in ("我生病了", "我感冒了", "今天有点不舒服"):
        assert detect(said) is not None, said
