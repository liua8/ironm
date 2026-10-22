"""本机调试：用真实模型跑一轮（健康数据用假的），打印整合核对没通过的原因。不进日志。"""

import asyncio
import os
import sys

from ironm_agent import compose as compose_mod
from ironm_agent.plugin import IronMAgent
from tests.fakes import FakeHealth

_orig = compose_mod.review


def _review(answer, **kw):  # type: ignore[no-untyped-def]
    problems = _orig(answer, **kw)
    print("\n--- 整合稿 ---\n" + answer + "\n--- 核对问题 ---\n" + ("\n".join(problems) or "通过"))
    return problems


compose_mod.review = _review


async def main() -> None:
    weight = {"indicator": "Body weight", "name": "bodyMasss", "date": "2026-09-14", "value": "69.2", "unit": "kg", "rid": "r1"}
    agent = IronMAgent(health=FakeHealth(rows=[weight]), environ=os.environ)
    async for b in agent.generate_response("42", [{"role": "user", "content": sys.argv[1]}], session_id=""):
        if b["type"] == "text":
            print("\n=== 最终 ===\n" + b["text"])


asyncio.run(main())
