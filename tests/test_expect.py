"""调整有没有用（spec [2026-10-23] §89）：预期到期由代码核对，结果交给模型、也告诉他；满 4 周出阶段小结。"""

import asyncio
from datetime import timedelta
from typing import Any

from ironm_agent import review
from ironm_agent.coach_state import evaluate
from ironm_agent.expect import Check, judge, measure, parse_check, stage_due, stage_facts
from ironm_agent.metrics import Readings
from ironm_agent.training import LogItem, SetDone, WorkoutLog
from tests.fakes import FakeLLM
from tests.test_coach import TODAY, plan_today
from tests.test_insights import BUSY, days, tired
from tests.test_review import facts_id, model, setup

RHR = {"metric": "resting_hr", "op": "<=", "value": 62, "days": 3}


def test_checks_are_parsed_strictly() -> None:
    assert parse_check(RHR) == Check(metric="resting_hr", op="<=", value=62, days=3)
    assert parse_check({**RHR, "metric": "心情"}) is None
    assert parse_check({**RHR, "days": 60}) is None
    assert parse_check({"metric": "e1rm", "op": ">=", "value": 100, "days": 14}) is None  # 缺动作名
    assert parse_check(RHR).line() == "3 天后静息心率不高于 62 次/分"  # type: ignore[union-attr]


def test_measure_uses_only_data_up_to_the_due_day() -> None:
    r = tired()  # 最近 7 天静息心率约 66，之前约 58
    v, how = measure(Check(**RHR), TODAY - timedelta(days=3), TODAY, r, [], None)
    assert v is not None and v > 62 and "到期前 7 天平均" in how
    assert judge(Check(**RHR), v) == "missed"
    early = TODAY - timedelta(days=10)  # 到期在更早的时候：只看那时候的数
    v, _ = measure(Check(**RHR), early - timedelta(days=3), early, r, [], None)
    assert v is not None and judge(Check(**RHR), v) == "met"
    v, how = measure(Check(**RHR), TODAY, TODAY + timedelta(days=30), r, [], None)
    assert v is None and "只有 0 天" in how and judge(Check(**RHR), v) == "unknown"
    waist = Readings(waist=((TODAY - timedelta(days=20), 90.0), (TODAY - timedelta(days=5), 88.0)))
    v, how = measure(
        Check(metric="waist", op="<=", value=88, days=14), TODAY, TODAY, waist, [], None
    )
    assert v == 88.0 and "是 88 厘米" in how
    log = WorkoutLog(day=TODAY, items=[LogItem(exercise="杠铃深蹲",
                                               done_sets=[SetDone(reps=5, weight_kg=100)])])  # fmt: skip
    e = Check(metric="e1rm", op=">=", value=110, days=14, exercise="杠铃深蹲")
    v, _ = measure(e, TODAY, TODAY, Readings(), [log], None)
    assert v is not None and 115 < v < 118 and judge(e, v) == "met"
    done = Check(metric="completion", op=">=", value=80, days=7)
    v, how = measure(done, TODAY - timedelta(days=7), TODAY, Readings(), BUSY, plan_today())
    assert v is not None and "按计划该练" in how


def adjust_today(seen: list[str]) -> dict[str, Any]:
    f = facts_id(seen, "当前计划")
    return {"type": "today", "ratio": 0.6, "why": "恢复不够", "basis": [f],
            "expect": "三天后静息心率回到 62 以下", "check": RHR}  # fmt: skip


def test_due_expectation_is_checked_and_given_to_the_model_and_to_him() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    llm, _ = model(adjust_today(seen))
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert (
        got.done[0].due == TODAY + timedelta(days=3) and got.done[0].check["metric"] == "resting_hr"
    )
    [c] = [c for c in asyncio.run(dp.store.history("42")) if c.key == "review:today" and c.check]
    assert c.check and c.due == TODAY + timedelta(days=3) and not c.result
    # 第二天：还没到期，告诉模型"还在等结果"，不要叠加
    later, seen2 = model()
    asyncio.run(review.run("42", dp, later, today=TODAY + timedelta(days=1)))
    assert "还在等结果" in seen2[0] and "以前调整的效果" not in seen2[0]
    # 到期那天：代码核对（最近静息心率约 66，没达到），结果写回调整经历、交给模型、放进管家消息
    due, seen3 = model()
    day = TODAY + timedelta(days=3)
    out = asyncio.run(review.run("42", dp, due, today=day))
    [c] = [c for c in asyncio.run(dp.store.history("42", 200))
           if c.key == "review:today" and c.check]  # fmt: skip
    assert c.result == "missed" and c.outcome.startswith("没达到（到期前 7 天平均")
    assert "以前调整的效果" in seen3[0] and "没达到" in seen3[0]
    assert out.checked and "没达到" in out.checked[0]
    state, _ = asyncio.run(evaluate("42", dp, reason="x", today=day, force=True))
    assert any(x.title == "上次的调整效果怎么样" and "没达到" in x.why for x in state.items)
    # 核对过的不再核对
    again, _ = model()
    assert not asyncio.run(review.run("42", dp, again, today=day, force=True)).checked


def test_undone_or_uncheckable_adjustments_are_not_checked() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    llm, _ = model(adjust_today(seen))
    asyncio.run(review.run("42", dp, llm, force=True))
    asyncio.run(review.undo("42", dp, "review:today"))
    due, seen2 = model()
    out = asyncio.run(review.run("42", dp, due, today=TODAY + timedelta(days=3)))
    assert not out.checked and "以前调整的效果" not in seen2[0]  # 撤销了的不核对
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    bad = {**adjust_today(seen), "check": {"metric": "心情", "op": "<=", "value": 1, "days": 3}}
    llm, _ = model(bad)
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert got.done and not got.done[0].check  # 写错的照样执行，只是不核对


def test_stage_facts_compare_the_two_halves() -> None:
    w = Readings(weight=days(28, lambda i: 80 + 0.05 * i))
    logs = [WorkoutLog(day=TODAY - timedelta(days=d), items=[LogItem(
        exercise="杠铃深蹲", done_sets=[SetDone(reps=5, weight_kg=kg)])]) for d, kg in ((20, 90), (3, 100))]  # fmt: skip
    got = stage_facts(
        w, logs, TODAY, goal_line="目标 75 公斤", adjustments=["10月1日 今天休息，达到了"]
    )
    text = "\n".join(got)
    assert (
        "这 4 周练了 2 次" in text
        and "杠铃深蹲估算最大重量：前两周 105 公斤，后两周 117 公斤" in text
    )
    assert (
        "体重：前两周平均" in text
        and "目标进度：目标 75 公斤" in text
        and "今天休息，达到了" in text
    )
    assert stage_due(None, TODAY - timedelta(days=28), [], TODAY)
    assert not stage_due(None, TODAY - timedelta(days=27), [], TODAY)
    assert not stage_due(None, None, [], TODAY)  # 没计划也没记录：不出


def test_four_week_summary_is_written_shown_and_remembered(monkeypatch: Any) -> None:
    dp = setup()  # 计划今天开始用
    early, seen = model()
    asyncio.run(review.run("42", dp, early))
    assert "阶段：" not in seen[0]  # 不满 28 天
    day = TODAY + timedelta(days=28)

    def down(*_: Any) -> Any:
        raise RuntimeError("模型挂了")

    asyncio.run(review.run("42", dp, FakeLLM(down), today=day))
    assert asyncio.run(dp.store.get("42")).stage_day is None  # type: ignore[union-attr]  # 失败了第二天再做
    from tests.fakes import jsonr

    seen: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        seen.append(str(messages[-1]["content"]))
        return jsonr(
            {
                "summary": "一般",
                "adjust": [],
                "stage": "这 4 周练了 5 次，深蹲在涨。下 4 周先把睡眠补上。",
            }
        )

    day = day + timedelta(days=1)
    out = asyncio.run(review.run("42", dp, FakeLLM(answer), today=day))
    assert "阶段：这 4 周练了" in seen[0] and out.stage.startswith("这 4 周练了 5 次")
    state = asyncio.run(dp.store.get("42"))
    assert state is not None and state.stage_day == day and "深蹲在涨" in state.stage_text
    state, _ = asyncio.run(evaluate("42", dp, reason="x", today=day, force=True))
    assert any(x.key == "review:stage" and "深蹲在涨" in x.why for x in state.items)
    nxt, seen2 = model()
    asyncio.run(review.run("42", dp, nxt, today=day + timedelta(days=1)))
    assert "阶段：" not in seen2[0]  # 下一次从今天起再算 28 天
    # 对话档案里讲得出来
    from tests.test_single_agent import single
    from tests.test_turn_flow import run

    a, s = single(lambda *_: jsonr({"answer": "这 4 周深蹲在涨。"}), monkeypatch, old=True)
    a._coach_store = dp.store
    run(a, "这个月练得怎么样")
    assert "最近一次 4 周阶段小结" in s.user and "深蹲在涨" in s.user
