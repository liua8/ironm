"""动作库：内容齐全、分类合法；接口按登录返回。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.exercises import EQUIPMENT, PARTS, library


def test_every_exercise_is_complete() -> None:
    lib = library()
    assert len(lib.exercises) >= 30 and lib.review == "claude_draft"
    for x in lib.exercises:
        assert len(x.steps) >= 3 and len(x.cues) >= 2 and x.mistakes and x.avoid, x.id
        assert x.easier and x.harder, x.id
    assert {x.part for x in lib.exercises} == set(PARTS)  # 每个部位都有动作
    assert {e for x in lib.exercises for e in x.equipment} == set(EQUIPMENT)


def test_api_lists_the_library() -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    data = TestClient(app).get("/iron/api/exercises").json()
    assert data["parts"][0] == "腿臀" and "哑铃" in data["equipment"]
    squat = next(x for x in data["exercises"] if x["id"] == "goblet-squat")
    assert squat["name"] == "高脚杯深蹲" and squat["equipment"] == ["哑铃", "壶铃"]
