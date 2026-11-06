"""今日简报与每周复盘（spec [2026-10-23] §10）：只给事实，不定级、不给规则建议（§182）。"""

from datetime import date, timedelta

from ironm_agent.brief import today_brief, weekly_review
from ironm_agent.casefile import Snapshot
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import Plan

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


def test_today_brief_gives_body_numbers_not_a_level() -> None:
    tired = Readings(
        sleep_hours=days(7.2, last=(4.5, 4.6, 4.4)), resting_hr=days(58, last=(66, 67, 68))
    )
    b = today_brief(snap(tired), [], PLAN, [])
    assert "readiness" not in b and b["training"]["name"] == "上肢拉"
    assert b["body"][0].startswith("睡眠：最近一晚（今天）4.4 小时") and "少 2.8 小时" in b["body"][0]
    assert "你平时 58 次/分，高 9 次/分" in b["body"][1]
    assert not b["training"]["tip"] and not b["alert"]  # 不再由规则建议减量、休息（§163）
    text = str(b)
    assert not any(w in text for w in ("恢复偏慢", "状态差", "一般", "'poor'", "'fair'"))
    rest = today_brief(
        snap(Readings()), [], PLAN.model_copy(update={"sessions": PLAN.sessions[:2]}), []
    )
    assert rest["training"]["kind"] == "rest"
    none = today_brief(snap(Readings()), [], None, [])
    assert none["training"]["kind"] == "no_plan" and none["body"] == ["还没有睡眠、心率记录"]
    assert "睡眠和心率" in none["alert"]  # 没数据时提醒连手表，不说"判断你今天的状态"


def test_weekly_review_gives_facts_without_rule_advice() -> None:
    """§182：每周复盘只给这周的事实；减到几天、整体七成、少吃 200 千卡这类规则建议去掉。"""
    flat = Readings(weight=days(70.0, n=30), sleep_hours=days(6.3, n=10))
    w = weekly_review(snap(flat, goal="fat_loss"), PLAN, [])
    assert (w["planned"], w["due"], w["done"]) == (3, 3, 0)
    assert "tips" not in w and "actions" not in w
    assert w["sleep"]["value"] is not None and w["weight"] is not None
    # 计划是今天才定的：之前没练不算该练
    fresh = weekly_review(snap(Readings()), PLAN, [], since=TODAY)
    assert (fresh["planned"], fresh["due"]) == (1, 1)
    two = PLAN.model_copy(update={"sessions": PLAN.sessions[:2], "days_per_week": 2})
    assert weekly_review(snap(Readings()), two, [])["due"] == 2


# ---- 今日战报（spec [2026-10-23] §19）------------------------------------------------------------


def test_hero_line_four_cases() -> None:
    from ironm_agent.brief import hero_line

    def today(kind: str, *, done: bool = False) -> dict[str, object]:
        t = {"kind": kind, "name": "下肢", "minutes": 50, "done": done}
        return {"training": t}

    week = {"planned": 3, "done": 1}
    assert hero_line(today("session", done=True), week)["title"] == "下肢 已拿下"
    plain = hero_line(today("session"), week)
    assert plain["title"] == "今天练下肢" and "轻松" not in plain["push"]  # 不再按规则叫他轻松练（§163）
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


def test_page_does_not_show_basis_codes_in_coach_inbox() -> None:
    """spec [2026-10-23] §29 需求 2：管家消息里不显示依据编号（出处内部留底，追问才说）。"""
    from pathlib import Path

    app = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()
    inbox = app[app.index("function inboxView") : app.index("function syncComposer")]
    assert "basis" not in inbox and "依据" not in inbox


def test_home_page_has_no_code_judged_readiness_sentence() -> None:
    """§182：首页"今天整体恢复偏慢，可以降低强度"这类代码判断的话去掉，看管家今天的版本说的。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    web = (root / "ironm_agent" / "web" / "app.js").read_text(encoding="utf-8")
    assert "恢复偏慢" not in web and "readiness" not in web
    assert "这周没有需要调整的地方" not in web and "w.tips" not in web  # 规则的每周建议也去掉
    app = "\n".join(p.read_text(encoding="utf-8") for p in (root / "app" / "src").rglob("*.ts*")
                     if "__tests__" not in p.parts)  # fmt: skip
    assert "恢复偏慢" not in app and "readiness" not in app and "这周没有需要调整的地方" not in app
