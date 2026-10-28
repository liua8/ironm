"""约束核对（spec [2026-10-23] §4）：伤病与动作、状态与强度、血压、孕期、热量下限、减重速度。"""

from datetime import date

from ironm_agent.casefile import CaseFile, Readiness, Risk
from ironm_agent.constraints import Context, annotate, annotate_plan, check, fixes
from ironm_agent.metrics import Profile

KNEE = Context(injuries=("joint.knee",))


def kinds(text: str, ctx: Context) -> list[str]:
    return [v.kind for v in check(text, ctx)]


def test_knee_squat_without_a_limit_is_flagged() -> None:
    assert kinds("高脚杯深蹲 3 组，每组 10 次", KNEE) == ["knee"]
    assert kinds("热身：原地踏步或开合跳", KNEE) == ["knee"]


def test_written_limits_are_fine() -> None:
    for ok in (
        "箱式深蹲 3 组，蹲到不疼的深度",
        "高脚杯深蹲只做到不疼的深度",
        "先别做跳跃动作",
        "要绕开深蹲到底的动作",
        "保加利亚分腿蹲换成臀桥",
        "心跳加快是正常的",  # 心跳不是跳跃
    ):
        assert kinds(ok, KNEE) == [], ok


def test_one_overall_statement_covers_the_list() -> None:
    covered = "膝盖有伤，所有蹲类动作只蹲到不疼的深度。高脚杯深蹲 3 组，弓步 3 组。"
    assert kinds(covered, KNEE) == []
    # 说了"先别做跳跃"不等于说过深蹲怎么做；说了深蹲的限制也不等于照顾到了跳跃
    assert kinds("膝盖有伤，先别做跳跃。高脚杯深蹲 3 组。", KNEE) == ["knee"]
    assert kinds("膝盖有伤，蹲到不疼的深度。热身做开合跳。", KNEE) == ["knee"]
    # 注明一处之后，同类动作不再逐个重复
    marked = annotate("高脚杯深蹲 3 组。弓步 3 组。开合跳 1 分钟。", KNEE)
    assert marked.count("（膝盖有伤") == 2 and check(marked, KNEE) == []


def test_every_violating_clause_is_listed_for_the_rewrite() -> None:
    [v] = check("今天做深蹲 3 组。再做弓步 3 组。", KNEE)
    assert "深蹲" in v.detail and "弓步" in v.detail


def test_poor_readiness_blocks_heavy_or_all_out_work() -> None:
    poor = Context(poor=True)
    assert kinds("今天可以冲一下大重量", poor) == ["readiness"]
    assert kinds("今天做 4 组力竭", poor) == ["readiness"]
    assert kinds("今天别上大重量，改成轻松版", poor) == []
    assert kinds("今天可以冲一下大重量", Context()) == []  # 状态好时不限制


def test_blood_pressure_and_pregnancy() -> None:
    high = Context(risks=frozenset({"bp_high"}))
    assert kinds("可以试试大重量深蹲", high) == ["blood_pressure"]
    assert kinds("发力时呼气，不要憋气", high) == []
    # "吸一口气憋住"也是憋气发力（体感讲解里"肚子像要挨一拳那样绷住"常和它连着说）
    assert kinds("蹲之前吸一口气憋住，肚子像要挨一拳那样绷住", high) == ["blood_pressure"]
    assert kinds("肚子像要挨一拳那样绷住，别憋住气", high) == []
    preg = Context(risks=frozenset({"pregnancy"}))
    assert kinds("可以做仰卧卷腹 3 组", preg) == ["pregnancy"]
    assert kinds("卷腹改成侧卧抬腿", preg) == []
    assert kinds("站着推举时屏住呼吸再发力", preg) == ["pregnancy"]


def test_calorie_floor_and_weight_loss_rate() -> None:
    male = Context(floor=1500)
    assert kinds("建议每天吃 1200 千卡", male) == ["calories"]
    assert kinds("每天摄入 1300–1600 千卡", male) == ["calories"]  # 按范围的下限算
    assert kinds("每天吃 1800 千卡左右", male) == []
    assert kinds("每天比消耗少吃 500 千卡", male) == []  # 说的是缺口，不是摄入
    assert kinds("加餐 200 千卡就够", male) == []  # 一餐的量
    assert kinds("每周减 2 公斤", Context()) == ["weight_rate"]
    assert kinds("一周瘦 3 斤", Context()) == ["weight_rate"]
    assert kinds("每周减 0.5–1 公斤", Context()) == []
    assert kinds("每周减重别超过 1 公斤", Context()) == []


def test_annotate_writes_the_limit_next_to_each_violation() -> None:
    ctx = Context(injuries=("joint.knee", "joint.lumbar"), poor=True, floor=1500)
    text = "热身做开合跳。高脚杯深蹲 3 组，大重量硬拉 5 组。每天吃 1200 千卡。每周减 2 公斤。"
    marked = annotate(text, ctx)
    assert (
        "开合跳（膝盖有伤：跳跃先别做）" in marked
        and "深蹲（膝盖有伤：只做到不疼的深度）" in marked
    )
    assert "硬拉（腰有伤" in marked and "1200 千卡（太低了：每天不要低于 1500 千卡）" in marked
    assert "每周减 2 公斤（太快了" in marked
    assert check(marked, ctx) == []
    assert annotate("今天练臀桥 3 组", ctx) == "今天练臀桥 3 组"  # 没问题的不动


def test_context_from_case_file() -> None:
    case = CaseFile(
        basics="", limits=(), readiness=Readiness("poor"), risks=(Risk("bp_high", "…"),), calcs={},
        calc_lines=(), injuries=("joint.knee",), profile=Profile(sex="male", birth=date(1990, 1, 1)), bmr=1699.4,
    )  # fmt: skip
    ctx = Context.of(case)
    assert ctx.poor and ctx.injuries == ("joint.knee",) and ctx.risks == {"bp_high"} and ctx.floor == 1699
    assert (
        Context.of(case.__class__(**{**case.__dict__, "bmr": None, "profile": Profile()})).floor
        == 1200
    )
    assert "膝盖" in fixes(check("做深蹲 3 组", ctx))


def test_vague_words_elsewhere_do_not_count_as_a_limit() -> None:
    """独立审查：同一分句或下一分句里出现"不、别、等"就算写了限制，会漏判。"""
    poor = Context(poor=True)
    assert kinds("今天做深蹲、硬拉等大重量动作，5 组", poor) == ["readiness"]
    assert kinds("深蹲 4 组，别忘了喝水", KNEE) == ["knee"]
    assert kinds("每周减重约 1.5 公斤", Context()) == ["weight_rate"]
    # 具体的写法在紧跟的分句里仍然算；泛泛的词在动作前面或紧跟在后面也算
    assert kinds("深蹲 3 组，蹲到不疼的深度", KNEE) == []
    assert kinds("深蹲先别做", KNEE) == [] and kinds("先别做深蹲", KNEE) == []
    assert kinds("等恢复了再上大重量", poor) == []


def test_annotate_inserts_where_the_violation_is() -> None:
    poor = Context(poor=True)
    text = "今天别冲刺。热身后，冲刺，4 组"
    marked = annotate(text, poor)
    assert (
        marked.startswith("今天别冲刺。") and "热身后，冲刺（今天状态不好：先别做），4 组" in marked
    )
    assert check(marked, poor) == []


def test_plan_notes_keep_the_limit_and_skip_todays_state() -> None:
    from ironm_agent.training import Plan

    long_note = "要" * 80
    plan = Plan.model_validate(
        {
            "title": "x",
            "days_per_week": 1,
            "sessions": [{"day": 1, "name": "腿", "items": [
                {"exercise": "高脚杯深蹲", "sets": 3, "reps": "10", "note": long_note},
                {"exercise": "大重量硬拉", "sets": 3, "reps": "5"},
            ]}],
        }
    )  # fmt: skip
    marked = annotate_plan(plan, Context(injuries=("joint.knee",), poor=True))
    squat, deadlift = marked.sessions[0].items
    assert squat.note.startswith("膝盖有伤") and len(squat.note) == 80
    assert "今天状态不好" not in deadlift.note  # 当天的状态不写进长期的周计划
