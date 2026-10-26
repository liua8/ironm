"""问 App 怎么用（spec [2026-10-23] §36）：照使用说明给具体操作；说明里的数字可以照说，编出来的数字仍退回固定介绍。"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ironm_agent.coach import APP_HELP, GREETING, app_guide, direct
from ironm_agent.llm import ModelUnavailable, Reply, Stage
from tests.fakes import FakeLLM


def ask(intent: str, text: str, answer: str) -> tuple[str, list[str]]:
    systems: list[str] = []

    def handler(stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        systems.append(str(messages[0]["content"]))
        return Reply(answer)

    return asyncio.run(direct(intent, text, [], FakeLLM(handler))), systems


def test_guide_covers_the_main_pages() -> None:
    guide = app_guide()
    for words in (
        "首页",
        "今日任务",
        "练完打卡",
        "记一条",
        "设置城市",
        "历史",
        "撤销",
        "目前还做不到",
    ):
        assert words in guide, words


def test_app_question_gets_steps_from_the_guide() -> None:
    steps = "在数据页点体重，再点“记一条”，填数值和日期就行。饮食复盘每两周看一次，每 4 周提醒复测一次。"
    got, systems = ask("app", "怎么记体重", steps)
    assert got == steps  # 说明里出现的数字（两周、4 周）可以照说
    assert "使用说明" in systems[0] and "练完打卡" in systems[0]


def test_made_up_numbers_still_fall_back() -> None:
    got, _ = ask("app", "怎么记体重", "每天称 3 次，每次减 500 千卡")
    assert got == APP_HELP
    chat, systems = ask("chat", "你好", "你好！今天练 5 组深蹲吧")
    assert chat == GREETING and "使用说明" not in systems[0]  # 闲聊不带使用说明，规矩照旧


def test_model_unavailable_uses_the_fixed_intro() -> None:
    def down(*_: Any) -> Reply:
        raise ModelUnavailable("missing_key")

    assert asyncio.run(direct("app", "怎么用", [], FakeLLM(down))) == APP_HELP
