"""从 Wikimedia Commons 取饮食配图（spec [2026-10-23] §119），下载到本机数据目录，并写图片清单。

用法：
    .venv/bin/python scripts/fetch_food_images.py            # 找图并下载
    .venv/bin/python scripts/fetch_food_images.py --dry-run  # 只列出找到的图，不下载、不写清单
- 检索词写在 ironm_agent/food_photos.yaml；每条取第一张许可合格的位图（找法和排行榜配图同一个函数）。
  第一张不合适时，检索词直接写 Commons 上的文件名（File:…），只取这一张。
- 图片下载到 $IRONM_DATA_DIR/food-images/（默认 data/，不进仓库）；清单写进 ironm_agent/food_images.yaml（进仓库）。
- 已经在清单里、文件也在的不重找；要换图就把清单里那一条删掉再跑。
"""

from __future__ import annotations

import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402
from fetch_rank_images import _get, find  # noqa: E402

from ironm_agent.food_images import MANIFEST, QUERIES, image_dir  # noqa: E402


def polite(call: Any, *args: Any) -> Any:
    """Commons 限流（429）时等一会儿再试，最多 5 次。"""
    for wait in (10, 30, 60, 120, 240):
        try:
            return call(*args)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            print(f"被限流，等 {wait} 秒")
            time.sleep(wait)
    return call(*args)


def main(dry: bool) -> None:
    queries = yaml.safe_load(QUERIES.read_text())["queries"]
    old = (
        (yaml.safe_load(MANIFEST.read_text()) or {}).get("images", {}) if MANIFEST.exists() else {}
    )
    out: dict[str, dict[str, str]] = {}
    folder = image_dir()
    folder.mkdir(parents=True, exist_ok=True)
    total = 0
    for key, query in queries.items():
        if not query:  # 挑过、没有合适的图：页面用色块
            continue
        have = old.get(key)
        if have and (folder / have["file"]).is_file():
            out[key] = have
            continue
        got = polite(find, query)
        time.sleep(2)
        if got is None:
            print(f"没找到：{key}（{query}）")
            continue
        kind, ident = key.split(":", 1)
        name = f"{kind}-{ident}.{got['ext']}"
        print(f"{key} → {got['title']}（{got['license']}，{got['author']}）")
        if dry:
            continue
        data = polite(_get, got["thumb"])
        total += len(data)
        (folder / name).write_bytes(data)
        out[key] = {"file": name, "query": query, "source": got["thumb"], "page": got["page"],
                    "license": got["license"], "license_url": got["license_url"],
                    "author": got["author"]}  # fmt: skip
    if dry:
        return
    head = (
        "# 饮食配图清单（spec [2026-10-23] §119），由 scripts/fetch_food_images.py 生成，不要手改。\n"
        "# 图片来自 Wikimedia Commons，每张写明作者、许可和来源；食谱页和饮食记录里署名。图片文件在本机数据目录，不进仓库。\n"
    )
    body = yaml.safe_dump({"images": out}, allow_unicode=True, sort_keys=False, width=200)
    MANIFEST.write_text(head + body, encoding="utf-8")
    print(f"清单写了 {len(out)} 条，这次下载 {total / 1024:.0f} KB：{MANIFEST}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
