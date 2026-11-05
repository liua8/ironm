"""照片（spec [2026-10-23] §126、§131）：收 Unsplash、Pexels 的免费许可；训练照片按部位。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ironm_agent import food_images
from ironm_agent.food_images import allowed, image_for, train_images

MANIFEST = food_images._load(food_images.MANIFEST)


def test_licenses() -> None:
    assert allowed("Unsplash License") and allowed("Pexels License") and allowed("CC BY-SA 4.0")
    assert not allowed("Unsplash+") and not allowed("CC BY-NC 4.0") and not allowed("")


def test_manifest_has_credit_for_every_photo() -> None:
    assert len(MANIFEST) >= 65
    for key, im in MANIFEST.items():
        assert im["author"] and im["page"].startswith("https://") and allowed(im["license"]), key
        assert food_images.FILE_NAME.match(im["file"]), key


def test_train_photo_by_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRONM_DATA_DIR", str(tmp_path))
    (tmp_path / "food-images").mkdir()
    assert image_for("train:legs") is None  # 没下载就不给
    (tmp_path / "food-images" / "train-legs.jpg").write_bytes(b"\xff\xd8x")
    im = image_for("train:legs")
    assert (
        im
        and im["url"] == "/iron/api/food-images/train-legs.jpg"
        and im["license"] == "Unsplash License"
    )
    assert set(train_images()) == {"腿臀"}
