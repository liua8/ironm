"""提醒和每周复盘交给管家（spec [2026-10-23] §163 需求 4）：每周叫醒一次，能提临时调整，都要他确认。

不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from ironm_agent import review
from ironm_agent.plan_layers import load
from tests.fakes import FakeLLM, call, jsonr
from tests.test_coach import TODAY
from tests.test_review import facts_id, model, setup


def temp_model(*adjust: dict[str, Any]) -> FakeLLM:
    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        done = sum(1 for m in messages if m.get("role") == "tool")
        if tools and done < len(adjust):
            return call("propose_temporary_change", **adjust[done])
        return jsonr({"summary": "这周病过，下周缓一缓"})

    return FakeLLM(answer)


def test_weekly_review_can_propose_a_temp_change_that_waits_for_him() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    before = [x.sets for s in asyncio.run(dp.training.plan("42")).plan.sessions for x in s.items]  # type: ignore[union-attr]
    assert "上周：计划" in seen[0] and "这周到今天：计划" in seen[0]  # 每周复查看这周练了几次
    start = TODAY + timedelta(days=8)  # 复查那天（下周）之后
    ops = [{"kind": "reduce", "ratio": 0.7}]
    got = asyncio.run(review.run("42", dp, temp_model({"start": start.isoformat(), "end": (start + timedelta(days=6)).isoformat(),
                                                       "ops": ops, "why": "病后缓一周", "basis": [f]}),
                                 force=True, today=TODAY + timedelta(days=7)))  # fmt: skip
    [d] = got.done
    assert d.type == "propose" and d.key == "review:temp" and "临时这样练" in d.title
    draft = asyncio.run(dp.training.draft("42", str(d.value["draft"])))
    assert draft is not None and draft.kind == "temp" and draft.state == "pending"
    assert asyncio.run(load(dp.training, "42")) == []  # 没确认：计划没变
    sets = [x.sets for s in asyncio.run(dp.training.plan("42")).plan.sessions for x in s.items]  # type: ignore[union-attr]
    assert sets == before  # 计划本身没动


def test_the_plan_is_looked_at_once_a_week() -> None:
    dp = setup()
    llm, _ = model()
    asyncio.run(review.run("42", dp, llm))
    state = asyncio.run(dp.store.get("42"))
    assert state is not None and state.week_day == TODAY  # 这周看过了
    llm, _ = model()
    asyncio.run(review.run("42", dp, llm, force=True))
    assert "排训练计划" not in "\n".join(str(m[1][0]["content"]) for m in llm.seen)
    llm, _ = model()
    asyncio.run(
        review.run("42", dp, llm, force=True, today=TODAY + timedelta(days=7))
    )  # 下周：再看一次
    assert "【排训练计划 · 到期复查】" in "\n".join(str(m[1][0]["content"]) for m in llm.seen)


def test_bad_temp_proposals_from_the_review_are_not_saved() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    past = TODAY - timedelta(days=1)
    got = asyncio.run(review.run("42", dp, temp_model({"start": past.isoformat(), "end": TODAY.isoformat(),
                                                       "ops": [{"kind": "reduce", "ratio": 0.7}], "why": "x", "basis": [f]}),
                                 force=True, today=TODAY + timedelta(days=7)))  # fmt: skip
    assert got.done == [] and asyncio.run(dp.training.temps("42")) == []
