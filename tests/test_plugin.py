"""整轮：mirobody 调用 iron-m 的 Agent，得到的流式块。"""

import asyncio
from collections.abc import Mapping, Sequence
from importlib.metadata import entry_points
from typing import Any

from ironm_agent.llm import ModelUnavailable, Reply, Stage, load_models
from ironm_agent.plugin import FAILED, IronMAgent
from ironm_agent.tools import HEALTH
from tests.fakes import FakeHealth, call, jsonr, system_of, tool_results


class Scripted:
    """按环节与角色回答的假模型（替换 TurnLLM）。"""

    def __init__(self, compose_text: str = "", fail: bool = False) -> None:
        self.compose_text = compose_text
        self.fail = fail
        self.count = 0

    def __call__(
        self, stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool
    ) -> Reply:
        self.count += 1
        if self.fail:
            raise ModelUnavailable("missing_key")
        system = system_of(messages)
        if stage == "route":
            return jsonr(
                {"intent": "pro", "primary": "data", "helpers": [], "reason": "问自己的数据"}
            )
        if stage == "expert":
            if "数据分析" in system:
                if not tool_results(messages):
                    return call(HEALTH, indicators=["restingHeartRates"], view="stats")
                return jsonr(
                    {
                        "speak": True,
                        "conclusion": "<statement>近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>",
                    }
                )
            return jsonr({"speak": False, "reason": "没有需要提醒的风险"})
        return Reply(self.compose_text)


def agent(
    script: Scripted, health: FakeHealth | None = None, monkeypatch: Any = None
) -> IronMAgent:
    from ironm_agent import plugin

    class _LLM:
        def __init__(self, *_: Any) -> None:
            from tests.fakes import FakeLLM

            self._inner = FakeLLM(script)
            self.calls = self._inner.calls

        async def chat(self, *args: Any, **kwargs: Any) -> Reply:
            return await self._inner.chat(*args, **kwargs)

    monkeypatch.setattr(plugin, "TurnLLM", _LLM)
    return IronMAgent(health=health or FakeHealth(), models=load_models(), environ={})


def collect(a: IronMAgent, content: Any) -> list[dict[str, Any]]:
    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": content}]
        return [b async for b in a.generate_response("42", msgs, session_id="42:s1")]

    return asyncio.run(go())


def text_of(blocks: list[dict[str, Any]]) -> str:
    return "".join(b.get("text", "") for b in blocks if b["type"] == "text")


def test_emergency_answers_without_any_model_call(monkeypatch: Any) -> None:
    s = Scripted()
    blocks = collect(agent(s, monkeypatch=monkeypatch), "跑步的时候胸口突然很痛，现在还在疼")
    assert s.count == 0
    assert "**" in text_of(blocks) and not any(b["type"] == "tool_call" for b in blocks)


def test_data_question_streams_roles_and_cited_answer(monkeypatch: Any) -> None:
    answer = "**结论**\n<statement>你近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>，在正常范围。"
    blocks = collect(agent(Scripted(answer), monkeypatch=monkeypatch), "我最近的静息心率怎么样")
    names = [b["name"] for b in blocks if b["type"] == "tool_call"]
    assert names == ["主教练", "数据分析", "安全官"]
    assert "<cite>[r1]</cite>" in text_of(blocks)
    from mirobody.kernel.citations import parse

    assert any("r1" in seg.cites for seg in parse(text_of(blocks)))


def test_failed_review_degrades_with_notice(monkeypatch: Any) -> None:
    blocks = collect(
        agent(Scripted("你的静息心率平均 99 次/分。"), monkeypatch=monkeypatch),
        "我最近的静息心率怎么样",
    )
    assert any(b["type"] == "notice" and "受限" in b["text"] for b in blocks)
    assert "58" in text_of(blocks)  # 列出的是已经核对过的意见


def test_health_failure_still_answers(monkeypatch: Any) -> None:
    answer = "**结论**\n这次没读到你的数据。"
    script = Scripted(answer)
    blocks = collect(
        agent(script, FakeHealth(fail=True), monkeypatch=monkeypatch), "我最近的静息心率怎么样"
    )
    assert any(b["type"] == "notice" and "没读到" in b["text"] for b in blocks)
    assert not any(b["type"] == "error" for b in blocks)


def test_list_content_and_empty_message(monkeypatch: Any) -> None:
    a = agent(Scripted("**结论**\n好的。"), monkeypatch=monkeypatch)
    assert any(
        b["type"] == "tool_call"
        for b in collect(a, [{"type": "text", "text": "我最近的静息心率怎么样"}])
    )
    assert collect(a, []) == [{"type": "notice", "text": "没有收到文字问题。"}]


def test_model_down_everywhere_gives_honest_no_answer(monkeypatch: Any) -> None:
    blocks = collect(agent(Scripted(fail=True), monkeypatch=monkeypatch), "我最近的静息心率怎么样")
    assert "没有找到可靠的依据" in text_of(blocks)
    assert not any(b["type"] == "error" for b in blocks)


def test_unexpected_error_hides_details(monkeypatch: Any) -> None:
    from ironm_agent import plugin

    async def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("SELECT secret FROM th_messages")

    monkeypatch.setattr(plugin, "route", boom)
    blocks = collect(agent(Scripted(), monkeypatch=monkeypatch), "我最近的静息心率怎么样")
    assert blocks == [{"type": "error", "message": FAILED}]


def test_entry_point_is_registered() -> None:
    assert [ep.value for ep in entry_points(group="mirobody.agents")] == ["ironm_agent.plugin"]


def test_web_picker_gets_the_model_iron_m_actually_uses() -> None:
    """网页先取 /api/models 的第一项作为默认模型才能发问；列表为空时无法提问。"""
    entries = {
        "claude-sonnet": {"llm_type": "openai", "api_key": "OPENROUTER_API_KEY"},
        "deepseek": {"llm_type": "openai", "api_key": "DEEPSEEK_API_KEY"},
    }
    assert set(IronMAgent.load_llm_clients(entries)) == {"deepseek"}


def test_web_picker_never_empty_when_some_model_is_configured() -> None:
    entries = {"qwen": {"llm_type": "openai", "api_key": "DASHSCOPE_API_KEY"}}
    assert set(IronMAgent.load_llm_clients(entries)) == {"qwen"}
