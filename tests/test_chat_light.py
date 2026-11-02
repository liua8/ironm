"""打招呼不再带出计划（spec [2026-10-23] §98）：选规程判断是闲聊时只给记忆和历史，不给档案和排计划的条件。"""

from __future__ import annotations

from typing import Any

from tests.fakes import jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import run

CHAT = {"skills": [], "domains": [], "intent": "打招呼", "fit": "chat"}


def turn(monkeypatch: Any, routed: dict[str, Any], text: str) -> tuple[Any, dict[str, Any]]:
    a, s = single(lambda *_: jsonr({"answer": "你好！"}), monkeypatch, seeded=True, old=True)
    s.route = lambda _: jsonr(routed)
    _, seen = run(a, text)
    return s, seen


def test_greeting_gets_memory_and_history_but_no_case_file(monkeypatch: Any) -> None:
    s, seen = turn(monkeypatch, CHAT, "你好")
    assert seen["chat_light"] and seen["skills"]["general"] == []
    assert (
        "这个人的档案" not in s.user
        and "按计划" not in s.user
        and "排新计划要用的条件" not in s.user
    )
    assert "最新的基本数据" not in s.user  # 不给数据，免得报数
    assert "用户画像" in s.user  # 记忆还在，可以像熟人那样问候


def test_not_chat_keeps_the_case_file(monkeypatch: Any) -> None:
    routed = {
        "skills": ["readiness-adjust"],
        "domains": ["train"],
        "intent": "今天练什么",
        "fit": "skill",
    }
    s, seen = turn(monkeypatch, routed, "你好，今天练什么")
    assert not seen["chat_light"] and "这个人的档案" in s.user and "按计划" in s.user
