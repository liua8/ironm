"""从 Everkinetic 开源动作库取动作配图（spec [2026-11-03] §144），下载到本机数据目录，并写图片清单。

用法：.venv/bin/python scripts/fetch_everkinetic_images.py
- 来源 https://github.com/everkinetic/data（CC BY-SA 4.0），每个动作两张线稿：放松（起始）、发力（结束），
  和 wger 上 Everkinetic 那批是同一套图；两张拼成动图见 scripts/make_exercise_gifs.py。
- 动作和 Everkinetic 编号的对应写在 EVERKINETIC 里（对过图）；这里有的动作，页面用这里的图、不用 wger 的。
- 图片下载到 $IRONM_DATA_DIR/exercise-images/<动作>-ek-1.png、-ek-2.png（默认 data/，不进仓库）；
  清单写进 ironm_agent/exercise_images_everkinetic.yaml（进仓库：作者、许可、来源，页面上要署名）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = "https://raw.githubusercontent.com/everkinetic/data/master/dist/png/"
PAGE = "https://github.com/everkinetic/data"
EVERKINETIC: dict[str, str] = {
    # 原来没图
    "box-squat": "0136:2", "step-up": "0137", "side-plank": "0113", "ab-wheel": "0286", "smith-squat": "0124",
    "seated-leg-curl": "0119", "t-bar-row": "0029", "sumo-squat": "0152", "triceps-kickback": "0204",
    # 原来的图拼不成动图，或者来路可疑
    "back-squat": "0122", "romanian-deadlift": "0118:2", "deadlift": "0099:2", "bulgarian-split-squat": "0132",
    "glute-bridge": "0109", "calf-raise": "0281", "leg-press": "0127", "push-up": "0077", "pull-up": "0087",
    "walking-lunge": "0121", "leg-extension": "0142", "seated-calf-raise": "0279", "hip-abduction": "0156",
    "machine-chest-press": "0066", "decline-push-up": "0075", "seated-cable-row": "0025",
    "inverted-row": "0086", "straight-arm-pulldown": "0092", "dumbbell-shrug": "0005", "front-raise": "0033",
    "rope-pushdown": "0206",
}  # fmt: skip
# 编号后面写 ":2" 的只要第二张（发力）：这几个的第一张是放大的特写，和第二张拼不到一起。
# 看过不用的：高脚杯深蹲、后撤弓步、双杠臂屈伸（第一张是特写，原来 wger 的图更好）；哑铃颈后臂屈伸（姿势对不上）


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "iron-m/0.1 (exercise images)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return bytes(r.read())


def main() -> int:
    out_dir = Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "exercise-images"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 动作配图清单（spec [2026-11-03] §144），由 scripts/fetch_everkinetic_images.py 生成，不要手改。",
        "# 图片来自 Everkinetic 开源动作库（https://github.com/everkinetic/data，CC BY-SA 4.0）；页面上署名。",
        "# 这里有的动作用这里的图，不用 exercise_images.yaml（wger）里的。图片文件在本机数据目录，不进仓库。",
        "images:",
    ]
    for eid, code in EVERKINETIC.items():
        num, _, only = code.partition(":")
        frames = [("relaxation", "tension")[int(only) - 1]] if only else ["relaxation", "tension"]
        lines.append(f"  {eid}:")
        for i, frame in enumerate(frames, start=1):
            name = f"{eid}-ek-{i}.png"
            (out_dir / name).write_bytes(get(f"{RAW}{num}-{frame}.png"))
            fields = {
                "file": name, "source": f"{RAW}{num}-{frame}.png", "page": PAGE, "site": "Everkinetic",
                "license": "CC-BY-SA 4", "license_url": "https://creativecommons.org/licenses/by-sa/4.0/deed.en",
                "author": "Everkinetic", "author_url": "",
            }  # fmt: skip
            lines.append("    - " + json.dumps(fields, ensure_ascii=False))
    (ROOT / "ironm_agent" / "exercise_images_everkinetic.yaml").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"done: {len(EVERKINETIC)} exercises")
    return 0


if __name__ == "__main__":
    sys.exit(main())
