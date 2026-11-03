"""网页界面改版第一期（spec [2026-10-23] §104）：训练中自己调的上下限要的数据、修掉的几个问题、首页和导航。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ironm_agent import spoken
from tests.fakes import FakeLLM, jsonr
from tests.test_live import PLAN, client
from tests.test_live_adjust import start

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
JS = (WEB / "app.js").read_text()


def test_live_items_carry_the_planned_weight_and_step(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    from ironm_agent import web_live

    r = c.post("/iron/api/live/start", json={"today_plan": True}).json()
    squat = r["live"]["items"][0]
    assert squat["plan_kg"] == squat["sets"][0]["weight_kg"]  # 开始时预填的重量，上下限按它算
    assert r["steps"]["杠铃深蹲"] == 5.0 and r["live"]["no_heavier"] is False  # 下肢一档 5 公斤
    assert web_live.ui_step("哑铃卧推") == 1.0 and web_live.ui_step("杠铃卧推") == 2.5


def test_special_conditions_start_with_no_heavier(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    from ironm_agent import web_live

    async def pregnant(*_: Any) -> frozenset[str]:
        return frozenset({"pregnancy"})

    monkeypatch.setattr(web_live, "_special", pregnant)
    assert c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]["no_heavier"]


def test_saying_it_hurts_turns_on_no_heavier(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, live, _ = start(monkeypatch)
    monkeypatch.setattr(
        spoken,
        "default_llm",
        lambda: FakeLLM(lambda *_: jsonr({"say": "先停一下。", "changes": []})),
    )
    r = c.post("/iron/api/live/adjust", json={"id": live["id"], "said": "膝盖有点疼"}).json()
    assert r["live"]["no_heavier"] is True
    assert c.get("/iron/api/live").json()["live"]["no_heavier"] is True  # 存下来了，后面一直不加重


def test_page_rules_in_the_script() -> None:
    assert "alert(" not in JS and "confirm(" not in JS  # 页面内提示，不用浏览器自带弹窗
    assert (
        'if (here === "live") render(); else location.hash = "#live";' in JS
    )  # 训练中空页"开始训练"有反应
    assert "先填这一组做了几次（和重量），再打勾。" in JS  # 空的一组不能打勾
    assert "over > stepOf(it) + 1e-9 || over > plan * 0.1 + 1e-9" in JS  # 一档以内、一成以内不提示
    assert "今天不比计划加重" in JS and "L.no_heavier" in JS  # 特殊人群和说过疼的不能加重
    assert "it.best * 1.1" in JS  # 比以前最好成绩重一成以上提醒防手误
    assert "没读到" in JS and 'notLoaded("训练", "今天的训练安排")' in JS  # 读不到不当成没有计划
    assert "三个专业角色" not in JS and "训练教练、营养师、康复恢复师" not in JS
    home = JS[JS.index("async function home(view)") : JS.index("// ---- 首页三块")]
    assert "reportCard(" not in home and "weekPlanCard(" not in home  # 战报和本周计划挪到训练页
    assert (
        "startLive({ today_plan: true })"
        in JS[JS.index("function trainCard") : JS.index("function dietCard")]
    )


def test_lack_row_lays_out_in_a_row() -> None:
    css = (WEB / "style.css").read_text()
    assert ".card.lack-row { flex-direction: row; }" in css
