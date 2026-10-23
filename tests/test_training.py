"""训练计划与训练记录（spec [2026-10-23] §9）：格式校验、记录里的数字不编造、预览确认 / 取消 / 撤销、本周进度。"""

import asyncio
from datetime import date, timedelta
from typing import Any

from ironm_agent.training import (
    Draft,
    Plan,
    TrainingBook,
    WorkoutLog,
    case_lines,
    log_content,
    parse_log,
    parse_plan,
    plan_content,
    task_of,
    trusted_log,
    week_of,
)

TODAY = date(2026, 10, 23)  # 周五
PLAN = {
    "title": "居家三分化",
    "goal": "增肌",
    "days_per_week": 3,
    "sessions": [
        {"day": 1, "name": "下肢", "minutes": 45, "items": [{"exercise": "箱式深蹲", "sets": 3, "reps": "10–12"}]},
        {"day": 3, "name": "上肢推", "minutes": 45, "items": [{"exercise": "哑铃卧推", "sets": 4, "reps": 10}]},
        {"day": 5, "name": "上肢拉", "minutes": 45, "items": [{"exercise": "单臂哑铃划船", "sets": 4, "reps": "8–12", "load": "20 公斤"}]},
    ],
}  # fmt: skip


def plan() -> Plan:
    p, why = parse_plan(PLAN)
    assert p is not None, why
    return p


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_plan_shape_is_checked() -> None:
    p = plan()
    assert p.days_per_week == 3 and p.sessions[1].items[0].reps == "10"  # 次数写成数字也收
    assert p.session_on(TODAY).name == "上肢拉" and p.session_on(TODAY + timedelta(days=1)) is None
    bad = {**PLAN, "sessions": [*PLAN["sessions"], PLAN["sessions"][0]]}
    assert parse_plan(bad)[0] is None and "同一天" in parse_plan(bad)[1]
    assert parse_plan({"title": "x", "days_per_week": 3, "sessions": []})[0] is None
    assert parse_plan(None)[0] is None


def test_log_numbers_must_come_from_what_the_user_said() -> None:
    said = "今天练了单臂哑铃划船 4 组 10 次 20 公斤，感觉打 7 分"
    raw = {
        "session": "上肢拉",
        "items": [{"exercise": "单臂哑铃划船", "sets": 4, "reps": "10", "weight_kg": 25}],
        "rpe": 8,
    }
    log, why = parse_log(raw, TODAY)
    assert log is not None and log.day == TODAY, why
    clean = trusted_log(log, said, plan())
    assert clean.items[0].sets == 4 and clean.items[0].reps == "10"
    assert clean.items[0].weight_kg is None  # 25 公斤是编出来的
    assert clean.rpe is None  # 说的是 7 分
    assert parse_log({**raw, "day": "2026-11-01"}, TODAY)[0] is None  # 不能记未来


def test_task_detection() -> None:
    for text in (
        "帮我排一个每周 3 练的计划",
        "把周三改成练背",
        "这周末出差，周五练不了，帮我调整一下",
        "帮我做个训练计划",
    ):
        assert task_of(text) == "plan", text
    for text in ("今天练了深蹲 3 组 8 次 40 公斤", "今天的计划练完了，有点累，感觉打 7 分"):
        assert task_of(text) == "log", text
    for text in ("今天练什么", "深蹲怎么做", "计划里的硬拉怎么做", "增肌一周练几次比较好"):
        assert task_of(text) is None, text


def test_confirm_writes_once_cancel_writes_nothing_undo_restores() -> None:
    book = TrainingBook()
    first = run(book.add_draft("u", "plan", plan_content(plan(), "新排的")))
    assert run(book.plan("u")) is None  # 确认前没有计划
    done = run(book.confirm("u", first.id))
    assert done is not None and done.state == "confirmed" and run(book.plan("u")).id == done.applied
    assert run(book.confirm("u", first.id)) is None  # 再点一次确认不会重复写入

    second_plan = plan().model_copy(update={"title": "改过的"})
    second = run(book.add_draft("u", "plan", plan_content(second_plan, "周三改成练背")))
    assert (
        run(book.cancel("u", second.id)).state == "cancelled"
        and run(book.confirm("u", second.id)) is None
    )
    third = run(book.add_draft("u", "plan", plan_content(second_plan)))
    run(book.confirm("u", third.id))
    assert run(book.plan("u")).plan.title == "改过的"
    assert run(book.undo("u", first.id)) is None  # 之后又换过计划，不能撤销更早的那次
    assert run(book.undo("u", third.id)).state == "undone"
    assert run(book.plan("u")).plan.title == "居家三分化"  # 回到上一版
    run(book.undo("u", first.id))
    assert run(book.plan("u")) is None  # 第一次生成的撤销后为没有计划

    log = WorkoutLog(day=TODAY, session="上肢拉", rpe=7)
    d = run(book.add_draft("u", "log", log_content(log)))
    run(book.confirm("u", d.id))
    assert [x.log.rpe for x in run(book.workouts("u", TODAY))] == [7]
    run(book.undo("u", d.id))
    assert run(book.workouts("u", TODAY)) == []


def test_drafts_are_private_and_expire() -> None:
    book = TrainingBook()
    d = run(book.add_draft("u", "plan", plan_content(plan())))
    assert run(book.draft("someone", d.id)) is None and run(book.confirm("someone", d.id)) is None
    old = Draft(d.id, d.kind, d.content, "pending", d.created - timedelta(hours=25))
    book._drafts["u"][d.id] = old
    assert old.expired() and old.json()["expired"] and run(book.confirm("u", d.id)) is None


def test_week_progress_and_case_lines() -> None:
    logs = [
        WorkoutLog(day=date(2026, 10, 19), session="下肢", rpe=7),
        WorkoutLog(day=date(2026, 10, 21), session="上肢推", rpe=8),
        WorkoutLog(day=date(2026, 10, 15), session="上肢拉"),  # 上周的不算
    ]
    w = week_of(plan(), logs, TODAY)
    assert (w.planned, w.due, w.done) == (3, 3, 2)
    assert [done for _, done in w.sessions] == [True, True, False]
    lines = case_lines(plan(), logs, TODAY)
    assert any("今天（周五）按计划：上肢拉" in x for x in lines)
    assert any("10月19日" in x and "感受 7 分" in x for x in lines) and not any(
        "10月15日" in x for x in lines
    )
    assert "还没有" in case_lines(None, [], TODAY)[0]


def test_task_detection_review_cases() -> None:
    """独立审查：饮食计划、讲经历、问句被当成写计划或记训练；"帮我记录一下今天的训练"漏判。"""
    for text in ("给我做一个一周的饮食计划", "我练了半年，每周 3 次，为什么没进步", "做了 3 组深蹲膝盖就疼了",
                 "今天练完腿还能吃夜宵吗"):  # fmt: skip
        assert task_of(text) is None, text
    assert task_of("帮我记录一下今天的训练：卧推 4 组 10 次 50 公斤") == "log"


def test_chinese_numbers_in_a_log_are_kept() -> None:
    log, _ = parse_log(
        {"items": [{"exercise": "深蹲", "sets": 3, "reps": "8", "weight_kg": 40}]}, TODAY
    )
    assert log is not None
    clean = trusted_log(log, "今天练了深蹲三组八次四十公斤", None)
    assert (clean.items[0].sets, clean.items[0].reps, clean.items[0].weight_kg) == (3, "8", 40)


def test_sessions_with_the_same_name_are_ticked_by_date() -> None:
    same = Plan.model_validate(
        {"title": "全身", "days_per_week": 3, "sessions": [
            {"day": d, "name": "全身", "items": [{"exercise": "深蹲", "sets": 3, "reps": "10"}]} for d in (1, 3, 5)]}
    )  # fmt: skip
    w = week_of(same, [WorkoutLog(day=date(2026, 10, 19), session="全身")], TODAY)
    assert [done for _, done in w.sessions] == [True, False, False]
