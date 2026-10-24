"""路由测评（spec [2026-10-23] §16）：在标注好"应该交给谁"的问答考题上，并排比较
模型、关键字、语义向量三路各自的准确率、加权后的准确率、去掉模型后的准确率，以及现在主教练调度的准确率。

用真实模型（分类打分和现在的主教练调度各调一次）；关键字和语义向量在本机算：
    .venv/bin/python evals/route/run.py            # 全部标注题
    .venv/bin/python evals/route/run.py --no-llm   # 只测关键字和语义向量（不花钱）
    .venv/bin/python evals/route/run.py --set heldout   # 留出题（spec [2026-10-23] §20，没用来调过路由）
报告写在 evals/route/reports/：<日期>-<标签>.json 与同名 .md。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.qa.run import load_env  # noqa: E402
from ironm_agent.llm import TurnLLM, load_models  # noqa: E402
from ironm_agent.router import route as coach_route  # noqa: E402
from ironm_agent.routing import (  # noqa: E402
    NAMES,
    Decision,
    KeywordScorer,
    VectorScorer,
    combine,
    keyword_intent,
    llm_scores,
)
from ironm_agent.yamlfile import load_yaml  # noqa: E402

HERE = Path(__file__).resolve().parent
METHODS = ("模型", "关键字", "语义向量", "加权（三路）", "加权（去掉模型）", "现在的主教练调度")


@dataclass
class Pick:
    intent: str
    roles: list[str]


@dataclass
class Row:
    id: str
    ask: str
    label: dict[str, Any]
    picks: dict[str, Pick] = field(default_factory=dict)
    scores: dict[str, Any] = field(default_factory=dict)


def top_only(intent: str, scores: Mapping[str, float] | None) -> Pick:
    if intent != "pro" or not scores or max(scores.values()) <= 0:
        return Pick(intent, [])
    return Pick("pro", [max(NAMES, key=lambda n: (scores[n], -NAMES.index(n)))])


def from_decision(d: Decision) -> Pick:
    return Pick(d.intent, [r.value for r in d.roles])


def judge(label: Mapping[str, Any], pick: Pick) -> dict[str, bool | int]:
    """intent 题：判对问题类型且没请人；专业题：主责对、必须请到的都请了、多请了几位。"""
    if "intent" in label:
        return {"intent_ok": pick.intent == label["intent"] and not pick.roles}
    primary = set(label.get("primary", []))
    required = set(label.get("required", []))
    allowed = primary | required | set(label.get("allowed", []))
    roles = pick.roles
    return {
        "pro_ok": pick.intent == "pro",
        "primary_ok": bool(roles) and roles[0] in primary,
        "required_ok": required <= set(roles),
        "extra": len([r for r in roles if r not in allowed]),
        "count": len(roles),
    }


async def one(
    case: Mapping[str, Any],
    label: Mapping[str, Any],
    *,
    kw: KeywordScorer,
    vec: VectorScorer,
    env: Mapping[str, str] | None,
    sem: asyncio.Semaphore,
) -> Row:
    text = str(case["ask"])
    r = Row(str(case["id"]), text, dict(label))
    ks = kw.scores(text)
    vs = vec.scores(text)
    r.scores["keyword"] = {k: round(v, 2) for k, v in ks.items()}
    r.scores["vector"] = {k: round(v, 2) for k, v in vs.items()}
    r.picks["关键字"] = top_only(keyword_intent(text) or "pro", ks)
    r.picks["语义向量"] = top_only("pro", vs)
    r.picks["加权（去掉模型）"] = from_decision(combine(text, llm=None, keyword=ks, vector=vs))
    if env is not None:
        async with sem:
            found = await llm_scores(text, TurnLLM(load_models(), env))
            coach = await coach_route(text, [], TurnLLM(load_models(), env))
        if found is not None:
            r.scores["llm"] = {k: round(v, 2) for k, v in found[1].items()}
            r.picks["模型"] = top_only(found[0], found[1])
        r.picks["加权（三路）"] = from_decision(combine(text, llm=found, keyword=ks, vector=vs))
        r.picks["现在的主教练调度"] = Pick(coach.intent, [x.value for x in coach.experts()])
    return r


def summarize(rows: Sequence[Row]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in METHODS:
        got = [(r.label, r.picks[m]) for r in rows if m in r.picks]
        if not got:
            continue
        pro = [judge(lb, p) for lb, p in got if "intent" not in lb]
        intents = [judge(lb, p) for lb, p in got if "intent" in lb]
        n = len(pro)
        out[m] = {
            "主责对": f"{sum(bool(x['primary_ok']) for x in pro)}/{n}",
            "主责准确率": round(sum(bool(x["primary_ok"]) for x in pro) / n, 3) if n else None,
            "必须请到的都请了": f"{sum(bool(x['required_ok']) for x in pro)}/{n}",
            "多请的人次": sum(int(x["extra"]) for x in pro),
            "平均请几位": round(sum(int(x["count"]) for x in pro) / n, 2) if n else None,
            "错当成闲聊等": sum(not x["pro_ok"] for x in pro),
            "问题类型对（闲聊等）": f"{sum(bool(x['intent_ok']) for x in intents)}/{len(intents)}",
        }
    return out


def report(rows: Sequence[Row], summary: Mapping[str, Mapping[str, Any]], tag: str) -> Path:
    folder = HERE / "reports"
    folder.mkdir(exist_ok=True)
    stem = folder / f"{date.today().isoformat()}-{tag}"
    stem.with_suffix(".json").write_text(
        json.dumps(
            {"summary": summary, "rows": [asdict(r) for r in rows]}, ensure_ascii=False, indent=1
        )
    )
    cols = [
        "主责准确率",
        "主责对",
        "必须请到的都请了",
        "多请的人次",
        "平均请几位",
        "错当成闲聊等",
        "问题类型对（闲聊等）",
    ]
    lines = [
        f"# 路由测评：{tag}",
        "",
        f"标注题 {len(rows)} 道（被安全前置、风险拦截、追问截住的题和靠上下文的题不在内）。",
        "",
    ]
    lines += ["| 方式 | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    for m, s in summary.items():
        lines.append(f"| {m} | " + " | ".join(str(s[c]) for c in cols) + " |")
    lines += ["", "## 加权（三路）选错主责或漏请的题", ""]
    for r in rows:
        p = r.picks.get("加权（三路）") or r.picks.get("加权（去掉模型）")
        if p is None:
            continue
        j = judge(r.label, p)
        bad = ("intent_ok" in j and not j["intent_ok"]) or (
            "primary_ok" in j and not (j["primary_ok"] and j["required_ok"])
        )
        if bad:
            want = r.label.get("intent") or "、".join(r.label.get("primary", []))
            lines.append(
                f"- **{r.id}** {r.ask}：选了 {p.intent if not p.roles else '、'.join(p.roles)}；应为 {want}"
            )
    path = stem.with_suffix(".md")
    path.write_text("\n".join(lines) + "\n")
    return path


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--label", default="route")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--set", choices=("labels", "heldout"), default="labels")
    args = parser.parse_args()
    if args.set == "heldout":
        held = load_yaml(HERE / "heldout.yaml")["cases"]
        cases = {c["id"]: c for c in held}
        labels = {c["id"]: {k: v for k, v in c.items() if k not in ("id", "ask")} for c in held}
    else:
        cases = {c["id"]: c for c in load_yaml(ROOT / "evals/qa/cases.yaml")["cases"]}
        labels = load_yaml(HERE / "labels.yaml")["labels"]
    kw, vec = KeywordScorer.build(), VectorScorer()
    env = None if args.no_llm else load_env()
    sem = asyncio.Semaphore(args.jobs)
    rows = await asyncio.gather(
        *(one(cases[i], lb, kw=kw, vec=vec, env=env, sem=sem) for i, lb in labels.items())
    )
    summary = summarize(rows)
    tag = (
        args.label
        + ("-heldout" if args.set == "heldout" else "")
        + ("-nollm" if args.no_llm else "")
    )
    path = report(rows, summary, tag)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"报告：{path}")


if __name__ == "__main__":
    asyncio.run(main())
