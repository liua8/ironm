"""每个人用自己的模型（spec §167）：没填时要模型的接口回 428 和"先填你自己的模型"、不调模型；
后台的事没填就跳过；对话链路以外没有地方再拿服务器的密钥建模型。"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from ironm_agent import user_models as um
from tests.conftest import model_is
from tests.test_diet import client as diet_client
from tests.test_live_adjust import start

ROOT = Path(__file__).resolve().parents[1]


def test_meal_estimate_and_recommend_say_fill_your_model(monkeypatch: pytest.MonkeyPatch) -> None:
    model_is(monkeypatch, None)
    c, meals, _ = diet_client(monkeypatch)
    r = c.post("/iron/api/meals", data={"said": "一碗牛肉面", "kind": "午餐"})
    assert r.status_code == 428 and r.json()["detail"] == um.NO_MODEL
    assert not asyncio.run(meals.day("42", date.today()))  # 没记下半条
    r = c.post("/iron/api/meals/recommend", json={"kind": "午餐"})
    assert r.status_code == 428 and r.json()["detail"] == um.NO_MODEL


def test_machine_recognize_says_fill_your_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_user_models import _client

    model_is(monkeypatch, None)
    c, _ = _client(monkeypatch)
    r = c.post("/iron/api/machines/recognize", files={"photo": ("a.jpg", b"\xff\xd8x", "image/jpeg")})
    assert r.status_code == 428 and r.json()["detail"] == um.NO_MODEL


def test_live_adjust_without_model_still_guards_pain(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, live, _ = start(monkeypatch)
    model_is(monkeypatch, None)
    r = c.post("/iron/api/live/adjust", json={"id": live["id"], "said": "膝盖有点疼"})
    assert r.status_code == 428 and r.json()["detail"] == um.NO_MODEL
    assert c.get("/iron/api/live").json()["live"]["no_heavier"] is True  # 安全底线照样守住


def test_background_jobs_skip_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import next_targets, review

    model_is(monkeypatch, None)
    ran: list[str] = []

    async def fake_run(*a: Any, **k: Any) -> None:
        ran.append("run")

    monkeypatch.setattr(review, "run", fake_run)
    monkeypatch.setattr(next_targets, "run", fake_run)
    asyncio.run(review.daily("42", object()))  # type: ignore[arg-type]
    asyncio.run(next_targets.after_log("42", object(), object()))  # type: ignore[arg-type]
    assert ran == []  # 没填就不做，也不报错


def test_background_jobs_use_the_users_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import next_targets, review

    mine = object()
    model_is(monkeypatch, mine)
    got: list[object] = []

    async def fake_run(user_id: str, deps: Any, llm: Any, *a: Any, **k: Any) -> None:
        got.append(llm)

    monkeypatch.setattr(review, "run", fake_run)
    monkeypatch.setattr(next_targets, "run", fake_run)
    asyncio.run(review.daily("42", object()))  # type: ignore[arg-type]
    asyncio.run(next_targets.after_log("42", object(), object()))  # type: ignore[arg-type]
    assert got == [mine, mine]


def test_body_note_is_not_read_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import body_state, web_more

    model_is(monkeypatch, None)
    read: list[str] = []

    async def fake_read(*a: Any, **k: Any) -> None:
        read.append("read")

    monkeypatch.setattr(body_state, "read_text", fake_read)

    async def go() -> None:
        web_more.body_later("42", "膝盖有点疼", date.today(), "随手记")
        await asyncio.sleep(0.05)

    asyncio.run(go())
    assert read == []  # 没填自己的模型就不读（§167 需求 3）
    model_is(monkeypatch, object())
    asyncio.run(go())
    assert read == ["read"]  # 填了就用他的模型读


def test_store_failure_is_not_treated_as_no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(um, "pick", broken)
    c, _, _ = diet_client(monkeypatch)
    r = c.post("/iron/api/meals", data={"said": "一碗牛肉面", "kind": "午餐"})
    assert r.status_code == 503 and "读不到你的模型设置" in r.json()["detail"]


# 对话链路（plugin.py 及其调用的作答、记忆整理、摘要）11-05 已接上（§167 第 5 条）
CHAT_PENDING: set[str] = set()  # 对话链路也接上了


def test_no_server_key_model_outside_the_chat_chain() -> None:
    hits = []
    for p in sorted((ROOT / "ironm_agent").glob("*.py")):
        src = p.read_text(encoding="utf-8")
        if "TurnLLM(load_models()" in src or "default_llm" in src:
            hits.append(p.name)
    assert set(hits) <= CHAT_PENDING, hits


def test_web_page_points_to_model_settings() -> None:
    js = (ROOT / "ironm_agent" / "web" / "app.js").read_text(encoding="utf-8")
    assert js.count("if (res.status === 428) throw noModelError(body);") == 1  # 接口 428 认得出来
    assert "if (xhr.status === 428) { reject(noModelError(body)); return; }" in js  # 上传也认得出来
    machines = js[js.index("async function machinesPage(") : js.index("const markList")]
    assert "errLine(err)" in machines  # 认器械没填模型：给"去填模型"
    assert 'send("/iron/api/meals", form); closeSheet(); redraw(r); }\n    catch (err) { msg.className = ""; msg.replaceChildren(errLine(err));' in js
    home = js[js.index("async function home(view)") : js.index("// ---- 填自己的模型")]
    assert 'api("/iron/api/my-model")' in home and "modelCard(mine)" in home
    card = js[js.index("function modelCard(mine)") : js.index("// ---- 场所与器材")]
    assert "mine.model" in card and "去填模型" in card and "以后再说" in card and "localStorage" not in card
    assert "默认模型" not in js and "换回默认" not in js


# ---- 对话（§167 第 5 条）：网页和 App 的问答用每个人自己填的模型 ----


def _chat_agent(monkeypatch: pytest.MonkeyPatch, script: Any) -> Any:
    from tests.test_plugin import agent

    a = agent(script, monkeypatch=monkeypatch)
    a._fixed = False  # 网页和 App 进来的问答：不带固定配置，按人取模型
    return a


def test_chat_without_model_says_fill_and_calls_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.plugin import NO_MODEL_CHAT
    from tests.test_plugin import Scripted, collect, text_of

    s = Scripted("今天练腿。")
    a = _chat_agent(monkeypatch, s)
    model_is(monkeypatch, None)
    blocks = collect(a, "今天练什么")
    assert text_of(blocks) == NO_MODEL_CHAT and s.count == 0  # 一次模型都没调


def test_chat_without_model_still_gives_the_fixed_safety_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_plugin import Scripted, collect, text_of

    s = Scripted()
    a = _chat_agent(monkeypatch, s)
    model_is(monkeypatch, None)
    blocks = collect(a, "跑步的时候胸口突然很痛，现在还在疼")
    assert "120" in text_of(blocks) and s.count == 0  # 规则判定、固定回答，不靠模型


def test_chat_uses_the_users_own_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import plugin
    from tests.test_plugin import Scripted, collect, text_of

    s = Scripted("近 30 天静息心率平均 58 次/分。")
    a = _chat_agent(monkeypatch, s)
    asked: list[str] = []

    async def own_config(user_id: str, *_: Any) -> Any:
        from ironm_agent.llm import load_models

        asked.append(user_id)
        return load_models(), {um.KEY_ENV: "his-key"}

    monkeypatch.setattr(um, "own_config", own_config)
    built: list[Any] = []
    fake = plugin.TurnLLM  # agent() 换上的假模型

    def spy(cfg: Any, env: Any) -> Any:
        built.append(env)
        return fake(cfg, env)

    monkeypatch.setattr(plugin, "TurnLLM", spy)
    blocks = collect(a, "我最近的静息心率正常吗")
    assert text_of(blocks) and s.count > 0
    assert asked and set(asked) == {"42"} and built and all(e == {um.KEY_ENV: "his-key"} for e in built)


def test_chat_settings_unreadable_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.plugin import SETTINGS_DOWN
    from tests.test_plugin import Scripted, collect, text_of

    s = Scripted()
    a = _chat_agent(monkeypatch, s)

    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(um, "own_config", broken)
    assert text_of(collect(a, "今天练什么")) == SETTINGS_DOWN and s.count == 0


def test_chat_background_jobs_skip_without_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """会话摘要、记忆提取、读身体情况都先取本人模型：没填、读不到都返回 None，这一步不做。"""
    from tests.test_plugin import Scripted

    a = _chat_agent(monkeypatch, Scripted())
    model_is(monkeypatch, None)
    assert asyncio.run(a._quiet_llm("42")) is None
    model_is(monkeypatch, object())
    assert asyncio.run(a._quiet_llm("42")) is not None

    async def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(um, "own_config", broken)
    assert asyncio.run(a._quiet_llm("42")) is None
    src = (ROOT / "ironm_agent" / "plugin.py").read_text(encoding="utf-8")
    assert src.count("await self._quiet_llm(user_id)) is None") == 3  # 摘要、读身体情况、记忆提取


def test_chat_pages_recognise_the_no_model_reply() -> None:
    """对话里那句"先填模型"下面给按钮：网页和 App 用开头认出来，开头要和服务端的话对得上。"""
    import re

    from ironm_agent.plugin import NO_MODEL_CHAT

    js = (ROOT / "ironm_agent" / "web" / "app.js").read_text(encoding="utf-8")
    web_lead = re.search(r'const NO_MODEL = "([^"]+)"', js).group(1)[:22]  # type: ignore[union-attr]
    assert NO_MODEL_CHAT.startswith(web_lead) and "startsWith(NO_MODEL.slice(0, 22))" in js
    tsx = (ROOT / "app" / "src" / "features" / "chat" / "message.tsx").read_text(encoding="utf-8")
    app_lead = re.search(r'export const NO_MODEL_LEAD = "([^"]+)"', tsx).group(1)  # type: ignore[union-attr]
    assert NO_MODEL_CHAT.startswith(app_lead) and "msg.text.startsWith(NO_MODEL_LEAD)" in tsx
