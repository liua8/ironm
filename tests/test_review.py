"""管家复盘（spec [2026-10-23] §85）：调不调、调什么、调多少由模型决定；代码只保证算对、守安全底线、能撤销。"""

import asyncio
from datetime import timedelta
from typing import Any

from ironm_agent import review
from ironm_agent.casefile import Snapshot
from ironm_agent.coach_state import CoachBook
from ironm_agent.diet_adjust import DietBook
from ironm_agent.metrics import Readings, compute_all
from ironm_agent.training import TrainingBook, plan_content
from tests.fakes import FakeLLM, jsonr
from tests.test_coach import TODAY, deps, plan_today
from tests.test_insights import BUSY, ME, tired


def snapshot_of(r: Readings) -> Snapshot:
    return Snapshot(ME, r, tuple(compute_all(r, ME, TODAY)), TODAY)


def setup(r: Readings | None = None) -> Any:
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", d.id))
    for log in BUSY:
        asyncio.run(book.log("42", log))
    return deps(
        training=book, snapshot=snapshot_of(r or tired()), diet=DietBook(), store=CoachBook()
    )


def model(*adjust: dict[str, Any], summary: str = "恢复不够") -> tuple[FakeLLM, list[str]]:
    seen: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        seen.append(str(messages[-1]["content"]))
        return jsonr({"summary": summary, "adjust": list(adjust)})

    return FakeLLM(answer), seen


def facts_id(seen: list[str], word: str) -> str:
    """模型看到的事实里，含这个词的那一条的编号。"""
    line = next(x for x in seen[0].split("\n") if word in x)
    return line.split("]")[0].lstrip("[")


def test_the_model_decides_today_and_a_note_and_it_takes_effect() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "认出的情况：恢复不够")
    assert "和标准比" in seen[0] and "K18" in seen[0]  # 事实带两种比较，资料带编号
    llm, _ = model(
        {"type": "today", "ratio": 0.5, "why": "这周练多了、睡得少", "basis": [f, "K18"],
         "expect": "三天后静息心率回到 60 以下"},
        {"type": "note", "text": "今晚早点睡", "why": "睡得少", "basis": [f]},
    )  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert [d.type for d in got.done] == ["today", "note"]
    state = asyncio.run(dp.store.get("42"))
    today = state.item("today")
    assert today.action == "auto" and "这周练多了、睡得少" in today.why
    assert "2 组" in today.title or "约 5 成" in today.title  # 4 组按五成 → 2 组
    assert "静息心率" in state.item("review:today").basis  # 依据讲得出用了哪条事实、哪份资料
    assert "心率变异性怎么看" in state.item("review:today").basis
    history = asyncio.run(dp.store.history("42"))
    assert any(c.kind == "review" and c.status == "auto" for c in history)
    again, calls = model()
    asyncio.run(review.run("42", dp, again))
    assert not calls  # 一天一次


def test_plan_change_is_applied_and_can_be_undone() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    day = TODAY.isoweekday()
    llm, _ = model({"type": "plan", "why": "膝盖不舒服先换", "basis": [f],
                    "ops": [{"kind": "swap", "day": day, "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}]})  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert got.done[0].type == "plan"
    names = [x.exercise for s in asyncio.run(dp.training.plan("42")).plan.sessions for x in s.items]
    assert "高脚杯深蹲" in names and "杠铃深蹲" not in names
    assert asyncio.run(review.undo("42", dp, "review:plan")) is not None
    names = [x.exercise for s in asyncio.run(dp.training.plan("42")).plan.sessions for x in s.items]
    assert "杠铃深蹲" in names  # 恢复上一版
    state = asyncio.run(dp.store.get("42"))
    assert state.item("review:plan") is None  # 撤销了的不再列出


def test_kcal_change_respects_the_safety_floor_and_can_be_undone() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -3000, "why": "想减快点", "basis": [f]})
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert got.done and "按基础代谢和安全下限" in got.done[0].title  # 低了按下限执行并写明
    floor_adj = asyncio.run(dp.diet.current("42"))
    assert floor_adj is not None and floor_adj.kcal < 0
    up, _ = model({"type": "kcal", "delta": 200, "why": "减得太快", "basis": [f]})
    asyncio.run(review.run("42", dp, up, force=True))
    assert asyncio.run(dp.diet.current("42")).kcal == floor_adj.kcal + 200  # type: ignore[union-attr]
    asyncio.run(review.undo("42", dp, "review:kcal"))
    assert asyncio.run(dp.diet.current("42")).kcal == floor_adj.kcal  # type: ignore[union-attr]


def test_only_correctness_is_checked_not_the_models_choice() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    llm, _ = model(
        {"type": "today", "ratio": 0.6, "why": "x", "basis": ["F999"]},  # 事实编号不存在
        {"type": "today", "ratio": 0.6, "why": "x", "basis": [f, "K999"]},  # 资料编号不存在
        {"type": "plan", "why": "x", "basis": [f], "ops": [{"kind": "swap", "day": 1, "exercise": "不存在的动作", "to": "俯卧撑"}]},
        {"type": "today", "ratio": 0.9, "why": "模型自己决定的比例", "basis": [f]},
    )  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert [(d.type, d.value) for d in got.done] == [("today", {"ratio": 0.9})]  # 比例不设规则限制


def test_risk_blocks_training_changes_and_model_failure_changes_nothing() -> None:
    bp = Readings(**{**tired().__dict__, "systolic": ((TODAY - timedelta(days=1), 186.0),),
                     "diastolic": ((TODAY - timedelta(days=1), 114.0),)})  # fmt: skip
    dp = setup(bp)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "当前计划")
    llm, _ = model({"type": "today", "ratio": 0.7, "why": "x", "basis": [f]},
                   {"type": "note", "text": "先去量血压", "why": "x", "basis": [f]})  # fmt: skip
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert [d.type for d in got.done] == ["note"]  # 危急指标：不调训练

    def broken(*_: Any) -> Any:
        raise RuntimeError("模型挂了")

    dp2 = setup()
    out = asyncio.run(review.run("42", dp2, FakeLLM(broken)))
    assert out.failed and not out.done
    assert (
        "这周练多了" not in asyncio.run(dp2.store.get("42")).item("today").why
    )  # 不退回规则替它决定


def test_chat_case_file_shows_todays_adjustments_with_their_basis(monkeypatch: Any) -> None:
    from tests.test_single_agent import single
    from tests.test_turn_flow import TODAY as FLOW  # 对话测试用的"今天"
    from tests.test_turn_flow import run

    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=FLOW))
    f = facts_id(seen, "当前计划")
    llm, _ = model(
        {"type": "today", "ratio": 0.5, "why": "这周练多了、睡得少", "basis": [f, "K18"]}
    )
    asyncio.run(review.run("42", dp, llm, today=FLOW, force=True))
    a, s = single(lambda *_: jsonr({"answer": "今天按五成练。"}), monkeypatch, old=True)
    a._coach_store = dp.store
    run(a, "为什么今天少练了")
    assert "管家今天已经调整：今天的训练按约5成练（原因：这周练多了、睡得少）" in s.user
