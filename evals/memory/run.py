"""跑记忆考题：每组情景按顺序把每一轮交给记忆提取，最后按 cases.yaml 的期望打分。

用真实模型（config/models.yaml 的 memory 环节，密钥从 .env 读）：
    .venv/bin/python evals/memory/run.py            # 全部情景
    .venv/bin/python evals/memory/run.py M02 M04    # 只跑几组
    .venv/bin/python evals/memory/run.py --runs 3   # 每组跑 3 遍，看稳不稳

指标：关键事实记全率（must 命中比例）、变化更新正确率（tags 含 update 的情景整组通过的比例）、
编造条数（absent 与 none 的违例）、每轮提取耗时、被规则拒掉的操作数。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ironm_agent.llm import TurnLLM, load_models  # noqa: E402
from ironm_agent.memory_extract import extract  # noqa: E402
from ironm_agent.memory_store import Item, MemoryBook  # noqa: E402
from ironm_agent.yamlfile import load_yaml  # noqa: E402

CASES = Path(__file__).with_name("cases.yaml")
THRESHOLDS = {"recall": 0.9, "update": 0.9, "fabricated": 0, "excess": 0}
LIVE = ("active", "pending")  # 编造检查看有效和待确认的
NEW_SESSION = "新会话"


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                env.setdefault(key.strip(), value.strip().strip("'\""))
    return env


def squash(text: str) -> str:
    return "".join(text.split())


def has_all(item: Item, words: list[Any]) -> bool:
    return all(squash(str(w)) in squash(item.content) for w in words)


@dataclass
class CaseResult:
    id: str
    tags: list[str]
    must_hit: int = 0
    must_total: int = 0
    misses: list[str] = field(default_factory=list)
    fabricated: list[str] = field(default_factory=list)
    excess: list[str] = field(default_factory=list)  # 多记：超过类别上限，或把一般原则记成了建议
    rejected: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.must_hit == self.must_total
            and not self.fabricated
            and not self.excess
            and not self.failed
        )


def score(case: dict[str, Any], items: list[Item], result: CaseResult) -> None:
    for m in case.get("must", []):
        result.must_total += 1
        want = m.get("status", "active")
        ok = any(
            x.category in m["category"] and x.status == want and has_all(x, m["keywords"])
            for x in items
        )
        if ok:
            result.must_hit += 1
        else:
            result.misses.append(f"{'/'.join(m['category'])} {m['keywords']} ({want})")
    live = [x for x in items if x.status in LIVE]
    for a in case.get("absent", []):
        for x in live:
            if has_all(x, a["keywords"]) and not any(
                squash(str(u)) in squash(x.content) for u in a.get("unless", [])
            ):
                result.fabricated.append(f"{a['keywords']} ← {x.category}：{x.content}")
    current = [x for x in items if x.status != "superseded"]
    for cat, most in (case.get("limits") or {}).items():
        n = sum(1 for x in current if x.category == cat)
        if n > most:
            result.excess.append(f"{cat} 记了 {n} 条（最多 {most}）")
    for word in case.get("generic", []):
        for x in current:
            if x.category == "advice" and squash(str(word)) in squash(x.content):
                result.excess.append(f"一般原则记成了建议（{word}）：{x.content}")
    if case.get("none"):
        for x in items:
            if x.category != "advice" and x.status != "superseded":
                result.fabricated.append(f"不该有记忆 ← {x.category}：{x.content}")


async def run_case(case: dict[str, Any], env: dict[str, str]) -> CaseResult:
    models = load_models()
    book = MemoryBook()
    result = CaseResult(case["id"], list(case.get("tags", [])))
    said: list[str] = []
    for turn in case["turns"]:
        if turn == NEW_SESSION:
            said = []  # 换了会话：前面说过的话看不到了，只剩记忆
            continue
        user_text, answer = turn
        llm = TurnLLM(models, env)
        start = time.perf_counter()
        current = await book.items("u")
        out = await extract(llm, current, user_text, answer, [f"用户：{s}" for s in said[-4:]])
        result.seconds.append(time.perf_counter() - start)
        result.rejected += out.rejected
        if out.failed:
            result.failed.append(out.failed)
        await book.apply("u", out.changes)
        said.append(user_text)
    result.items = await book.items("u", current_only=False)
    score(case, result.items, result)
    return result


def show(r: CaseResult, verbose: bool) -> None:
    mark = "通过" if r.passed else "未过"
    print(f"{r.id} {mark}  必记 {r.must_hit}/{r.must_total}  编造 {len(r.fabricated)}  "
          f"多记 {len(r.excess)}  "
          f"被拒 {len(r.rejected)}  耗时 {sum(r.seconds):.1f}s")  # fmt: skip
    for m in r.misses:
        print(f"    漏记：{m}")
    for f in r.fabricated:
        print(f"    编造：{f}")
    for f in r.excess:
        print(f"    多记：{f}")
    for f in r.failed:
        print(f"    失败：{f}")
    for why in r.rejected:
        print(f"    被拒：{why}")
    if verbose or not r.passed:
        for x in r.items:
            print(f"      [{x.status}/{x.origin}] {x.category}：{x.content}  ←「{x.evidence}」")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--jobs", type=int, default=6)
    args = ap.parse_args()
    env = load_env()
    suite: dict[str, Any] = load_yaml(CASES)  # type: ignore[assignment]
    cases = [c for c in suite["cases"] if not args.ids or c["id"] in args.ids]
    gate = asyncio.Semaphore(args.jobs)

    async def guarded(c: dict[str, Any]) -> CaseResult:
        async with gate:
            return await run_case(c, env)

    all_results: list[CaseResult] = []
    for run in range(args.runs):
        if args.runs > 1:
            print(f"\n==== 第 {run + 1} 遍 ====")
        results = await asyncio.gather(*(guarded(c) for c in cases))
        for r in results:
            show(r, args.verbose)
        all_results += results
    hit = sum(r.must_hit for r in all_results)
    total = sum(r.must_total for r in all_results)
    upd = [r for r in all_results if "update" in r.tags]
    fabricated = sum(len(r.fabricated) for r in all_results)
    excess = sum(len(r.excess) for r in all_results)
    secs = [s for r in all_results for s in r.seconds]
    recall = hit / total if total else 1.0
    update = sum(r.passed for r in upd) / len(upd) if upd else 1.0
    print("\n==== 汇总 ====")
    print(f"关键事实记全率 {recall:.0%}（{hit}/{total}，门槛 ≥ {THRESHOLDS['recall']:.0%}）")
    print(f"变化更新正确率 {update:.0%}（{sum(r.passed for r in upd)}/{len(upd)}，门槛 ≥ "
          f"{THRESHOLDS['update']:.0%}）")  # fmt: skip
    print(f"编造条数 {fabricated}（门槛 {THRESHOLDS['fabricated']}）")
    print(f"多记条数 {excess}（门槛 {THRESHOLDS['excess']}）")
    if secs:
        p95 = sorted(secs)[max(0, int(len(secs) * 0.95) - 1)]
        print(f"每轮提取耗时 平均 {statistics.mean(secs):.1f}s，p95 {p95:.1f}s，共 {len(secs)} 轮")
    print(f"被规则拒掉的操作 {sum(len(r.rejected) for r in all_results)}；"
          f"模型调用失败 {sum(len(r.failed) for r in all_results)}")  # fmt: skip
    ok = (
        recall >= THRESHOLDS["recall"]
        and update >= THRESHOLDS["update"]
        and fabricated <= THRESHOLDS["fabricated"]
        and excess <= THRESHOLDS["excess"]
    )
    print("结论：" + ("达标" if ok else "未达标"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
