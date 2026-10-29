"""单 Agent 开关（spec [2026-10-23] §62 需求 2、§67 需求 6）：配置切换架构，默认单 Agent，运行记录写明用的哪种。"""

from __future__ import annotations

from typing import Any

from ironm_agent.llm import load_models
from ironm_agent.plugin import MODE_ENV, IronMAgent, agent_mode
from tests.test_plugin import Scripted, agent, collect


def test_mode_comes_from_config_and_defaults_to_single() -> None:
    assert agent_mode({}) == "single"
    assert agent_mode({MODE_ENV: "multi"}) == "multi"
    assert agent_mode({MODE_ENV: " Multi "}) == "multi"
    assert agent_mode({MODE_ENV: "其他"}) == "single"  # 配错时用默认的单 Agent


def test_agent_reads_the_switch_at_start() -> None:
    assert IronMAgent(models=load_models(), environ={})._mode == "single"
    assert IronMAgent(models=load_models(), environ={MODE_ENV: "multi"})._mode == "multi"
    # 直接指定的优先（考题对比用）
    assert (
        IronMAgent(models=load_models(), environ={MODE_ENV: "multi"}, mode="single")._mode
        == "single"
    )


def test_run_record_names_the_mode(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}
    a = agent(
        Scripted("你近 30 天静息心率很稳。"), monkeypatch=monkeypatch
    )  # 测试助手固定用多 Agent
    a._observe = seen.update
    collect(a, "我最近的静息心率怎么样")
    assert seen["agent"] == "multi"
