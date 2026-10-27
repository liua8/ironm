"""改计划不能把计划改坏（spec [2026-10-23] §48）。"""

from typing import Any

from ironm_agent.plan_ops import Op, apply, blocked_days
from ironm_agent.protools.plan_check import check_plan
from tests.test_plan_ops import GEAR, Editor, _seeded, plan, run, text_of


def test_substitute_is_not_already_in_that_session() -> None:
    out = apply(plan(), [Op(kind="swap", day=1, exercise="罗马尼亚硬拉", to="杠铃深蹲")],
                equipment=GEAR, injured=("knee",))  # fmt: skip
    names = [x.exercise for x in out.plan.sessions[0].items]
    assert len(names) == len(set(names)), names
    same = apply(
        plan(), [Op(kind="swap", day=1, exercise="罗马尼亚硬拉", to="箱式深蹲")], equipment=GEAR
    )
    assert same.plan == plan() and any("已经有箱式深蹲" in x for x in same.skipped)


def test_duplicates_and_lost_muscle_groups_must_be_fixed() -> None:
    p = plan()
    dup = p.model_copy(deep=True)
    dup.sessions[0].items[1] = dup.sessions[0].items[0].model_copy()
    assert any("重复" in x for x in check_plan(dup).problems)
    no_push = p.model_copy(deep=True)
    no_push.sessions[1].items = [
        x.model_copy(update={"exercise": "单臂哑铃划船"}) for x in no_push.sessions[1].items[:1]
    ]
    lost = check_plan(no_push, current=p).problems
    assert any("胸" in x and "没练到" in x for x in lost), lost
    assert not any(
        "没练到" in x for x in check_plan(no_push).problems
    )  # 没有当前计划可比时只是提示


def test_moves_avoid_days_the_user_said_are_busy() -> None:
    assert blocked_days("这周末出差，周五练不了，帮我调整一下") == {5, 6, 7}
    assert blocked_days("周三有事，挪一下") == {3} and blocked_days("把周五挪到周六") == set()
    out = apply(plan(), [Op(kind="move", day=5, to_day=6)], equipment=GEAR, blocked={5, 6, 7})
    assert out.plan == plan() and any("周六" in x and "不方便" in x for x in out.skipped)
    ok = apply(plan(), [Op(kind="move", day=5, to_day=4)], equipment=GEAR, blocked={5, 6, 7})
    assert [s.day for s in ok.plan.sessions] == [1, 3, 4]


def test_new_problems_block_the_preview(monkeypatch: Any) -> None:
    t = Editor([{"kind": "swap", "day": 3, "exercise": "哑铃卧推", "to": "单臂哑铃划船"},
                {"kind": "swap", "day": 3, "exercise": "哑铃推举", "to": "弹力带坐姿划船"},
                {"kind": "remove", "day": 3, "exercise": "侧平举"}])  # fmt: skip
    a, _ = _seeded(t, monkeypatch)
    blocks, seen = run(a, "把周三改成练背")
    assert seen["plan_check"] == "failed"
    assert not any(str(b.get("id", "")).startswith("card-") for b in blocks)
    assert "没改" in text_of(blocks)


def test_dropping_a_day_the_user_named_still_goes_through_with_a_note(monkeypatch: Any) -> None:
    from tests.test_plan_ops import Team

    a, _ = _seeded(Team("trainer"), monkeypatch)
    blocks, seen = run(a, "周五删掉")
    assert seen["plan_check"] == "pass" and any(
        str(b.get("id", "")).startswith("card-") for b in blocks
    )
    assert "没练到背" in text_of(blocks)


def test_ops_do_not_jump_days_and_no_op_edits_do_not_count() -> None:
    wrong_day = apply(
        plan(), [Op(kind="edit", day=3, exercise="单臂哑铃划船", sets=5)], equipment=GEAR
    )
    assert wrong_day.plan == plan() and not wrong_day.done  # 周三没有划船：不改到周五去
    same = apply(plan(), [Op(kind="edit", day=5, exercise="单臂哑铃划船", sets=4)], equipment=GEAR)
    assert same.plan == plan() and not same.done and any("没有变化" in x for x in same.skipped)
    moved = apply(plan(), [Op(kind="move", day=3, to_day=4), Op(kind="edit", day=3, exercise="侧平举", sets=4)],
                  equipment=GEAR)  # fmt: skip
    assert (
        moved.plan.sessions[1].day == 4 and moved.plan.sessions[1].items[2].sets == 4
    )  # 先挪走了：照旧能找到


def test_add_moves_a_kind_of_training_to_another_day() -> None:
    ops = [Op(kind="swap", day=3, exercise="哑铃卧推", to="单臂哑铃划船"),
           Op(kind="add", day=1, exercise="哑铃卧推", sets=3, reps="8–12")]  # fmt: skip
    out = apply(plan(), ops, equipment=GEAR)
    assert [x.exercise for x in out.plan.sessions[0].items][-1] == "哑铃卧推"
    assert any("加上哑铃卧推" in x for x in out.lines)
    again = apply(plan(), [Op(kind="add", day=1, exercise="箱式深蹲")], equipment=GEAR)
    assert again.plan == plan() and any("已经有箱式深蹲" in x for x in again.skipped)


def test_trimming_time_never_drops_a_whole_muscle_group() -> None:
    from ironm_agent.plan_ops import fit_time
    from ironm_agent.protools.plan_check import weekly_sets

    ops = [
        Op(kind="swap", day=3, exercise=a, to=b)
        for a, b in (
            ("哑铃卧推", "单臂哑铃划船"),
            ("哑铃推举", "弹力带坐姿划船"),
            ("侧平举", "哑铃弯举"),
        )
    ]
    ops += [Op(kind="add", day=5, exercise=x, sets=n) for x, n in (("哑铃卧推", 4), ("哑铃推举", 3), ("侧平举", 3))]  # fmt: skip
    out = fit_time(apply(plan(), ops, equipment=GEAR))
    assert {"胸", "肩"} <= set(weekly_sets(out.plan)), out.notes
