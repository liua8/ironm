"""Skill 选择测评（spec [2026-10-23] §20）：问题交给某个角色时，装载的规程对不对。只用规则，不调用模型。

.venv/bin/python evals/skills/run.py            # 说法对不上时用本机向量模型兜底（和线上一样）
.venv/bin/python evals/skills/run.py --no-vector   # 只按说法匹配
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ironm_agent.roles import Role  # noqa: E402
from ironm_agent.routing import VectorScorer  # noqa: E402
from ironm_agent.skills import Similar, pick  # noqa: E402
from ironm_agent.yamlfile import load_yaml  # noqa: E402

CASES = Path(__file__).with_name("cases.yaml")


def run(similar: Similar | None = None) -> tuple[float, list[dict[str, Any]]]:
    cases = load_yaml(CASES)["cases"]  # type: ignore[index]
    misses = []
    for c in cases:
        chosen = pick(Role(c["role"]), c["ask"], c.get("on", ()), similar)
        got = [x.name for x in chosen if not x.style]
        if not set(got) & set(c["expect"]):
            misses.append({**c, "got": got})
    return 1 - len(misses) / len(cases), misses


if __name__ == "__main__":
    rate, misses = run(None if "--no-vector" in sys.argv else VectorScorer().similar)
    print(f"命中率 {rate:.1%}")
    for m in misses:
        print(
            f"- [{m['role']}] {m['ask']}：装载了 {'、'.join(m['got']) or '（无）'}；应为 {'、'.join(m['expect'])}"
        )
