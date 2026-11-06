"""问身体被排了计划（spec [2026-10-23] §108）：上一轮的状态不当成这一轮的意图，要不要出计划由模型判断。

整轮走一遍用假模型；不连数据库、不调用真实模型。
"""

from __future__ import annotations

from typing import Any

from ironm_agent.actions import NEW_PLAN
from ironm_agent.casefile import injured_parts
from ironm_agent.clarify import HEAD
from ironm_agent.memory_store import Item, now
from ironm_agent.skills import by_id, pick_routed
from tests.fakes import acting, jsonr
from tests.test_plan_ops import plan
from tests.test_plugin import text_of
from tests.test_single_agent import NEW, cards, single
from tests.test_skill_route import ids, routed
from tests.test_turn_flow import run

ASK_LINE = HEAD + "，我打算按这些排：①目标……②场景……③器械……④时间……⑤伤病……"


def _after_ask(a: Any) -> None:
    async def history(*_: str) -> list[str]:
        return ["用户：我想重新换一份计划", "教练（要点）：" + ASK_LINE]

    a._history = history


def test_body_question_right_after_the_confirm_list_gets_no_plan(monkeypatch: Any) -> None:
    calls: list[str] = []

    def answer(system: str, user: str, results: list[str]) -> Any:
        calls.append(user)
        return jsonr({"answer": "整体不错：体重在降、血压正常〔经验〕。"})  # 只答身体，不写计划

    a, s = single(answer, monkeypatch, seeded=True, old=True)
    s.route = routed(["data-read"], ["recovery"], intent="询问身体状况")
    _after_ask(a)
    blocks, seen = run(a, "我身体咋样")
    assert not cards(blocks) and not seen["_experts"][0].get("nudged")
    assert len(calls) == 1  # 不提醒它交计划（§120）
    assert "data-read" in ids(seen) and "plan-build" not in ids(seen)  # 不强装排训练计划
    assert "他问的是别的事（比如问身体、问吃什么），就只答他问的" in s.user  # 提示是有条件的
    assert "用户刚回答了排计划前的确认" not in s.user


def test_confirm_reply_judged_by_the_router_still_gets_the_plan_written(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Any:
        return jsonr({"answer": "按你确认的条件排好了〔经验〕。"})  # 计划只写在嘴上、没交给系统

    a, s = single(answer, monkeypatch, seeded=True, old=True)
    s.route = routed(["plan-build"], ["train"], intent="确认排计划条件")
    _after_ask(a)
    blocks, seen = run(a, "按这个排")
    assert seen["_experts"][0]["nudged"]  # 路由看了上一轮、判断他在回应：同一轮提醒一次（§120）
    assert "排好了" not in text_of(blocks) and seen["unacted"]  # 还是没交：不说已经排好了


def test_reviewing_the_plan_with_a_full_rewrite_is_an_edit_not_the_confirm_list(
    monkeypatch: Any,
) -> None:
    a, _ = single(acting(NEW_PLAN, {"plan": NEW, "changes": "调两处", "kind": "rewrite"},
                         {"answer": "要调两处〔经验〕。"}), monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "帮我看看现在的训练计划，需要调整吗？")
    assert seen["action"] == "edit" and seen["path"] != "clarify" and cards(blocks)
    assert HEAD not in text_of(blocks)  # 不被换成固定的确认五项


def test_plan_identical_to_the_current_one_gives_no_preview(monkeypatch: Any) -> None:
    same = plan().model_dump(mode="json")
    for s in same["sessions"]:
        for x in s["items"]:
            x["note"] = "换了个说法"  # 说明变了，天、动作、组次没变
    a, _ = single(acting(NEW_PLAN, {"plan": same, "changes": "", "kind": "rewrite"},
                         {"answer": "沿用现在的〔经验〕。"}), monkeypatch, seeded=True, old=True)  # fmt: skip
    blocks, seen = run(a, "帮我看看现在的训练计划，需要调整吗？")
    assert seen["preview"] == "unchanged" and not cards(blocks)


def test_what_he_asked_is_not_crowded_out_by_situation_skills() -> None:
    data = by_id("data-read")
    assert data is not None
    got = [x.id for x in pick_routed([data], (), "我身体咋样", {"injury", "plan"}) if not x.core]
    assert got[0] == "data-read" and len(got) == 3  # 他问的先装，情况要求的跟着


def _injury(content: str) -> Item:
    t = now()
    return Item(id="i", category="injury", content=content, evidence=content, origin="said",
                status="active", created=t, updated=t)  # fmt: skip


def test_posture_is_not_an_injury() -> None:
    assert injured_parts([_injury("久坐导致圆肩")], "") == ()
    assert injured_parts([_injury("驼背、骨盆前倾")], "") == ()
    assert injured_parts([_injury("圆肩，右肩一抬就疼")], "") == ("joint.shoulder",)  # 说了疼照样算
    assert injured_parts([_injury("左膝旧伤")], "") == ("joint.knee",)


def test_memory_instructions_say_posture_is_not_an_injury() -> None:
    from ironm_agent import memory_extract
    from ironm_agent.actions import REMEMBER_SCHEMA

    tool = REMEMBER_SCHEMA["function"]["description"]  # 写法在工具说明里（§145）
    assert "圆肩驼背是体态不是 injury" in tool and "久坐圆肩怎么改善" in tool
    assert "体态问题（圆肩、驼背、骨盆前倾）不是伤病" in memory_extract._PROMPT
    assert "久坐圆肩怎么改善" in memory_extract._PROMPT
