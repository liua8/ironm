"""打卡照片（spec [2026-10-23] §117）：挂在那次打卡记录上、在轨迹里看；加密存、只有本人能取。

原定的体态记录并进轨迹，不单独做。不连数据库、不调用模型。
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ironm_agent.checkin_photo import PhotoBook
from ironm_agent.training import LogItem, WorkoutLog
from tests.test_live import client as live_client

JPG = b"\xff\xd8\xff" + b"0" * 100
WEB = Path(__file__).resolve().parents[1] / "ironm_agent"
JS = (WEB / "web" / "app.js").read_text()


def client(
    monkeypatch: pytest.MonkeyPatch, user: str = "42", photos: PhotoBook | None = None
) -> tuple[TestClient, PhotoBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web_more

    c, _, _ = live_client(
        monkeypatch, logs=(WorkoutLog(day=date.today(), items=[LogItem(exercise="深蹲")]),)
    )
    photos = photos or PhotoBook()
    c.app.dependency_overrides[web_more.photo_store] = lambda: photos  # type: ignore[attr-defined]
    c.app.dependency_overrides[verify_token] = lambda: user  # type: ignore[attr-defined]
    return c, photos


def jpg(mime: str = "image/jpeg", data: bytes = JPG) -> dict[str, Any]:
    return {"photo": ("a.jpg", data, mime)}


def test_one_photo_per_checkin_and_bad_files_are_refused(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    c, photos = client(monkeypatch)
    wid = c.get("/iron/api/training").json()["workouts"][0]["id"]
    url = f"/iron/api/workouts/{wid}/photo"
    assert c.get("/iron/api/training").json()["workouts"][0]["photo"] is False
    assert c.post(url).status_code == 422
    assert c.post(url, files=jpg("image/gif")).status_code == 415
    assert c.post(url, files=jpg(data=b"0" * (5 * 1024 * 1024 + 1))).status_code == 413
    with caplog.at_level(logging.INFO, logger="ironm_agent.checkin_photo"):
        assert c.post(url, files=jpg()).status_code == 200
    assert "checkin photo added" in caplog.text
    assert c.post(url, files=jpg(data=JPG + b"2")).status_code == 200  # 再传一张就换掉
    got = c.get(url)
    assert got.content == JPG + b"2" and got.headers["content-type"] == "image/jpeg"
    assert len(photos.rows) == 1
    assert c.get("/iron/api/training").json()["workouts"][0]["photo"] is True


def test_only_the_owner_and_photo_goes_with_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    c, photos = client(monkeypatch)
    wid = c.get("/iron/api/training").json()["workouts"][0]["id"]
    url = f"/iron/api/workouts/{wid}/photo"
    c.post(url, files=jpg())
    other, _ = client(monkeypatch, user="7", photos=photos)
    assert other.get(url).status_code == 404  # 别人取不到
    assert other.post(url, files=jpg()).status_code == 404  # 也不能给别人的记录挂照片
    assert c.post("/iron/api/workouts/nope/photo", files=jpg()).status_code == 404
    assert c.delete(f"/iron/api/workouts/{wid}").status_code == 200
    assert not photos.rows and c.get(url).status_code == 404  # 删打卡记录，照片一起删


def test_no_separate_posture_record(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client(monkeypatch)
    assert c.get("/iron/api/posture").status_code == 404
    assert not (WEB / "posture.py").exists()
    for gone in ("记体态", "postureCard", "体态记录"):
        assert gone not in JS, gone
    assert "打卡照片" in JS and "checkinThumb" in JS and "st.attach(r.workout?.id)" in JS
