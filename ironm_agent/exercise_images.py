"""动作配图（spec [2026-10-23] §32）：读图片清单，给动作库接口带上配图和署名。

图片来自 wger 和 Everkinetic 开源动作库（§144），许可都是 CC BY-SA；清单（exercise_images.yaml、
exercise_images_everkinetic.yaml，后者有的动作用后者的）记着每张图的作者、许可和来源，页面上署名。
图片文件在本机数据目录（scripts/fetch_exercise_images.py 下载），没下载的不返回，页面就用部位色块。
有起止两张图的动作合成一张来回切换的动图（scripts/make_exercise_gifs.py，§144），同许可、署原图作者。
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Any

from ironm_agent.yamlfile import load_yaml

MANIFEST = Path(__file__).with_name("exercise_images.yaml")
EVERKINETIC = Path(__file__).with_name("exercise_images_everkinetic.yaml")
ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = re.compile(r"^[a-z0-9-]+-\d\.(png|jpe?g|gif|webp)$")
URL = "/iron/api/exercise-images/"


def image_dir() -> Path:
    return Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "exercise-images"


@cache
def _load(path: Path) -> dict[str, tuple[dict[str, str], ...]]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    images = data.get("images") if isinstance(data, dict) else None
    return {str(k): tuple(v) for k, v in (images or {}).items()}


def manifest() -> dict[str, tuple[dict[str, str], ...]]:
    return {**_load(MANIFEST), **_load(EVERKINETIC)}


def images_for(exercise_id: str) -> list[dict[str, Any]]:
    """这个动作已经下载好的配图：地址、作者、许可、来源。"""
    out = []
    for im in manifest().get(exercise_id, ()):
        name = str(im.get("file", ""))
        if not FILE_NAME.match(name) or not (image_dir() / name).is_file():
            continue
        out.append({"url": URL + name, "author": im.get("author", ""), "author_url": im.get("author_url", ""),
                    "license": im.get("license", ""), "license_url": im.get("license_url", ""),
                    "page": im.get("page", ""), "site": im.get("site", "wger")})  # fmt: skip
    return out


def gif_for(exercise_id: str) -> dict[str, Any] | None:
    """这个动作合成好的动图（§144）：由清单里前两张图合成，署名照原图；没合成的返回 None。"""
    frames = manifest().get(exercise_id, ())
    name = f"{exercise_id}-0.gif"
    if len(frames) < 2 or not FILE_NAME.match(name) or not (image_dir() / name).is_file():
        return None
    im = frames[0]
    return {"url": URL + name, "author": im.get("author", ""), "author_url": im.get("author_url", ""),
            "license": im.get("license", ""), "license_url": im.get("license_url", ""),
            "page": im.get("page", ""), "site": im.get("site", "wger"), "made": "由两张图合成"}  # fmt: skip


def image_path(name: str) -> Path | None:
    if not FILE_NAME.match(name):
        return None
    p = image_dir() / name
    return p if p.is_file() else None
