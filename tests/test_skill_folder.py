"""Skill 重新划分、文件夹规程、第 1 批评估类（spec [2026-10-23] §76）。"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from ironm_agent.kb import default_kb
from ironm_agent.memory_layers import PROFILE, RECALL, layers
from ironm_agent.memory_store import CATEGORIES, Item, now
from ironm_agent.skill_route import catalog
from ironm_agent.skills import SKILLS_DIR, folder_skills, pick_any, skills
from ironm_agent.tool_catalog import CATALOG
from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_skill_route import ids, routed
from tests.test_turn_flow import run

FIRST = ("intake-assess", "goal-set")
# 规程里能写的工具：对话里登记的工具，加上查记忆、App 用法
KNOWN_TOOLS = {t.agent for t in CATALOG if t.agent} | {RECALL, "app_help"}


def folder() -> list[Any]:
    return [x for x in skills() if x.body]


def test_folder_skills_load_with_every_field() -> None:
    rows = folder_skills()
    assert {r["id"] for r in rows} >= set(FIRST)
    assert len(rows) == len(list(SKILLS_DIR.glob("*/SKILL.md")))
    for x in folder():
        assert x.name and x.use and x.not_for and (x.role is not None or x.shared), x.id
        assert x.when and x.toolset and x.refs and len(x.body) > 800, x.id
        assert not x.core and not x.style and not x.steps, x.id  # 正文写在 SKILL.md 里，不用 steps


def test_folder_ids_are_unique_and_named_after_the_folder() -> None:
    all_ids = [x.id for x in skills()]
    assert len(all_ids) == len(set(all_ids))
    for md in SKILLS_DIR.glob("*/SKILL.md"):
        head = md.read_text(encoding="utf-8").split("\n---\n", 1)[0]
        assert f"\nid: {md.parent.name}\n" in head + "\n"


def test_tools_named_in_folder_skills_exist() -> None:
    for x in folder():
        assert set(x.toolset) <= KNOWN_TOOLS, (x.id, set(x.toolset) - KNOWN_TOOLS)
        for name in re.findall(r"`([a-z_]+)`", x.body):  # 正文里写的工具也要是真有的
            assert name in KNOWN_TOOLS, (x.id, name)
        assert set(re.findall(r"`([a-z_]+)`", x.body)) <= set(x.toolset), (
            x.id
        )  # 正文用到的都在开头写了


def test_every_ref_in_folder_skills_is_in_the_kb() -> None:
    kb = default_kb()
    for x in folder():
        cited = set(re.findall(r"〔(K\d{2,4})〕", x.body))
        assert cited <= set(x.refs), (x.id, cited - set(x.refs))  # 正文引的都在开头写了
        for ref in x.refs:
            assert kb.get(ref) is not None, (x.id, ref)
        assert set(x.refs_for(frozenset())) <= set(x.refs)


def test_catalog_lists_the_first_batch_and_loading_brings_the_body() -> None:
    text = catalog()
    for sid in FIRST:
        assert f"- {sid} " in text
    body_marker = "## ① 安全筛查"
    assert body_marker not in text  # 目录里只有名字和什么时候用
    x = next(s for s in skills() if s.id == "intake-assess")
    shown = x.text(frozenset())
    assert (
        shown.startswith("【初次评估】") and body_marker in shown and "query_medications" in shown
    )


def test_intake_flow_is_in_order_with_tools_and_stops_on_red_flags() -> None:
    body = next(s for s in skills() if s.id == "intake-assess").body
    steps = [body.index(f"## {n}") for n in "①②③④⑤⑥⑦"]
    assert steps == sorted(steps)
    screening = body[steps[0] : steps[1]]
    assert "先请医生评估" in screening and "评估到这里停下" in screening and "〔K56〕" in screening
    assert "每轮最多问 2 个问题" in body
    for tool in ("recall_memory", "query_health_indicators", "training_patterns"):
        assert f"`{tool}`" in body


def test_new_user_always_gets_intake_assessment() -> None:
    got = [x.id for x in pick_any("你好", {"new"})]
    assert "intake-assess" in got
    assert "intake-assess" not in [x.id for x in pick_any("你好", set())]


def test_new_user_routed_elsewhere_still_gets_intake(monkeypatch: Any) -> None:
    a, s = single(lambda *_: jsonr({"answer": "先问两件事〔K56〕。"}), monkeypatch)
    s.route = routed(["goal-set"], ["train"], intent="想减肥")
    _, seen = run(a, "我想减肥")
    got = ids(seen)
    assert got.index("intake-assess") < got.index("goal-set")  # 情况要求的排前面
    assert "## ① 安全筛查" in s.system and "【目标设定】" in s.system


def test_old_user_is_not_pushed_into_intake(monkeypatch: Any) -> None:
    a, s = single(lambda *_: jsonr({"answer": "8 周减 4 公斤〔K37〕。"}), monkeypatch, old=True)
    s.route = routed(["goal-set"], ["train"], intent="想减肥")
    _, seen = run(a, "我想减肥")
    assert "intake-assess" not in ids(seen) and "goal-set" in ids(seen)


def test_new_kb_entries_have_source_place_and_wait_for_review() -> None:
    kb = default_kb()
    for ref in ("K56", "K57", "K58"):
        e = kb.get(ref)
        assert e is not None and e.review == "claude_draft" and e.url
        assert e.source and e.summary and all(p.where for p in e.points)
    k58 = kb.get("K58")
    assert k58 is not None and k58.level == "study"  # 横断面研究，不当随机对照


def test_training_level_is_a_memory_category_in_the_profile() -> None:
    assert "level" in PROFILE and CATEGORIES["level"] == "训练水平"
    t = now()
    lvl = Item("a", "level", "练了不到 6 个月，做过高脚杯深蹲", "练了半年", "said", "active", t, t)
    lay = layers([lvl], date(2026, 10, 30))
    assert any("练了不到 6 个月" in line for line in lay.profile)


# ---- 第 3–5 批（§81）----

ALL = {"intake-assess", "goal-set", "plan-build", "cardio-fitness", "move-coach",
       "log-review", "readiness-adjust", "progress-plateau", "comeback", "pain-injury", "sick-days",
       "special-groups", "recovery-sleep", "diet-plan", "supplements-meds", "data-read"}  # fmt: skip
OLD = {"plan-readiness", "plan-deload", "plan-return", "move-teach", "move-swap", "move-warmup",
       "train-cardio", "train-habit", "food-targets", "food-muscle", "food-fatloss", "food-timing",
       "food-supplement", "food-takeout", "food-photo", "food-habit", "rest-readiness", "rest-sleep",
       "rest-soreness", "rest-sick", "rest-overtraining", "rest-return", "rest-pain", "rest-redflag",
       "data-trend", "data-labs", "data-missing"}  # fmt: skip


def test_all_eighteen_folder_skills_and_only_cores_left_in_yaml() -> None:
    assert {x.id for x in folder()} == ALL
    in_yaml = {x.id for x in skills() if not x.body}
    assert in_yaml == {"train-core", "food-core", "rest-core"}  # 体感讲解并进了动作教学（§88）
    assert not OLD & {x.id for x in skills()}


def test_situations_always_bring_their_skill() -> None:
    for trigger, sid, text in (("log", "log-review", "今天卧推 60 公斤 3 组"),
                               ("poor", "readiness-adjust", "嗯"),
                               ("injury", "pain-injury", "嗯"),
                               ("image", "diet-plan", "看看这个"),
                               ("lab", "data-read", "帮我看看"),
                               ("metric", "data-read", "帮我看看")):  # fmt: skip
        assert sid in [x.id for x in pick_any(text, {trigger})], trigger


def test_safety_floors_from_the_old_skills_are_kept() -> None:
    body = {x.id: x.body for x in folder()}
    assert "发烧时不运动" in body["sick-days"]
    assert all(w in body["pain-injury"] for w in ("断裂声", "不能活动或承重", "麻木", "不诊断"))
    assert "不给健康意见" in body["data-read"] and "不建议改药" in body["data-read"]
    assert "孕期、哺乳期、有慢病或在用药的人，吃补剂前先问医生或药师" in body["supplements-meds"]
    assert "不建议改药停药" in body["supplements-meds"]
    assert "立即停止并就医" in body["special-groups"]
    assert "不推荐安眠药" in body["recovery-sleep"]
    assert "状态差时不安排大重量" in body["readiness-adjust"]


def test_batch_three_to_five_kb_entries_wait_for_review() -> None:
    kb = default_kb()
    for n in range(65, 117):
        e = kb.get(f"K{n}")
        assert e is not None and e.review == "claude_draft" and e.url, n
        assert e.source and e.summary and all(p.where for p in e.points), n
