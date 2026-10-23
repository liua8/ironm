"""信息不够先追问（spec [2026-10-23] §6）。"""

from datetime import UTC, date, datetime

from ironm_agent.clarify import ANSWERED_NOTE, DEFAULT_NOTE, MARK, decide
from ironm_agent.memory_store import Item
from ironm_agent.memory_view import Recall
from ironm_agent.metrics import Profile

T0 = datetime(2026, 10, 20, tzinfo=UTC)
NONE = Recall()
KNOWN = Recall.of(
    [
        Item("e", "equipment", "家里只有一对 20 公斤哑铃", "", "said", "active", T0, T0),
        Item("s", "schedule", "工作日晚上能练 45 分钟", "", "said", "active", T0, T0),
    ],
    datetime(2026, 10, 23, tzinfo=UTC),
)
GOAL = Profile(goal="muscle", birth=date(1996, 1, 1))


def test_new_user_asking_for_a_plan_gets_one_question_with_at_most_two_items() -> None:
    d = decide("帮我做个训练计划", [], NONE, Profile())
    assert d.plan and d.ask and MARK in d.ask
    assert d.ask.count("？") == 2 and "一周能练几天" in d.ask and "器械" in d.ask
    assert d.missing == ("schedule", "equipment", "goal")


def test_no_question_when_enough_is_known() -> None:
    d = decide("帮我做个训练计划", [], KNOWN, GOAL)
    assert d.plan and not d.ask and d.missing == ()
    # 只缺一项也不问
    assert not decide("今天练什么", [], KNOWN, Profile()).ask
    # 这句话里自己说了
    assert not decide("帮我排个计划，一周三练，在家有哑铃", [], NONE, Profile()).ask


def test_not_a_training_request_never_asks() -> None:
    for text in ("深蹲怎么做", "早餐吃什么", "我最近的静息心率正常吗"):
        assert decide(text, [], NONE, Profile()) == decide(text, [], NONE, Profile()).__class__()


def test_after_asking_once_we_build_the_plan() -> None:
    asked = [
        "用户：帮我做个训练计划",
        f"教练（要点）：先确认两件事，好给你排得准：①…？②…？{MARK}，我先按…",
    ]
    you = decide("你定吧", asked, NONE, Profile())
    assert you.plan and not you.ask and you.note == DEFAULT_NOTE
    told = decide("一周三练，在家有哑铃", asked, NONE, Profile())
    assert told.plan and not told.ask and told.note == ANSWERED_NOTE
    # 同一件事只问一次：后面再提计划也不再问
    later = [*asked, "用户：一周三练", "教练（要点）：好的，按每周三练排……"]
    again = decide("帮我做个训练计划", later, NONE, Profile())
    assert again.plan and not again.ask


def test_defaults_word_skips_the_question() -> None:
    d = decide("随便给我排个训练计划", [], NONE, Profile())
    assert d.plan and not d.ask and d.note == DEFAULT_NOTE


def test_a_new_topic_after_the_question_is_not_an_answer() -> None:
    """独立审查：追问后的下一句一律当作回答，"早餐吃什么"也会排出计划。"""
    asked = ["用户：帮我做个训练计划", f"教练（要点）：先确认两件事…{MARK}，我先按每周 3 天…"]
    assert decide("早餐吃什么", asked, NONE, Profile()) == decide("早餐吃什么", [], NONE, Profile())
    d = decide("你定吧", asked, NONE, Profile())
    assert d.plan and d.origin == "帮我做个训练计划"
    today = ["用户：今天练什么", f"教练（要点）：先确认两件事…{MARK}"]
    assert decide("你定", today, NONE, Profile()).origin == "今天练什么"  # 据此不出周计划卡片


def test_a_confirmed_plan_counts_as_known_schedule_and_equipment() -> None:
    assert not decide("按我的计划今天练什么", [], NONE, GOAL, has_plan=True).ask
    assert decide("按我的计划今天练什么", [], NONE, GOAL).ask  # 没有计划、也没说过时间和器械
