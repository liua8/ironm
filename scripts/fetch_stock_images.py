"""下载训练和饮食的照片（spec [2026-10-23] §126、§131）：Unsplash / Pexels 免费许可，清单在 ironm_agent/stock_photos.yaml。

用法：
    .venv/bin/python scripts/fetch_stock_images.py            # 下载并写清单
    .venv/bin/python scripts/fetch_stock_images.py --dry-run  # 只列出要下的，不下载
- 图片下到 $IRONM_DATA_DIR/food-images/（默认 data/，不进仓库），文件名是 <种类>-<编号>.jpg（train-legs.jpg、recipe-xxx.jpg）。
- 清单写进 ironm_agent/food_images.yaml（进仓库），记作者、许可、来源页，页面署名用。
- 已经下好的不重下；要换图就改 stock_photos.yaml 里那一条，删掉清单里那一条和文件再跑。
"""

from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from ironm_agent.food_images import MANIFEST, image_dir  # noqa: E402

PHOTOS = ROOT / "ironm_agent" / "stock_photos.yaml"
LICENSE_URL = {
    "Unsplash License": "https://unsplash.com/license",
    "Pexels License": "https://www.pexels.com/license/",
}
UA = "IronM/1.0 (+https://github.com/; one-time download of free-licensed photos)"


def sized(url: str) -> str:
    """手机上看够用的尺寸：宽 1080，压缩过的 jpg。"""
    if "images.unsplash.com" in url:
        return url.split("?")[0] + "?w=1080&q=78&fm=jpg&fit=crop"
    return url.split("?")[0] + "?auto=compress&cs=tinysrgb&w=1080"


def main(dry: bool) -> None:
    photos = yaml.safe_load(PHOTOS.read_text())["photos"]
    old = (
        (yaml.safe_load(MANIFEST.read_text()) or {}).get("images", {}) if MANIFEST.exists() else {}
    )
    folder = image_dir()
    folder.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, str]] = {}
    total = 0
    for key, p in photos.items():
        if p["license"] not in LICENSE_URL:
            print(f"跳过（许可不在清单里）：{key} {p['license']}")
            continue
        kind, ident = key.split(":", 1)
        name = f"{kind}-{ident}.jpg"
        entry = {"file": name, "source": sized(p["url"]), "page": p["page"], "license": p["license"],
                 "license_url": LICENSE_URL[p["license"]], "author": p["author"]}  # fmt: skip
        if key in old and (folder / name).is_file():
            out[key] = entry
            continue
        print(f"{key} → {p['page']}（{p['license']}，{p['author']}）")
        if dry:
            continue
        req = urllib.request.Request(entry["source"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        if not data.startswith(b"\xff\xd8"):
            print(f"不是 jpg，跳过：{key}")
            continue
        (folder / name).write_bytes(data)
        total += len(data)
        out[key] = entry
        time.sleep(0.5)
    if dry:
        return
    head = (
        "# 照片清单（spec [2026-10-23] §119、§126、§131），由 scripts/fetch_stock_images.py 生成，不要手改。\n"
        "# 照片来自 Unsplash / Pexels（免费许可），每张写明作者、许可和来源；页面上署名。图片文件在本机数据目录，不进仓库。\n"
    )
    body = yaml.safe_dump({"images": out}, allow_unicode=True, sort_keys=False, width=200)
    MANIFEST.write_text(head + body, encoding="utf-8")
    print(f"清单写了 {len(out)} 条，这次下载 {total / 1024 / 1024:.1f} MB：{MANIFEST}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
