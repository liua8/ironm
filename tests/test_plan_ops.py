"""改计划用固定操作（spec [2026-10-23] §45）：规则解析、代码套用与修正、卡片差异、复盘生成的操作。"""

import pytest

from ironm_agent.plan_ops import (
    Conflict,
    Op,
    apply,
    fit_time,
    impact,
    only_this_time,
    parse_ops,
    review_ops,
    rows,
    rule_ops,
)
from ironm_agent.training import Plan

GEAR = frozenset({"自重", "哑铃", "弹力带"})


def plan() -> Plan:
    return Plan.model_validate(
        {
            "title": "居家哑铃三分化",
            "goal": "增肌",
            "days_per_week": 3,
            "sessions": [
                {"day": 1, "name": "下肢", "minutes": 45, "items": [
                    {"exercise": "箱式深蹲", "sets": 3, "reps": "10–12"},
                    {"exercise": "罗马尼亚硬拉", "sets": 3, "reps": "10–12"},
                    {"exercise": "臀桥", "sets": 3, "reps": "12–15"},
                    {"exercise": "提踵", "sets": 3, "reps": "15–20"}]},
                {"day": 3, "name": "上肢推", "minutes": 45, "items": [
                    {"exercise": "哑铃卧推", "sets": 4, "reps": "8–12"},
                    {"exercise": "哑铃推举", "sets": 3, "reps": "8–12"},
                    {"exercise": "侧平举", "sets": 3, "reps": "12–15"}]},
                {"day": 5, "name": "上肢拉", "minutes": 45, "items": [
                    {"exercise": "单臂哑铃划船", "sets": 4, "reps": "8–12"},
                    {"exercise": "哑铃弯举", "sets": 3, "reps": "10–12"}]},
            ],
        }
    )  # fmt: skip


def test_simple_sentences_become_operations_without_a_model() -> None:
    p = plan()
    ops = rule_ops("把周三挪到周四", p)
    assert ops is not None and ops[0].kind == "move" and (ops[0].day, ops[0].to_day) == (3, 4)
    assert [o.kind for o in rule_ops("周五删掉", p) or []] == ["remove"]
    light = rule_ops("这周整体轻一点", p)
    assert light is not None and light[0].kind == "reduce" and light[0].ratio == 0.7
    assert rule_ops("这周轻很多", p)[0].ratio == 0.5  # type: ignore[index]
    item = rule_ops("周一的提踵删掉", p)
    assert item is not None and item[0].exercise == "提踵"
    two = rule_ops("把周三挪到周四，周五删掉", p)
    assert two is not None and {o.kind for o in two} == {"move", "remove"}
    assert rule_ops("把周三改成练背", p) is None  # 说不清的交给训练教练
    assert rule_ops("把深蹲换成腿举，再把周三挪到周四", p) is None


def test_only_this_time_does_not_change_the_plan() -> None:
    assert only_this_time("今天轻一点")
    assert not only_this_time("以后每次都轻一点")
    assert not only_this_time("这周整体轻一点")


def test_move_onto_a_training_day_swaps_the_two() -> None:
    out = fit_time(apply(plan(), [Op(kind="move", day=3, to_day=5)]))
    assert not out.notes  # 原样挪过去的天不替用户减动作
    by = {s.day: s.name for s in out.plan.sessions}
    assert by == {1: "下肢", 3: "上肢拉", 5: "上肢推"} and "对调" in out.changes
    out = apply(plan(), [Op(kind="move", day=3, to_day=4)])
    assert {s.day for s in out.plan.sessions} == {1, 4, 5}


def test_reduce_keeps_at_least_one_set_and_leaves_weight_alone() -> None:
    out = apply(plan(), [Op(kind="reduce", ratio=0.7)])
    sets = [x.sets for s in out.plan.sessions for x in s.items]
    assert sets == [2, 2, 2, 2, 3, 2, 2, 3, 2] and all(
        x.load == "" for s in out.plan.sessions for x in s.items
    )
    half = apply(plan(), [Op(kind="reduce", ratio=0.5, weight=True)])
    assert [x.sets for x in half.plan.sessions[0].items] == [2, 2, 2, 2]
    one = apply(
        plan(), [Op(kind="edit", day=5, exercise="哑铃弯举", sets=1), Op(kind="reduce", ratio=0.5)]
    )
    assert one.plan.sessions[2].items[1].sets == 1  # 每个动作至少 1 组
    assert "重量减到约一半" in half.plan.sessions[0].items[0].load


def test_swap_to_an_unsuitable_move_picks_a_substitute() -> None:
    out = apply(
        plan(),
        [Op(kind="swap", day=1, exercise="罗马尼亚硬拉", to="杠铃深蹲")],
        equipment=GEAR,
        injured=("knee",),
    )
    new = out.plan.sessions[0].items[1].exercise
    assert new not in ("罗马尼亚硬拉", "杠铃深蹲") and "你要的杠铃深蹲" in out.changes
    keep = apply(plan(), [Op(kind="swap", day=1, exercise="箱式深蹲", to="杠铃深蹲")],
                 equipment=GEAR, injured=("knee",))  # fmt: skip
    assert keep.plan == plan() and keep.skipped  # 替代里最合适的就是原来的动作：不改
    ok = apply(plan(), [Op(kind="swap", day=3, exercise="侧平举", to="俯卧撑")], equipment=GEAR)
    assert ok.plan.sessions[1].items[2].exercise == "俯卧撑" and not ok.notes


def test_remove_and_edit_only_touch_what_was_asked() -> None:
    p = plan()
    out = apply(p, [Op(kind="edit", day=1, exercise="臀桥", sets=4), Op(kind="remove", day=5)])
    assert out.plan.sessions[0].items[2].sets == 4 and {s.day for s in out.plan.sessions} == {1, 3}
    assert out.plan.sessions[1] == p.sessions[1]  # 没提到的那天一点没动
    assert out.touched == {1, 5}


def test_conflicting_operations_are_not_guessed() -> None:
    with pytest.raises(Conflict):
        apply(
            plan(), [Op(kind="remove", day=5), Op(kind="edit", day=5, exercise="哑铃弯举", sets=4)]
        )
    with pytest.raises(Conflict):
        apply(plan(), [Op(kind="move", day=3, to_day=4), Op(kind="move", day=3, to_day=6)])
    # 先挪走周三、再改"周三的侧平举"：按动作名跟到周四，不算矛盾
    out = apply(
        plan(),
        [Op(kind="move", day=3, to_day=4), Op(kind="edit", day=3, exercise="侧平举", sets=4)],
    )
    assert out.plan.sessions[1].day == 4 and out.plan.sessions[1].items[2].sets == 4


def test_one_failed_operation_leaves_the_rest() -> None:
    out = apply(plan(), [Op(kind="remove", day=2), Op(kind="edit", day=1, exercise="臀桥", sets=4)])
    assert out.skipped == ["周二本来就没有训练"] and out.plan.sessions[0].items[2].sets == 4


def test_overtime_is_fixed_by_trimming_accessories_on_touched_days() -> None:
    out = apply(plan(), [Op(kind="edit", day=1, exercise="箱式深蹲", sets=6),
                         Op(kind="edit", day=1, exercise="罗马尼亚硬拉", sets=6)])  # fmt: skip
    fixed = fit_time(out)
    monday = fixed.plan.sessions[0]
    assert any("估计超过 45 分钟" in x for x in fixed.notes)
    assert monday.items[0].sets == 6  # 先减辅助动作，不动主项
    assert fixed.plan.sessions[1] == plan().sessions[1]


def test_card_rows_list_only_changes_and_impact() -> None:
    p = plan()
    out = apply(p, [Op(kind="edit", day=1, exercise="臀桥", sets=4)])
    assert rows(p, out.plan) == [
        {"what": "周一", "before": "臀桥 3×12–15", "after": "臀桥 4×12–15"}
    ]
    assert any("臀 " in x for x in impact(p, out.plan))


def test_model_operations_are_validated() -> None:
    ops = parse_ops([{"kind": "swap", "day": "周三", "exercise": "侧平举", "to": "俯卧撑"}])
    assert ops is not None and ops[0].day == 3
    assert parse_ops([{"kind": "rewrite"}]) is None and parse_ops("不是列表") is None


def test_review_actions_become_at_most_two_days_of_change() -> None:
    p = plan()
    fewer = review_ops([{"kind": "fewer_days", "days": 2}], p, equipment=GEAR)
    assert [(o.kind, o.day) for o in fewer] == [("remove", 5)]
    light = review_ops([{"kind": "lighter"}], p, equipment=GEAR)
    assert [o.day for o in light] == [1, 3]  # 整体减量也只改前两天
    pain = review_ops([{"kind": "swap_part", "part": "back"}], p, equipment=GEAR)
    assert [(o.kind, o.exercise) for o in pain] == [("swap", "罗马尼亚硬拉")]


# ---- 接到对话里（§45）------------------------------------------------------------------------

from collections.abc import Mapping, Sequence  # noqa: E402
from typing import Any  # noqa: E402

from ironm_agent.llm import Reply, Stage  # noqa: E402
from ironm_agent.training import TrainingBook  # noqa: E402
from tests.test_plugin import text_of  # noqa: E402
from tests.test_turn_flow import Team, agent, jsonr, run, snapshot_of, system_of  # noqa: E402


def _seeded(team: Any, monkeypatch: Any) -> tuple[Any, TrainingBook]:
    a = agent(team, monkeypatch=monkeypatch, snapshot=snapshot_of())
    store = TrainingBook()
    store.seed("42", plan())
    a._training = store
    return a, store


def _card_draft(blocks: list[dict[str, Any]], store: TrainingBook) -> Any:
    import asyncio

    cid = next(str(b["id"]) for b in blocks if str(b.get("id", "")).startswith("card-"))
    return asyncio.run(store.draft("42", cid.removeprefix("card-")))


def test_simple_edit_in_chat_needs_no_model(monkeypatch: Any) -> None:
    t = Team("trainer")
    a, store = _seeded(t, monkeypatch)
    blocks, seen = run(a, "把周三挪到周四")
    assert t.stages == [] and seen["path"] == "answer" and seen["plan_ops"]["by"] == "rule"
    d = _card_draft(blocks, store)
    assert (
        d.content["ops"][0]["kind"] == "move" and "周三「上肢推」挪到周四" in d.content["changes"]
    )
    assert "点「确认」才会保存" in text_of(blocks)


def test_plan_edit_sentences_are_recognised() -> None:
    from ironm_agent.training import task_of

    for ask in ("周五删掉", "周一的提踵删掉", "这周整体轻一点", "把周三挪到周四"):
        assert task_of(ask) == "plan", ask


def test_only_this_time_is_not_a_plan_change(monkeypatch: Any) -> None:
    a, _ = _seeded(Team("trainer"), monkeypatch)
    blocks, seen = run(a, "今天轻一点")
    assert seen.get("plan_ops") is None and not any(
        str(b.get("id", "")).startswith("card-") for b in blocks
    )


def test_second_edit_in_the_same_chat_builds_on_the_first(monkeypatch: Any) -> None:
    import asyncio

    a, store = _seeded(Team("trainer"), monkeypatch)
    first, _ = run(a, "把周三挪到周四")
    d1 = _card_draft(first, store)

    async def told(*_: str) -> list[str]:
        return ["用户：把周三挪到周四", "教练（要点）：按你说的改好了"]

    a._history = told
    second, seen = run(a, "周五删掉")
    d2 = _card_draft(second, store)
    assert seen["plan_ops"]["merged"] and {s["day"] for s in d2.content["plan"]["sessions"]} == {
        1,
        4,
    }
    assert [o["kind"] for o in d2.content["ops"]] == ["move", "remove"]
    assert asyncio.run(store.draft("42", d1.id)).state == "cancelled"  # type: ignore[union-attr]


class Editor(Team):
    """训练教练只写操作（§45）。"""

    def __init__(self, ops: list[dict[str, Any]]) -> None:
        super().__init__("trainer")
        self.ops = ops

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        if stage == "expert":
            self.stages.append("expert")
            assert '"ops"' in system_of(messages)
            return jsonr({"answer": "按你说的改了〔经验〕。", "ops": self.ops})
        return super().__call__(stage, messages, tools)


def test_trainer_writes_operations_and_code_applies_them(monkeypatch: Any) -> None:
    t = Editor(
        [{"kind": "swap", "day": 3, "exercise": "侧平举", "to": "俯卧撑", "why": "你要求的"}]
    )
    a, store = _seeded(t, monkeypatch)
    blocks, seen = run(a, "把周三的侧平举换成俯卧撑")
    assert seen["plan_ops"]["by"] == "model" and t.stages.count("expert") == 1
    d = _card_draft(blocks, store)
    names = [x["exercise"] for x in d.content["plan"]["sessions"][1]["items"]]
    assert names == ["哑铃卧推", "哑铃推举", "俯卧撑"]
    assert d.content["plan"]["sessions"][0] == plan().sessions[0].model_dump()  # 没提到的天不动


def test_conflicting_operations_ask_the_user(monkeypatch: Any) -> None:
    t = Editor(
        [
            {"kind": "remove", "day": 5},
            {"kind": "edit", "day": 5, "exercise": "哑铃弯举", "sets": 4},
        ]
    )
    a, _ = _seeded(t, monkeypatch)
    blocks, seen = run(a, "周五不练了，再把周五的弯举加到 4 组")
    assert seen["plan_ops"]["conflict"] and "请分开说" in text_of(blocks)
    assert not any(str(b.get("id", "")).startswith("card-") for b in blocks)


def test_confirmed_operations_go_into_the_coach_history() -> None:
    import asyncio

    from ironm_agent.coach_state import CoachBook, record_plan

    coach = CoachBook()
    draft = {
        "kind": "plan",
        "changes": "周三「上肢推」挪到周四",
        "ops": [{"kind": "move", "day": 3, "to_day": 4, "why": "出差"}],
    }
    assert asyncio.run(record_plan(coach, "42", draft))
    ch = coach.changes["42"][0]
    assert (
        ch.key == "plan" and ch.change == "accepted" and ch.why == "出差" and "挪到周四" in ch.after
    )
    assert not asyncio.run(
        record_plan(coach, "42", {"kind": "plan", "changes": "整份新排"})
    )  # 不是按操作改的不记


def test_removing_a_day_and_editing_it_in_one_sentence_asks_without_a_model(
    monkeypatch: Any,
) -> None:
    t = Team("trainer")
    a, _ = _seeded(t, monkeypatch)
    blocks, seen = run(a, "周五不练了，再把周五的弯举加到 4 组")
    assert t.stages == [] and seen["plan_ops"]["conflict"] and "请分开说" in text_of(blocks)
