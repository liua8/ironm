"""核对退回后的改句对不上原句：去掉出处标记、按开头认（复核 11-05）。不调用真实模型。"""

from __future__ import annotations

import json
from typing import Any

from ironm_agent.experts import Opinion, _locate, _patched
from ironm_agent.roles import Role

ANSWER = ("能练上半身，左腿先别负重。\n1. 坐姿推举、划船、下拉各3组，每组8–12次，组间休息2分钟〔经验〕\n"
          "2. 核心训练选平板支撑，3组，每组30–40秒，不做弓步、深蹲、跳跃")  # fmt: skip


def patch(*fixes: tuple[str, str]) -> tuple[Opinion | None, dict[str, Any]]:
    trace: dict[str, Any] = {}
    body = json.dumps({"fixes": [{"old": o, "new": n} for o, n in fixes]}, ensure_ascii=False)
    got = _patched(Role.GENERAL, Opinion(role=Role.GENERAL, speak=True, answer=ANSWER), body, "", trace)
    return got, trace


def test_exact_and_loose_quotes_are_found() -> None:
    assert _locate(ANSWER, "能练上半身，左腿先别负重。") == "能练上半身，左腿先别负重。"
    # 照核对给的开头 30 个字抄、带省略号
    assert _locate(ANSWER, "2. 核心训练选平板支撑，3组，每组30–40秒，不做弓步、…").startswith("2. 核心训练")
    # 抄的时候多写了出处标记、改了空白
    assert _locate(ANSWER, "能练上半身， 左腿先别负重〔经验〕。") == "能练上半身，左腿先别负重。"


def test_short_or_ambiguous_quotes_are_not_guessed() -> None:
    assert _locate(ANSWER, "能练下半身") is None  # 太短又不是原文
    assert _locate(ANSWER, "能练 上半") is None  # 去掉空白后只剩 4 个字：不按开头猜
    twice = "每组做到还剩两次就停。每组做到还剩两次就换下一个。"
    assert _locate(twice, "每组做到还剩两次…") is None  # 两句都对得上：不猜


def test_patch_outcome_is_recorded() -> None:
    got, trace = patch(("2. 核心训练选平板支撑，3组，每组30–40秒，不做弓步、…", "2. 核心训练选平板支撑，3组，每组30–40秒〔经验〕"))
    assert got is not None and "每组30–40秒〔经验〕" in got.answer and trace["patch"] == "applied"
    assert "不做弓步" not in got.answer  # 整句换掉，不留半句
    _, miss = patch(("这句回答里没有的话，完全对不上", "x"))
    assert miss["patch"] == "no_match"
    _, bad = patch()
    assert bad["patch"] == "empty"
    t: dict[str, Any] = {}
    _patched(Role.GENERAL, Opinion(role=Role.GENERAL, speak=True, answer=ANSWER), "不是 JSON", "", t)
    assert t["patch"] == "unreadable"
