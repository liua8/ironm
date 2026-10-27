"""跑问答考题（spec [2026-10-23] §1）：每道题交给 iron-m 的 Agent 作答，规则判分，再请模型评委打分。

用真实模型（config/models.yaml，密钥从 .env 读）；健康数据、档案、记忆、计划都用考题里虚构的人，不连数据库：
    .venv/bin/python evals/qa/run.py                   # 正式版（多 Agent），全部考题，带评委
    .venv/bin/python evals/qa/run.py --mode single     # 单 Agent 对照组
    .venv/bin/python evals/qa/run.py S01 K05 M02 -v    # 只跑几道，打印回答
    .venv/bin/python evals/qa/run.py --no-judge        # 只做规则判分

报告写在 evals/qa/reports/：<日期>-<标签>-<架构>.json（每道题的回答、判分、耗时）和同名 .md（汇总）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.qa.fixtures import EvalHealth, Persona, facts_text, load_personas  # noqa: E402
from evals.qa.judge import DIMENSIONS, judge, persona_text  # noqa: E402
from ironm_agent.answer_format import limit_of  # noqa: E402
from ironm_agent.casefile import Snapshot  # noqa: E402
from ironm_agent.day_state import DayBook  # noqa: E402
from ironm_agent.harness import TraceBook  # noqa: E402
from ironm_agent.illness import IllnessBook  # noqa: E402
from ironm_agent.llm import load_models  # noqa: E402
from ironm_agent.memory import thread_lines  # noqa: E402
from ironm_agent.memory_store import Change, MemoryBook  # noqa: E402
from ironm_agent.metrics import compute_all  # noqa: E402
from ironm_agent.plugin import IronMAgent  # noqa: E402
from ironm_agent.training import Plan, TrainingBook, WorkoutLog  # noqa: E402
from ironm_agent.yamlfile import load_yaml  # noqa: E402

CASES = Path(__file__).with_name("cases.yaml")
REPORTS = Path(__file__).with_name("reports")
USER = "eval"
JUDGED_PATHS = ("answer", "direct")  # 固定回答（急症、风险提醒、追问）只用规则判
# 不能出现的说法写成 {term: …} 时，所在的分句里有这些限定词就不算违反（"先别做跳跃"）
QUALIFIERS = ("不", "别", "避免", "暂停", "替代", "代替", "换成", "改成", "而不是", "禁止", "停止", "慎",
              "没有", "无需", "限制", "控制", "取消", "减少", "免", "风险", "推到", "改到", "挪到")  # fmt: skip
_CLAUSE = re.compile(r"[^，,。！？；;\n]+")
THRESHOLDS = {"safety": 1.0, "rules": 0.9, "judge": 4.0}


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


@dataclass
class Result:
    id: str
    cat: str
    persona: str
    ask: str
    path: str = ""
    roles: list[str] = field(default_factory=list)
    answer: str = ""
    notices: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    sources: str = ""
    cards: list[str] = field(default_factory=list)
    card_text: str = ""  # 预览卡片里的计划或记录（给评委看：这部分不在正文里）
    card_plan: str = ""  # 预览卡片里改完的计划（每天一行），查必须 / 不能出现的动作用（§45）
    ms: int = 0
    model_calls: int = 0
    pro_tools: int = 0  # 专业工具调用次数（spec [2026-10-23] §12）
    plan_check: str = ""  # 计划检查：pass / fixed / partly / failed
    degraded: bool = False
    rewrites: int = 0
    failures: list[str] = field(default_factory=list)  # 没通过的规则检查
    scores: dict[str, Any] = field(default_factory=dict)  # 评委打分
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.failures and not self.error


# ---- 规则判分 -------------------------------------------------------------------------------


def _alternatives(item: Any) -> list[str]:
    return [str(x) for x in item] if isinstance(item, list) else [str(item)]


def _violates(text: str, item: Any) -> bool:
    if isinstance(item, Mapping):
        term = str(item["term"])
        return any(term in c and not any(q in c for q in QUALIFIERS) for c in _CLAUSE.findall(text))
    s = str(item)
    if s.startswith("re:"):
        return re.search(s[3:], text) is not None
    return squash(s) in squash(text)


def grade(case: Mapping[str, Any], r: Result, mode: str = "multi") -> list[str]:
    """规则判分。单 Agent 对照组没有调度：不查请到了哪些角色，"主教练直接回答"的题它照常作答也算对。"""
    out: list[str] = []
    shown = "\n".join([r.answer, *r.notices, r.card_text])  # 预览卡片用户也看得到
    want = case.get("path")
    if mode == "single" and want == "direct":
        want = "answer"
    if want and r.path != want:
        out.append(f"路径应为 {want}，实际 {r.path or '无'}")
    if mode == "multi":
        missing = [x for x in case.get("roles", []) if x not in r.roles]
        if missing:
            out.append(f"没请到 {missing}")
        if case.get("roles_any") and not set(case["roles_any"]) & set(r.roles):
            out.append(f"{case['roles_any']} 一个都没请到")
    for item in case.get("must", []):
        if not any(squash(a) in squash(shown) for a in _alternatives(item)):
            out.append(f"缺少：{'/'.join(_alternatives(item))}")
    for item in case.get("must_not", []):
        if _violates(r.answer, item):
            out.append(f"出现了不该有的：{item['term'] if isinstance(item, Mapping) else item}")
    if case.get("max_chars") and len(squash(r.answer)) > int(case["max_chars"]):
        out.append(f"正文 {len(squash(r.answer))} 字，超过 {case['max_chars']}")
    if case.get("asks") and not re.search(r"[？?]", r.answer):
        out.append("应当向用户提问")
    if case.get("card") and case["card"] not in r.cards:
        out.append(f"没有出现 {case['card']} 预览卡片")
    if case.get("no_card") and r.cards:
        out.append("不该出现预览卡片")
    for item in case.get("card_must", []):  # 改完的计划里必须有（§45）
        if not any(squash(a) in squash(r.card_plan) for a in _alternatives(item)):
            out.append(f"计划里缺少：{'/'.join(_alternatives(item))}")
    for item in case.get("card_must_not", []):
        if squash(str(item)) in squash(r.card_plan):
            out.append(f"计划里不该有：{item}")
    if "max_calls" in case and r.model_calls > int(case["max_calls"]):
        out.append(f"调用了 {r.model_calls} 次模型，超过 {case['max_calls']} 次")
    return out


# ---- 跑一道题 -------------------------------------------------------------------------------


async def run_case(
    case: Mapping[str, Any],
    persona: Persona,
    *,
    env: Mapping[str, str],
    today: date,
    mode: str,
    use_judge: bool,
) -> Result:
    r = Result(case["id"], case["cat"], persona.name, case["ask"])
    book = MemoryBook()
    if persona.memory:
        await book.apply(USER, [Change("insert", item=x) for x in persona.memory])
    training = TrainingBook()
    plan = Plan.model_validate(persona.plan) if persona.plan else None
    logs = [WorkoutLog.model_validate({"day": w["date"], **w}) for w in persona.workouts]
    training.seed(USER, plan, logs)
    rows = [
        row
        for t in case.get("history", [])
        for row in (
            {"role": "user", "content": t["user"]},
            {"role": "assistant", "content": t["coach"]},
        )
    ]

    async def snapshot(_: str) -> Snapshot:
        metrics = compute_all(persona.readings(), persona.profile, today)
        return Snapshot(persona.profile, persona.readings(), tuple(metrics), today)

    async def history(_: str, text: str) -> list[str]:
        return thread_lines(rows, text)

    async def sources(*_: str) -> str | None:
        return None

    async def earlier(_: str) -> str:
        return "\n".join(t["coach"] for t in case.get("history", []))

    seen: dict[str, Any] = {}
    agent = IronMAgent(
        health=EvalHealth(persona),
        models=load_models(),
        environ=env,
        snapshot=snapshot,
        memory=book,
        training=training,
        history=history,
        earlier=earlier,
        sources=sources,
        remember=False,
        mode=mode,  # type: ignore[arg-type]
        observe=seen.update,
        weather=no_weather,
        traces=TraceBook(),  # 运行框架的轨迹留在内存里，考试不写数据库
        illness=IllnessBook(),  # 生病记录也留在内存里（§46）
        day=DayBook(),  # 今日状态也留在内存里（§54）
    )
    start = time.perf_counter()
    try:
        session = f"{USER}:{case['id']}"
        msgs = [{"role": "user", "content": case["ask"]}]
        async for b in agent.generate_response(USER, msgs, session_id=session):
            kind = b.get("type")
            if kind == "text":
                r.answer += b.get("text", "")
            elif kind == "notice":
                r.notices.append(str(b.get("text", "")))
            elif kind == "error":
                r.error = str(b.get("message", ""))
            elif kind == "tool_call":
                if str(b.get("id", "")).startswith("card-"):
                    r.cards.append(str((b.get("args") or {}).get("kind", "")))
                elif b.get("id") not in ("sources", "turn"):  # turn 是这一轮的编号，页面不显示
                    r.steps.append(str(b.get("name", "")))
            elif kind == "tool_result" and b.get("tool_call_id") == "sources":
                r.sources = str(b.get("content", ""))
            elif kind == "tool_result" and str(b.get("tool_call_id", "")).startswith("card-"):
                r.card_text += card_text(str(b.get("content", "")))
                r.card_plan += card_plan(str(b.get("content", "")))
    except Exception as e:  # 跑考题时不让一道题的异常停掉整轮
        r.error = f"{type(e).__name__}: {e}"
    r.ms = int(seen.get("ms", (time.perf_counter() - start) * 1000))
    r.path = str(seen.get("path", ""))
    r.roles = [str(x) for x in seen.get("roles", [])]
    r.model_calls = int(seen.get("model_calls", 0))
    r.pro_tools = int(seen.get("pro_tools", 0))
    r.plan_check = str(seen.get("plan_check", ""))
    r.degraded = bool(seen.get("degraded", False))
    r.rewrites = int(seen.get("rewrites", 0))
    r.failures = grade(case, r, mode)
    if use_judge and r.path in JUDGED_PATHS and r.answer.strip():
        r.scores = await score(case, persona, judged(r), env=env, today=today)
    return r


async def no_weather(_: str) -> None:
    """考题里的人没有城市，不去取天气（不连网、不连数据库）。"""
    return None


def card_text(content: str) -> str:
    try:
        card = json.loads(content)
    except json.JSONDecodeError:
        return ""
    lines = [str(card.get("headline", ""))]
    lines += [f"{x['day']} {x['name']}：" + "、".join(x["items"]) for x in card.get("sessions", [])]
    lines += [str(x) for x in card.get("items", [])]
    return "\n".join(x for x in lines if x)


def card_plan(content: str) -> str:
    """卡片里改完的计划：每天一行"周几 名称：动作 组×次、……"。"""
    try:
        card = json.loads(content)
    except json.JSONDecodeError:
        return ""
    return "\n".join(
        f"{x['day']} {x['name']}：" + "、".join(x["items"]) for x in card.get("sessions", [])
    )


def judged(r: Result) -> str:
    """交给评委的回答：正文，加上预览卡片里的计划或记录（用户在卡片上看得到），以及系统给出的
    "依据与来源"（工具和指标计算从这个人的原始数据算出的数，评委据此核对，不当成编造）。"""
    out = r.answer
    if r.card_text:
        out += f"\n\n【回答下面附的预览卡片，用户确认后保存】\n{r.card_text}"
    if r.sources:
        out += f"\n\n【系统附的依据与来源：用户可以展开看；里面的数是系统从他的原始数据和资料算出来的】\n{r.sources}"
    return out


async def score(
    case: Mapping[str, Any], persona: Persona, answer: str, *, env: Mapping[str, str], today: date
) -> dict[str, Any]:
    memory = [x.content for x in persona.memory]
    history_text = "\n".join(
        f"用户：{t['user']}\n教练：{t['coach']}" for t in case.get("history", [])
    )
    return await judge(
        env,
        persona=persona_text(persona.desc, memory, persona.plan),
        facts=facts_text(persona, today, str(case["ask"])),
        history=history_text,
        ask=case["ask"],
        ref=str(case.get("ref", "")),
        answer=answer,
    )


# ---- 汇总 -----------------------------------------------------------------------------------


def _median(xs: Sequence[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def summarize(results: Sequence[Result]) -> dict[str, Any]:
    by_cat: dict[str, list[Result]] = defaultdict(list)
    for r in results:
        by_cat[r.cat].append(r)
    judged = [r for r in results if r.scores and "error" not in r.scores]
    dims = (
        {k: round(statistics.fmean(float(r.scores[k]) for r in judged), 2) for k in DIMENSIONS}
        if judged
        else {}
    )
    answered = [r for r in results if r.path in ("answer",)]
    one = [r.ms / 1000 for r in answered if len(r.roles) == 1]
    many = [r.ms / 1000 for r in answered if len(r.roles) > 1]
    safety = by_cat.get("safety", [])
    return {
        "cases": len(results),
        "rules_pass": round(sum(r.passed for r in results) / len(results), 3) if results else 0,
        "safety_pass": round(sum(r.passed for r in safety) / len(safety), 3) if safety else None,
        "by_category": {
            c: f"{sum(r.passed for r in rs)}/{len(rs)}" for c, rs in sorted(by_cat.items())
        },
        "judge": dims,
        "judge_mean": round(statistics.fmean(dims.values()), 2) if dims else None,
        "judged": len(judged),
        "seconds_median": round(_median([r.ms / 1000 for r in answered]), 1),
        "seconds_max": round(max((r.ms / 1000 for r in results), default=0), 1),
        "seconds_one_role": round(_median(one), 1),
        "seconds_many_roles": round(_median(many), 1),
        "model_calls_median": _median([r.model_calls for r in answered]),
        # 回答长度（spec [2026-10-23] §38）：正文字数，以及超过按问题类型定的上限的题数
        "chars_median": _median([len(squash(r.answer)) for r in answered]),
        "over_limit": sum(len(squash(r.answer)) > limit_of(r.ask) for r in answered),
        "degraded": sum(r.degraded for r in results),
        "errors": sum(bool(r.error) for r in results),
    }


def markdown(label: str, mode: str, summary: Mapping[str, Any], results: Sequence[Result]) -> str:
    s = summary
    lines = [
        f"# 问答考题报告：{label}（{'正式版' if mode == 'multi' else '单 Agent 对照组'}）",
        "",
        f"- 题数 {s['cases']}；规则通过率 {s['rules_pass']:.0%}；安全题通过率 " + (f"{s['safety_pass']:.0%}" if s["safety_pass"] is not None else "—"),
        f"- 评委均分 {s['judge_mean']}（{s['judged']} 道）：" + "，".join(f"{DIMENSIONS[k]} {v}" for k, v in s["judge"].items()),
        f"- 专业回答耗时中位 {s['seconds_median']} 秒（一位角色 {s['seconds_one_role']}，多位 {s['seconds_many_roles']}），最慢 {s['seconds_max']} 秒；每轮模型调用中位 {s['model_calls_median']} 次",
        f"- 降级 {s['degraded']} 次，出错 {s['errors']} 次",
        "",
        "| 类别 | 通过 |",
        "|---|---|",
        *[f"| {c} | {v} |" for c, v in s["by_category"].items()],
        "",
        "## 没通过的题",
        "",
    ]  # fmt: skip
    for r in results:
        if r.passed:
            continue
        lines.append(f"- **{r.id}**（{r.persona}）{r.ask}：{'；'.join(r.failures) or r.error}")
    lines += ["", "## 评委扣分较多的题（任一项 ≤ 3）", ""]
    for r in results:
        sc = r.scores
        if sc and "error" not in sc and min(float(sc[k]) for k in DIMENSIONS) <= 3:
            low = "，".join(f"{DIMENSIONS[k]} {sc[k]:g}" for k in DIMENSIONS if float(sc[k]) <= 3)
            lines.append(f"- **{r.id}** {r.ask}：{low}。{sc.get('comment', '')}")
    return "\n".join(lines) + "\n"


async def main() -> int:
    parser = argparse.ArgumentParser(description="跑问答考题")
    parser.add_argument("ids", nargs="*", help="只跑这几道（按编号）")
    parser.add_argument("--mode", choices=["multi", "single"], default="multi")
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--jobs", type=int, default=4, help="同时跑几道")
    parser.add_argument("--label", default="run", help="报告文件名里的标签")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每道题的回答")
    parser.add_argument(
        "--rejudge", metavar="JSON", help="不重新作答：对一份报告里的回答重新判分（规则与评委）"
    )
    args = parser.parse_args()

    env = load_env()
    data = load_yaml(CASES)
    today = date.fromisoformat(str(data["today"]))
    personas = load_personas(data["personas"], today)
    cases = [c for c in data["cases"] if not args.ids or c["id"] in args.ids]
    gate = asyncio.Semaphore(max(1, args.jobs))
    if args.rejudge:
        return await rejudge(Path(args.rejudge), cases, personas, env=env, today=today, gate=gate)

    async def one(case: Mapping[str, Any]) -> Result:
        async with gate:
            r = await run_case(
                case,
                personas[case.get("persona", "base")],
                env=env,
                today=today,
                mode=args.mode,
                use_judge=not args.no_judge,
            )
        mark = "✓" if r.passed else "✗"
        score = ""
        if r.scores and "error" not in r.scores:
            score = " 评委 " + "/".join(f"{float(r.scores[k]):g}" for k in DIMENSIONS)
        print(
            f"{mark} {r.id:4} {r.path:9} {r.ms / 1000:5.1f}s {r.model_calls:2d} 次 {','.join(r.roles):28}{score}  {'；'.join(r.failures)[:120]}"
        )
        if args.verbose:
            print(
                "   "
                + r.answer.replace("\n", "\n   ")
                + ("\n   [提示] " + "；".join(r.notices) if r.notices else "")
            )
        return r

    results = await asyncio.gather(*(one(c) for c in cases))
    summary = summarize(results)
    REPORTS.mkdir(exist_ok=True)
    stem = f"{today.isoformat()}-{args.label}-{args.mode}"
    (REPORTS / f"{stem}.json").write_text(
        json.dumps(
            {"summary": summary, "results": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=1,
        )
    )
    (REPORTS / f"{stem}.md").write_text(markdown(args.label, args.mode, summary, results))
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"报告：{REPORTS / stem}.md")
    ok = (
        (summary["safety_pass"] or 0) >= THRESHOLDS["safety"]
        and summary["rules_pass"] >= THRESHOLDS["rules"]
        and (summary["judge_mean"] is None or summary["judge_mean"] >= THRESHOLDS["judge"])
    )
    return 0 if ok else 1


async def rejudge(
    path: Path,
    cases: Sequence[Mapping[str, Any]],
    personas: Mapping[str, Persona],
    *,
    env: Mapping[str, str],
    today: date,
    gate: asyncio.Semaphore,
) -> int:
    """对一份旧报告里的回答重新判分（考题或评委改了之后，不用重新作答）。"""
    old = json.loads(path.read_text())
    mode = "single" if path.stem.endswith("-single") else "multi"
    by_id = {c["id"]: c for c in cases}
    keep = set(Result.__dataclass_fields__)
    results = [
        Result(**{k: v for k, v in r.items() if k in keep})
        for r in old["results"]
        if r["id"] in by_id
    ]

    async def one(r: Result) -> None:
        case = by_id[r.id]
        r.failures = grade(case, r, mode)
        if r.path in JUDGED_PATHS and r.answer.strip():
            async with gate:
                r.scores = await score(case, personas[r.persona], judged(r), env=env, today=today)
        else:
            r.scores = {}

    await asyncio.gather(*(one(r) for r in results))
    summary = summarize(results)
    stem = path.stem.replace(f"-{mode}", f"-rejudged-{mode}")
    label = stem.split("-", 3)[-1].rsplit("-", 1)[0]
    (REPORTS / f"{stem}.json").write_text(
        json.dumps(
            {"summary": summary, "results": [asdict(r) for r in results]},
            ensure_ascii=False,
            indent=1,
        )
    )
    (REPORTS / f"{stem}.md").write_text(markdown(label, mode, summary, results))
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"报告：{REPORTS / stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
