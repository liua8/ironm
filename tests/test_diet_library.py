"""饮食方案库（spec [2026-11-06] §184）：方案的检查、按热量目标缩放、看方案、套用和撤销、管家的工具、新补的依据、食物和食谱。

不连数据库、不调用模型。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from ironm_agent.diet_library import (
    BRANDS,
    MAX_SERVINGS,
    MIN_SERVINGS,
    SETS,
    by_id,
    day_meals,
    day_total,
    diet_templates,
    library,
    named,
    scaled,
)
from ironm_agent.foods import by_id as food_by_id
from ironm_agent.foods import find
from ironm_agent.kb import KnowledgeBase, default_kb
from ironm_agent.meals import presets
from ironm_agent.recipes import SLOTS, TAGS, DietBook, recommended
from tests.test_diet import client

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
NEED = {  # §184 要覆盖的几类，各有一份
    "均衡家常", "减脂·高蛋白（家常）", "减脂·外卖食堂", "增肌·家常", "增肌·上班带饭", "地中海", "DASH", "控糖", "蛋奶素",
    "60 岁以上", "限时进食",
}  # fmt: skip


# ---- 方案库读出来就是对的 ----------------------------------------------------------------------------


def test_library_covers_the_asked_kinds_and_every_plan_is_complete() -> None:
    plans = library()
    assert 10 <= len(plans) <= 12
    for want in NEED:
        assert any(want in p.name for p in plans), want
    rec, pre = {r.id for r in recommended()}, {x.id for x in presets()}
    kb = default_kb()
    for p in plans:
        for s in SETS:
            assert set(p.days[s]) == set(SLOTS), (p.id, s)  # 工作日、周末各四顿
            for slot in p.days[s].values():
                assert slot.id in (rec if slot.type == "recipe" else pre), (p.id, slot.id)
                assert MIN_SERVINGS <= slot.servings <= MAX_SERVINGS and slot.servings * 2 == int(
                    slot.servings * 2
                )
        assert p.refs and all(kb.get(r) is not None for r in p.refs), p.id
        assert 3 <= len(p.points) <= 6 and p.suits and p.not_for
        assert any("医生" in x or "营养师" in x for x in p.not_for), p.id  # 写明谁要先问医生
        for text in p.texts():  # 数字都有出处，没有的写〔经验〕
            assert not re.search(r"\d", text) or "〔" in text, (p.id, text)
        for text in p.every_text():
            assert not any(b in text for b in BRANDS), (p.id, text)


def test_library_rejects_broken_plans(tmp_path: Path) -> None:
    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "diet_library.yaml").read_text(
        encoding="utf-8"
    )
    cases = {
        "missing recipe": src.replace("id: millet-egg-spinach", "id: no-such-recipe", 1),
        "missing kb": src.replace("refs: [K09, K17, K36]", "refs: [K09, K17, K36, K999]", 1),
        "missing slot": src.replace(
            "        加餐: {type: recipe, id: yogurt-banana-snack, servings: 1}\n      weekend:",
            "      weekend:",
            1,
        ),
        "number without source": src.replace(
            "每天喝水 1500–1700 毫升，首选白水〔K17〕", "每天喝水 1500–1700 毫升，首选白水", 1
        ),
        "brand": src.replace("照膳食指南的食物量吃", "照膳食指南的食物量吃，早餐喝星巴克", 1),
        "servings": src.replace(
            "id: mushroom-chicken-rice, servings: 1.5",
            "id: mushroom-chicken-rice, servings: 1.2",
            1,
        ),
    }
    for why, text in cases.items():
        assert text != src, why
        bad = tmp_path / f"{why.replace(' ', '-')}.yaml"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            library.__wrapped__(bad)


def test_time_restricted_says_no_extra_benefit_and_who_should_not() -> None:
    p = by_id("time-restricted")
    assert p is not None
    assert "没有额外好处" in p.summary and "K123" in p.summary
    assert {"K123", "K125"} <= set(p.refs)
    told = "；".join(p.not_for)
    for who in ("糖尿病在用药", "孕期", "哺乳期", "进食障碍"):
        assert who in told


def test_energy_does_not_cut_twice() -> None:
    for pid in ("cut-home", "cut-takeout"):
        p = by_id(pid)
        assert p is not None and "已经算在目标里" in p.energy and "不再另减" in p.energy
    bulk = by_id("bulk-home")
    assert bulk is not None and "不再另加" in bulk.energy


def test_vegetarian_plan_uses_only_vegetarian_recipes() -> None:
    meat = {"肉蛋", "水产"}
    p = by_id("vegetarian")
    assert p is not None
    for s in SETS:
        for slot in p.days[s].values():
            r = next(x for x in recommended() if x.id == slot.id)
            assert "素食" in r.tags
    for r in recommended():
        if "素食" in r.tags:  # 素食的食谱里只有蛋，没有肉和水产
            cats = {
                food_by_id()[x.food_id].cat
                for x in r.parts
                if x.food_id not in ("egg", "egg-white")
            }
            assert not cats & meat, r.id


def test_named_finds_plans_by_short_names() -> None:
    assert named("地中海") is not None and named("地中海").id == "mediterranean"  # type: ignore[union-attr]
    assert named("DASH").id == "dash"  # type: ignore[union-attr]
    assert named("控糖").id == "low-gi"  # type: ignore[union-attr]
    assert named("限时进食").id == "time-restricted"  # type: ignore[union-attr]
    assert named("") is None and named("生酮") is None


# ---- 按热量目标缩放 --------------------------------------------------------------------------------


def test_scaling_clamps_rounds_to_half_and_keeps_takeout_whole() -> None:
    for p in library():
        for s in SETS:
            assert scaled(p, s, None) == {
                k: p.days[s][k].servings for k in SLOTS
            }  # 没有目标：推荐份数
            for target in (900, 1600, 2000, 2600, 3200, 9000):
                sv = scaled(p, s, target)
                for k, v in sv.items():
                    assert MIN_SERVINGS <= v <= MAX_SERVINGS and v * 2 == int(v * 2), (p.id, k, v)
                    if p.days[s][k].type == "preset":
                        assert v == 1  # 外卖、食堂是一整份
    p = by_id("balanced-home")
    assert p is not None
    assert set(scaled(p, "weekday", 9000).values()) == {3.0}  # 太多：每顿最多 3 份
    assert set(scaled(p, "weekday", 300).values()) == {0.5}  # 太少：每顿最少半份
    for target in (1600, 2000, 2400):
        got = day_total(day_meals(p, "weekday", scaled(p, "weekday", target))).kcal
        assert abs(got - target) <= 0.12 * target  # 半份一档，合计接近目标


# ---- 接口 ----------------------------------------------------------------------------------------


def test_list_and_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch)
    got = c.get("/iron/api/diet/library").json()
    assert len(got["plans"]) == len(library())
    first = got["plans"][0]
    assert {"id", "name", "goals", "suits", "summary", "per_day"} <= set(first)
    assert first["per_day"]["weekday"]["kcal"] > 0 and first["per_day"]["weekend"]["protein_g"] > 0
    d = c.get("/iron/api/diet/library/mediterranean").json()
    assert d["name"] == "地中海式" and d["refs"] and d["points"] and d["not_for"]
    text = str(d)
    assert "〔" not in text and "K118" not in text  # 出处编号不给用户看
    for s in SETS:
        day = d["days"][s]
        assert set(day["slots"]) == set(SLOTS) and day["total"]["kcal"] > 0
        assert all(x["name"] and x["kcal"] > 0 and x["foods"] for x in day["slots"].values())
    assert d["scaled"]["target"] == {"kcal": 2000, "protein_g": 120}  # 和饮食计划同一个目标
    total = d["scaled"]["days"]["weekday"]["total"]["kcal"]
    assert abs(total - 2000) <= 240
    assert c.get("/iron/api/diet/library/nope").status_code == 404
    assert c.get("/iron/api/diet/library/nope").json()["detail"] == "饮食方案库里没有这份方案"


def test_apply_backs_up_scales_and_undo_works_once(monkeypatch: pytest.MonkeyPatch) -> None:
    kitchen = DietBook()
    c, _, _ = client(monkeypatch, kitchen=kitchen)
    mine = {"type": "recipe", "id": "tuna-rice-bowl", "servings": 1}
    assert (
        c.put(
            "/iron/api/diet/plan", json={"set": "weekday", "slot": "午餐", "ref": mine}
        ).status_code
        == 200
    )
    before = c.get("/iron/api/diet/plan").json()
    r = c.post("/iron/api/diet/library/cut-home/apply")
    assert r.status_code == 200
    got = r.json()
    assert got["applied"] == {"id": "cut-home", "name": "减脂·高蛋白（家常）"}
    p = by_id("cut-home")
    assert p is not None
    for s in SETS:
        want = scaled(p, s, 2000)
        for k in SLOTS:
            slot = got["sets"][s][k]
            assert (
                slot["id"] == p.days[s][k].id
                and slot["servings"] == want[k]
                and not slot["missing"]
            )
        assert abs(got["totals"][s]["kcal"] - 2000) <= 240
    assert got["target"] == {"kcal": 2000, "protein_g": 120}
    # 之后在饮食计划里照常能改
    assert (
        c.put("/iron/api/diet/plan", json={"set": "weekend", "slot": "加餐", "ref": None}).json()[
            "sets"
        ]["weekend"]["加餐"]
        is None
    )
    u = c.post("/iron/api/diet/library/undo")
    assert u.status_code == 200 and u.json()["undone"] is True
    assert u.json()["sets"] == before["sets"]  # 回到套用前
    again = c.post("/iron/api/diet/library/undo")
    assert again.status_code == 404 and "撤销" in again.json()["detail"]  # 只能撤销一次


def test_apply_without_a_plan_undoes_to_empty_and_without_target_uses_recommended(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ironm_agent import web_more

    c, _, kitchen = client(monkeypatch)

    async def no_target(_: str) -> tuple[Any, str, Any]:
        return None, "", None

    monkeypatch.setattr(web_more, "_targets", no_target)
    assert c.post("/iron/api/diet/library/undo").status_code == 404  # 还没套用过
    got = c.post("/iron/api/diet/library/dash/apply").json()
    p = by_id("dash")
    assert p is not None
    assert all(
        got["sets"]["weekday"][k]["servings"] == p.days["weekday"][k].servings for k in SLOTS
    )
    assert c.post("/iron/api/diet/library/nope/apply").status_code == 404
    out = c.post("/iron/api/diet/library/undo").json()
    assert all(
        v is None for s in SETS for v in out["sets"][s].values()
    )  # 原来是空的，撤销后还是空的
    assert asyncio.run(kitchen.get("42", "plan", "plan_backup")) is None


def test_takeout_plan_applies_presets_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch)
    got = c.post("/iron/api/diet/library/cut-takeout/apply").json()
    assert (
        got["sets"]["weekday"]["午餐"]["type"] == "preset"
        and got["sets"]["weekday"]["午餐"]["servings"] == 1
    )


# ---- 管家的工具 ------------------------------------------------------------------------------------


def test_coach_tool_catalog_and_one_plan() -> None:
    from ironm_agent.protools.registry import ToolContext, run, tools_for

    assert "diet_templates" in {t.name for t in tools_for("nutrition")}
    ctx = ToolContext.build(__import__("datetime").date.today(), goal="fat_loss", weight_kg=70, readings=None,
                            kcal_target=1800, injured=())  # fmt: skip
    cat = asyncio.run(run("diet_templates", ctx, {}))
    text = "\n".join(cat.notes)
    assert f"一共 {len(library())} 份" in text and all(p.name in text for p in library())
    assert "不要自己改他的饮食计划" in text
    one = asyncio.run(run("diet_templates", ctx, {"name": "控糖"}))
    text = "\n".join(one.notes)
    assert "控糖（血糖偏高）" in text and "〔K121〕" in text and "1800 千卡" in text
    assert one.entries == ("K121",)  # 回答里能引用这份的依据
    missing = asyncio.run(run("diet_templates", ctx, {"name": "生酮"}))
    assert "没有「生酮」" in missing.notes[0]
    assert "按推荐份数" in "\n".join(diet_templates("dash").notes)  # 没有热量目标


def test_skill_and_catalog_mention_the_tool() -> None:
    from ironm_agent.skills import by_id as skill
    from ironm_agent.tool_catalog import CATALOG

    x = skill("diet-plan")
    assert x is not None and "diet_templates" in x.toolset and "`diet_templates`" in x.body
    assert any(t.agent == "diet_templates" and t.mcp == "diet_templates" for t in CATALOG)
    guide = (Path(__file__).resolve().parents[1] / "ironm_agent" / "app_guide.md").read_text(
        encoding="utf-8"
    )
    assert "饮食方案库" in guide and "撤销" in guide


# ---- 依据、食物、食谱 --------------------------------------------------------------------------------


def test_new_kb_entries_load_and_are_drafts() -> None:
    kb = KnowledgeBase.load()
    for k in ("K118", "K119", "K120", "K121", "K122", "K123", "K124", "K125"):
        e = kb.get(k)
        assert e is not None and e.review == "claude_draft" and e.points and e.url, k
        assert all(p.where for p in e.points)
        assert "〔" not in e.source  # 出处里不带像编号的括号
    assert "转载" in kb.get("K121").source  # type: ignore[union-attr]


def test_new_foods_and_recipes_resolve() -> None:
    for name, fid in (("鹰嘴豆", "chickpeas"), ("小扁豆", "lentils"), ("黑豆", "black-beans"), ("低脂牛奶", "lowfat-milk"),
                      ("红豆", "adzuki"), ("荞麦面", "soba"), ("全麦意面", "wholewheat-pasta"), ("混合坚果", "mixed-nuts")):  # fmt: skip
        f = find(name)
        assert f is not None and f.id == fid, name
    assert find("扁豆").id == "green-beans"  # type: ignore[union-attr]  # 扁豆还是四季豆
    recs = recommended()
    assert len(recs) >= 45
    for r in recs:
        assert set(r.tags) <= set(TAGS), r.id
        assert 2 <= len(r.steps) <= 4, r.id  # 加餐两步，正餐三四步
        m = r.per_serving()
        assert 100 <= m.kcal <= 900 and m.protein_g > 0, r.id
        assert not any(b in r.name or any(b in s for s in r.steps) for b in BRANDS), r.id


def test_web_wires_the_diet_library() -> None:
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for s in ("/iron/api/diet/library", "/apply", "/iron/api/diet/library/undo", "用这份当我的饮食计划", "dietLibSheet(",
              "饮食方案", "撤销"):  # fmt: skip
        assert s in js, s
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert ".diet-day" in css
