"""路由没把握时由管家结合上下文答（spec [2026-10-23] §56）：不调用真实模型。"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ironm_agent.coach import ASK_PREVIEW, ASK_WHICH, GREETING, direct
from ironm_agent.llm import Reply, Stage
from ironm_agent.routing import KeywordScorer, combine, follow_up
from ironm_agent.training import TrainingBook
from tests.fakes import FakeLLM, route_reply

ZERO = {"trainer": 0.0, "nutrition": 0.0, "recovery": 0.0}
PREV = ["用户：我要重新定计划", "教练（要点）：给你排了一份每周 4 练的计划，看看预览。"]


def s(**kw: float) -> dict[str, float]:
    return ZERO | kw


def test_keyword_below_threshold_scores_zero() -> None:
    kw = KeywordScorer.build()
    assert kw.scores("不太行") == ZERO  # 只重合一个"不"字
    hit = kw.scores("深蹲膝盖疼怎么办")
    assert max(hit.values()) == 1.0  # 到门槛的照旧归一
    d = combine("x", llm=("pro", s(nutrition=1.0)), keyword=ZERO, vector=s(nutrition=1.0))
    assert "keyword" not in d.channels  # 没命中这一路不算


def test_short_follow_ups_go_to_the_butler() -> None:
    for text in ("不太行", "不行", "好的", "然后呢", "为什么", "还有吗", "不满意", "什么意思？"):
        assert follow_up(text, PREV), text
        d = combine(text, llm=("pro", s(trainer=0.9)), keyword=s(trainer=1.0), vector=None,
                    history=PREV)  # fmt: skip
        assert d.intent == "chat" and d.roles == () and d.unsure == "follow_up", text
        assert d.log()["unsure"] == "follow_up"
        alone = combine(text, llm=("pro", s(trainer=0.9)), keyword=s(trainer=1.0), vector=None)
        assert not alone.unsure, text  # 没有上一轮照常路由
    for text in ("不行，膝盖疼", "膝盖疼还能深蹲吗", "早餐吃什么"):
        assert not follow_up(text, PREV), text
        d = combine(text, llm=("pro", s(recovery=0.9)), keyword=s(recovery=1.0), vector=None,
                    history=PREV)  # fmt: skip
        assert d.intent == "pro" and d.roles and not d.unsure, text


def test_agree_after_question_is_routed() -> None:
    asked = ["用户：周三有事", "教练（要点）：要我把周三那次挪到周四吗？"]
    for text in ("好的", "可以", "行"):
        assert not follow_up(text, asked), text
    assert follow_up("不太行", asked)


def test_three_channels_disagree_and_llm_unsure() -> None:
    llm, kw, vec = s(trainer=0.5), s(nutrition=1.0), s(recovery=1.0)
    d = combine("x", llm=("pro", llm), keyword=kw, vector=vec)
    assert d.intent == "chat" and d.unsure == "disagree"
    sure = combine("熬夜加班后第二天还去健身，练前吃点什么好",
                   llm=("pro", s(nutrition=0.9, recovery=0.6)), keyword=s(trainer=1.0),
                   vector=s(recovery=1.0))  # fmt: skip
    assert sure.intent == "pro" and not sure.unsure  # 模型有把握
    two = combine("x", llm=("pro", llm), keyword=kw, vector=None)
    assert two.intent == "pro" and not two.unsure  # 只有两路
    hurt = combine("膝盖疼", llm=("pro", llm), keyword=kw, vector=vec, history=PREV)
    assert not hurt.unsure  # 身体不适照常交给专业角色


PREVIEW = "待确认的计划预览（上一轮给的）：每周练 4 次（周一全身力量A约 50 分钟）"


def butler(
    text: str, answer: str, context: Sequence[str] = (), preview: bool = False
) -> tuple[str, str]:
    seen: list[str] = []

    def handler(stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        seen.append(str(messages[0]["content"]))
        return Reply(answer)

    got = asyncio.run(direct("chat", text, PREV, FakeLLM(handler), unsure=True, context=context,
                             preview=preview))  # fmt: skip
    return got, seen[0]


def test_butler_sees_preview_and_checks_numbers() -> None:
    ok = "刚才那份是每周 4 练、每次约 50 分钟。你觉得哪里不行？"
    got, system = butler("不太行", ok, [PREVIEW], preview=True)
    assert got == ok and PREVIEW in system
    assert "复述那份预览的要点" in system and "不要扯回今天打卡" in system
    made_up = "那改成每周 3 练、每次 40 分钟。"  # 预览和上一条回答里都没有的数字
    assert butler("不太行", made_up, [PREVIEW], preview=True)[0] == ASK_PREVIEW
    assert butler("然后呢", made_up)[0] == ASK_WHICH
    assert ASK_PREVIEW != GREETING and "预览" in ASK_PREVIEW


def test_chain_hands_follow_up_to_butler_with_preview(monkeypatch: Any) -> None:
    import mirobody.agent.chat.message as message

    from tests.test_turn_flow import Team, agent, run

    async def history(owner: str, session: str) -> list[dict[str, Any]]:
        return [{"role": "user", "content": "我要重新定计划"},
                {"role": "assistant", "content": "给你排了一份每周 4 练的计划，看看预览。"},
                {"role": "user", "content": "不太行"}]  # fmt: skip

    monkeypatch.setattr(message, "get_chat_history", history)

    class Butler(Team):
        system = ""

        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "route":
                return route_reply("pro", "trainer")
            if stage == "compose":
                Butler.system = str(messages[0]["content"])
                return Reply("刚才那份是每周 4 练。你觉得哪里不行？")
            return super().__call__(stage, messages, tools)

    team = Butler("trainer")
    a = agent(team, monkeypatch=monkeypatch)
    book = TrainingBook()
    plan = {"title": "减重计划", "goal": "减脂", "days_per_week": 4, "sessions": [
        {"day": d, "name": f"力量{d}", "minutes": 50,
         "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": 10}]} for d in (1, 2, 4, 6)]}  # fmt: skip
    asyncio.run(book.add_draft("42", "plan", {"plan": plan}))
    a._training = book
    blocks, seen = run(a, "不太行")
    assert seen["path"] == "direct" and seen["route_unsure"] == "follow_up"
    assert seen["follow_context"]["preview"] is True
    assert "expert" not in team.stages
    assert "待确认的计划预览" in Butler.system and "每周练 4 次" in Butler.system
    assert any("哪里不行" in str(b.get("text", "")) for b in blocks)
