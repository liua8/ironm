"""红旗测试集：43 句话 → 期望判定（来自 IronM，已审定）。"""

from pathlib import Path
from typing import Any

import pytest

from ironm_agent.safety.emergency import assess
from ironm_agent.yamlfile import load_yaml

DATA: Any = load_yaml(Path(__file__).with_name("red_flags.yaml"))
CASES: list[dict[str, Any]] = DATA["cases"]


def test_dataset_shape() -> None:
    assert len(CASES) >= 40
    assert len({c["id"] for c in CASES}) == len(CASES)
    assert {c["expect"] for c in CASES} == {"emergency", "red_flag", "none"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_red_flag(case: dict[str, Any]) -> None:
    if case.get("pending"):
        pytest.xfail(case["pending"])
    assert assess(case["text"]).level == case["expect"]
