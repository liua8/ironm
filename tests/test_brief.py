"""今日简报与每周复盘（spec [2026-10-23] §10）：只用规则。"""

from datetime import date, timedelta

from ironm_agent.brief import today_brief, weekly_review
from ironm_agent.casefile import Snapshot
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import Plan, WorkoutLog

TODAY = date(2026, 10, 23)  # 周五
PLAN = Plan.model_validate(
    {
        "title": "三分化",
        "days_per_week": 3,
        "sessions": [
            {"day": d, "name": n, "items": [{"exercise": "深蹲", "sets": 3, "reps": "10"}]}
            for d, n in ((1, "下肢"), (3, "上肢推"), (5, "上肢拉"))
        ],
    }
)


def days(value: float, n: int = 40, last: tuple[float, ...] = ()) -> tuple[tuple[date, float], ...]:
    values = [value + (0.4 if i % 2 else -0.4) for i in range(n)]
    if last:
        values[-len(last) :] = list(last)
    return tuple((TODAY - timedelta(days=n - 1 - i), v) for i, v in enumerate(values))


def snap(readings: Readings, goal: str = "muscle") -> Snapshot:
    p = Profile(height_cm=170, birth=date(1995, 1, 1), sex="female", goal=goal, activity="light")  # type: ignore[arg-type]
    return Snapshot(p, readings, tuple(compute_all(readings, p, TODAY)), TODAY)


def test_today_brief_with_plan_and_poor_state() -> None:
    tired = Readings(
        sleep_hours=days(7.2, last=(4.5, 4.6, 4.4)), resting_hr=days(58, last=(66, 67, 68))
    )
    b = today_brief(snap(tired), [], PLAN, [])
    assert b["readiness"]["level"] == "poor" and b["training"]["name"] == "上肢拉"
    assert "轻松版" in b["training"]["tip"] and b["alert"]
    rest = today_brief(
        snap(Readings()), [], PLAN.model_copy(update={"sessions": PLAN.sessions[:2]}), []
    )
    assert rest["training"]["kind"] == "rest"
    none = today_brief(snap(Readings()), [], None, [])
    assert none["training"]["kind"] == "no_plan" and none["readiness"]["level"] == "unknown"


def test_weekly_review_rules() -> None:
    # 计划练 3 次一次没练、减脂体重不降、睡眠不足 7 小时：三条建议
    flat = Readings(weight=days(70.0, n=30), sleep_hours=days(6.3, n=10))
    w = weekly_review(snap(flat, goal="fat_loss"), PLAN, [])
    tips = "".join(w["tips"])
    assert (w["planned"], w["due"], w["done"]) == (3, 3, 0)
    assert "不到一半" in tips and "少吃约 200 千卡" in tips and "平均只睡 6." in tips
    # 练够了、睡够了、增肌目标：没有要调整的
    logs = [
        WorkoutLog(day=TODAY - timedelta(days=4), session="下肢"),
        WorkoutLog(day=TODAY - timedelta(days=2), session="上肢推"),
    ]
    good = weekly_review(snap(Readings(sleep_hours=days(7.6, n=10))), PLAN, logs)
    assert good["tips"] == [] and good["done"] == 2
    # 计划是今天才定的：之前没练不算没完成
    fresh = weekly_review(snap(Readings()), PLAN, [], since=TODAY)
    assert (fresh["planned"], fresh["due"]) == (1, 1) and not any(
        "不到一半" in t for t in fresh["tips"]
    )


def test_two_day_plan_is_not_told_to_drop_to_two_days() -> None:
    two = PLAN.model_copy(update={"sessions": PLAN.sessions[:2], "days_per_week": 2})
    w = weekly_review(snap(Readings()), two, [])
    assert w["due"] == 2 and not any("减到 2 天" in t for t in w["tips"])


# ---- 今日战报（spec [2026-10-23] §19）------------------------------------------------------------


def test_hero_line_four_cases() -> None:
    from ironm_agent.brief import hero_line

    def today(kind: str, *, done: bool = False, level: str = "good") -> dict[str, object]:
        t = {"kind": kind, "name": "下肢", "minutes": 50, "done": done}
        return {"training": t, "readiness": {"level": level}}

    week = {"planned": 3, "done": 1}
    assert hero_line(today("session", done=True), week)["title"] == "下肢 已拿下"
    poor = hero_line(today("session", level="poor"), week)
    assert poor["title"] == "今天练下肢" and "今天的版本" in poor["push"]
    go = hero_line(today("session"), week)
    assert "50 分钟" in go["push"] and "冲" in go["push"]
    assert hero_line(today("rest"), week)["title"] == "休息日"
    assert "本周目标已经拿下" in hero_line(today("rest"), {"planned": 3, "done": 3})["push"]
    assert hero_line(today("no_plan"), {})["title"] == "开练吧"


def test_web_files_load_nothing_external() -> None:
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
    for name in ("index.html", "style.css", "app.js"):
        text = (
            (web / name).read_text().replace("http://www.w3.org/2000/svg", "")
        )  # SVG 命名空间不是请求
        assert not re.search(r"https?://|@import|//cdn", text), name
