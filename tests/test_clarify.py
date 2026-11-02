"""信息不够先追问（spec [2026-10-23] §6）；排新计划前先确认五项（§55）。"""

from datetime import UTC, date, datetime

from ironm_agent.clarify import (
    ANSWERED_NOTE,
    CONFIRM,
    CONFIRMED_NOTE,
    DEFAULT_NOTE,
    HEAD,
    MARK,
    conditions,
    decide,
    wants_new,
)
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


def test_new_user_asking_for_a_plan_is_asked_all_five_items() -> None:
    """§55：新用户（记忆和档案都没有）要计划，五项都问，没有旧答案的只问一句。"""
    d = decide("帮我做个训练计划", [], NONE, Profile())
    assert d.plan and d.ask and HEAD in d.ask and d.new
    for item in ("①目标", "②场景", "③器械", "④时间", "⑤伤病"):
        assert item in d.ask
    assert d.ask.count("？") == 5 and CONFIRM in d.ask


def test_old_answers_come_with_where_and_when() -> None:
    """§55：已有计划、记忆里有时间和器械、档案有目标，说"给我一份计划"也要确认，带上来源和日期。"""
    d = decide(
        "我想要更好的减重，给我一份计划吗", [], KNOWN, GOAL, has_plan=True,
        target="目标体重 65 公斤，2027年10月26日前（10月26日设的）",
        plan_line="每周 4 练：周一、周二、周四、周六", today=date(2026, 10, 27), checked_today=True,
    )  # fmt: skip
    assert d.ask and d.new and HEAD in d.ask
    assert "65 公斤" in d.ask and "2027年10月26日" in d.ask
    assert "20 公斤哑铃（10月20日你说的）" in d.ask and "45 分钟（10月20日你说的）" in d.ask
    assert "在家（10月20日你说的）" in d.ask and "每周 4 练" in d.ask
    assert "新计划从明天（10月28日）开始" in d.ask
    not_yet = decide("帮我做个训练计划", [], KNOWN, GOAL, today=date(2026, 10, 27))
    assert "今天开始还是明天（10月28日）开始" in not_yet.ask
    # 没有目标表时写档案的目标类别
    assert "档案里写的是增肌" in decide("帮我做个训练计划", [], NONE, GOAL).ask


def test_replan_wording_counts_as_a_new_plan() -> None:
    """§55 需求 3。"""
    for text in (
        "我想要更好的减重，给我一份计划吗",
        "我要重新定计划",
        "来一份新的训练计划",
        "给我一份训练计划",
    ):
        assert wants_new(text, has_plan=True), text
        assert decide(text, [], KNOWN, GOAL, has_plan=True).ask, text


def test_changing_one_spot_is_not_confirmed() -> None:
    """§55：只改现有计划的某一处不问。"""
    for text in (
        "把周三的计划挪到周四",
        "计划里把深蹲换掉",
        "这周计划少练一次",
        "按我的计划今天练什么",
    ):
        d = decide(text, [], KNOWN, GOAL, has_plan=True)
        assert not d.ask and not d.new, text


def test_answering_the_confirmation_builds_the_plan_once() -> None:
    first = decide("给我一份训练计划", [], KNOWN, GOAL, has_plan=True)
    asked = ["用户：给我一份训练计划", f"教练（要点）：{first.ask}"]
    for reply in ("按这个排", "没变", "现在只有 30 分钟", "你定"):
        d = decide(reply, asked, KNOWN, GOAL, has_plan=True)
        assert d.plan and not d.ask and d.note == CONFIRMED_NOTE and d.new, reply
        assert d.origin == "给我一份训练计划"
    later = [*asked, "用户：按这个排", "教练（要点）：好的，按每周 4 练排……"]
    assert not decide("再给我一份训练计划", later, KNOWN, GOAL, has_plan=True).ask


def test_no_question_for_today_when_enough_is_known() -> None:
    """§6（没有计划、问今天练什么）：只缺一项不问；这句话里自己说了也不问。"""
    assert not decide("今天练什么", [], KNOWN, Profile()).ask
    assert not decide("今天练什么，一周三练，在家有哑铃", [], NONE, Profile()).ask
    assert decide("今天练什么", [], NONE, Profile()).ask


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


def test_temporary_conditions_are_listed_apart_with_dates() -> None:
    """§55 需求 7：临时的和长期的分开写，带起止日期（缺终点时默认两周）。"""
    trip = datetime(2026, 10, 22, tzinfo=UTC)
    recall = Recall.of(
        [
            *KNOWN.items,
            Item("t", "event", "这两周出差只有酒店健身房", "", "said", "active", trip, trip),
        ],
        datetime(2026, 10, 23, tzinfo=UTC),
    )
    d = decide("帮我做个训练计划", [], recall, GOAL)
    assert "③器械：家里只有一对 20 公斤哑铃" in d.ask  # 长期的照旧
    assert (
        "这两周的临时条件（到期就不再用）：这两周出差只有酒店健身房（10月22日起，到10月29日）"
        in d.ask
    )


def test_temporary_conditions_end_when_they_say() -> None:
    """说的是今天的只算那天，这周的到周日；已经过了的不写。"""
    oct22 = datetime(2026, 10, 22, tzinfo=UTC)  # 周四
    oct27 = datetime(2026, 10, 27, tzinfo=UTC)  # 周二
    recall = Recall.of(
        [
            *KNOWN.items,
            Item("a", "event", "今天在家练腿，没有器械可用", "", "said", "active", oct22, oct22),
            Item("b", "event", "这周整体训练量调轻", "", "said", "active", oct27, oct27),
            Item("c", "event", "今晚加班", "", "said", "active", oct27, oct27),
        ],
        datetime(2026, 10, 27, tzinfo=UTC),
    )
    lines = conditions(recall, GOAL, today=date(2026, 10, 27))
    temp = next(x for x in lines if x.startswith("这两周的临时条件"))
    assert "今天在家练腿" not in temp
    assert "这周整体训练量调轻（10月27日起，到11月1日）" in temp
    assert "今晚加班（10月27日当天）" in temp


def test_time_comes_with_the_days_of_the_current_plan() -> None:
    from ironm_agent.training import schedule_line
    from tests.test_plan_ops import plan

    assert schedule_line(plan()) == "现在的计划每周 3 练：周一、周三、周五，每次约 45 分钟"
