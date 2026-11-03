"""饮食配图（spec [2026-10-23] §119）：食物库里的原料和菜品、推荐食谱、减脂餐。

和排行榜配图同一个做法（§80）：图片来自 Wikimedia Commons，只收允许再用的许可；清单（food_images.yaml）记着
每张图的作者、许可和来源，食谱页和饮食记录里署名。图片文件在本机数据目录（scripts/fetch_food_images.py 下载），
没下载的不返回，页面用"分类颜色色块 + 名字首字"。
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
FILE_NAME = re.compile(r"^(food|recipe|preset)-[a-z0-9-]{1,40}\.(png|jpe?g|webp)$")
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
    """key 是 food:<编号>、recipe:<编号>、preset:<编号>；没有下载好或许可不合格的不返回。"""
    im = _load(MANIFEST).get(key)
    if im is None:
        return None
    name = str(im.get("file", ""))
    if not FILE_NAME.match(name) or not LICENSES.match(str(im.get("license", ""))):
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
