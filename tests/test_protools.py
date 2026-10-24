"""各角色专业工具（spec [2026-10-23] §12）：只算事实，不调用模型、不写数据。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from ironm_agent.exercises import library
from ironm_agent.frameworks import FRAMEWORKS, framework
from ironm_agent.metrics import Readings
from ironm_agent.protools.movement import equipment_of, find, moves, substitutes
from ironm_agent.protools.nutrition import nutrition
from ironm_agent.protools.pain import pain_check
from ironm_agent.protools.patterns import training_patterns
from ironm_agent.protools.plan_check import check_plan, estimate_minutes
from ironm_agent.protools.registry import TOOLS, ToolContext, allowed, render, run, tools_for
from ironm_agent.protools.result import Result
from ironm_agent.protools.strength import load_for, one_rep_max
from ironm_agent.protools.trends import trend
from ironm_agent.roles import EXPERTS, Role
from ironm_agent.training import LogItem, Plan, PlanItem, Session, StoredPlan, WorkoutLog

TODAY = date(2026, 10, 23)


def _text(r: Result) -> str:
    return "\n".join([*(f.detail() for f in r.findings), *r.notes])


def _plan(*sessions: tuple[int, str, list[tuple[str, int]]], minutes: int = 60) -> Plan:
    return Plan(
        title="测试计划",
        days_per_week=len(sessions),
        sessions=[
            Session(
                day=d,
                name=n,
                minutes=minutes,
                items=[PlanItem(exercise=e, sets=s, reps="8–12") for e, s in items],
            )
            for d, n, items in sessions
        ],
    )


# ---- 动作标注 ---------------------------------------------------------------------------------


def test_every_exercise_has_tags() -> None:
    assert len(moves()) == len(library().exercises)


def test_find_by_name() -> None:
    assert find("高脚杯深蹲") is not None and find("高脚杯深蹲").name == "高脚杯深蹲"  # type: ignore[union-attr]
    assert find("哑铃卧推 3×10").name == "哑铃卧推"  # type: ignore[union-attr]
    assert find("不存在的动作") is None


def test_equipment_of_memory() -> None:
    assert equipment_of([]) is None
    assert equipment_of(["家里只有一对 20 公斤哑铃和弹力带"]) == frozenset(
        {"自重", "哑铃", "弹力带"}
    )
    assert "杠铃" in (equipment_of(["在健身房练"]) or frozenset())


def test_substitutes_respect_equipment_and_injury() -> None:
    r = substitutes("杠铃深蹲", equipment=frozenset({"自重", "哑铃"}), injured=("knee",))
    text = _text(r)
    assert "箱式深蹲" in text  # 照顾膝盖、只用自重或哑铃
    assert "波比跳" not in text and "保加利亚分腿蹲" not in text  # 跳跃、给膝盖加负担的不出现
    assert "腿举" not in text  # 需要器械
    assert "不给膝盖加负担" in text
    assert r.entries[0] == find("杠铃深蹲").ref  # type: ignore[union-attr]


def test_substitutes_unknown_exercise() -> None:
    assert "没有" in _text(substitutes("火箭推", equipment=None))


# ---- 力量 -----------------------------------------------------------------------------------


def test_one_rep_max_epley() -> None:
    r = one_rep_max(60, 8)
    assert "约 76 公斤（Epley）" in r.findings[0].text
    assert "Brzycki" in r.findings[0].text
    assert one_rep_max(60, 20).findings == ()  # 次数太多不估


def test_load_for_target_reps() -> None:
    r = load_for(8, 2, max_kg=100)
    # 100 ÷ (1 + 10/30) = 75，取 2.5 的整数倍
    assert "约 75 公斤" in r.findings[0].text and "RPE 8" in r.findings[0].text
    r2 = load_for(8, 2, weight=60, reps=8)
    assert "最近一组 60 公斤 × 8 次" in r2.findings[0].data
    assert load_for(10, 4, max_kg=100).findings == ()  # 加起来超过 12 次


# ---- 计划检查 ---------------------------------------------------------------------------------


def test_check_plan_volume_and_frequency_for_muscle() -> None:
    plan = _plan(
        (1, "全身", [("高脚杯深蹲", 3), ("哑铃卧推", 3), ("单臂哑铃划船", 3)]),
        (4, "全身", [("罗马尼亚硬拉", 3), ("俯卧撑", 3)]),
    )
    r = check_plan(plan, goal="muscle")
    text = _text(r)
    assert "每周 10 组以上" in text and "胸 6 组" in text
    assert "至少练 2 次" in text and "背" in text  # 背只练了 1 次


def test_check_plan_injury_equipment_time() -> None:
    plan = _plan(
        (1, "下肢", [("波比跳", 3), ("杠铃卧推", 4), ("箱式深蹲", 3)]),
        (3, "上肢", [("单臂哑铃划船", 3)]),
        minutes=30,
    )
    r = check_plan(
        plan, injured=("knee",), equipment=frozenset({"自重", "哑铃"}), available_minutes=30
    )
    text = _text(r)
    assert "波比跳" in text and "膝盖有伤" in text
    assert "箱式深蹲〔" not in text.split("计划检查")[1].split("提示")[0]  # 箱式深蹲本身照顾膝盖
    assert "杠铃卧推需要杠铃" in text
    assert "超过了 30 分钟" in text


def test_check_plan_limited_injury_note_is_ok() -> None:
    plan = Plan(
        title="下肢",
        days_per_week=1,
        sessions=[
            Session(
                day=2,
                name="下肢",
                items=[
                    PlanItem(
                        exercise="高脚杯深蹲", sets=3, reps="10", note="蹲到不疼的深度，控制幅度"
                    )
                ],
            )
        ],
    )
    assert "有伤" not in _text(check_plan(plan, injured=("knee",)))


def test_check_plan_novice_and_back_to_back() -> None:
    plan = _plan(
        (1, "胸", [("哑铃卧推", 5)]),
        (2, "胸", [("俯卧撑", 3)]),
        (4, "腿", [("高脚杯深蹲", 3)]),
        (6, "背", [("单臂哑铃划船", 3)]),
    )
    text = _text(check_plan(plan, novice=True))
    assert "新手每周练 2–3 天" in text
    assert "哑铃卧推 5 组" in text
    assert "连续两天" in text and "胸" in text


def test_check_plan_diff_with_current() -> None:
    old = _plan(
        (1, "下肢", [("高脚杯深蹲", 3)]),
        (3, "上肢", [("哑铃卧推", 3)]),
        (5, "全身", [("俯卧撑", 3)]),
    )
    new = _plan((1, "下肢", [("高脚杯深蹲", 3)]), (3, "背", [("单臂哑铃划船", 3)]))
    diff = next(f for f in check_plan(new, current=old).findings if f.name == "和当前计划相比")
    assert "周三" in diff.text and "「上肢」改为「背」" in diff.text
    assert "周五去掉「全身」" in diff.text and "周一" not in diff.text


def test_estimate_minutes() -> None:
    s = Session(
        day=1,
        name="x",
        minutes=45,
        items=[
            PlanItem(exercise="高脚杯深蹲", sets=4, reps="8"),
            PlanItem(exercise="哑铃弯举", sets=2, reps="12"),
        ],
    )
    assert estimate_minutes(s) == 10 + 4 * 3.5 + 2 * 2.5


# ---- 训练规律 ---------------------------------------------------------------------------------


def _logs(days_ago: list[int], **kw: object) -> list[WorkoutLog]:
    return [WorkoutLog(day=TODAY - timedelta(days=d), minutes=40, rpe=7, **kw) for d in days_ago]  # type: ignore[arg-type]


def test_patterns_enough_data() -> None:
    logs = _logs([1, 4, 8, 11, 15, 18, 22, 25])
    r = training_patterns(logs, TODAY, days=28)
    text = _text(r)
    assert "完成 8 次" in text and "每周 2.0 次" in text
    assert "每次平均 40 分钟" in text and "感受平均 7.0 分" in text


def test_patterns_not_enough_data() -> None:
    r = training_patterns(_logs([1, 3, 5]), TODAY)
    assert "数据不足" in r.findings[0].text and "还差 3 次" in r.findings[0].text
    assert len(r.findings) == 1  # 不给规律


def test_patterns_completion_rate() -> None:
    plan = _plan((1, "a", [("俯卧撑", 3)]), (4, "b", [("俯卧撑", 3)]))  # 周一、周四
    mondays_thursdays = [d for d in range(28) if (TODAY - timedelta(days=d)).isoweekday() in (1, 4)]
    logs = _logs(mondays_thursdays[:6])
    r = training_patterns(logs, TODAY, plan=plan, plan_since=TODAY - timedelta(days=27))
    rate = next(f for f in r.findings if f.name == "按计划的完成率")
    assert "该练 8 次" in rate.text and "当天练了 6 次" in rate.text and "75%" in rate.text


def test_patterns_skipped_exercise() -> None:
    plan = _plan((1, "a", [("高脚杯深蹲", 3), ("后撤弓步", 3)]), (4, "b", [("高脚杯深蹲", 3)]))
    days = [d for d in range(28) if (TODAY - timedelta(days=d)).isoweekday() in (1, 4)]
    logs = [
        WorkoutLog(day=TODAY - timedelta(days=d), items=[LogItem(exercise="高脚杯深蹲", sets=3)])
        for d in days
    ]
    r = training_patterns(logs, TODAY, plan=plan)
    skipped = next(f for f in r.findings if f.name == "常跳过的动作")
    assert "后撤弓步" in skipped.text


# ---- 营养 -----------------------------------------------------------------------------------


def test_nutrition_protein_and_supplements() -> None:
    r = nutrition(70, goal="muscle", items=["protein", "creatine", "caffeine"])
    text = _text(r)
    assert "每天约 112–140 克" in text  # 增肌 1.6–2.0 克/公斤，与数据页同一份系数
    assert "每餐约 18–28 克" in text
    assert "每天 3–5 克" in text
    assert "210–420 毫克" in text
    assert "不推荐品牌" in text


def test_nutrition_needs_weight_and_minutes() -> None:
    assert "没有体重记录" in _text(nutrition(None))
    assert "每天练多久" in _text(nutrition(70, items=["carbs"]))
    assert "350–490 克" in _text(nutrition(70, items=["carbs"], training_minutes=60))
    # 热量目标容纳不下按训练量的碳水时，以热量目标为准
    tight = _text(
        nutrition(70, goal="fat_loss", items=["carbs"], training_minutes=60, kcal_target=1466)
    )
    assert "以热量目标为准" in tight and "剩下约 906–1018 千卡" in tight
    assert "98–112" in _text(nutrition(70, items=["protein"]))  # 没有目标时 1.4–1.6


# ---- 疼痛 -----------------------------------------------------------------------------------


def test_pain_levels() -> None:
    assert "可以继续" in pain_check(3).findings[0].text
    assert "第二天早上前消退" in pain_check(3).findings[0].text
    assert "减量" in pain_check(6).findings[0].text
    assert "立即就医" in pain_check(3, ["numbness"]).findings[0].text
    assert "立即就医" in pain_check(2, ["cannot_bear"]).findings[0].text
    assert "看医生" in pain_check(9).findings[0].text
    assert pain_check(None).findings == ()  # 没打分时先问
    assert any("立即就医" in n for n in pain_check(3).notes)  # 总是写明什么时候要就医


# ---- 趋势 -----------------------------------------------------------------------------------


def test_trend_uses_asked_range() -> None:
    points = tuple((TODAY - timedelta(days=d), 72.0 - 0.02 * (59 - d)) for d in range(0, 90))
    r = trend(points, TODAY, indicator="weight", days=60)
    assert "最近 60 天" in r.findings[0].name
    assert "记录 60 条" in r.findings[0].data
    change = r.findings[1].text
    assert "明显下降" in change


def test_trend_flat_and_missing() -> None:
    noisy = tuple((TODAY - timedelta(days=d), 60.0 + (1 if d % 2 else -1)) for d in range(28))
    assert "基本持平" in trend(noisy, TODAY, indicator="resting_hr", days=28).findings[1].text
    short = tuple((TODAY - timedelta(days=d), 60.0) for d in range(5))
    r = trend(short, TODAY, indicator="resting_hr", days=28)
    assert len(r.findings) == 1 and "至少要 14 天" in r.notes[0]
    assert "不能推测为正常" in _text(trend((), TODAY, indicator="sleep_hours", days=7))


# ---- 清单与角色 ---------------------------------------------------------------------------------


def test_tools_only_for_listed_roles() -> None:
    assert {t.name for t in tools_for("trainer")} == {
        "estimate_strength",
        "check_plan",
        "training_patterns",
        "find_substitutes",
        "trend_analysis",
    }
    assert {t.name for t in tools_for("nutrition")} == {"nutrition_calc", "trend_analysis"}
    assert {t.name for t in tools_for("recovery")} == {
        "training_patterns",
        "find_substitutes",
        "pain_check",
        "trend_analysis",
    }
    assert not allowed("nutrition", "check_plan") and allowed("trainer", "check_plan")
    assert not allowed("trainer", "pain_check")  # 疼痛由康复恢复师判断
    assert {t.name for t in tools_for("general")} == set(TOOLS)


def test_render_assigns_calc_ids_by_role() -> None:
    calcs = {"C0": "基本", "C3": "x"}
    entries: dict[str, object] = {}
    from ironm_agent.exercises import library_entries

    lib = {e.id: e for e in library_entries()}
    text = render(
        substitutes("杠铃深蹲", equipment=None),
        role="recovery",
        calcs=calcs,
        entries=entries,
        library=lib,
    )  # type: ignore[arg-type]
    assert "可以换成" in text and entries  # 动作库条目记为依据
    text2 = render(one_rep_max(60, 8), role="recovery", calcs=calcs, entries=entries, library=lib)  # type: ignore[arg-type]
    assert text2.startswith("[C68]") and "C68" in calcs  # 康复恢复师用自己的编号段
    text3 = render(one_rep_max(60, 8), role="trainer", calcs=calcs, entries=entries, library=lib)  # type: ignore[arg-type]
    assert text3.startswith("[C20]")
    text4 = render(one_rep_max(50, 5), role="recovery", calcs=calcs, entries=entries, library=lib)  # type: ignore[arg-type]
    assert text4.startswith("[C69]")


def test_registry_runs_with_context() -> None:
    plan = _plan((1, "a", [("俯卧撑", 3)]))
    stored = StoredPlan("p1", plan, __import__("datetime").datetime(2026, 10, 1, 8))

    async def get_plan() -> StoredPlan:
        return stored

    async def workouts(since: date) -> list[WorkoutLog]:
        return []

    ctx = ToolContext.build(
        TODAY, goal="muscle", weight_kg=70.0, readings=Readings(), injured=["knee"],
        equipment_said=["只有哑铃"], plan=get_plan, workouts=workouts,
    )  # fmt: skip
    r = asyncio.run(run("nutrition_calc", ctx, {"items": ["protein"]}))
    assert "112–140" in _text(r) and "最新的体重记录" in _text(r)
    r = asyncio.run(run("check_plan", ctx, {"plan": plan.model_dump(mode="json")}))
    assert any(f.name == "和当前计划相比" for f in r.findings)
    r = asyncio.run(run("training_patterns", ctx, {}))
    assert "数据不足" in _text(r)
    r = asyncio.run(run("trend_analysis", ctx, {"indicator": "weight", "days": 60}))
    assert "没有体重记录" in _text(r)
    r = asyncio.run(run("check_plan", ctx, {"plan": {"title": "x"}}))
    assert "格式不对" in _text(r)


# ---- 思考框架 ---------------------------------------------------------------------------------


def test_each_role_has_its_own_framework() -> None:
    for role in EXPERTS:
        assert framework(role), role
    assert "训练计划" in FRAMEWORKS[Role.TRAINER] and "check_plan" in FRAMEWORKS[Role.TRAINER]
    assert all("trend_analysis" in FRAMEWORKS[r] for r in EXPERTS)  # 数据归各自领域解读
    assert "pain_check" in FRAMEWORKS[Role.RECOVERY]


def test_check_plan_flags_unlimited_squat_for_knee() -> None:
    plan = Plan(
        title="下肢",
        days_per_week=1,
        sessions=[
            Session(day=2, name="下肢", items=[PlanItem(exercise="高脚杯深蹲", sets=3, reps="10")])
        ],
    )
    text = _text(check_plan(plan, injured=("knee",)))
    assert "高脚杯深蹲" in text and "膝盖有伤" in text
