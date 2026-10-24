"""Skill 选择测评（spec [2026-10-23] §20、§21）：问题交给某个角色时，装载的规程对不对。

    .venv/bin/python evals/skills/run.py              # 本地规则：说法匹配 + 本机向量兜底 + 默认规程（不花钱）
    .venv/bin/python evals/skills/run.py --no-vector  # 只按说法匹配
    .venv/bin/python evals/skills/run.py --route      # 路由模型选（和线上一样：没选这个角色时按本地规则），要调用真实模型
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.qa.run import load_env  # noqa: E402
from ironm_agent.llm import TurnLLM, load_models  # noqa: E402
from ironm_agent.roles import Role  # noqa: E402
from ironm_agent.routing import VectorScorer, llm_scores  # noqa: E402
from ironm_agent.skills import Similar, choose  # noqa: E402
from ironm_agent.yamlfile import load_yaml  # noqa: E402

CASES = Path(__file__).with_name("cases.yaml")


async def run(similar: Similar | None, route: bool = False) -> dict[str, Any]:
    cases = load_yaml(CASES)["cases"]  # type: ignore[index]
    env = load_env() if route else None
    sem = asyncio.Semaphore(4)

    async def one(c: dict[str, Any]) -> dict[str, Any]:
        routed = None
        if env is not None:
            async with sem:
                found = await llm_scores(c["ask"], TurnLLM(load_models(), env))
            routed = found.skills.get(c["role"]) if found is not None else None
        chosen, by = choose(Role(c["role"]), c["ask"], c.get("on", ()), similar, routed)
        got = [x.name for x in chosen if not x.style]
        ok = not got if not c["expect"] else bool(set(got) & set(c["expect"]))
        return {**c, "got": got, "by": by, "ok": ok}

    rows = await asyncio.gather(*(one(c) for c in cases))
    content = [r for r in rows if r["expect"]]
    none = [r for r in rows if not r["expect"]]
    return {
        "rate": sum(r["ok"] for r in content) / len(content),
        "none_rate": sum(r["ok"] for r in none) / len(none) if none else 1.0,
        "by_route": sum(r["by"] == "route" for r in rows),
        "total": len(rows),
        "misses": [r for r in rows if not r["ok"]],
    }


if __name__ == "__main__":
    similar = None if "--no-vector" in sys.argv else VectorScorer().similar
    out = asyncio.run(run(similar, route="--route" in sys.argv))
    print(f"命中率 {out['rate']:.1%}（该装规程的题）；用不上规程的题判对 {out['none_rate']:.1%}；"
          f"{out['by_route']}/{out['total']} 道由路由选")  # fmt: skip
    for m in out["misses"]:
        want = "、".join(m["expect"]) or "（不装）"
        print(f"- [{m['role']}] {m['ask']}：装载了 {'、'.join(m['got']) or '（无）'}；应为 {want}")
