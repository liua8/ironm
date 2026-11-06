"""认器械（spec [2026-11-03] §149）：资料写全、能练的动作都在动作库；模型看照片直接写（不限于清单），
对上清单的带编号；没有模型、模型不可用、照片里没有器械都如实说；照片不保存。不连网络、不连数据库。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import machines as mc
from ironm_agent.exercises import library


def test_machine_data_complete() -> None:
    got = mc.machines()
    assert len(got) >= 25 and {x.group for x in got} == {"gym", "free", "cardio"}
    known = {x.id for x in library().exercises}
    for m in got:
        assert m.trains and m.setup and m.careful and set(m.moves) <= known, m.id


class FakeLLM:
    def __init__(self, reply: str | None) -> None:
        self.reply, self.sent = reply, []

    async def chat(self, stage, messages, **kw):  # type: ignore[no-untyped-def]
        from ironm_agent.llm import ModelUnavailable, Reply

        self.sent.append((stage, messages, kw))
        if self.reply is None:
            raise ModelUnavailable("missing_key")
        return Reply(content=self.reply)


SAID = (
    '{"name": "倒蹬机", "aka": ["腿举机"], "trains": "大腿前侧、臀部", "setup": ["靠背调好", "双脚踩中间"], '
    '"careful": ["膝盖别锁死"], "moves": ["腿举", "单腿腿举"], "score": 0.9, "match": "leg-press-machine"}'
)


def run(model: object) -> mc.Recognition:
    return asyncio.run(mc.recognize(b"\xff\xd8img", "image/jpeg", model))  # type: ignore[arg-type]


def test_model_writes_freely_and_links_to_the_list() -> None:
    llm = FakeLLM(SAID)
    got = run(mc.ModelLooker(llm))
    j = got.json()
    assert j["status"] == "ok" and j["name"] == "倒蹬机" and j["match"] == "leg-press-machine"
    assert j["moves"] == [
        {"name": "腿举", "id": "leg-press"},
        {"name": "单腿腿举", "id": None},
    ]  # 动作库有的带编号
    stage, messages, kw = llm.sent[0]
    text, image = messages[0]["content"]
    assert stage == "vision" and kw["json_mode"] and "leg-press-machine：腿举机" in text["text"]
    assert image["image_url"]["url"].startswith("data:image/jpeg;base64,")
    # 清单里没有的器械照样写；编号对不上的不带
    other = run(
        mc.ModelLooker(
            FakeLLM('{"name": "腰腹训练椅", "trains": "腹部", "score": 0.4, "match": "火箭"}')
        )
    )
    assert (
        other.status == "unsure"
        and other.json()["match"] is None
        and other.json()["name"] == "腰腹训练椅"
    )
    assert run(mc.ModelLooker(FakeLLM('{"name": ""}'))).status == "none"  # 照片里没有器械
    assert run(mc.ModelLooker(FakeLLM("不是 JSON"))).status == "none"
    assert run(mc.ModelLooker(FakeLLM(None))).status == "failed"
    assert asyncio.run(mc.recognize(b"x", "image/jpeg")).status == "no_model"


def _client() -> TestClient:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    return TestClient(app)


def test_endpoints(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    c = _client()
    got = c.get("/iron/api/machines").json()["machines"]
    leg = next(x for x in got if x["id"] == "leg-press-machine")
    assert leg["moves"][0] == {"id": "leg-press", "name": "腿举"}
    jpg = ("a.jpg", b"\xff\xd8\xff fake", "image/jpeg")
    monkeypatch.setattr(mc, "looker", lambda *a: None)
    assert c.post("/iron/api/machines/recognize", files={"photo": jpg}).json() == {
        "status": "no_model"
    }
    bad = c.post("/iron/api/machines/recognize", files={"photo": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 415
    monkeypatch.setattr(mc, "looker", lambda *a: mc.ModelLooker(FakeLLM(SAID)))
    with caplog.at_level("INFO"):
        r = c.post("/iron/api/machines/recognize", files={"photo": jpg}).json()
    assert r["status"] == "ok" and r["name"] == "倒蹬机"
    assert "fake" not in caplog.text and "倒蹬机" not in caplog.text  # 日志不记图片和模型写的内容


def test_page_wiring() -> None:
    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    assert (
        '["machines", "器械"]' in src
        and 'if (cur === "machines") return machinesPage(view);' in src  # §175 器械是图鉴的大标签
    )
    assert (
        "照片会发给识别服务，认完不保存。" in src
        and "IronM 看照片说的，可能不准，以现场说明为准。" in src
    )
    assert "看图鉴里的${known.name}" in src and "图鉴里还没有" in src


def test_vision_stage_falls_back_to_expert(tmp_path: Path) -> None:
    import yaml

    from ironm_agent.llm import MODELS_PATH, load_models

    raw = yaml.safe_load(MODELS_PATH.read_text(encoding="utf-8"))
    assert load_models().route("vision").model == "deepseek-flash"
    raw["stages"].pop("vision")
    path = tmp_path / "m.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    cfg = load_models(path)
    assert cfg.route("vision") == cfg.route("expert")


def test_chat_camera_entry() -> None:
    """§152：对话输入框"+"旁边有"拍一张"，传好就发；不分认器械、算热量两个入口。"""
    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    page = src[src.index("function chatPage(view)") : src.index("function chatPage(view)") + 3000]
    assert '"拍一张：吃的、器械都能认"' in page and 'capture: "environment"' in page
    assert "await attachPick(e.currentTarget);" in page and "form.requestSubmit()" in page
    assert 'h("form", { class: "composer" }, clip, cam, input, send)' in page
    assert "return Promise.all(uploads);" in src
