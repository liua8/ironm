"""三路打分路由（spec [2026-10-23] §16）：不调用模型；语义向量用假的嵌入模型。"""

import asyncio
from pathlib import Path
from typing import Any

from ironm_agent.roles import Role
from ironm_agent.routing import (
    NAMES,
    KeywordScorer,
    VectorScorer,
    combine,
    examples,
    keyword_intent,
    llm_scores,
)
from ironm_agent.yamlfile import load_yaml
from tests.fakes import FakeLLM, down, jsonr

ROOT = Path(__file__).resolve().parents[1]
ZERO = dict.fromkeys(NAMES, 0.0)


def s(**kw: float) -> dict[str, float]:
    return ZERO | kw


def test_examples_do_not_copy_eval_questions() -> None:
    asks = {c["ask"] for c in load_yaml(ROOT / "evals/qa/cases.yaml")["cases"]}  # type: ignore[index]
    lib = examples()
    mine = {x for r in lib.roles.values() for x in r.examples}
    assert not (mine & asks)  # 例句和考题重复会让测出来的准确率虚高
    assert all(len(r.examples) >= 25 for r in lib.roles.values())


def test_keyword_channel() -> None:
    kw = KeywordScorer.build()

    def top(text: str) -> str:
        sc = kw.scores(text)
        return max(sc, key=lambda k: sc[k])

    assert top("我的体脂率是多少") == "data"
    assert top("哑铃划船怎么做才能练到背") == "exercise"
    assert top("练前吃什么好") == "nutrition"
    assert max(kw.scores("asdf").values()) == 0.0


def test_keyword_intent() -> None:
    assert keyword_intent("今天股市怎么样") == "out_of_scope"
    assert keyword_intent("你是什么模型") == "app"
    assert keyword_intent("谢谢") == "chat"
    assert (
        keyword_intent("谢谢，那深蹲之后膝盖疼要怎么调整训练") is None
    )  # 长句里带"谢谢"仍是专业问题


def test_top_role_and_join_threshold() -> None:
    llm = ("pro", s(planner=0.9, nutrition=0.8, exercise=0.3))
    d = combine(
        "x", llm=llm, keyword=s(planner=1.0, nutrition=0.7), vector=s(planner=1.0, nutrition=0.9)
    )
    assert [r.value for r in d.roles] == ["planner", "nutrition"]  # 营养 ≥ 0.6 且差距 ≤ 0.2
    far = combine(
        "x",
        llm=("pro", s(planner=1.0, nutrition=0.7)),
        keyword=s(planner=1.0),
        vector=s(planner=1.0),
    )
    assert [r.value for r in far.roles] == ["planner"]  # 营养 0.49 不到 0.6
    many = combine("x", llm=("pro", s(planner=0.9, nutrition=0.9, exercise=0.85, data=0.8)),
                   keyword=s(planner=1, nutrition=1, exercise=1, data=1), vector=None)  # fmt: skip
    assert len(many.roles) == 4  # 人数不设上限


def test_fallback_weights() -> None:
    d = combine("x", llm=None, keyword=s(data=1.0), vector=s(exercise=1.0))
    assert d.weights == {"keyword": 2 / 3, "vector": 1 / 3} and d.primary is Role.DATA
    e = combine("x", llm=("pro", s(exercise=1.0)), keyword=s(data=1.0), vector=None)
    assert round(e.weights["llm"], 3) == round(7 / 9, 3) and e.primary is Role.EXERCISE


def test_intent_and_discomfort() -> None:
    chat = combine("你好", llm=("chat", ZERO), keyword=ZERO, vector=ZERO)
    assert chat.intent == "chat" and chat.roles == ()
    hurt = combine(
        "练完腿膝盖疼", llm=("chat", s(planner=1.0)), keyword=s(planner=1.0), vector=None
    )
    assert hurt.intent == "pro" and Role.RECOVERY in hurt.roles  # 身体不适一律按专业问题，并请恢复
    order = combine(
        "x",
        llm=("pro", s(planner=1.0, recovery=0.95)),
        keyword=s(planner=1.0, recovery=1.0),
        vector=None,
    )
    assert order.primary is Role.PLANNER and order.roles == (Role.PLANNER, Role.RECOVERY)


def test_log_has_scores_not_text() -> None:
    d = combine(
        "我左膝疼得厉害", llm=("pro", s(recovery=1.0)), keyword=s(recovery=1.0), vector=None
    )
    log = d.log()
    assert set(log) == {"intent", "roles", "weights", "weighted", "channels"}
    assert "左膝" not in str(log)


class FakeEmbed:
    """按关键字把句子放到几个方向上的假嵌入模型。"""

    def embed(self, texts: list[str]) -> Any:
        for t in texts:
            yield [
                float("吃" in t or "喝" in t),
                float("睡" in t or "疼" in t),
                float("体重" in t or "多少" in t),
                0.1,
            ]


def test_vector_channel_with_fake_model() -> None:
    v = VectorScorer(model=FakeEmbed())
    sc = v.scores("晚上吃什么")
    assert max(sc, key=lambda k: sc[k]) == "nutrition" and min(sc.values()) == 0.0


def test_llm_channel_parses_and_falls_back() -> None:
    llm = FakeLLM(
        lambda *_: jsonr({"intent": "pro", "scores": {"planner": 0.9, "data": 2, "x": 1}})
    )
    got = asyncio.run(llm_scores("一周练几次", llm))
    assert (
        got is not None and got[0] == "pro" and got[1]["planner"] == 0.9 and got[1]["data"] == 1.0
    )
    assert asyncio.run(llm_scores("x", FakeLLM(down))) is None
    assert asyncio.run(llm_scores("x", FakeLLM(lambda *_: jsonr({"intent": "什么"})))) is None


def test_as_route_and_summary_for_the_chain() -> None:
    from ironm_agent.compose import _PROMPT as COMPOSE
    from ironm_agent.plugin import as_route, route_summary

    d = combine("x", llm=("pro", s(nutrition=1.0, planner=0.9)), keyword=None, vector=None)
    r = as_route(d)
    assert r.by == "weighted" and r.primary is Role.NUTRITION and r.helpers == (Role.PLANNER,)
    text = route_summary(r)
    assert "三路打分" in text and "营养 1.00" in text and "模型 1.0" in text
    assert "管家直接回答" in route_summary(
        as_route(combine("你好", llm=("chat", ZERO), keyword=None, vector=None))
    )
    assert "AI 健身管家" in COMPOSE  # 多位角色时以管家的口吻整合


def test_chain_logs_route_scores(monkeypatch: Any) -> None:
    """作答链路的运行记录里有三路的得分（这里只有模型一路），不含用户原话。"""
    from tests.test_turn_flow import Team, agent, run

    a = agent(Team("nutrition", ["planner"]), monkeypatch=monkeypatch)
    _, seen = run(a, "增肌期练完吃什么比较好")
    assert seen["route_by"] == "weighted" and seen["route"]["roles"] == ["nutrition", "planner"]
    assert "llm" in seen["route"]["channels"] and "增肌" not in str(seen["route"])
