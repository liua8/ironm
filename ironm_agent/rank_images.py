"""排行榜起步条目的配图（spec [2026-10-23] §80）：健身餐、补剂、蛋白粉、器材。

图片来自 Wikimedia Commons，只收允许再用的许可（CC0、CC BY、CC BY-SA、公有领域）；清单（rank_images.yaml）
记着每张图的作者、许可和来源，条目页署名。图片文件在本机数据目录（scripts/fetch_rank_images.py 下载），
没下载的不返回，页面就用榜的图标。动作和训练计划用动作库的配图（exercise_images）。
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Any

from ironm_agent.yamlfile import load_yaml

MANIFEST = Path(__file__).with_name("rank_images.yaml")
ROOT = Path(__file__).resolve().parents[1]
FILE_NAME = re.compile(r"^[a-z]+-\d{2}\.(png|jpe?g|webp)$")
URL = "/iron/api/rank-images/"
# 允许再用的许可（Commons 的 LicenseShortName）
LICENSES = re.compile(
    r"^(CC0( 1\.0)?|Public domain|PD[\w-]*|CC BY(-SA)? [1-4]\.0( [a-z]{2})?)$", re.I
)


def image_dir() -> Path:
    return Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "rank-images"


@cache
def _load(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    images = data.get("images") if isinstance(data, dict) else None
    return {str(k): dict(v) for k, v in (images or {}).items() if isinstance(v, dict)}


def manifest() -> dict[str, dict[str, str]]:
    return _load(MANIFEST)


def image_for(key: str) -> dict[str, Any] | None:
    """这个条目已经下载好的配图：地址、作者、许可、来源。许可不在允许的范围里的不返回。"""
    im = manifest().get(key)
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
