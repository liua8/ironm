"""计划与饮食的动态调整（spec [2026-10-23] §18）。不调用真实模型。"""

import asyncio
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.protools.plan_check import changed_days, check_plan
from ironm_agent.render import plan_card
from ironm_agent.training import Plan, TrainingBook, plan_content

TODAY = date.today()


def plan_of(*sessions: tuple[int, str]) -> Plan:
    return Plan.model_validate(
        {"title": "三练", "days_per_week": len(sessions),
         "sessions": [{"day": d, "name": n, "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]} for d, n in sessions]}
    )  # fmt: skip


OLD = plan_of((1, "全身A"), (3, "全身B"), (5, "全身C"))


# ---- 需求 1：每周复盘直接出方案 ------------------------------------------------------------------


def test_changed_days_and_review_limit() -> None:
    two = plan_of((1, "全身A"), (3, "上肢"), (6, "下肢"))  # 周三改了、周五去掉、周六新增 = 3 天
    assert changed_days(two, OLD) == 3
    assert any(
        "最多改 2 天" in p for p in check_plan(two, current=OLD, max_changed_days=2).problems
    )
    one = plan_of((1, "全身A"), (3, "上肢"), (5, "全身C"))
    assert (
        changed_days(one, OLD) == 1
        and not check_plan(one, current=OLD, max_changed_days=2).problems
    )
    assert not any(
        "最多改" in p for p in check_plan(two, current=OLD).problems
    )  # 对话里改计划不限天数


class FakeAgent:
    """假装走了一遍改计划的链路：存一份预览，返回预览卡片。"""

    def __init__(self, training: TrainingBook, new: Plan) -> None:
        self.training, self.new, self.asked = training, new, ""

    async def generate_response(
        self, user_id: str, messages: list[dict[str, Any]], **_: Any
    ) -> Any:
        self.asked = messages[-1]["content"]
        draft = await self.training.add_draft(
            user_id, "plan", plan_content(self.new, "周三改成上肢")
        )
        yield {"type": "text", "text": "按复盘把周三改成了上肢。"}
        for b in plan_card(draft, self.new, OLD):
            yield b


def client(
    monkeypatch: pytest.MonkeyPatch, new: Plan, tips: list[str]
) -> tuple[TestClient, TrainingBook, dict[str, Any]]:
    from mirobody.server.auth import verify_token

    from ironm_agent import brief, web, web_more

    book = TrainingBook()
    asyncio.run(book.add_draft("42", "plan", plan_content(OLD)))
    d = asyncio.run(book.add_draft("42", "plan", plan_content(OLD)))
    asyncio.run(book.confirm("42", d.id))
    seen: dict[str, Any] = {}

    def fake_agent(training: TrainingBook, memory: Any) -> FakeAgent:
        seen["agent"] = FakeAgent(training, new)
        return seen["agent"]

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        p = Profile(height_cm=175, sex="male", goal="muscle", activity="moderate")
        r = Readings(weight=tuple((TODAY - timedelta(days=i), 70.0) for i in range(20)))
        return Snapshot(p, r, tuple(compute_all(r, p, TODAY)), TODAY)

    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(web_more, "make_agent", fake_agent)
    monkeypatch.setattr(brief, "weekly_review", lambda *a, **k: {"tips": tips})
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web_more.memory_store] = MemoryBook
    app.dependency_overrides[web.training_store] = lambda: book
    return TestClient(app), book, seen


def test_review_proposal_makes_a_plan_preview(monkeypatch: pytest.MonkeyPatch) -> None:
    new = plan_of((1, "全身A"), (3, "上肢"), (5, "全身C"))
    c, book, seen = client(
        monkeypatch, new, ["这周计划 3 次只练了 1 次，不到一半：可以把每周训练减到 2 天。"]
    )
    r = c.post("/iron/api/review/proposal").json()
    assert r["status"] == "ok" and r["changed_days"] == 1 and r["warning"] == ""
    assert (
        seen["agent"].asked.startswith("按这周的复盘调整训练计划")
        and "最多改两处" in seen["agent"].asked
    )
    assert r["draft"]["kind"] == "plan" and r["draft"]["state"] == "pending"
    assert asyncio.run(book.plan("42")).plan.sessions[1].name == "全身B"  # 确认前计划不变
    assert c.post(f"/iron/api/drafts/{r['draft']['id']}/confirm").status_code == 200
    assert asyncio.run(book.plan("42")).plan.sessions[1].name == "上肢"
    assert c.post(f"/iron/api/drafts/{r['draft']['id']}/undo").status_code == 200
    assert asyncio.run(book.plan("42")).plan.sessions[1].name == "全身B"  # 撤销后回到原来的


def test_review_proposal_warns_and_handles_no_tips(monkeypatch: pytest.MonkeyPatch) -> None:
    big = plan_of((2, "a"), (4, "b"), (6, "c"))
    c, _, _ = client(monkeypatch, big, ["睡眠不足"])
    r = c.post("/iron/api/review/proposal").json()
    assert r["changed_days"] > 2 and "超过了每次最多改 2 天" in r["warning"]
    c2, _, _ = client(monkeypatch, big, [])
    assert c2.post("/iron/api/review/proposal").json()["status"] == "no_change"


def test_chain_sends_back_a_review_plan_that_changes_too_much() -> None:
    from types import SimpleNamespace

    from ironm_agent.constraints import Context
    from ironm_agent.experts import Opinion
    from ironm_agent.plugin import REVIEW_ASK, IronMAgent
    from ironm_agent.protools.registry import ToolContext
    from ironm_agent.roles import Role
    from tests.fakes import FakeLLM, jsonr

    too_much = plan_of((2, "a"), (4, "b"), (6, "c"))
    ok = plan_of((1, "全身A"), (3, "上肢"), (5, "全身C"))
    llm = FakeLLM(lambda *_: jsonr({"plan": ok.model_dump(mode="json")}))
    lead = SimpleNamespace(opinion=Opinion(role=Role.PLANNER, speak=True, answer="改好了"))
    run: dict[str, Any] = {}
    tools = ToolContext.build(
        TODAY, goal="muscle", weight_kg=70, readings=None, injured=[], equipment_said=[]
    )
    new, _ = asyncio.run(
        IronMAgent._check_plan(
            IronMAgent(), too_much, {}, REVIEW_ASK + "：……", lead, OLD, tools, Context(), llm,
            SimpleNamespace(text=lambda **_: "档案"), run,  # type: ignore[arg-type]
        )
    )  # fmt: skip
    assert run["plan_check"] == "fixed" and changed_days(new, OLD) == 1
    assert "最多改 2 天" in str(llm.seen[0][1][-1]["content"])


# ---- 需求 2：饮食目标能真正调整 ------------------------------------------------------------------

from ironm_agent.diet_adjust import DietBook, propose  # noqa: E402
from ironm_agent.metrics import KcalAdjust  # noqa: E402


def snap_with(
    goal: str,
    per_week: float,
    *,
    sex: str = "male",
    start: float = 80.0,
    adjust: KcalAdjust | None = None,
) -> Snapshot:
    p = Profile(height_cm=175, birth=date(1995, 1, 1), sex=sex, goal=goal, activity="moderate")  # type: ignore[arg-type]
    r = Readings(
        weight=tuple(
            (TODAY - timedelta(days=i), round(start + per_week / 7 * (27 - i), 2))
            for i in range(28)
        )
    )
    return Snapshot(p, r, tuple(compute_all(r, p, TODAY, adjust)), TODAY)


def test_propose_rules() -> None:
    s = snap_with("fat_loss", 0.0)
    p, _ = propose(s.metrics, s.profile, None, TODAY)
    assert (
        p is not None and p.delta == -200 and "没有下降" in p.reason and p.after == p.before - 200
    )
    fast = snap_with("fat_loss", -1.2)  # 每周掉 1.2 公斤，超过 80 公斤的 1%
    p2, _ = propose(fast.metrics, fast.profile, None, TODAY)
    assert p2 is not None and p2.delta == 150 and "掉得太快" in p2.reason
    ok = snap_with("fat_loss", -0.5)
    assert propose(ok.metrics, ok.profile, None, TODAY)[0] is None
    gain = snap_with("muscle", 0.0)
    assert propose(gain.metrics, gain.profile, None, TODAY)[0].delta == 150  # type: ignore[union-attr]
    quick = snap_with("muscle", 0.6)  # 超过 80 公斤的 0.5%
    assert propose(quick.metrics, quick.profile, None, TODAY)[0].delta == -150  # type: ignore[union-attr]
    health = snap_with("health", 0.0)
    assert propose(health.metrics, health.profile, None, TODAY)[0] is None


def test_propose_limits() -> None:
    recent = KcalAdjust(-200, TODAY - timedelta(days=10), "x")
    s = snap_with("fat_loss", 0.0, adjust=recent)
    p, why = propose(s.metrics, s.profile, recent, TODAY)
    assert p is None and "两周后再看" in why  # 14 天内不重复调整
    near_cap = KcalAdjust(400, TODAY - timedelta(days=20), "x")
    s2 = snap_with("muscle", 0.0, adjust=near_cap)
    p2, _ = propose(s2.metrics, s2.profile, near_cap, TODAY)
    assert p2 is not None and p2.total == 500 and p2.delta == 100  # 累计不超过 ±500
    deep = KcalAdjust(-400, TODAY - timedelta(days=20), "x")
    s3 = snap_with("fat_loss", 0.0, adjust=deep)
    p4, _ = propose(s3.metrics, s3.profile, deep, TODAY)
    floor = max(1500, round(next(m for m in s3.metrics if m.key == "bmr").value or 0))
    assert p4 is None or (p4.total >= -500 and p4.after >= floor)  # 减到下限为止
    small = snap_with("fat_loss", 0.0, sex="female", start=45.0)
    p3, why3 = propose(small.metrics, small.profile, None, TODAY)
    bmr = next(m for m in small.metrics if m.key == "bmr").value
    assert p3 is None or p3.after >= max(1200, round(bmr or 0))  # 不低于基础代谢与安全下限
    if p3 is None:
        assert "下限" in why3


def test_target_includes_adjustment() -> None:
    adj = KcalAdjust(-200, TODAY, "减脂期体重这几周没有下降")
    base = next(m for m in snap_with("fat_loss", 0.0).metrics if m.key == "kcal_target")
    after = next(
        m for m in snap_with("fat_loss", 0.0, adjust=adj).metrics if m.key == "kcal_target"
    )
    assert after.value is not None and base.value is not None and after.value == base.value - 200
    assert "调整 -200" in after.how and "没有下降" in after.how


def test_diet_book_apply_and_undo() -> None:
    b = DietBook()
    asyncio.run(b.apply("42", KcalAdjust(-200, TODAY, "a")))
    asyncio.run(b.apply("42", KcalAdjust(-400, TODAY, "b")))
    assert asyncio.run(b.current("42")).kcal == -400  # type: ignore[union-attr]
    assert asyncio.run(b.undo("42")).kcal == -200  # type: ignore[union-attr]
    assert asyncio.run(b.undo("42")) is None and asyncio.run(b.current("42")) is None
    assert asyncio.run(b.current("7")) is None


def test_diet_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    book = DietBook()

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        return snap_with("fat_loss", 0.0, adjust=await book.current(user_id))

    monkeypatch.setattr(web, "snapshot_for", snap)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.diet_store] = lambda: book
    c = TestClient(app)
    r = c.get("/iron/api/diet/review").json()
    assert r["current"] is None and r["proposal"]["delta"] == -200
    before = r["proposal"]["before"]
    r2 = c.post("/iron/api/diet/adjust").json()
    assert r2["current"]["kcal"] == -200 and r2["target"] == before - 200
    assert r2["proposal"] is None and "两周后再看" in r2["message"]
    assert c.post("/iron/api/diet/adjust").status_code == 409  # 不在复盘时间：不接受
    r3 = c.post("/iron/api/diet/adjust/undo").json()
    assert r3["current"] is None and r3["target"] == before
    assert c.post("/iron/api/diet/adjust/undo").status_code == 404
