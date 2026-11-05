"""饮食和训练配图（spec [2026-10-23] §119、§126、§131）：食物库里的原料和菜品、推荐食谱、减脂餐、按部位的训练照片。

图片来自 Wikimedia Commons（允许再用的许可）或 Unsplash / Pexels（免费许可，不收 Unsplash+）；清单（food_images.yaml）记着
每张图的作者、许可和来源，页面上署名。图片文件在本机数据目录（scripts/fetch_stock_images.py 下载），不进仓库；
没下载的不返回，页面用占位。
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Any

from ironm_agent.rank_images import LICENSES
from ironm_agent.yamlfile import load_yaml

MANIFEST = Path(__file__).with_name("food_images.yaml")
QUERIES = Path(__file__).with_name("food_photos.yaml")
ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = re.compile(r"^(food|recipe|preset|train)-[a-z0-9-]{1,40}\.(png|jpe?g|webp)$")
# Unsplash、Pexels 的免费许可也收（§126、§131，项目负责人同意下载）；Unsplash+ 付费图不收
STOCK_LICENSES = frozenset({"Unsplash License", "Pexels License"})
# 训练照片按部位（§131）：首页"今日委托"的大图
TRAIN_PARTS = {"腿臀": "legs", "胸": "chest", "背": "back", "肩": "shoulders", "手臂": "arms",
               "核心": "core", "全身": "fullbody", "有氧": "cardio", "休息": "rest"}  # fmt: skip


def allowed(license: str) -> bool:
    return bool(LICENSES.match(license)) or license in STOCK_LICENSES


URL = "/iron/api/food-images/"


def image_dir() -> Path:
    return Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "food-images"


@cache
def _load(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    images = data.get("images") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in (images or {}).items() if isinstance(v, dict)}


def image_for(key: str) -> dict[str, Any] | None:
    """key 是 food:<编号>、recipe:<编号>、preset:<编号>、train:<部位>；没有下载好或许可不合格的不返回。"""
    im = _load(MANIFEST).get(key)
    if im is None:
        return None
    name = str(im.get("file", ""))
    if not FILE_NAME.match(name) or not allowed(str(im.get("license", ""))):
        return None
    if not (image_dir() / name).is_file():
        return None
    return {"url": URL + name, "author": im.get("author", ""), "license": im.get("license", ""),
            "license_url": im.get("license_url", ""), "page": im.get("page", "")}  # fmt: skip


def image_path(name: str) -> Path | None:
    if not FILE_NAME.match(name):
        return None
    p = image_dir() / name
    return p if p.is_file() else None


def train_images() -> dict[str, dict[str, Any]]:
    """每个部位的训练照片（下载好了的才有）。"""
    return {part: im for part, key in TRAIN_PARTS.items() if (im := image_for(f"train:{key}"))}
