"""spec [2026-10-23] §58、§121、§124、§126：现在是像素农场风（§131）；不用蓝、青；文字对比度够；不再有更早那版白色基调的写死颜色。"""

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


def test_pixel_farm_palette() -> None:
    """§131：像素农场风——草地绿底、羊皮纸面板、深木棕正文、深草绿按钮。"""
    t = _tokens()
    r, g, b = (int(t["bg"][i : i + 2], 16) for i in (1, 3, 5))
    assert g > r > b  # 草地绿
    r, g, b = (int(t["surface"][i : i + 2], 16) for i in (1, 3, 5))
    assert _lum(t["surface"]) > 0.7 and r > g > b  # 羊皮纸
    assert _lum(t["ink"]) < 0.05  # 深木棕
    assert "Fusion Pixel" in CSS and "fusion-pixel-12px-zh_hans.woff2" in CSS  # 像素字体放在项目里
    assert "color-scheme: light" in CSS[: CSS.index("}", CSS.index(":root {"))]


def test_no_blue_or_cyan() -> None:
    """§121：项目负责人"颜色不要蓝色"——样式表里没有蓝、青色（紫色可以，管脂肪）。"""
    import colorsys

    found = []
    for m in re.finditer(r"#([0-9a-fA-F]{6})\b|rgb\((\d+) (\d+) (\d+)", CSS):
        rgb = (
            [int(m.group(1)[i : i + 2], 16) for i in (0, 2, 4)]
            if m.group(1)
            else [int(x) for x in m.group(2, 3, 4)]
        )
        hue, light, sat = colorsys.rgb_to_hls(*(x / 255 for x in rgb))
        if sat > 0.25 and light > 0.08 and 160 <= hue * 360 <= 250:
            found.append(m.group(0))
    assert not found, found
    js = (WEB / "app.js").read_text()
    hues = re.search(r"const FOOD_HUE = \{([^}]*)\}", js)
    assert hues and all(
        not 160 <= int(v) <= 250 for v in re.findall(r": (\d+)", hues.group(1))
    )  # 食物色块也不用


@pytest.mark.parametrize(
    ("fg", "bg", "least"),
    [
        ("ink", "surface", 4.5), ("ink", "bg", 4.5), ("ink-2", "surface", 4.5),
        ("muted", "surface", 3.0), ("muted", "bg", 3.0), ("accent-text", "surface", 4.5),
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
    assert 'content="#7ec850"' in (WEB / "index.html").read_text()  # §131 草地绿
