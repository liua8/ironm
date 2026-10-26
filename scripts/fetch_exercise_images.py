"""从 wger 取动作配图（spec [2026-10-23] §32），下载到本机数据目录，并写图片清单。

用法：.venv/bin/python scripts/fetch_exercise_images.py
- 动作和 wger 动作编号的对应写在 WGER 里；只取许可写明的图（wger 的图是 CC BY-SA 3.0 / 4.0），
  不取 AI 生成的，每个动作最多 2 张，主图在前；下载 wger 提供的中等缩略图。
- 图片下载到 $IRONM_DATA_DIR/exercise-images/（默认 data/，不进仓库）；
  清单写进 ironm_agent/exercise_images.yaml（进仓库：作者、许可、来源，页面上要署名）。
- free-exercise-db 的图片来源不明（维护者说不知道图从哪来），不用。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://wger.de/api/v2"
MAX_PER_EXERCISE = 2
WGER: dict[str, int] = {
    # 第一批
    "goblet-squat": 203, "back-squat": 1801, "romanian-deadlift": 1652, "deadlift": 184,
    "bulgarian-split-squat": 1706, "reverse-lunge": 999, "glute-bridge": 265, "calf-raise": 622,
    "leg-press": 371, "push-up": 1551, "dumbbell-bench-press": 75, "bench-press": 73, "one-arm-row": 81,
    "pull-up": 475, "lat-pulldown": 158, "dumbbell-shoulder-press": 567, "lateral-raise": 348,
    "band-face-pull": 1732, "dumbbell-curl": 92, "bench-dip": 197, "plank": 458, "bird-dog": 1572,
    "kettlebell-swing": 960, "cycling": 1618, "brisk-walk": 1615,
    # 第二批（§32）
    "front-squat": 257, "walking-lunge": 206, "hip-thrust": 1642, "sumo-deadlift": 1612,
    "single-leg-rdl": 1736, "leg-extension": 369, "lying-leg-curl": 365, "seated-calf-raise": 1620,
    "good-morning": 1392, "hack-squat": 375, "side-lunge": 1653, "hip-abduction": 1748,
    "pistol-squat": 456, "band-kickback": 1613, "incline-dumbbell-press": 537, "incline-bench-press": 538,
    "dumbbell-fly": 238, "cable-crossover": 323, "machine-chest-press": 129, "pec-deck": 135,
    "decline-push-up": 1112, "dumbbell-floor-press": 1084, "parallel-dip": 194, "barbell-row": 83,
    "seated-cable-row": 1117, "inverted-row": 1198, "chin-up": 152, "straight-arm-pulldown": 1726,
    "chest-supported-row": 1283, "back-extension": 301, "dumbbell-shrug": 572, "overhead-press": 566,
    "machine-shoulder-press": 543, "front-raise": 256, "rear-delt-fly": 487, "upright-row": 694,
    "cable-lateral-raise": 1378, "hammer-curl": 272, "barbell-curl": 91, "preacher-curl": 465,
    "cable-curl": 95, "rope-pushdown": 1900, "overhead-triceps-extension": 1336, "skull-crusher": 246,
    "close-grip-push-up": 1086, "crunch": 167, "lying-leg-raise": 377, "russian-twist": 1193,
    "ab-wheel": 1573, "pallof-press": 1194, "side-bend": 1650, "plank-shoulder-tap": 1091,
    "wall-ball": 1100, "dumbbell-snatch": 1947, "high-knees": 983, "hip-flexor-stretch": 1867,
    "hamstring-band-stretch": 1870, "quad-stretch": 1873, "pigeon-stretch": 1872, "calf-stretch": 1239,
    "knee-to-chest": 1452, "foam-roll-quads": 1858, "foam-roll-calves": 1854,
}  # fmt: skip


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "iron-m/0.1 (exercise images)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return bytes(r.read())


def main() -> int:
    out_dir = Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "exercise-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    licenses = {x["id"]: x for x in json.loads(get(f"{API}/license/?format=json"))["results"]}
    images = json.loads(get(f"{API}/exerciseimage/?limit=1000&format=json"))["results"]
    by: dict[int, list[dict]] = {}
    for im in images:
        if not im.get("is_ai_generated"):
            by.setdefault(im["exercise"], []).append(im)
    lines = [
        "# 动作配图清单（spec [2026-10-23] §32），由 scripts/fetch_exercise_images.py 生成，不要手改。",
        "# 图片来自 wger（https://wger.de），每张写明作者和许可；页面上署名。图片文件在本机数据目录，不进仓库。",
        "images:",
    ]
    missing = []
    for eid, wid in WGER.items():
        got = sorted(by.get(wid, []), key=lambda x: not x.get("is_main"))[:MAX_PER_EXERCISE]
        if not got:
            missing.append(eid)
            continue
        lines.append(f"  {eid}:")
        for i, im in enumerate(got, start=1):
            # 用 wger 自己生成的中等缩略图（约 400 像素），原图有的好几 MB，手机上太慢
            url = (im.get("thumbnails") or {}).get("medium") or im["image"]
            ext = ".png" if url.endswith(".png") else Path(url).suffix.lower() or ".png"
            name = f"{eid}-{i}{ext}"
            (out_dir / name).write_bytes(get(url))
            lic = licenses.get(im["license"], {})
            author = im.get("license_author") or "wger.de 贡献者"
            fields = {
                "file": name, "source": im["image"], "page": f"https://wger.de/exercise/{wid}/view/",
                "license": lic.get("short_name", "").strip(), "license_url": lic.get("url", ""),
                "author": author, "author_url": im.get("license_author_url") or "",
            }  # fmt: skip
            lines.append("    - " + json.dumps(fields, ensure_ascii=False))
    (ROOT / "ironm_agent" / "exercise_images.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"done: {len(WGER) - len(missing)} exercises; missing: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
