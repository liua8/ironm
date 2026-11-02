"""方案库与"选初步方案"、排训练计划规程（spec [2026-10-23] §77）。"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import date
from typing import Any

import pytest

from ironm_agent.kb import default_kb
from ironm_agent.protools import templates as tpl
from ironm_agent.protools.movement import find, stressed
from ironm_agent.protools.plan_check import back_to_back, check_plan
from ironm_agent.protools.registry import ToolContext, run
from ironm_agent.protools.templates import choose, draft, plan_templates, templates
from ironm_agent.skills import pick_any, skills

GYM: frozenset[Any] | None = None  # 健身房：不知道具体器械时不拦
BANDS = frozenset({"自重", "弹力带"})
OLD = ("plan-newbie", "plan-muscle", "plan-strength", "plan-fatloss", "plan-home", "plan-weekly")


def top(**kw: Any) -> str:
    args: dict[str, Any] = {"level": None, "goal": None, "minutes": None, "place": None,
                            "people": "adult", "equipment": None, **kw}  # fmt: skip
    return choose(**args)[0].template.id


def test_library_loads_and_covers_every_kind_of_person() -> None:
    plans = templates()
    assert len({t.id for t in plans}) == len(plans) >= 10
    kb = default_kb()
    for t in plans:
        assert t.why and t.intensity and t.progress and t.deload, t.id
        assert all(kb.get(r) is not None for r in t.refs), t.id
        cited = set(re.findall(r"〔(K\d{2,4})〕", t.why + t.intensity + t.progress + t.deload))
        assert cited <= set(t.refs), (t.id, cited - set(t.refs))  # 写到的依据都登记了
    assert {x for t in plans for x in t.levels} == {"none", "lt6m", "6m-2y", "2y+"}
    assert {"health", "fat_loss", "muscle", "strength"} <= {x for t in plans for x in t.goals}
    assert {t.place for t in plans} >= {"gym", "home"}
    assert {x for t in plans for x in t.people} == {"adult", "older", "youth"}


def test_the_right_plan_for_each_kind_of_person() -> None:
    assert top(level="none", goal="health", days=3, place="gym") == "kai-tan-ppl"  # 标准方案（§79）
    assert top(level="none", goal="health", days=3, minutes=30, place="gym") != "kai-tan-ppl"
    assert top(level="none", goal="muscle", days=2, place="gym") == "start-full-2"
    assert top(level="lt6m", goal="health", days=3, place="home", equipment=BANDS) == "kai-tan-ppl"
    assert top(level="lt6m", goal="health", days=2, place="home", equipment=BANDS) == "home-3"
    assert top(level="6m-2y", goal="muscle", days=4, place="gym") == "upper-lower-4"
    assert top(level="2y+", goal="muscle", days=6, place="gym") == "kai-tan-ppl"
    assert top(level="2y+", goal="strength", days=3, place="gym") == "strength-3"
    assert top(level="lt6m", goal="fat_loss", days=4, place="gym") == "fatloss-mix"
    assert top(level="lt6m", goal="muscle", days=3, minutes=30, place="gym") == "short-30"
    assert top(goal="health", days=2, people="older") == "older-2-3"
    assert top(level="none", goal="muscle", days=3, people="youth") == "youth-2-3"
    assert (
        tpl.people_of(70) == "older"
        and tpl.people_of(15) == "youth"
        and tpl.people_of(None) == "adult"
    )


def test_mismatches_are_said_not_hidden() -> None:
    c = choose(level="none", goal="muscle", days=5, minutes=60, place="gym", people="adult",
               equipment=GYM)[0]  # fmt: skip
    assert c.template.id == "start-full-3" and c.days == 3  # 新手要练 5 天：给 3 天的，说清楚
    assert any("没有每周 5 天的版本" in g for g in c.gaps)
    barbell = choose(level="2y+", goal="strength", days=3, minutes=60, place="home",
                     people="adult", equipment=frozenset({"哑铃"}))  # fmt: skip
    assert "strength-3" not in [x.template.id for x in barbell]  # 没有杠铃不给力量方案


def test_moves_follow_equipment_and_avoid_the_injured_joint() -> None:
    t = next(x for x in templates() if x.id == "start-full-3")
    plan, notes = draft(t, 3, goal="health", equipment=BANDS, injured=("joint.knee",))
    for s in plan.sessions:
        for item in s.items:
            m = find(item.exercise)
            assert m is not None and set(m.exercise.equipment) & BANDS, item.exercise
            assert not stressed(m, ("joint.knee",)), item.exercise
    assert any("换成同类的" in n for n in notes)  # 换了什么写出来


def test_training_days_are_spread_and_follow_the_days_he_can_train() -> None:
    for t in templates():
        for n in t.weeks:
            plan, _ = draft(t, n, goal=None, equipment=GYM)
            assert len({s.day for s in plan.sessions}) == n
            if n <= 4:
                assert not back_to_back(plan), (t.id, n)  # 同一肌群不连着两天
    t = next(x for x in templates() if x.id == "start-full-3")
    plan, _ = draft(t, 3, goal=None, equipment=GYM, weekdays=[2, 3, 4, 6, 7])
    assert [s.day for s in plan.sessions] in ([2, 4, 6], [2, 4, 7], [3, 6, 7], [2, 4, 7])
    assert not back_to_back(plan)


def test_every_draft_is_a_valid_plan_that_passes_the_check() -> None:
    for t in templates():
        gear = BANDS if t.place == "home" else GYM
        for n in t.weeks:
            plan, _ = draft(t, n, goal=t.goals[0], equipment=gear, minutes=t.minutes[1])
            r = check_plan(plan, goal=t.goals[0], equipment=gear, available_days=n,
                           available_minutes=t.minutes[1])  # fmt: skip
            assert not r.problems, (t.id, n, r.problems)


def test_drafts_are_cut_to_the_minutes_he_has() -> None:
    t = next(x for x in templates() if x.id == "upper-lower-4")
    plan, notes = draft(t, 4, goal="muscle", equipment=GYM, minutes=45)
    assert not check_plan(plan, available_minutes=45).problems
    assert any("按 45 分钟裁剪" in n for n in notes)
    short, notes = draft(t, 4, goal="muscle", equipment=GYM, minutes=25)
    assert all(len(s.items) == 3 for s in short.sessions)  # 减组数还不够：去掉排在后面的动作
    assert any("去掉" in n for n in notes)


def test_tool_output_has_reasons_progression_and_a_usable_draft() -> None:
    r = plan_templates(level="none", goal="health", days=2, minutes=60, place="gym", age=30,
                       equipment=GYM)  # fmt: skip
    text = "\n".join(r.notes)
    assert "为什么这样排" in text and "怎么进阶" in text and "什么时候减量" in text
    raw = next(x for x in r.notes if "草稿" in x).split("：", 1)[1]
    assert json.loads(raw)["days_per_week"] == 2
    assert r.findings and "入门全身" in r.findings[0].name
    home = plan_templates(level=None, goal=None, days=2, minutes=None, place="home", age=None,
                          equipment=None)  # fmt: skip
    assert any("先按只有自重排" in x for x in home.notes)
    assert any("按入门挑的" in x for x in home.notes)


def test_no_matching_plan_is_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    only = tuple(t for t in templates() if t.id == "strength-3")
    monkeypatch.setattr(tpl, "templates", lambda: only)
    r = plan_templates(level="none", goal="strength", days=3, minutes=None, place="home",
                       age=None, equipment=frozenset({"哑铃"}))  # fmt: skip
    assert "没有合适的初步方案" in "\n".join(r.notes) and not r.findings


def test_the_tool_uses_age_equipment_and_injuries_from_the_context() -> None:
    ctx = ToolContext(date(2026, 10, 30), goal="health", equipment=BANDS,
                      injured=("joint.knee",), age=68)  # fmt: skip
    r = asyncio.run(run("plan_templates", ctx, {"days_per_week": 3}))
    assert "60 岁以上" in r.findings[0].name
    assert (
        "方案库一共" in asyncio.run(run("plan_templates", ctx, {})).notes[0]
    )  # 不写天数：列方案库（§83）
    assert "days_per_week" in asyncio.run(run("plan_templates", ctx, {"days_per_week": 9})).notes[0]


def test_plan_build_skill_replaces_the_old_six() -> None:
    ids = {x.id for x in skills()}
    assert "plan-build" in ids and not ids & set(OLD)
    x = next(s for s in skills() if s.id == "plan-build")
    steps = [x.body.index(f"## {n}") for n in "①②③④⑤⑥"]
    assert steps == sorted(steps)
    assert "plan_templates" in x.toolset and "`plan_templates`" in x.body
    for text in ("给我排个增肌计划", "在家没器械怎么练", "想冲大重量怎么练", "减脂期训练怎么安排"):
        assert "plan-build" in [s.id for s in pick_any(text, set())], text


def test_new_kb_entries_wait_for_review() -> None:
    kb = default_kb()
    for ref in ("K59", "K60", "K61", "K62", "K63", "K64"):
        e = kb.get(ref)
        assert e is not None and e.review == "claude_draft" and e.url
        assert all(p.where for p in e.points)


# ---- 博主方案（§78）----


def test_blogger_plans_must_say_where_they_come_from() -> None:
    bloggers = [t for t in templates() if t.kind == "blogger"]
    assert bloggers and all(t.source is not None for t in bloggers)
    for t in bloggers:
        assert t.source is not None and t.source.authors and t.source.url.startswith("https://")
        assert t.conflicts  # 和依据不一致的地方要写出来
    raw = json.loads(json.dumps({"id": "x", "kind": "blogger"}))
    base = next(t for t in templates() if t.kind == "base").model_dump()
    with pytest.raises(ValueError, match="博主方案要写来源"):
        tpl.Template.model_validate({**base, **raw, "source": None})


def test_named_blogger_plan_is_picked_and_fitted_to_him() -> None:
    r = plan_templates(level="6m-2y", goal="muscle", days=6, minutes=85, place="gym", age=30,
                       equipment=GYM, injured=("joint.knee",), name="我想练谭成义的计划")  # fmt: skip
    assert r.findings[0].name == "方案1「凯圣王×谭成义三分化」" and len(r.findings) == 1
    text = "\n".join(r.notes)
    assert "博主方案：参考凯圣王、谭成义的公开计划" in text and "不要说成官方计划" in text
    assert "第三方整理" in text and "和依据不一致" in text and "附加（不放进计划" in text
    plan = json.loads(next(x for x in r.notes if "草稿" in x).split("：", 1)[1])
    assert plan["days_per_week"] == 6
    for s in plan["sessions"]:
        for item in s["items"]:
            m = find(item["exercise"])
            assert m is None or not stressed(m, ("joint.knee",)), item["exercise"]  # 照样避开伤处
    # 点名时不按条件筛掉，对不上的写出来
    older = plan_templates(level="2y+", goal="muscle", days=3, minutes=None, place="gym",
                           age=66, equipment=GYM, name="谭成义")  # fmt: skip
    assert "kai-tan-ppl" in "\n".join(older.notes) and "给成年人排的" in older.findings[0].text


def test_unknown_name_falls_back_and_says_so() -> None:
    r = plan_templates(level="none", goal="health", days=2, minutes=None, place="gym", age=30,
                       equipment=GYM, name="帕梅拉")  # fmt: skip
    assert any("方案库里没有「帕梅拉」" in x for x in r.notes)
    assert r.findings[0].name.startswith("方案1「入门全身")


def test_own_plans_come_before_blogger_plans_when_not_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flipped = tuple(reversed(templates()))  # 博主方案排在文件前面也一样
    monkeypatch.setattr(tpl, "templates", lambda: flipped)
    got = [c.template for c in choose(level="2y+", goal="muscle", days=4, minutes=None,
                                      place="gym", people="adult", equipment=GYM, k=20)]  # fmt: skip
    kinds = [t.kind for t in got]
    assert "blogger" in kinds and kinds.index("blogger") > kinds.index("base")


def test_kai_tan_split_has_the_structure_of_the_source() -> None:
    t = next(x for x in templates() if x.id == "kai-tan-ppl")
    assert set(t.weeks) == {3, 6} and list(t.sessions) == ["推", "拉", "腿"]
    assert all(len(slots) == 5 for slots in t.sessions.values())
    bench = t.sessions["推"][0]
    assert bench.reps == "15/12/10/8" and "10/8/6/力竭" in bench.note
    assert all(f"第 {w}" in t.progress for w in ("1–4 周", "5–8 周", "9–11 周", "12 周"))


# ---- 一般人的标准方案（§79）----

DUMBBELLS = frozenset({"自重", "哑铃"})


def test_standard_split_is_the_default_for_ordinary_adults_only() -> None:
    for goal in ("muscle", "fat_loss", "health"):
        for days in (3, 6):
            assert top(level="6m-2y", goal=goal, days=days, place="gym") == "kai-tan-ppl"
    assert (
        top(level="none", goal="muscle", days=3, place="home", equipment=DUMBBELLS) == "kai-tan-ppl"
    )
    assert top(level="2y+", goal="strength", days=3, place="gym") == "strength-3"  # 冲重量照旧
    assert top(level="none", goal="health", days=2, place="gym") == "start-full-2"
    assert top(level="6m-2y", goal="muscle", days=4, place="gym") == "upper-lower-4"
    assert top(goal="health", days=3, people="older") == "older-2-3"
    assert top(goal="muscle", days=3, people="youth") == "youth-2-3"


def test_novices_get_fewer_sets_and_no_failure() -> None:
    t = next(x for x in templates() if x.id == "kai-tan-ppl")
    for level, most in (("none", 2), ("lt6m", 3)):
        plan, _ = draft(t, 3, goal="muscle", equipment=GYM, level=level)
        items = [i for s in plan.sessions for i in s.items]
        assert max(i.sets for i in items) == most
        assert not any("力竭" in i.reps + i.note for i in items)
    plan, _ = draft(t, 3, goal="muscle", equipment=GYM, level="2y+")
    items = [i for s in plan.sessions for i in s.items]
    assert max(i.sets for i in items) == 4 and any("力竭" in i.note for i in items)  # 有基础照原版


def test_standard_split_works_with_gym_dumbbells_or_bands() -> None:
    t = next(x for x in templates() if x.id == "kai-tan-ppl")
    for gear in (GYM, DUMBBELLS, BANDS, frozenset({"自重"})):  # 完全没有器械也排得满（§79 需求 5）
        plan, notes = draft(t, 3, goal="muscle", equipment=gear, level="lt6m")
        assert all(len(s.items) == 5 for s in plan.sessions), (gear, notes)  # 不缺位
        for s in plan.sessions:
            for item in s.items:
                m = find(item.exercise)
                assert m is not None, item.exercise
                assert gear is None or set(m.exercise.equipment) & gear, (gear, item.exercise)
                if gear == BANDS and set(m.exercise.equipment) & gear == {"弹力带"}:
                    assert "用弹力带做" in item.note, item.exercise
        assert not check_plan(plan, goal="muscle", equipment=gear).problems


def test_single_arm_pulldown_was_added_without_renumbering() -> None:
    m = find("单臂高位下拉")
    assert m is not None and m.ref == "K997" and m.tag.pattern == "v_pull"
    assert find("高位下拉").ref == "K920"  # type: ignore[union-attr]  # 原来的编号不变


def test_tool_says_it_is_the_standard_plan_and_where_it_comes_from() -> None:
    r = plan_templates(level="none", goal="muscle", days=3, minutes=None, place="gym", age=28,
                       equipment=GYM)  # fmt: skip
    text = "\n".join(r.notes)
    assert "一般人的标准方案" in text and "按零基础减到每个动作最多 2 组" in text
    assert "博主方案：参考凯圣王、谭成义" in text and "和依据不一致" in text


def test_four_digit_library_ids_can_be_cited() -> None:
    from ironm_agent.checks import KB_REF
    from ironm_agent.exercises import library_entries

    ids = {e.id for e in library_entries()}
    for name in ("门把手毛巾划船", "俯卧超人下拉", "俯卧 Y 字举", "毛巾对抗弯举"):
        m = find(name)
        assert m is not None and m.ref in ids and m.exercise.equipment[0] == "自重"
    assert "K1000" in ids and KB_REF.findall("做 Y 字举〔K1000〕。") == ["K1000"]


# ---- 问有多少训练计划（§83）----


def test_catalog_lists_every_plan_and_says_where_to_see_them() -> None:
    from ironm_agent.protools.templates import catalog

    notes = catalog().notes
    text = "\n".join(notes)
    assert notes[0] == f"方案库一共 {len(templates())} 份初步方案："
    assert all(t.name in text for t in templates())
    assert "（一般人的标准方案）" in text and "训练计划榜" in text and "当前计划" in text


def test_skill_and_app_guide_explain_how_many_plans() -> None:
    from pathlib import Path

    body = next(x for x in skills() if x.id == "plan-build").body
    assert "## 问有多少计划、有哪些计划" in body and "什么都不填" in body
    guide = (Path(__file__).parents[1] / "ironm_agent" / "app_guide.md").read_text(encoding="utf-8")
    assert "训练计划榜" in guide and "按我的情况用这个计划" in guide
    assert "社区榜" not in guide and "我排的" not in guide


def test_asking_how_many_plans_is_not_a_request_for_a_new_plan() -> None:
    from ironm_agent.clarify import wants_new
    from ironm_agent.training import task_of

    for text in ("你们有多少训练计划", "有哪些训练计划", "训练计划有几个", "还有别的训练计划吗"):
        assert not wants_new(text, has_plan=False) and task_of(text) is None, text
    for text in ("给我排个训练计划", "有哪些训练计划适合我，给我排一份"):
        assert wants_new(text, has_plan=False), text
