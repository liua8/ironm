"""训练中重量、次数能自己填数字（spec [2026-10-23] §178）。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
    encoding="utf-8"
)


def _typed(cases: list[tuple[str, dict[str, object]]]) -> list[float | None]:
    """把 app.js 里的 typedNum 拿出来用 node 跑。"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("没有 node")
    src = re.search(r"^function typedNum\(.*?^}\n", JS, re.S | re.M)
    assert src, "app.js 里要有 typedNum"
    script = (
        src.group(0)
        + f"console.log(JSON.stringify({json.dumps(cases)}.map(([t, o]) => typedNum(t, o))));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    result: list[float | None] = json.loads(out)
    return result


def test_typed_weight_and_reps_are_parsed_within_range() -> None:
    kg = {"max": 500, "dec": True}
    reps = {"max": 100}
    got = _typed([
        ("62.5", kg), (" 70 ", kg), ("70，5", kg), ("７５", kg), ("62.55", kg), ("0", kg),
        ("8", reps), ("8.6", reps),
    ])  # fmt: skip
    assert got == [62.5, 70, 70.5, 75, 62.6, 0, 8, 9]


def test_bad_input_keeps_the_old_value() -> None:
    kg = {"max": 500, "dec": True}
    reps = {"max": 100}
    got = _typed([("", kg), ("abc", kg), ("-5", kg), ("600", kg), ("1e3", kg), ("101", reps)])
    assert got == [None] * 6


def test_big_numbers_are_inputs_wired_like_the_buttons() -> None:
    # 大数字是输入框，填完和 − / + 走同一个 setVal（加重检查 checkKg 在里面）
    assert "class: `step-in num" in JS
    assert "const bump = (i, j, key, d) => setVal(" in JS
    set_val = JS[JS.index("const setVal = ") : JS.index("const bump = ")]
    assert 'if (key === "weight_kg") checkKg(i, j, prev);' in set_val
    assert '{ range: { max: 500, dec: true }, set: (v) => setVal(i, j, "weight_kg", v) }' in JS
    assert '{ range: { max: 100 }, set: (v) => setVal(i, j, "reps", v) }' in JS
    # 填得不对还原，不调 setVal
    big = JS[JS.index("const bigNum = ") : JS.index("// 当前这一组（§104 需求 6）")]
    assert "if (v == null || v === value) { el.value" in big
