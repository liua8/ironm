"""动作配图与动作库扩充（spec [2026-10-23] §32）：只返回已下载的图并带署名；图片地址出不了数据目录；
拉伸放松不计训练组数。不连网络、不连数据库。"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import exercise_images
from ironm_agent.exercises import EQUIPMENT, PARTS, library
from ironm_agent.protools.movement import moves

MANIFEST = """images:
  goblet-squat:
    - {"file": "goblet-squat-1.png", "source": "x", "page": "https://wger.de/exercise/203/view/", "license": "CC-BY-SA 4", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/", "author": "philip", "author_url": ""}
    - {"file": "goblet-squat-2.png", "source": "x", "page": "p", "license": "CC-BY-SA 4", "license_url": "u", "author": "philip", "author_url": ""}
  push-up:
    - {"file": "../../etc/passwd", "source": "x", "page": "p", "license": "l", "license_url": "u", "author": "a", "author_url": ""}
"""


@pytest.fixture
def images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "exercise_images.yaml"
    path.write_text(MANIFEST, encoding="utf-8")
    data = tmp_path / "data"
    (data / "exercise-images").mkdir(parents=True)
    (data / "exercise-images" / "goblet-squat-1.png").write_bytes(b"\x89PNG fake")
    monkeypatch.setenv("IRONM_DATA_DIR", str(data))
    monkeypatch.setattr(exercise_images, "MANIFEST", path)
    return data


def test_only_downloaded_images_with_credit(images: Path) -> None:
    got = exercise_images.images_for("goblet-squat")
    assert len(got) == 1  # 第二张没下载：不返回
    assert got[0]["url"] == "/iron/api/exercise-images/goblet-squat-1.png"
    assert (
        got[0]["author"] == "philip"
        and got[0]["license"] == "CC-BY-SA 4"
        and "wger.de" in got[0]["page"]
    )
    assert exercise_images.images_for("push-up") == []  # 清单里的文件名不合规：不返回
    assert exercise_images.images_for("plank") == []


def test_image_endpoint_stays_inside_data_dir(images: Path) -> None:
    from ironm_agent import web

    app = FastAPI()
    app.include_router(web.router)
    c = TestClient(app)
    ok = c.get("/iron/api/exercise-images/goblet-squat-1.png")
    assert ok.status_code == 200 and ok.content.startswith(b"\x89PNG")
    assert c.get("/iron/api/exercise-images/goblet-squat-2.png").status_code == 404
    assert c.get("/iron/api/exercise-images/..%2F..%2Fsecret.png").status_code == 404
    assert c.get("/iron/api/exercise-images/notes.txt").status_code == 404


def test_library_second_batch() -> None:
    lib = library().exercises
    assert len(lib) == 101 and "拉伸放松" in PARTS and "泡沫轴" in EQUIPMENT
    assert lib[0].id == "bodyweight-squat"  # 原有动作的顺序（依据编号 K901 起）不变
    stretch = [m for m in moves() if m.tag.pattern == "stretch"]
    assert len(stretch) == 8 and all(m.exercise.part == "拉伸放松" for m in stretch)
    assert all(not m.tag.muscles and not m.tag.assist for m in stretch)  # 不计组数、不算恢复


def test_stretching_does_not_count_as_training_volume() -> None:
    from ironm_agent.protools.plan_check import check_plan
    from ironm_agent.training import Plan

    plan = Plan.model_validate({"title": "x", "days_per_week": 2, "sessions": [
        {"day": 1, "name": "A", "items": [{"exercise": "杠铃深蹲", "sets": 4, "reps": "8"},
                                          {"exercise": "跪姿髋屈肌拉伸", "sets": 2, "reps": "30 秒"}]},
        {"day": 4, "name": "B", "items": [{"exercise": "杠铃深蹲", "sets": 4, "reps": "8"},
                                          {"exercise": "仰卧抱膝", "sets": 2, "reps": "30 秒"}]}]})  # fmt: skip
    text = " ".join(check_plan(plan).problems)
    assert "拉伸" not in text
