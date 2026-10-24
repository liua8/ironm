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
