"""整轮：mirobody 调用 iron-m 的 Agent，得到的流式块。"""

import asyncio
from collections.abc import Mapping, Sequence
from importlib.metadata import entry_points
from typing import Any

from ironm_agent.casefile import Snapshot
from ironm_agent.day_state import DayBook
from ironm_agent.goal import GoalBook
from ironm_agent.illness import IllnessBook
from ironm_agent.llm import ModelUnavailable, Reply, Stage, load_models
from ironm_agent.memory_store import MemoryBook, MemoryStore
from ironm_agent.plugin import FAILED, IronMAgent
from ironm_agent.render import TURN_ID
from ironm_agent.tools import HEALTH
from ironm_agent.triggers import PainBook
from tests.fakes import FakeHealth, call, jsonr, system_of, tool_results


class Scripted:
    """单 Agent 的假模型（替换 TurnLLM）：先查静息心率，再写回答；选规程给不出合格结果（退回按关键词）。"""

    def __init__(self, answer: str = "", fail: bool = False) -> None:
        self.answer = answer
        self.fail = fail
        self.count = 0
        self.stages: list[str] = []
        self.inputs: list[str] = []

    def __call__(
        self, stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool
    ) -> Reply:
        self.count += 1
        self.stages.append(stage)
        if self.fail:
            raise ModelUnavailable("missing_key")
        if stage == "route":
            return Reply("不是 JSON")
        if stage == "expert":
            self.inputs.append("\n".join(str(m.get("content", "")) for m in messages))
            stated = "<statement>近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>"
            if has_tools and not tool_results(messages):
                return call(HEALTH, indicators=["restingHeartRates"], view="stats")
            return jsonr({"answer": self.answer or stated})
        return Reply(self.answer)


def agent(
    script: Any,
    health: FakeHealth | None = None,
    monkeypatch: Any = None,
    memory: MemoryStore | None = None,
    snapshot: Any = None,
    goals: GoalBook | None = None,
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

    async def no_data(_: str) -> Snapshot:
        return Snapshot()

    return IronMAgent(
        health=health or FakeHealth(),
        models=load_models(),
        environ={},
        memory=memory if memory is not None else MemoryBook(),
        snapshot=snapshot or no_data,
        pain=PainBook(),
        illness=IllnessBook(),
        day=DayBook(),
        goals=goals if goals is not None else GoalBook(),
    )


def collect(a: IronMAgent, content: Any) -> list[dict[str, Any]]:
    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": content}]
        blocks = [b async for b in a.generate_response("42", msgs, session_id="42:s1")]
        await a.settle()  # 等后台的记忆提取做完
        return shown(blocks)

    return asyncio.run(go())


def shown(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉这一轮的编号块（页面评价时用，不显示，spec [2026-10-23] §31）。"""
    return [b for b in blocks if TURN_ID not in (b.get("id"), b.get("tool_call_id"))]


def text_of(blocks: list[dict[str, Any]]) -> str:
    return "".join(b.get("text", "") for b in blocks if b["type"] == "text")


def test_emergency_answers_without_reading_data_or_tools(monkeypatch: Any) -> None:
    """急症（§86）：只调一次模型说话，不读数据、不调工具；模型不可用时退回四段式固定回答。"""
    health = FakeHealth()
    s = Scripted(fail=True)
    blocks = collect(
        agent(s, health, monkeypatch=monkeypatch), "跑步的时候胸口突然很痛，现在还在疼"
    )
    assert s.stages == ["expert"] and health.asked == []
    assert "**" in text_of(blocks) and "120" in text_of(blocks)
    assert not any(b["type"] == "tool_call" for b in blocks)


def test_data_question_answers_plainly_and_attaches_sources(monkeypatch: Any) -> None:
    answer = "你近 30 天静息心率很稳。<statement>平均 58 次/分<cite>[r1]</cite></statement>，在正常范围。"
    blocks = collect(agent(Scripted(answer), monkeypatch=monkeypatch), "我最近的静息心率怎么样")
    names = [b["name"] for b in blocks if b["type"] == "tool_call"]
    assert names == ["管家", "依据与来源"]
    text = text_of(blocks)
    assert (
        "平均 58 次/分" in text
        and "<statement>" not in text
        and "〔" not in text
        and "[r1]" not in text
    )
    sources = next(
        b["content"]
        for b in blocks
        if b["type"] == "tool_result" and b["tool_call_id"] == "sources"
    )
    assert "你的数据" in sources and "58.2" in sources


def test_asking_for_sources_explains_the_previous_answer(monkeypatch: Any) -> None:
    from ironm_agent import plugin

    async def fake_sources(session_id: str, call_id: str) -> str:
        assert call_id == "sources"
        return "计算：\n- 每日热量目标：约 2764 千卡/天。计算：每日总消耗 2513 × 1.1 = 2764\n\n资料：\n- 中国居民膳食指南（2022）"

    monkeypatch.setattr(plugin, "last_sources", fake_sources)
    said = "2764 是按你每天总消耗 2513 千卡再加一成算的。"
    s = Scripted(said)
    blocks = collect(agent(s, monkeypatch=monkeypatch), "2764 是怎么算的")
    # 依据交给模型讲（§86）：它看得到上一条回答的计算和资料，说的话就是回答，不按模板念
    assert "2513 × 1.1" in s.inputs[-1] and "膳食指南" in s.inputs[-1]
    assert said in text_of(blocks) and "上一条回答的依据：" not in text_of(blocks)


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
    assert "没答上来" in text_of(blocks)
    assert not any(b["type"] == "error" for b in blocks)


def test_unexpected_error_hides_details(monkeypatch: Any) -> None:
    from ironm_agent import plugin

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("SELECT secret FROM th_messages")

    monkeypatch.setattr(plugin, "assess", boom)
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


def test_asking_for_someone_else_is_not_supported(monkeypatch: Any) -> None:
    """不做关爱圈：提问人（会话编号前半）和数据的主人不同，只说明不支持，不读对方数据、不碰记忆；
    话交给模型说（§86），模型不可用时退回固定的一句。"""
    from ironm_agent.memory_store import Change, Item, MemoryBook
    from ironm_agent.plugin import HELP_ASK

    s = Scripted(fail=True)
    health = FakeHealth()
    book = MemoryBook()
    from datetime import UTC, datetime

    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    asyncio.run(
        book.apply(
            "42",
            [
                Change(
                    "insert", item=Item("k", "injury", "左膝旧伤", "左膝", "said", "active", t0, t0)
                )
            ],
        )
    )
    a = agent(s, health, monkeypatch=monkeypatch, memory=book)

    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": "我妈最近血压怎么样，我自己膝盖也疼"}]
        blocks = shown([b async for b in a.generate_response("42", msgs, session_id="7:s1")])
        await a.settle()
        return blocks

    blocks = asyncio.run(go())
    assert text_of(blocks) == HELP_ASK and s.stages == ["expert"] and health.asked == []
    assert [x.content for x in asyncio.run(book.items("42"))] == ["左膝旧伤"]


def test_single_mode_answers_in_one_pass_without_routing_or_composing(monkeypatch: Any) -> None:
    """单 Agent（spec [2026-10-23] §67）：不调度、不整合，一个 Agent 调工具直接写回答，照常核对并附“依据与来源”。"""
    from tests.fakes import FakeLLM

    def script(stage: Stage, messages: Sequence[Mapping[str, Any]], has_tools: bool) -> Reply:
        if stage == "route":  # 按意图选规程（§75），不是调度给角色
            return jsonr(
                {"skills": ["data-read"], "domains": ["rest"], "intent": "心率", "fit": "skill"}
            )
        assert stage == "expert" and "AI 健身管家" in system_of(messages)
        if not tool_results(messages):
            return call(HEALTH, indicators=["restingHeartRates"], view="stats")
        return jsonr(
            {
                "answer": "你最近很稳：<statement>近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>。"
            }
        )

    a = agent(script, monkeypatch=monkeypatch)
    a._remember_on = False
    stages: list[str] = []
    real = FakeLLM.chat

    async def spy(self: FakeLLM, stage: Stage, *args: Any, **kwargs: Any) -> Reply:
        stages.append(stage)
        return await real(self, stage, *args, **kwargs)

    monkeypatch.setattr(FakeLLM, "chat", spy)
    blocks = collect(a, "我最近的静息心率怎么样")
    assert (
        set(stages) == {"route", "expert"} and stages.count("route") == 1
    )  # 不整合（没有 compose）
    assert [b["name"] for b in blocks if b["type"] == "tool_call"] == ["管家", "依据与来源"]
    assert "平均 58 次/分" in text_of(blocks) and "<statement>" not in text_of(blocks)


def test_observer_gets_the_run_record(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}
    a = agent(Scripted("你近 30 天静息心率很稳。"), monkeypatch=monkeypatch)
    a._observe = seen.update
    collect(a, "我最近的静息心率怎么样")
    assert seen["path"] == "answer" and seen["roles"] == ["general"] and seen["agent"] == "single"
    assert seen["model_calls"] >= 3  # 选规程、查数据、作答
