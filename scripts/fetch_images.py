"""按仓库里的配图清单把图下到本机数据目录（spec [2026-10-23] §177：在自己电脑上跑）。

用法：.venv/bin/python scripts/fetch_images.py
- 读 ironm_agent/ 下四份清单（动作 wger、动作 Everkinetic、训练和饮食照片、排行榜），每张记着
  作者、许可、来源；只下本机还没有的，清单一个字也不改（重新挑图、写清单用各自的 fetch_*_images.py）。
- wger 清单记的是原图（有的好几 MB），下来后缩到最长边约 400 像素，和当初取的中等缩略图一样大；
  文件扩展名和清单对不上时（比如原图是 webp、清单写 jpg）按清单的格式另存。
- 下不到的跳过、最后列个数，不让启动失败；不连别的网站，不带个人信息。
"""

from __future__ import annotations

import io
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
UA = "iron-m/0.1 (self-hosted fitness app; image list download)"
LISTS = (  # 清单 → 数据目录下的子目录
    ("exercise_images.yaml", "exercise-images"),
    ("exercise_images_everkinetic.yaml", "exercise-images"),
    ("food_images.yaml", "food-images"),
    ("rank_images.yaml", "rank-images"),
)
SHRINK = {"wger.de": 400}  # 这些来源的原图缩到最长边多少像素
WORKERS = 8  # 同时下几张
TOTAL_S = 90  # 一张最多等几秒
MAX_BYTES = 20 * 1024 * 1024
FORMATS = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".gif": "GIF"}


def entries(name: str) -> list[dict[str, Any]]:
    images = (yaml.safe_load((ROOT / "ironm_agent" / name).read_text(encoding="utf-8")) or {}).get(
        "images"
    ) or {}
    out: list[dict[str, Any]] = []
    for v in images.values():
        out.extend(v if isinstance(v, list) else [v])
    return [x for x in out if x.get("file") and x.get("source")]


def get(url: str) -> bytes:
    """一张最多等 TOTAL_S 秒、最大 MAX_BYTES：慢得一点一点传的直接放弃，不让启动卡住。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    deadline = time.monotonic() + TOTAL_S
    chunks: list[bytes] = []
    size = 0
    with urllib.request.urlopen(req, timeout=30) as r:
        while chunk := r.read(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES or time.monotonic() > deadline:
                raise TimeoutError("太大或太慢")
    return b"".join(chunks)


def encode(raw: bytes, suffix: str, host: str) -> bytes:
    """原样用；要缩小或格式和扩展名对不上时用 PIL 转。"""
    want = FORMATS.get(suffix.lower())
    img: Image.Image = Image.open(io.BytesIO(raw))
    size = SHRINK.get(host)
    if want is None or (img.format == want and not (size and max(img.size) > size)):
        return raw
    if size and max(img.size) > size:
        img.thumbnail((size, size))
    if want == "JPEG" and img.mode not in ("RGB", "L"):
        bg = Image.new("RGB", img.size, "white")  # 透明底铺白
        bg.paste(img, mask=img.convert("RGBA").split()[-1])
        img = bg
    buf = io.BytesIO()
    img.save(buf, want, **({"quality": 85} if want == "JPEG" else {}))
    return buf.getvalue()


def fetch_one(x: dict[str, Any], path: Path) -> str | None:
    """下一张；成功返回 None，失败返回写给人看的一句。"""
    try:
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(encode(get(x["source"]), path.suffix, x["source"].split("/")[2]))
        tmp.replace(path)
        return None
    except Exception as e:  # 一张下不到不影响别的
        return f"{x['file']}（{type(e).__name__}）"


def main() -> int:
    base = Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data")
    have = 0
    todo: list[tuple[dict[str, Any], Path]] = []
    for name, sub in LISTS:
        out = base / sub
        out.mkdir(parents=True, exist_ok=True)
        for x in entries(name):
            path = out / Path(x["file"]).name
            if path.exists() and path.stat().st_size > 0:
                have += 1
            else:
                todo.append((x, path))
    print(f"  要下 {len(todo)} 张（本来就有 {have} 张）", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda t: fetch_one(*t), todo))
    failed = [r for r in results if r]
    got = len(todo) - len(failed)
    print(f"配图：新下 {got} 张，本来就有 {have} 张，没下到 {len(failed)} 张")
    for f in failed[:10]:
        print(f"  没下到：{f}")
    if len(failed) > 10:
        print(f"  ……还有 {len(failed) - 10} 张；以后再跑一次 scripts/fetch_images.py 会补")
    return 0


if __name__ == "__main__":
    sys.exit(main())
