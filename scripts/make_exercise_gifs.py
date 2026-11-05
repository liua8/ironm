"""把动作的起止两张图合成一张来回切换的动图（spec [2026-11-03] §144）。

用法：.venv/bin/python scripts/make_exercise_gifs.py
- 读动作配图清单（ironm_agent/exercise_images.yaml）和本机数据目录里已下载的图，不连网络。
- 只合成真正是"同一张图的起止两帧"的：一样大的两张原样叠；不一样大的（Everkinetic 的图按画面裁过边）
  先按线条对齐，对不上（重合的线条太少）的跳过；几乎一样（两张都是同一个姿势）的跳过；
  SKIP 里是看过后不合适的（两张是不同的图）。
- 透明底铺白，缩到最长边 480 像素；每帧停 0.9 秒，循环播放。输出 <动作>-0.gif 到图片目录，
  和原图同许可（CC BY-SA），页面署原图作者。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ironm_agent.exercise_images import manifest  # noqa: E402

FRAME_MS = 900
MIN_DIFF = 3.0  # 两帧缩成 64×64 灰度后平均每个点差多少，低于这个算同一个姿势
MIN_OVERLAP = 0.15  # 对齐后两张重合的线条占线条少的那张的多少，低于这个算两张不相干的图
SIZE = 480
# 看过不合适的：wger 上高位下拉、相扑硬拉的两张是不同的图；Everkinetic 的俯卧撑两张视角不同，
# 健腹轮、杠铃深蹲第一张裁掉了半截身体，拼起来会跳（照旧两张并排放）
SKIP = {"lat-pulldown", "sumo-deadlift", "push-up", "ab-wheel", "back-squat"}


def flat(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, "white")
    bg.alpha_composite(im)
    return bg.convert("RGB")


def _ink(im: Image.Image, scale: float) -> np.ndarray:
    small = im.convert("L").resize(
        (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    )
    return (np.asarray(small) < 160).astype(np.float64)


def align(a: Image.Image, b: Image.Image) -> tuple[int, int, float]:
    """第二张相对第一张放在哪儿线条重合得最多：返回偏移（原图像素）和重合的比例。"""
    scale = min(1.0, 240 / max(a.width, a.height, b.width, b.height))
    x, y = _ink(a, scale), _ink(b, scale)
    h, w = x.shape[0] + y.shape[0], x.shape[1] + y.shape[1]
    corr = np.fft.irfft2(np.fft.rfft2(x, (h, w)) * np.conj(np.fft.rfft2(y, (h, w))), (h, w))
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    dy = dy - h if dy >= x.shape[0] else dy  # 负的偏移绕到了后面
    dx = dx - w if dx >= x.shape[1] else dx
    overlap = float(corr.max()) / max(1.0, min(x.sum(), y.sum()))
    return round(dx / scale), round(dy / scale), overlap


def frames_of(a: Path, b: Path) -> tuple[Image.Image, Image.Image] | None:
    """两张图能当起止两帧就返回对齐、铺好白底、一样大的两帧，不能返回 None。"""
    x, y = flat(a), flat(b)
    if abs(x.width - y.width) <= 2 and abs(x.height - y.height) <= 2:
        dx, dy = 0, 0  # 一样大的是同一块画布上的两帧，原样叠
    else:
        dx, dy, overlap = align(x, y)
        if overlap < MIN_OVERLAP:
            return None
    left, top = min(0, dx), min(0, dy)
    size = (max(x.width, dx + y.width) - left, max(x.height, dy + y.height) - top)
    frames = []
    for im, at in ((x, (-left, -top)), (y, (dx - left, dy - top))):
        canvas = Image.new("RGB", size, "white")
        canvas.paste(im, at)
        canvas.thumbnail((SIZE, SIZE))
        frames.append(canvas)
    small = [im.convert("L").resize((64, 64)) for im in frames]
    diff = sum(ImageChops.difference(*small).tobytes()) / 64 / 64
    return (frames[0], frames[1]) if diff >= MIN_DIFF else None


def make_gif(a: Path, b: Path, out: Path) -> bool:
    got = frames_of(a, b)
    if got is None:
        return False
    x, y = got
    x.save(out, save_all=True, append_images=[y], duration=FRAME_MS, loop=0, optimize=True)
    return True


def main() -> int:
    img_dir = Path(os.environ.get("IRONM_DATA_DIR") or ROOT / "data") / "exercise-images"
    made, skipped = [], []
    for ex_id, frames in manifest().items():
        if len(frames) < 2:
            continue
        a, b = (img_dir / str(f.get("file", "")) for f in frames[:2])
        out = img_dir / f"{ex_id}-0.gif"
        if ex_id in SKIP or not a.is_file() or not b.is_file() or not make_gif(a, b, out):
            out.unlink(missing_ok=True)
            skipped.append(ex_id)
            continue
        made.append(ex_id)
    print(f"合成 {len(made)} 张：{'、'.join(made)}")
    print(f"跳过 {len(skipped)} 个：{'、'.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
