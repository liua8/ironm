"""记忆核对补强（spec [2026-10-23] §159）：否定说法、查旧记忆按部位和相近说法找。不连数据库、不调用模型。"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from ironm_agent.facts import derive, structured
from ironm_agent.memory_layers import search
from tests.test_memory_layers import TODAY, item


@pytest.mark.parametrize(
    ("text", "gear"),
    [("家里没有杠铃，只有哑铃", ["哑铃"]), ("哑铃卖了，现在只有弹力带", ["弹力带"]), ("还没买壶铃", []),
     ("家里有哑铃和壶铃", ["哑铃", "壶铃"]), ("不用杠铃用哑铃", ["哑铃"]), ("没想到哑铃这么好用", ["哑铃"]),
     ("以前没买过哑铃现在有了", ["哑铃"]), ("哑铃片坏了一块", ["哑铃"]), ("哑铃都卖了", [])],
)  # fmt: skip
def test_gear_he_says_he_does_not_have_is_not_recorded(text: str, gear: list[str]) -> None:
    assert derive("equipment", text)[1].get("gear", []) == gear


def test_given_gear_that_he_said_he_lacks_is_sent_back() -> None:
    raw = {"gear": ["哑铃", "杠铃"]}
    _, _, why = structured("equipment", raw, "家里只有哑铃", "家里没有杠铃，只有哑铃")
    assert why == "器械和原话对不上"
    assert (
        structured("equipment", {"gear": ["哑铃"]}, "家里只有哑铃", "家里没有杠铃，只有哑铃")[2]
        == ""
    )


def test_a_part_he_says_is_fine_is_not_the_injury() -> None:
    assert derive("injury", "膝盖没问题，就是右肩疼")[1]["parts"] == ["joint.shoulder"]
    assert derive("injury", "左膝不疼了")[1]["parts"] == [
        "joint.knee"
    ]  # 全说好了：说的就是这处好了
    _, _, why = structured("injury", {"parts": ["膝"]}, "右肩疼", "膝盖没问题，就是右肩疼")
    assert why == "部位和原话对不上"


def test_recall_finds_the_same_joint_said_differently() -> None:
    meniscus = replace(item("m", "injury", "半月板损伤，蹲深会疼", TODAY - timedelta(days=30)),
                       data={"parts": ["joint.knee"]})  # fmt: skip
    old_text = item("o", "injury", "髌骨那里一直不舒服", TODAY - timedelta(days=40))
    shoulder = item("s", "injury", "右肩撞击", TODAY - timedelta(days=20))
    got = search([meniscus, old_text, shoulder], "膝盖", 90, TODAY)
    assert "半月板损伤" in got and "髌骨" in got and "右肩" not in got


def test_recall_keeps_keyword_hits_first_and_does_not_flood() -> None:
    """ "吃"不再是一类（"睡前吃什么"会带出全部饮食）；关键词命中的排在补的前面（复核 11-04）。"""
    meals = [
        item(f"d{i}", "diet", f"每天吃{i}个鸡蛋", TODAY - timedelta(days=1)) for i in range(30)
    ]
    got = search(meals, "睡前吃什么", 90, TODAY)
    assert got == "没有查到。"
    trip = item("t", "event", "去上海出差", TODAY - timedelta(days=40))
    talks = [item(f"m{i}", "event", f"开会第{i}天", TODAY - timedelta(days=1)) for i in range(12)]
    lines = search([trip, *talks], "出差", 90, TODAY).splitlines()
    assert "去上海出差" in lines[0] and len(lines) == 1 + 8  # 关键词命中在前，同类的最多补 8 条
    older = item("t0", "event", "去广州出差", TODAY - timedelta(days=60))
    first = search([older, trip, *talks], "出差", 90, TODAY).splitlines()
    assert "去上海出差" in first[0] and "去广州出差" in first[1]  # 关键词命中的里面新的在前


def test_recall_finds_the_same_kind_of_thing() -> None:
    trip = item("t", "event", "去上海开会一周", TODAY - timedelta(days=30))
    cold = item("c", "event", "感冒了", TODAY - timedelta(days=10))
    got = search([trip, cold], "出差", 90, TODAY)
    assert "去上海开会" in got and "感冒" not in got


def test_recall_fills_in_with_similar_wording_above_a_floor() -> None:
    advice = item("a", "advice", "深蹲换成箱式深蹲，练 4 周再看", TODAY - timedelta(days=5))
    other = item("b", "advice", "每天喝两升水", TODAY - timedelta(days=5))
    got = search([advice, other], "箱式蹲", 90, TODAY)  # 关键词对不上，"箱式"一半片段对上
    assert "箱式深蹲" in got and "喝两升水" not in got
    assert search([other], "箱式蹲", 90, TODAY) == "没有查到。"
    warm = item("w", "advice", "每次深蹲前热身", TODAY - timedelta(days=5))
    assert search([warm], "箱式深蹲换法", 90, TODAY) == "没有查到。"  # 只对上五分之一：不算相近
