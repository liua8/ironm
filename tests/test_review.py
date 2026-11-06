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
from tests.fakes import FakeLLM, call, jsonr
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


_TOOL = {"today": "adjust_today", "kcal": "propose_kcal_change", "plan": "propose_plan_edit",
         "note": "coach_note", "ask": "coach_note"}  # fmt: skip


def model(*adjust: dict[str, Any], summary: str = "恢复不够") -> tuple[FakeLLM, list[str]]:
    """假管家（§129）：按顺序把每条调整交给对应的工具，交完写一句总结；seen 记下它看到的事实。"""
    seen: list[str] = []

    def answer(stage: Any, messages: Any, tools: Any) -> Any:
        seen.append(str(messages[1]["content"]))
        done = sum(1 for m in messages if m.get("role") == "tool")
        if tools and done < len(adjust):
            a = dict(adjust[done])
            kind = a.pop("type")
            if kind in ("note", "ask"):
                a["kind"] = kind
            return call(_TOOL[kind], **a)
        return jsonr({"summary": summary})

    return FakeLLM(answer), seen


def facts_id(seen: list[str], word: str) -> str:
    """模型看到的事实里，含这个词的那一条的编号。"""
    line = next(x for x in seen[0].split("\n") if word in x)
    return line.split("]")[0].lstrip("[")


def test_the_model_decides_today_and_a_note_and_it_takes_effect() -> None:
    dp = setup()
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "静息心率：和你自己比")
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


def test_plan_change_is_proposed_on_a_stage_day_and_needs_his_ok() -> None:
    """§129：复查提的改计划只在满 4 周那天有；存成预览、出一条待确认，他同意才保存；不用了就作废。"""
    from ironm_agent.coach_state import pending

    dp = setup()
    stage = TODAY + timedelta(days=28)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe, today=stage))
    f = facts_id(seen, "当前计划")
    day = TODAY.isoweekday()
    op = {"kind": "swap", "day": day, "exercise": "杠铃深蹲", "to": "高脚杯深蹲"}
    llm, _ = model({"type": "plan", "why": "膝盖不舒服先换", "basis": [f], "ops": [op]})
    got = asyncio.run(review.run("42", dp, llm, force=True, today=stage))
    assert [d.type for d in got.done] == ["propose"]
    names = [x.exercise for s in asyncio.run(dp.training.plan("42")).plan.sessions for x in s.items]
    assert "杠铃深蹲" in names and "高脚杯深蹲" not in names  # 没自动保存
    draft = asyncio.run(dp.training.draft("42", str(got.done[0].value["draft"])))
    assert draft is not None and draft.state == "pending"  # 存成了预览
    state = asyncio.run(dp.store.get("42"))
    asks = pending(state, stage)
    mine = [x for x in asks if x.key == "review:propose"]
    assert mine and "高脚杯深蹲" in mine[0].title  # 出一条待确认
    assert all(x.key != "proposal:review" for x in asks)  # 这天不再出规则的每周复盘建议
    assert asyncio.run(review.undo("42", dp, "review:propose", today=stage)) is not None
    assert asyncio.run(dp.training.draft("42", draft.id)).state == "cancelled"  # type: ignore[union-attr]
    # 平时（不是满 4 周那天）没有改计划这个工具
    plain, _ = model({"type": "plan", "why": "x", "basis": [f], "ops": [op]})
    assert not asyncio.run(review.run("42", dp, plain, force=True)).done


def live_kcal(dp: Any, profile: Any = ME) -> Any:
    """快照跟着热量调整走（和线上一样：每日热量目标算上现在的调整量）。"""
    from dataclasses import replace

    base = asyncio.run(dp.snapshot("42"))

    async def snapshot(_: str) -> Snapshot:
        adj = await dp.diet.current("42")
        return Snapshot(profile, base.readings, tuple(compute_all(base.readings, profile, TODAY, adj)), TODAY)

    return replace(dp, snapshot=snapshot)


def kcal_of(dp: Any) -> tuple[int, int]:
    """不算调整量时的每日热量目标和安全下限。"""
    from ironm_agent.metrics import safe_floor

    s = asyncio.run(dp.snapshot("42"))
    by = {m.key: m.value for m in compute_all(s.readings, s.profile, TODAY)}
    return round(by["kcal_target"]), round(safe_floor(by["bmr"], s.profile))


def test_kcal_change_respects_the_safety_floor_and_can_be_undone() -> None:
    """§182：热量只在管家复盘里调；单次最多 300、不低于安全下限、被下限推成反方向不调，能撤销。"""
    dp = live_kcal(setup())
    target, floor = kcal_of(dp)
    assert 300 < target - floor < 500  # 前提：第二次就碰到下限，比累计 ±500 先到
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    llm, _ = model({"type": "kcal", "delta": -3000, "why": "想减快点", "basis": [f]})
    got = asyncio.run(review.run("42", dp, llm, force=True))
    assert got.done and "一次最多调 300 千卡" in got.done[0].title  # 单次最多 300
    assert asyncio.run(dp.diet.current("42")).kcal == -300  # type: ignore[union-attr]
    soon, _ = model({"type": "kcal", "delta": 200, "why": "减得太快", "basis": [f]})
    assert asyncio.run(review.run("42", dp, soon, force=True)).done == got.done  # 不到 14 天不复查热量（§129）
    assert asyncio.run(dp.diet.current("42")).kcal == -300  # type: ignore[union-attr]  # 早上定的照留着
    later = TODAY + timedelta(days=14)
    probe2, seen2 = model()
    asyncio.run(review.run("42", dp, probe2, force=True, today=later))
    f = facts_id(seen2, "每日热量目标")  # 换了一天，事实重新编号
    down, _ = model({"type": "kcal", "delta": -300, "why": "还想减", "basis": [f]})
    got2 = asyncio.run(review.run("42", dp, down, force=True, today=later))
    assert got2.done and "按基础代谢和安全下限" in got2.done[0].title  # 低了按下限执行并写明
    floor_adj = asyncio.run(dp.diet.current("42"))
    assert floor_adj is not None and floor_adj.kcal == floor - target
    again = TODAY + timedelta(days=28)
    probe3, seen3 = model()
    asyncio.run(review.run("42", dp, probe3, force=True, today=again))
    f = facts_id(seen3, "每日热量目标")
    llm3, _ = model({"type": "kcal", "delta": -100, "why": "再减点", "basis": [f]},  # 已经在下限：不调
                    {"type": "kcal", "delta": 200, "why": "减得太快", "basis": [f]})  # fmt: skip
    got3 = asyncio.run(review.run("42", dp, llm3, force=True, today=again))
    assert [d.title.split("，")[0] for d in got3.done] == ["每日热量目标加 200 千卡"]
    assert asyncio.run(dp.diet.current("42")).kcal == floor_adj.kcal + 200  # type: ignore[union-attr]
    asyncio.run(review.undo("42", dp, "review:kcal", today=again))
    assert asyncio.run(dp.diet.current("42")).kcal == floor_adj.kcal  # type: ignore[union-attr]


def test_kcal_change_is_not_a_cut_for_minors_and_stays_within_500() -> None:
    """18 岁以下不减热量（特殊人群硬规则，§90）；加热量累计不超过原目标 +500。"""
    from dataclasses import replace

    teen = replace(ME, birth=TODAY.replace(year=TODAY.year - 16))
    dp = live_kcal(setup(), teen)
    probe, seen = model()
    asyncio.run(review.run("42", dp, probe))
    f = facts_id(seen, "每日热量目标")
    cut, _ = model({"type": "kcal", "delta": -200, "why": "想减", "basis": [f]})
    assert not asyncio.run(review.run("42", dp, cut, force=True)).done
    assert asyncio.run(dp.diet.current("42")) is None
    from ironm_agent.metrics import KcalAdjust

    asyncio.run(dp.diet.apply("42", KcalAdjust(400, TODAY - timedelta(days=20), "以前加的")))
    later = TODAY + timedelta(days=14)
    probe2, seen2 = model()
    asyncio.run(review.run("42", dp, probe2, force=True, today=later))
    f = facts_id(seen2, "每日热量目标")
    add, _ = model({"type": "kcal", "delta": 300, "why": "长得慢", "basis": [f]})
    got = asyncio.run(review.run("42", dp, add, force=True, today=later))
    assert got.done and "累计最多调 500 千卡" in got.done[0].title
    assert asyncio.run(dp.diet.current("42")).kcal == 500  # type: ignore[union-attr]

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
