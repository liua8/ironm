"""练完打卡后叫醒管家定下次怎么练（spec [2026-10-23] §132）：规则降为参考和兜底，代码只管算对和安全。

不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import pytest

from ironm_agent import next_targets
from ironm_agent.coach_state import CoachBook, evaluate
from ironm_agent.progression import Decided, day_mark, target_lines, targets
from ironm_agent.training import LogItem, SetDone, TrainingBook, WorkoutLog, plan_content
from ironm_agent.triggers import PainBook
from tests.fakes import FakeLLM, call
from tests.test_coach import TODAY, deps, plan_today


def squat(back: int, reps: int = 9, weight: float = 60, **kw: Any) -> WorkoutLog:
    sets = [SetDone(reps=reps, weight_kg=weight)] * 4
    return WorkoutLog(day=TODAY - timedelta(days=back), session="下肢",
                      items=[LogItem(exercise="杠铃深蹲", done_sets=sets)], **kw)  # fmt: skip


def setup(*logs: WorkoutLog, pain: PainBook | None = None) -> Any:
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", d.id))
    for log in logs:
        asyncio.run(book.log("42", log))
    return deps(training=book, store=CoachBook(), pain=pain or PainBook())


def coach(*calls: dict[str, Any], text: str = "这次练到力竭了") -> FakeLLM:
    """假管家：按顺序调 set_next_target，交完说一句。"""

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        done = sum(1 for m in messages if m.get("role") == "tool")
        if tools and done < len(calls):
            return call(next_targets.TOOL, **calls[done])
        return type(call("x"))(text)

    return FakeLLM(answer)


HARD = squat(0, reps=9, rpe=10, note="最后一组练到力竭，膝盖有点不舒服")


def held(logs: list[WorkoutLog]) -> Decided:
    """按今天这次定的、还算数的一条（记着那天的组和计划的组次）。"""
    return Decided(exercise="杠铃深蹲", sets=4, reps="6–8", weight_kg=60, why="先保持", after=TODAY,
                   mark=day_mark("杠铃深蹲", logs, TODAY), plan="4×6–8")  # fmt: skip


def test_the_coach_gets_this_session_the_last_two_today_and_the_rule() -> None:
    pain = PainBook()
    asyncio.run(pain.add("42", "joint.knee", TODAY))
    dp = setup(squat(4), HARD, pain=pain)
    llm = coach()
    got = asyncio.run(next_targets.run("42", dp, llm, HARD))
    assert got == {}  # 没调用工具：什么都不存，照规则
    system, user = (str(m["content"]) for m in llm.seen[0][1])
    assert "【记训练与复盘 · 练完定下次】" in system and "set_next_target" in system
    assert "感受 10 分" in user and "备注：最后一组练到力竭，膝盖有点不舒服" in user
    assert "杠铃深蹲：计划 4 组 × 6–8 次" in user and "60 公斤 × 9" in user
    assert user.count("60 公斤 × 9、60 公斤 × 9、60 公斤 × 9、60 公斤 × 9") == 2  # 最近两次
    assert "规则的参考：62.5 公斤" in user  # 连续两次每组超过上限：规则说加重
    assert "说膝关节疼" in user or "说膝盖疼" in user
    assert "罗马尼亚硬拉" not in user  # 这次没练到的不定
    state = asyncio.run(dp.store.get("42"))
    assert state is None or not state.targets


def test_a_valid_target_is_stored_and_used_until_a_newer_log() -> None:
    dp = setup(squat(4), HARD)
    llm = coach({"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "6-8", "sets": 4,
                 "why": "这次练到力竭还说膝盖不舒服，先保持 60 公斤"})  # fmt: skip
    got = asyncio.run(next_targets.run("42", dp, llm, HARD))
    assert got["杠铃深蹲"].after == TODAY and got["杠铃深蹲"].reps == "6–8"
    assert "已存下" in str(llm.seen[1][1][-1]["content"])
    state = asyncio.run(dp.store.get("42"))
    item = state.item("target:杠铃深蹲")
    assert item.title == "杠铃深蹲 下次 60 公斤 × 6–8 次 × 4 组" and item.value["by"] == "coach"
    assert (
        "先保持 60 公斤" in item.why and "规则算的是 62.5 公斤" in item.why
    )  # 和规则不同：说明带上规则
    assert item.basis.startswith("管家")
    hist = asyncio.run(dp.store.history("42", 20))
    assert any(
        c.key == "target:杠铃深蹲" and "60 公斤" in c.after and c.why == item.why for c in hist
    )
    # 再评估（比如第二天打开）照样用管家定的
    again, _ = asyncio.run(evaluate("42", dp, reason="打开对话"))
    assert again.item("target:杠铃深蹲").value["by"] == "coach" and again.targets
    # 之后又记了一次：回到规则
    asyncio.run(dp.training.log("42", squat(-1, reps=9)))
    later, _ = asyncio.run(evaluate("42", dp, reason="打卡", today=TODAY + timedelta(days=1)))
    assert later.item("target:杠铃深蹲").value["by"] == "rule"


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ({"exercise": "卧推", "weight_kg": 40, "reps": "8", "sets": 3}, "不在这次要定的动作里"),
        ({"exercise": "杠铃深蹲", "weight_kg": 67, "reps": "6–8", "sets": 4}, "一成"),
        ({"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "6–8", "sets": 11}, "组数要 1–10"),
        ({"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "很多", "sets": 4}, "次数要写成"),
        ({"exercise": "杠铃深蹲", "weight_kg": -5, "reps": "6–8", "sets": 4}, "重量不为负"),
    ],
)
def test_bad_targets_are_sent_back(args: dict[str, Any], why: str) -> None:
    dp = setup(squat(4), HARD)
    llm = coach({**args, "why": "x"})
    got = asyncio.run(next_targets.run("42", dp, llm, HARD))
    assert got == {} and why in str(llm.seen[1][1][-1]["content"])
    state = asyncio.run(dp.store.get("42"))
    assert state is None or not state.targets


def test_ten_percent_is_allowed_and_bodyweight_gets_no_new_load() -> None:
    dp = setup(squat(4), HARD)
    ok = asyncio.run(next_targets.run("42", dp, coach(
        {"exercise": "杠铃深蹲", "weight_kg": 66, "reps": "6–8", "sets": 4, "why": "轻松"}), HARD))  # fmt: skip
    assert ok["杠铃深蹲"].weight_kg == 66
    bare = squat(0, weight=0)
    dp = setup(squat(4, weight=0), bare)
    llm = coach({"exercise": "杠铃深蹲", "weight_kg": 20, "reps": "6–8", "sets": 4, "why": "x"})
    assert asyncio.run(next_targets.run("42", dp, llm, bare)) == {}
    assert "不新加重量" in str(llm.seen[1][1][-1]["content"])


def failing(*first: Any) -> FakeLLM:
    turns = iter(first)

    def answer(*_: Any) -> Any:
        try:
            return next(turns)
        except StopIteration:
            raise RuntimeError("模型挂了") from None

    return FakeLLM(answer)


def test_model_failure_stores_nothing_but_keeps_what_was_already_stored() -> None:
    dp = setup(squat(4), HARD)
    assert asyncio.run(next_targets.run("42", dp, failing(), HARD)) == {}
    state = asyncio.run(dp.store.get("42"))
    assert state is None or not state.targets  # 一个都没定成：什么都不存，照规则
    ok = call(
        next_targets.TOOL, exercise="杠铃深蹲", weight_kg=60, reps="6–8", sets=4, why="先保持"
    )
    got = asyncio.run(next_targets.run("42", dp, failing(ok), HARD))
    assert list(got) == ["杠铃深蹲"]  # 已经告诉它存下的：最后那句没说出来也照存（审查 11-03）
    assert asyncio.run(dp.store.get("42")).item("target:杠铃深蹲").value["by"] == "coach"


def test_not_woken_for_a_rest_day_or_when_nothing_in_the_plan_was_logged() -> None:
    rest = WorkoutLog(day=TODAY, done=False, note="出差")
    other = WorkoutLog(day=TODAY, items=[LogItem(exercise="引体向上", done_sets=[SetDone(reps=8)])])
    for log in (rest, other):
        dp = setup(squat(4), log)
        llm = coach()
        assert asyncio.run(next_targets.run("42", dp, llm, log)) == {} and not llm.seen


def test_targets_and_lines_say_who_decided() -> None:
    plan, logs = plan_today(), [squat(4), HARD]
    d = held(logs)
    found = targets(plan, logs, {"杠铃深蹲": d})
    assert found["杠铃深蹲"].by == "coach" and found["杠铃深蹲"].action == "hold"
    assert targets(plan, logs)["杠铃深蹲"].by == "rule"
    stale = d.model_copy(update={"after": TODAY - timedelta(days=4)})
    assert (
        targets(plan, logs, {"杠铃深蹲": stale})["杠铃深蹲"].by == "rule"
    )  # 定的不是最新这次：照规则
    line = target_lines(plan, logs, TODAY, {"杠铃深蹲": d})[0]
    assert "〔管家定的〕" in line and "杠铃深蹲 下次 60 公斤" in line


def test_web_training_and_triggers(
    monkeypatch: pytest.MonkeyPatch, next_targets_recorded: list[Any]
) -> None:
    """打卡、对话记的训练确认后都叫醒管家；计划页拿到的下次目标带 by。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ironm_agent import web, web_more

    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", d.id))
    for log in (squat(4), HARD):
        asyncio.run(book.log("42", log))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[web._verify()] = lambda: "42"
    app.dependency_overrides[web.training_store] = lambda: book
    decided = held([squat(4), HARD])

    async def mine(_: str) -> dict[str, Any]:
        return {"杠铃深蹲": decided}

    monkeypatch.setattr(web_more, "decided_targets", mine)
    client = TestClient(app)
    t = client.get("/iron/api/training").json()["targets"]["杠铃深蹲"]
    assert t["by"] == "coach" and t["weight_kg"] == 60
    log = {
        "day": TODAY.isoformat(),
        "items": [{"exercise": "杠铃深蹲", "done_sets": [{"reps": 8, "weight_kg": 60}]}],
    }
    draft = asyncio.run(book.add_draft("42", "log", {"log": log}))
    assert client.post(f"/iron/api/drafts/{draft.id}/confirm").status_code == 200
    assert next_targets_recorded and next_targets_recorded[-1][1].items[0].exercise == "杠铃深蹲"


def test_logs_have_counts_and_result_kinds_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.next_targets")
    dp = setup(squat(4), HARD)
    asyncio.run(next_targets.run("42", dp, coach(
        {"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "6–8", "sets": 4, "why": "膝盖不舒服先保持"}), HARD))  # fmt: skip
    text = caplog.text
    assert '"exercises": 1' in text and '"decided": 1' in text
    assert "膝盖" not in text and "杠铃深蹲" not in text and "60" not in text


def test_a_checkin_wakes_the_coach(next_targets_recorded: list[Any]) -> None:
    from tests.test_checkin_state import client

    c, _, _ = client()
    body = {
        "session": "下肢",
        "items": [{"exercise": "杠铃深蹲", "done_sets": [{"reps": 8, "weight_kg": 60}]}],
    }
    assert c.post("/iron/api/workouts", json=body).status_code == 200
    [(uid, log)] = next_targets_recorded
    assert uid == "42" and log.items[0].exercise == "杠铃深蹲"


def test_a_backdated_log_does_not_override_a_newer_one() -> None:
    old = squat(6, reps=7)
    dp = setup(squat(4), HARD, old)  # 补记了更早的一次：最新的还是今天这次，不按补记的定
    llm = coach()
    assert asyncio.run(next_targets.run("42", dp, llm, old)) == {} and not llm.seen


def test_not_woken_for_a_session_while_sick() -> None:
    """生病期间练的那次（§46）：组次不算进下次目标，也不叫醒管家。"""
    from dataclasses import replace

    from ironm_agent.illness import Episode, IllnessBook

    ill = IllnessBook()
    asyncio.run(
        ill.save("42", Episode(symptoms=["发烧"], level="fever", started=TODAY - timedelta(days=1)))
    )
    dp = replace(setup(squat(4), HARD), illness=ill)
    llm = coach()
    assert asyncio.run(next_targets.run("42", dp, llm, HARD)) == {} and not llm.seen


def test_agreeing_with_the_rule_still_shows_the_coach_and_its_reason() -> None:
    """管家定的和规则一样：标题不变，但首页的说明换成管家的、标成管家定的；不加版本、不记经历。"""
    easy = squat(0, reps=9, rpe=6, note="挺轻松")
    dp = setup(squat(4), easy)
    first, _ = asyncio.run(evaluate("42", dp, reason="打卡"))
    asyncio.run(next_targets.run("42", dp, coach(
        {"exercise": "杠铃深蹲", "weight_kg": 62.5, "reps": "6–8", "sets": 4, "why": "这次挺轻松，加到 62.5"}), easy))  # fmt: skip
    state = asyncio.run(dp.store.get("42"))
    item = state.item("target:杠铃深蹲")
    assert (
        item.value["by"] == "coach"
        and item.why == "这次挺轻松，加到 62.5"
        and state.version == first.version
    )


def test_a_second_log_the_same_day_or_a_plan_change_goes_back_to_the_rule() -> None:
    """同一天又记了一次、或者改了计划的组次：之前定的对不上了，回到规则（审查 11-03）。"""
    from ironm_agent.training import Plan

    plan, logs = plan_today(), [squat(4), HARD]
    d = held(logs)
    assert targets(plan, logs, {"杠铃深蹲": d})["杠铃深蹲"].by == "coach"
    again = [*logs, squat(0, reps=5)]  # 同一天第二次
    assert targets(plan, again, {"杠铃深蹲": d})["杠铃深蹲"].by == "rule"
    redone = [squat(4), squat(0, reps=7)]  # 删了重记
    assert targets(plan, redone, {"杠铃深蹲": d})["杠铃深蹲"].by == "rule"
    raw = plan.model_dump()
    raw["sessions"][0]["items"][0].update(sets=3, reps="10–12")
    assert targets(Plan.model_validate(raw), logs, {"杠铃深蹲": d})["杠铃深蹲"].by == "rule"


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ({"weight_kg": 60, "reps": "8–40", "sets": 4}, "不超过 30 次"),
        ({"weight_kg": 60, "reps": "10 次，力竭", "sets": 4}, "次数要写成"),
        ({"weight_kg": None, "reps": "6–8", "sets": 4}, "重量不能去掉"),
        ({"weight_kg": 30, "reps": "6–8", "sets": 4}, "三成"),
        ({"weight_kg": 60, "reps": "6–8", "sets": 4, "why": " "}, "要写原因"),
    ],
)
def test_more_bad_targets_are_sent_back(args: dict[str, Any], why: str) -> None:
    dp = setup(squat(4), HARD)
    llm = coach({"exercise": "杠铃深蹲", "why": "x", **args})
    assert asyncio.run(next_targets.run("42", dp, llm, HARD)) == {}
    assert why in str(llm.seen[1][1][-1]["content"])


def test_a_concurrent_evaluate_does_not_drop_the_decision() -> None:
    """记完同时触发的重新评估读得慢：管家定的不被它整份写回时冲掉（审查 11-03）。"""
    from dataclasses import replace

    dp = setup(squat(4), HARD)

    async def main() -> Any:

        async def slow(_: str) -> None:
            await asyncio.sleep(0.2)

        e = asyncio.create_task(evaluate("42", replace(dp, weather=slow), reason="打卡"))
        await asyncio.sleep(0.01)
        llm = coach(
            {"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "6–8", "sets": 4, "why": "先保持"}
        )
        got = await next_targets.run("42", dp, llm, HARD)
        await e
        return got, await dp.store.get("42")

    got, state = asyncio.run(main())
    assert list(got) == ["杠铃深蹲"] and "杠铃深蹲" in state.targets
    assert state.item("target:杠铃深蹲").value["by"] == "coach"


def test_a_backfilled_log_does_not_get_todays_state() -> None:
    from dataclasses import replace
    from datetime import UTC, datetime

    from ironm_agent.day_state import DayBook, Entry

    day = DayBook()
    asyncio.run(day.add("42", TODAY, [Entry(kind="tired", at=datetime.now(UTC))]))
    old = squat(1, reps=9, rpe=8)
    dp = replace(setup(squat(5), old), day=day)
    llm = coach()
    asyncio.run(next_targets.run("42", dp, llm, old))
    assert "有点累" not in str(llm.seen[0][1][1]["content"])
    llm = coach()
    asyncio.run(next_targets.run("42", replace(setup(squat(4), HARD), day=day), llm, HARD))
    assert "有点累" in str(llm.seen[0][1][1]["content"])


def test_mcp_marks_who_decided() -> None:
    from ironm_agent.progression import Target

    t = Target("杠铃深蹲", 4, "6–8", 60, "hold", "先保持", by="coach")
    assert t.line().endswith("〔管家定的〕") and not Target(
        "x", 3, "8", None, "hold", "y"
    ).line().endswith("〕")


def test_relogging_the_same_sets_does_not_bring_back_the_old_decision() -> None:
    """删了按同样的组次重记，这次管家没调：以前定的清掉，照规则（复核 11-03）。"""
    dp = setup(squat(4), HARD)
    asyncio.run(next_targets.run("42", dp, coach(
        {"exercise": "杠铃深蹲", "weight_kg": 62.5, "reps": "6–8", "sets": 4, "why": "加"}), HARD))  # fmt: skip
    assert "杠铃深蹲" in asyncio.run(dp.store.get("42")).targets
    asyncio.run(next_targets.run("42", dp, coach(), HARD))  # 重记后再叫醒，这次没调
    state = asyncio.run(dp.store.get("42"))
    assert "杠铃深蹲" not in state.targets and state.item("target:杠铃深蹲").value["by"] == "rule"


def test_two_logs_the_same_day_compare_with_the_heaviest_set() -> None:
    light = squat(0, reps=8, weight=40)
    heavy = squat(0, reps=8, weight=60)
    dp = setup(squat(4), light, heavy)
    llm = coach({"exercise": "杠铃深蹲", "weight_kg": 60, "reps": "6–8", "sets": 4, "why": "保持"})
    assert asyncio.run(next_targets.run("42", dp, llm, heavy))["杠铃深蹲"].weight_kg == 60
