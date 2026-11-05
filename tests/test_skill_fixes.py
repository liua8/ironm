"""规程内容修错和过时的地方（spec [2026-10-23] §169）：只查规程文字。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "ironm_agent"


def text(skill: str) -> str:
    return (ROOT / "skills" / skill / "SKILL.md").read_text()


ALL = {p.parent.name: p.read_text() for p in (ROOT / "skills").glob("*/SKILL.md")} | {
    "skills.yaml": (ROOT / "skills.yaml").read_text()
}


def test_return_after_illness_depends_on_the_illness() -> None:
    card = next(x for x in text("readiness-adjust").splitlines() if x.startswith("③"))
    assert "感冒这类轻症几天内慢慢加回" in card
    assert "发过烧、病了一周以上、新冠流感这类病毒感染，症状消失满 7 天" in card  # 满 7 天只给这几种


def test_carbs_and_deficit_say_who_they_are_for() -> None:
    diet = text("diet-plan")
    assert "每天练 1 小时左右的，每天 5–7 克/公斤〔K38〕" in diet and "用不到这么多" in diet
    assert diet.count("以 500 为准") == 2  # 步骤卡和正文都写了冲突时听谁的


def test_review_claims_match_the_sources() -> None:
    review = text("log-review")
    assert "只会更多，不会更少" not in review and "再多做 1 次左右，但因人差别很大〔K79〕" in review
    assert "一成〔经验〕" not in review and "不能防伤〔K68〕" in review
    assert "K68" in review.split("---")[1]  # 引的依据在开头列了


def test_chest_symptoms_are_not_handled_as_injuries() -> None:
    assert "胸闷、胸痛、心慌、头晕、喘不上气不是伤痛" in text("pain-injury")


def test_no_skill_asks_for_tools_the_agent_no_longer_uses_that_way() -> None:
    for name, body in ALL.items():
        assert "写进记忆" not in body, name  # §166：回答后系统自己记
        assert "记成待跟进（followup）" not in body and "记成近期事件" not in body, name
        assert "再 `check_plan`" not in body and "先用 check_plan 检查" not in body, name  # §165
        assert "调 `check_plan` 检查时长" not in body, name


def test_comebacks_and_trips_use_temporary_changes() -> None:
    plan = text("plan-build")
    back = plan.split("## 回归·回来怎么练")[1].split("## ")[0]
    assert "`propose_temporary_change`" in back
    trip = plan.split("## 回归·马上要中断")[1].split("## ")[0]
    assert "`propose_temporary_change`" in trip
    assert "`propose_temporary_change`" in text("readiness-adjust")


def test_unconfigured_tools_are_conditional() -> None:
    for name, body in ALL.items():
        for tool in ("query_medications", "search_medical_knowledge"):
            for line in body.splitlines():
                if f"调 `{tool}`" in line:
                    assert f"有 `{tool}` 时" in line, (name, line[:40])
