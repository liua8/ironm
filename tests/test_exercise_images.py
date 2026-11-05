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
    monkeypatch.setattr(exercise_images, "EVERKINETIC", tmp_path / "none.yaml")
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
    assert len(lib) >= 101 and "拉伸放松" in PARTS and "泡沫轴" in EQUIPMENT
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


# ---- §144 起止两张合成动图 -------------------------------------------------------------------


def _script():
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "make_exercise_gifs.py"
    spec = importlib.util.spec_from_file_location("make_exercise_gifs", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _png(path: Path, size: tuple[int, int], box: tuple[int, int, int, int] | None) -> Path:
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", size, (0, 0, 0, 0))  # 透明底
    if box:
        ImageDraw.Draw(im).rectangle(box, fill="black")
    im.save(path)
    return path


def test_gif_only_for_real_start_end_frames(tmp_path: Path) -> None:
    from PIL import Image

    mod = _script()
    a = _png(tmp_path / "a.png", (80, 80), (5, 5, 30, 30))
    b = _png(tmp_path / "b.png", (80, 80), (45, 45, 75, 75))
    out = tmp_path / "x-0.gif"
    assert mod.make_gif(a, b, out)
    gif = Image.open(out)
    assert gif.n_frames == 2 and gif.info["duration"] == mod.FRAME_MS and gif.info["loop"] == 0
    assert gif.convert("RGB").getpixel((60, 10)) == (255, 255, 255)  # 透明底铺成白的，不是黑的
    same = _png(tmp_path / "d.png", (80, 80), (5, 5, 30, 30))
    assert not mod.make_gif(a, same, tmp_path / "z-0.gif")  # 同一个姿势：不做动图
    shifted = _png(
        tmp_path / "e.png", (120, 100), (45, 25, 70, 50)
    )  # 裁边不同：画面一样，只是挪了位置
    assert not mod.make_gif(a, shifted, tmp_path / "w-0.gif")  # 对齐后是同一个姿势
    dx, dy, overlap = mod.align(mod.flat(a), mod.flat(shifted))
    assert (dx, dy) == (-40, -20) and overlap > 0.9


def test_gif_for_credits_original_author(images: Path) -> None:
    folder = images / "exercise-images"
    assert exercise_images.gif_for("goblet-squat") is None  # 还没合成
    (folder / "goblet-squat-0.gif").write_bytes(b"GIF89a fake")
    got = exercise_images.gif_for("goblet-squat")
    assert got and got["url"] == "/iron/api/exercise-images/goblet-squat-0.gif"
    assert (
        got["author"] == "philip"
        and got["license"] == "CC-BY-SA 4"
        and got["made"] == "由两张图合成"
    )
    (folder / "plank-0.gif").write_bytes(b"GIF89a fake")
    assert exercise_images.gif_for("plank") is None  # 清单里没有起止两张：不认


def test_library_endpoint_carries_gif(images: Path) -> None:
    from ironm_agent import web

    (images / "exercise-images" / "goblet-squat-0.gif").write_bytes(b"GIF89a fake")
    app = FastAPI()
    app.include_router(web.router)
    c = TestClient(app)
    assert c.get("/iron/api/exercise-images/goblet-squat-0.gif").status_code == 200
    from mirobody.server.auth import verify_token

    app.dependency_overrides[verify_token] = lambda: "42"
    moves = {x["id"]: x for x in c.get("/iron/api/exercises").json()["exercises"]}
    assert moves["goblet-squat"]["gif"]["made"] == "由两张图合成" and moves["plank"]["gif"] is None
    src = (Path(web.__file__).parent / "web" / "app.js").read_text(encoding="utf-8")
    assert "x.gif ? moveImages([x.gif])" in src and "im.made" in src  # 详情先放动图、注明合成


def test_common_moves_third_batch() -> None:
    """§144：常见动作约 100 个；补进来的健身房常见动作字段写全、体感提示和标注都有，有氧按时长记。"""
    from ironm_agent.exercises import feel_cues
    from ironm_agent.live import new_item

    lib = {x.id: x for x in library().exercises}
    common = [x for x in lib.values() if x.common]
    assert 95 <= len(common) <= 105
    assert (
        not lib["towel-door-row"].common and not lib["towel-curl"].common
    )  # 在家替代用的冷门动作留着、不算常见
    added = ["treadmill-run", "elliptical", "rowing-machine", "jump-rope", "jumping-jack", "mountain-climber",
             "hanging-leg-raise", "smith-squat", "seated-leg-curl", "t-bar-row", "reverse-pec-deck",
             "sumo-squat", "assisted-pull-up", "triceps-kickback"]  # fmt: skip
    tags = {m.exercise.id: m.tag for m in moves()}
    feel = feel_cues()
    for i in added:
        assert lib[i].common and i in tags and 1 <= len(feel[i]) <= 3
    for i in ["treadmill-run", "elliptical", "rowing-machine", "jump-rope"]:
        assert lib[i].part == "有氧" and tags[i].pattern == "cardio"
        assert new_item(lib[i].name, None, [], {}).cardio  # 训练里只记时长（§130）
    assert lib["mountain-climber"].timed


def test_everkinetic_images_take_over(
    images: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§144：Everkinetic 清单里有的动作用它的图，署名写 Everkinetic；没有的照旧用 wger。"""
    ek = tmp_path / "ek.yaml"
    ek.write_text(
        'images:\n  goblet-squat:\n    - {"file": "goblet-squat-ek-1.png", "page": "https://github.com/everkinetic/data",'
        ' "site": "Everkinetic", "license": "CC-BY-SA 4", "license_url": "u", "author": "Everkinetic", "author_url": ""}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(exercise_images, "EVERKINETIC", ek)
    (images / "exercise-images" / "goblet-squat-ek-1.png").write_bytes(b"\x89PNG fake")
    got = exercise_images.images_for("goblet-squat")
    assert [x["url"] for x in got] == ["/iron/api/exercise-images/goblet-squat-ek-1.png"]
    assert got[0]["site"] == "Everkinetic" and got[0]["author"] == "Everkinetic"
    monkeypatch.setattr(exercise_images, "EVERKINETIC", tmp_path / "none.yaml")
    assert exercise_images.images_for("goblet-squat")[0]["site"] == "wger"
