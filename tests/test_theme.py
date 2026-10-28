"""spec [2026-10-23] §58：整体换成黑绿；文字对比度够、样式表里不再有白色基调的写死颜色。"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
CSS = (WEB / "style.css").read_text()


def _tokens() -> dict[str, str]:
    root = CSS[CSS.index(":root {") : CSS.index("}", CSS.index(":root {"))]
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", root))


def _lum(hex_: str) -> float:
    rgb = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def test_dark_base_and_green_accent() -> None:
    t = _tokens()
    assert _lum(t["bg"]) < 0.01 and _lum(t["surface"]) < 0.02  # 黑底、深灰面板
    r, g, b = (int(t["accent"][i : i + 2], 16) for i in (1, 3, 5))
    assert g > 200 and g > r and g > b  # 主色是绿
    assert "color-scheme: dark" in CSS[: CSS.index("}", CSS.index(":root {"))]


@pytest.mark.parametrize(
    ("fg", "bg", "least"),
    [
        ("ink", "surface", 4.5), ("ink", "bg", 4.5), ("ink-2", "surface", 4.5),
        ("muted", "surface", 3.0), ("muted", "bg", 3.0), ("accent", "surface", 4.5),
        ("warn", "surface", 4.5), ("heat", "surface", 4.5),
        ("accent-ink", "fire", 4.5), ("accent-ink", "fire-2", 4.5), ("accent-ink", "heat", 4.5),
    ],
)  # fmt: skip
def test_text_contrast(fg: str, bg: str, least: float) -> None:
    t = _tokens()
    assert contrast(t[fg], t[bg]) >= least, (fg, bg, round(contrast(t[fg], t[bg]), 2))


def test_no_light_theme_leftovers() -> None:
    for old in (
        "rgb(21 19 15",
        "rgb(240 86 29",
        "#f6f6f4",
        "#f0f0ed",
        "#15130f",
        "#fafaf8",
        "rgb(255 255 255 / 88%)",
    ):
        assert old not in CSS, old
    # 写死的白色只留给动作照片底和视频上的播放按钮
    whites = [
        ln.split("{")[0].strip() for ln in CSS.splitlines() if re.search(r"#fff\b|#ffffff", ln)
    ]
    assert whites == [".move-cover .play", ".move-cover .move-img", ".move-frames img"]
    assert 'content="#0a0c0b"' in (WEB / "index.html").read_text()
