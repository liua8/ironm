"""从 Wikimedia Commons 取排行榜起步条目的配图（spec [2026-10-23] §80），下载到本机数据目录，并写图片清单。

用法：
    .venv/bin/python scripts/fetch_rank_images.py            # 找图并下载
    .venv/bin/python scripts/fetch_rank_images.py --dry-run  # 只列出找到的图，不下载、不写清单
- 检索词写在 rank_seed.yaml 每个条目的 photo 里；每个条目取第一张许可合格的位图。第一张不合适（露出品牌、
  内容不对）时，photo 直接写 Commons 上的文件名（File:…），只取这一张。
- 只收 CC0、CC BY、CC BY-SA、公有领域（和 ironm_agent/rank_images.py 的 LICENSES 一致）；作者、许可、来源写进清单，
  条目页署名。
- 图片下载到 $IRONM_DATA_DIR/rank-images/（默认 data/，不进仓库）；清单写进 ironm_agent/rank_images.yaml（进仓库）。
- 已经在清单里、文件也在的条目不重找；要换图就把清单里那一条删掉再跑。
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from ironm_agent.rank_images import LICENSES, MANIFEST, image_dir  # noqa: E402
from ironm_agent.tier import custom_key  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
UA = "IronM/0.1 (fitness app; rank board images; https://github.com/)"
WIDTH = 320
MIMES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
BOARDS = ("meal", "supplement", "protein", "gear")


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data: bytes = r.read()
        return data


def _text(html: str) -> str:
    text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
    return re.split(r"\s*(?:Credit information|\(\s*talk\s*\))", text)[0].strip()[:60]


def find(query: str) -> dict[str, str] | None:
    """Commons 上这个检索词的第一张许可合格的位图；query 是 File:… 时只看这一张。"""
    params = {
        "action": "query", "format": "json", "prop": "imageinfo",
        "iiprop": "url|extmetadata|mime", "iiurlwidth": str(WIDTH),
    }  # fmt: skip
    if query.startswith("File:"):
        params["titles"] = query
    else:
        params |= {"generator": "search", "gsrnamespace": "6",
                   "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": "10"}  # fmt: skip
    data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
    pages = sorted(
        (data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99)
    )
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = str((meta.get("LicenseShortName") or {}).get("value", "")).strip()
        if info.get("mime") not in MIMES or not LICENSES.match(lic) or not info.get("thumburl"):
            continue
        return {
            "thumb": info["thumburl"], "ext": MIMES[info["mime"]], "license": lic,
            "license_url": str((meta.get("LicenseUrl") or {}).get("value", "")),
            "author": _text(str((meta.get("Artist") or {}).get("value", ""))) or "Wikimedia Commons",
            "page": info.get("descriptionurl", ""), "title": page.get("title", ""),
        }  # fmt: skip
    return None


def main(dry: bool) -> None:
    seeds = yaml.safe_load((ROOT / "ironm_agent" / "rank_seed.yaml").read_text())
    old = (
        (yaml.safe_load(MANIFEST.read_text()) or {}).get("images", {}) if MANIFEST.exists() else {}
    )
    out: dict[str, dict[str, str]] = {}
    folder = image_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for board in BOARDS:
        for i, x in enumerate(seeds.get(board) or [], start=1):
            key = custom_key(x["name"])
            have = old.get(key)
            if have and (folder / have["file"]).is_file():
                out[key] = have
                continue
            got = find(x.get("photo") or x["name"])
            time.sleep(0.5)
            if got is None:
                print(f"没找到：{x['name']}（{x.get('photo')}）")
                continue
            name = f"{board}-{i:02d}.{got['ext']}"
            print(f"{x['name']} → {got['title']}（{got['license']}，{got['author']}）")
            if dry:
                continue
            (folder / name).write_bytes(_get(got["thumb"]))
            out[key] = {"file": name, "name": x["name"], "source": got["thumb"], "page": got["page"],
                        "license": got["license"], "license_url": got["license_url"],
                        "author": got["author"]}  # fmt: skip
    if dry:
        return
    head = (
        "# 排行榜起步条目的配图清单（spec [2026-10-23] §80），由 scripts/fetch_rank_images.py 生成，不要手改。\n"
        "# 图片来自 Wikimedia Commons，每张写明作者、许可和来源；条目页署名。图片文件在本机数据目录，不进仓库。\n"
    )
    body = yaml.safe_dump({"images": out}, allow_unicode=True, sort_keys=False, width=200)
    MANIFEST.write_text(head + body, encoding="utf-8")
    print(f"清单写了 {len(out)} 条：{MANIFEST}")


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
