"""回归回放集（spec [2026-10-23] §138）：后台用例的准备和判断、报告、和以前的结果比。不连网、不调用真实模型。"""

from __future__ import annotations

import asyncio
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from evals.replay import agent
from evals.replay.report import Row, baseline, compare, exit_code, load, render, save
from ironm_agent.llm import Reply
from ironm_agent.metrics import Profile
from tests.fakes import FakeLLM, call

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "evals" / "replay" / "cases.yaml").read_text())
ME = Profile(**{**SPEC["profile"], "birth": date.fromisoformat(str(SPEC["profile"]["birth"]))})
TODAY = date(2026, 11, 3)


def case(cid: str) -> dict[str, Any]:
    return next(c for c in SPEC["agent"] if c["id"] == cid)


def test_readings_recent_and_usual() -> None:
    r = agent.readings(
        {"sleep_hours": {"recent": 5.0, "usual": 7.4, "days": 10, "recent_days": 2}}, TODAY
    )
    vals = dict(r.sleep_hours)
    assert (
        len(r.sleep_hours) == 10 and vals[TODAY] == 5.0 and vals[TODAY - timedelta(days=1)] == 5.0
    )
    assert vals[TODAY - timedelta(days=2)] == 7.4  # 没写 wiggle：平时不波动
    try:
        agent.readings({"blood": {"recent": 1}}, TODAY)
    except ValueError as e:
        assert "不认识" in str(e)
    else:
        raise AssertionError("不认识的数据应报错")


def test_every_agent_case_builds_its_state() -> None:
    """清单里每条后台用例都能准备出状态：种类认得、计划今天有训练、next 用例最后一条是今天。"""
    assert {c["kind"] for c in SPEC["agent"]} <= set(agent.KINDS)
    for c in SPEC["agent"]:
        dp, logs = asyncio.run(agent.deps_for(c, ME, TODAY))
        stored = asyncio.run(dp.training.plan(agent.USER))
        assert stored is not None and stored.plan.session_on(TODAY) is not None, c["id"]
        if c["kind"] == "next":
            assert logs[-1].day == TODAY, c["id"]


def test_judge_checkup() -> None:
    j = agent.judge_checkup
    assert j({"done": ["today"]}, ["today"], "睡得少，今天按七成", False) == []
    assert "该有「today」" in j({"done": ["today"]}, [], "", False)[0]
    assert "不该有「propose」" in j({"not_done": ["propose"]}, ["propose"], "", False)[0]
    assert j({"any": False}, ["note"], "", False) and j({"any": True}, [], "", False)
    assert "没说到「睡 / 心率」" in j({"summary_must": [["睡", "心率"]]}, [], "都正常", False)[0]
    assert "算失败" in j({}, ["note"], "", True)[0]  # 失败一律不符合


def test_judge_next() -> None:
    j = agent.judge_next
    assert (
        j({"targets": {"深蹲": ["hold", "down"]}}, {"深蹲": "hold"}, {"深蹲": "膝盖不舒服"}, 0)
        == []
    )
    assert "应为 up / rule" in j({"targets": {"深蹲": ["up", "rule"]}}, {"深蹲": "down"}, {}, 0)[0]
    assert j({"targets": {"深蹲": ["up", "rule"]}}, {}, {}, 0) == []  # 没定：照规则
    assert j({"targets": {"深蹲": "not_up"}}, {}, {}, 0) == [] and j(
        {"targets": {"深蹲": "not_up"}}, {"深蹲": "up"}, {}, 0
    )
    assert (
        "没说到「膝」"
        in j({"why_must": {"深蹲": [["膝"]]}}, {"深蹲": "hold"}, {"深蹲": "累了"}, 0)[0]
    )
    assert j({"why_must": {"深蹲": [["膝"]]}}, {}, {}, 0) == []  # 没定就没有说明，不查
    assert (
        "出现了「加重」"
        in j({"why_must_not": {"深蹲": ["加重"]}}, {"深蹲": "hold"}, {"深蹲": "先别加重"}, 0)[0]
    )
    assert "退回最多 0 次" in j({"rejected": 0}, {}, {}, 2)[0]


def test_next_case_runs_end_to_end_with_a_fake_model() -> None:
    """假管家：深蹲保持 60（说明带膝盖）→ 符合；工具和退回次数记下。"""
    turns = iter([
        call("set_next_target", exercise="杠铃深蹲", weight_kg=70, reps="6–8", sets=4, why="加"),  # 超过一成：退回
        call("set_next_target", exercise="杠铃深蹲", weight_kg=60, reps="6–8", sets=4, why="膝盖不舒服先保持"),
    ])  # fmt: skip

    def answer(*_: Any) -> Reply:
        return next(turns, Reply("深蹲先保持"))

    res = asyncio.run(agent.run_case(case("next-hard-knee"), ME, FakeLLM(answer), TODAY))
    assert res.tools == ["set_next_target", "set_next_target"] and res.detail["rejected"] == 1
    assert res.detail["moves"] == {"杠铃深蹲": "hold"}
    assert res.bad == ["被退回最多 0 次，实际 1 次"]


def test_checkup_case_runs_end_to_end_and_reports_what_was_missing() -> None:
    def answer(*_: Any) -> Reply:
        return Reply(json.dumps({"summary": "都正常"}, ensure_ascii=False))

    res = asyncio.run(agent.run_case(case("checkup-tired"), ME, FakeLLM(answer), TODAY))
    assert res.answer == "都正常" and res.tools == [] and res.detail["done"] == []
    assert any("该有「today」" in b for b in res.bad)
    broken = asyncio.run(agent.run_case({"id": "x", "kind": "nope"}, ME, FakeLLM(answer), TODAY))
    assert broken.bad == ["不认识的种类：nope"]


def test_a_crash_is_a_failed_row_not_an_exception() -> None:
    def boom(*_: Any) -> Reply:
        raise RuntimeError("模型挂了")

    for cid in ("checkup-normal", "checkup-one-signal", "next-easy", "next-hard-knee"):
        res = asyncio.run(agent.run_case(case(cid), ME, FakeLLM(boom), TODAY))
        assert "模型调用出错：RuntimeError" in res.bad, cid  # 被吞掉的错也不算符合（审查 11-03）
    bad_setup = {"id": "y", "kind": "checkup", "setup": {"readings": {"blood": {"recent": 1}}}}
    res = asyncio.run(agent.run_case(bad_setup, ME, FakeLLM(boom), TODAY))
    assert res.bad == ["运行出错：ValueError"]


def rows(*spec: tuple[str, int, bool, float]) -> list[Row]:
    return [
        Row(case=c, turn=t, say=f"{c}-{t}", ok=ok, bad=[] if ok else ["没说到"], secs=s)
        for c, t, ok, s in spec
    ]


def test_report_saves_loads_and_builds_the_baseline(tmp_path: Path) -> None:
    first = save(rows(("a", 1, True, 3.0)), "基线 v1", tmp_path, datetime(2026, 11, 3, 9, 0, 0))
    second = save(rows(("a", 1, False, 4.0)), "", tmp_path, datetime(2026, 11, 3, 10, 0, 0))
    assert first.name == "2026-11-03-090000-基线v1.json" and second.name == "2026-11-03-100000.json"
    assert load(first)[0].ok and not load(second)[0].ok and load(second)[0].bad == ["没说到"]
    old, used = baseline(tmp_path, before=second)
    assert [r.ok for r in old] == [True] and used == [first.name]
    assert baseline(tmp_path, before=first) == ([], []) and baseline(tmp_path / "none") == ([], [])


def test_a_partial_run_does_not_hide_the_older_full_run(tmp_path: Path) -> None:
    """完整跑 → 只跑一部分 → 再完整跑：每轮都和最近一次跑过它的比，变差照样列出（审查 11-03）。"""
    save(
        rows(("chat", 1, True, 1.0), ("agent", 1, True, 1.0)),
        "",
        tmp_path,
        datetime(2026, 11, 3, 9, 0, 0),
    )
    save(rows(("agent", 1, True, 2.0)), "", tmp_path, datetime(2026, 11, 3, 10, 0, 0))
    (tmp_path / "2026-11-03-103000.json").write_text("坏的")
    now = save(
        rows(("chat", 1, False, 1.0), ("agent", 1, True, 1.0)),
        "",
        tmp_path,
        datetime(2026, 11, 3, 11, 0, 0),
    )
    old, used = baseline(tmp_path, before=now)
    assert {r.key: r.secs for r in old} == {
        ("agent", 1): 2.0,
        ("chat", 1): 1.0,
    }  # agent 取较新的那次
    assert used == ["2026-11-03-100000.json", "2026-11-03-090000.json"]
    d = compare(old, load(now))
    assert [n.key for _, n in d.worse] == [("chat", 1)] and exit_code(load(now), d) == 1


def test_compare_lists_worse_better_added_removed_and_time() -> None:
    old = rows(
        ("a", 1, True, 10.0), ("a", 2, False, 10.0), ("b", 1, True, 5.0), ("gone", 1, True, 1.0)
    )
    new = rows(
        ("a", 1, False, 12.0), ("a", 2, True, 8.0), ("b", 1, True, 10.0), ("new", 1, True, 99.0)
    )
    d = compare(old, new)
    assert [n.key for _, n in d.worse] == [("a", 1)] and [n.key for _, n in d.better] == [("a", 2)]
    assert [r.case for r in d.added] == ["new"] and [r.case for r in d.removed] == ["gone"]
    assert d.secs == (25.0, 30.0) and d.regressed  # 耗时只算两边都有的轮
    text = render(d, "old.json")
    assert "✗ 变差：a 第 1 轮" in text and "✓ 变好：a 第 2 轮" in text and "+20%" in text
    assert "+ 新加：new" in text and "- 这次没跑：gone" in text
    same = compare(old, old)
    assert not same.regressed and "符不符合都和上次一样" not in render(
        same, "x"
    )  # a 第 2 轮还是不符合
    assert "· 还是不符合：a 第 2 轮" in render(same, "x")


def test_exit_codes() -> None:
    ok, bad = rows(("a", 1, True, 1.0)), rows(("a", 1, False, 1.0))
    assert exit_code(ok, None) == 0 and exit_code(bad, None) == 3
    assert exit_code(bad, compare(ok, bad)) == 1 and exit_code(bad, compare(bad, bad)) == 3


def test_reports_are_not_committed_and_make_has_the_targets() -> None:
    assert "evals/replay/reports/" in (ROOT / ".gitignore").read_text()
    make = (ROOT / "Makefile").read_text()
    assert "replay:" in make and "replay-agent:" in make and "--agent-only" in make


def test_rejections_in_the_last_round_are_counted() -> None:
    """往返到上限、最后一轮的工具结果后面没有再调模型：也要数进被退回的次数。"""
    bad = call("set_next_target", exercise="杠铃深蹲", weight_kg=90, reps="6–8", sets=4, why="加")

    def answer(*_: Any) -> Reply:
        return bad

    res = asyncio.run(agent.run_case(case("next-easy"), ME, FakeLLM(answer), TODAY))
    assert res.detail["rejected"] == 4 and "实际 4 次" in res.bad[-1]


def test_moves_tell_more_reps_from_hold() -> None:
    from ironm_agent.progression import Decided
    from ironm_agent.training import PlanItem

    item = PlanItem(exercise="深蹲", sets=4, reps="6–8")

    def d(w: float | None, sets: int = 4, reps: str = "6–8") -> Decided:
        return Decided(exercise="深蹲", sets=sets, reps=reps, weight_kg=w, why="x", after=TODAY)

    assert agent.move(d(62.5), 60, item) == "up" and agent.move(d(55), 60, item) == "down"
    assert (
        agent.move(d(60, reps="8–10"), 60, item) == "more"
        and agent.move(d(60, sets=5), 60, item) == "more"
    )
    assert agent.move(d(60), 60, item) == "hold" and agent.move(d(None), None, item) == "hold"


def test_readings_by_trend() -> None:
    r = agent.readings({"weight": {"recent": 78.2, "trend": -0.6, "days": 15}}, TODAY)
    vals = dict(r.weight)
    assert (
        vals[TODAY] == 78.2
        and vals[TODAY - timedelta(days=7)] == 78.8
        and vals[TODAY - timedelta(days=14)] == 79.4
    )


def test_case_ids_are_unique_across_chat_and_agent() -> None:
    ids = [c["id"] for c in [*SPEC["cases"], *SPEC["agent"]]]
    assert len(ids) == len(set(ids))


def test_a_timeout_is_not_a_pass() -> None:
    """超时被取消（CancelledError 不是 Exception）：也算模型调用出错（复核 11-03）。"""
    from ironm_agent import next_targets

    seen: list[int] = []

    class Hang:
        def __init__(self) -> None:
            self.calls: list[Any] = []

        async def chat(self, *_: Any, **__: Any) -> Reply:
            seen.append(1)
            await asyncio.sleep(5)
            raise AssertionError("不该等到这里")

    old = next_targets.TIMEOUT_S
    next_targets.TIMEOUT_S = 0.05
    try:
        res = asyncio.run(agent.run_case(case("next-easy"), ME, Hang(), TODAY))  # type: ignore[arg-type]
    finally:
        next_targets.TIMEOUT_S = old
    assert seen and "模型调用出错：CancelledError" in res.bad


def test_chat_judge_checks_memory_counts() -> None:
    """对话用例能查各类有效记忆的条数（§145）。"""
    spec = importlib.util.spec_from_file_location("replay_script", ROOT / "scripts" / "replay.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    turn = {"memory": {"injury": 1, "equipment": 1}}
    assert mod.judge(turn, "好", [], None, None, {"injury": 1, "equipment": 1}) == []
    bad = mod.judge(turn, "好", [], None, None, {"injury": 2})
    assert (
        "有效的 injury 记忆应有 1 条，实际 2 条" in bad
        and "有效的 equipment 记忆应有 1 条，实际 0 条" in bad
    )


def test_chat_judge_checks_memory_keys() -> None:
    """对话用例能查记忆的键（§148：伤病记成部位+左右、特殊情况记成代码）。"""
    spec = importlib.util.spec_from_file_location("replay_script", ROOT / "scripts" / "replay.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    keyed = {"memory_keys": ["injury:joint.knee:左"]}
    assert mod.judge(keyed, "好", [], None, None, None, {"injury:joint.knee:左"}) == []
    assert mod.judge(keyed, "好", [], None, None, None, set()) == [
        "应有记忆键 injury:joint.knee:左，没有"
    ]


def test_chat_judge_checks_the_gear_page() -> None:
    """对话用例能查器械页上有哪些（§150）。"""
    spec = importlib.util.spec_from_file_location("replay_script", ROOT / "scripts" / "replay.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    want = {"gear": ["哑铃", "壶铃"]}
    assert mod.judge(want, "好", [], None, None, None, None, {"哑铃", "壶铃", "弹力带"}) == []
    assert mod.judge(want, "好", [], None, None, None, None, {"哑铃"}) == ["器械页少了 壶铃"]
