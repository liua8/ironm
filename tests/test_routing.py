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

    assert top("我的体脂率是多少") == "nutrition"  # 体脂归营养师（spec [2026-10-23] §20）
    assert top("哑铃划船怎么做才能练到背") == "trainer"
    assert top("最近静息心率有点高") == "recovery"
    assert top("这个月步数达标了吗") == "trainer"
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
    llm = ("pro", s(trainer=0.9, nutrition=0.8, recovery=0.3))
    d = combine(
        "x", llm=llm, keyword=s(trainer=1.0, nutrition=0.7), vector=s(trainer=1.0, nutrition=0.9)
    )
    assert [r.value for r in d.roles] == ["trainer", "nutrition"]  # 营养 ≥ 0.6 且差距 ≤ 0.2
    far = combine(
        "x",
        llm=("pro", s(trainer=1.0, nutrition=0.7)),
        keyword=s(trainer=1.0),
        vector=s(trainer=1.0),
    )
    assert [r.value for r in far.roles] == ["trainer"]  # 营养 0.49 不到 0.6
    many = combine("x", llm=("pro", s(trainer=0.9, nutrition=0.9, recovery=0.85)),
                   keyword=s(trainer=1, nutrition=1, recovery=1), vector=None)  # fmt: skip
    assert len(many.roles) == 3  # 人数不设上限


def test_fallback_weights() -> None:
    d = combine("x", llm=None, keyword=s(nutrition=1.0), vector=s(trainer=1.0))
    assert d.weights == {"keyword": 2 / 3, "vector": 1 / 3} and d.primary is Role.NUTRITION
    e = combine("x", llm=("pro", s(trainer=1.0)), keyword=s(nutrition=1.0), vector=None)
    assert round(e.weights["llm"], 3) == round(7 / 9, 3) and e.primary is Role.TRAINER


def test_intent_and_discomfort() -> None:
    chat = combine("你好", llm=("chat", ZERO), keyword=ZERO, vector=ZERO)
    assert chat.intent == "chat" and chat.roles == ()
    hurt = combine(
        "练完腿膝盖疼", llm=("chat", s(trainer=1.0)), keyword=s(trainer=1.0), vector=None
    )
    assert (
        hurt.intent == "pro" and Role.RECOVERY in hurt.roles
    )  # 身体不适一律按专业问题，并请康复恢复师
    order = combine(
        "x",
        llm=("pro", s(trainer=1.0, recovery=0.95)),
        keyword=s(trainer=1.0, recovery=1.0),
        vector=None,
    )
    assert order.primary is Role.TRAINER and order.roles == (Role.TRAINER, Role.RECOVERY)


def test_log_has_scores_not_text() -> None:
    d = combine(
        "我左膝疼得厉害", llm=("pro", s(recovery=1.0)), keyword=s(recovery=1.0), vector=None
    )
    log = d.log()
    assert set(log) == {"intent", "roles", "weights", "weighted", "channels", "skills"}
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
        lambda *_: jsonr({"intent": "pro", "scores": {"trainer": 0.9, "nutrition": 2, "x": 1}})
    )
    got = asyncio.run(llm_scores("一周练几次", llm))
    assert (
        got is not None
        and got[0] == "pro"
        and got[1]["trainer"] == 0.9
        and got[1]["nutrition"] == 1.0
    )
    assert asyncio.run(llm_scores("x", FakeLLM(down))) is None
    assert asyncio.run(llm_scores("x", FakeLLM(lambda *_: jsonr({"intent": "什么"})))) is None


def test_as_route_and_summary_for_the_chain() -> None:
    from ironm_agent.compose import _PROMPT as COMPOSE
    from ironm_agent.plugin import as_route, route_summary

    d = combine("x", llm=("pro", s(nutrition=1.0, trainer=0.9)), keyword=None, vector=None)
    r = as_route(d)
    assert r.by == "weighted" and r.primary is Role.NUTRITION and r.helpers == (Role.TRAINER,)
    text = route_summary(r)
    assert "三路打分" in text and "营养师 1.00" in text and "模型 1.0" in text
    assert "管家直接回答" in route_summary(
        as_route(combine("你好", llm=("chat", ZERO), keyword=None, vector=None))
    )
    assert "AI 健身管家" in COMPOSE  # 多位角色时以管家的口吻整合


def test_chain_logs_route_scores(monkeypatch: Any) -> None:
    """作答链路的运行记录里有三路的得分（这里只有模型一路），不含用户原话。"""
    from tests.test_turn_flow import Team, agent, run

    a = agent(Team("nutrition", ["trainer"]), monkeypatch=monkeypatch)
    _, seen = run(a, "增肌期练完吃什么比较好")
    assert seen["route_by"] == "weighted" and seen["route"]["roles"] == ["nutrition", "trainer"]
    assert "llm" in seen["route"]["channels"] and "增肌" not in str(seen["route"])


# ---- 路由同时选 Skill（spec [2026-10-23] §21）--------------------------------------------------


def test_llm_channel_picks_skills_and_drops_bad_ids() -> None:
    from ironm_agent.routing import LLMResult

    reply = {
        "intent": "pro",
        "scores": {"trainer": 1.0, "nutrition": 0.8, "recovery": 0},
        "skills": {
            "trainer": ["plan-muscle", "food-muscle", "move-feel", "nope", "plan-muscle", "move-teach",
                        "plan-weekly"],
            "nutrition": [],
            "recovery": "rest-sleep",
        },
    }  # fmt: skip
    got = asyncio.run(llm_scores("增肌怎么练怎么吃", FakeLLM(lambda *_: jsonr(reply))))
    assert isinstance(got, LLMResult)
    # 别的角色的、讲法类的、不存在的、重复的去掉，最多 2 份；空列表表示不装；格式不对的当没选
    assert got.skills == {"trainer": ("plan-muscle", "move-teach"), "nutrition": ()}
    d = combine("x", llm=got, keyword=None, vector=None)
    assert d.skills == {"trainer": ("plan-muscle", "move-teach"), "nutrition": ()}
    assert d.log()["skills"] == {"trainer": ["plan-muscle", "move-teach"], "nutrition": []}
    only = combine("x", llm=LLMResult("pro", s(trainer=1.0), {"nutrition": ("food-muscle",)}),
                   keyword=None, vector=None)  # fmt: skip
    assert only.skills == {}  # 没请到的角色不带
    assert combine("x", llm=("pro", s(trainer=1.0)), keyword=None, vector=None).skills == {}


def test_route_prompt_lists_skill_catalog() -> None:
    seen: list[str] = []

    def reply(stage: Any, messages: Any, tools: bool) -> Any:
        seen.append(str(messages[0]["content"]))
        return jsonr({"intent": "pro", "scores": {}})

    asyncio.run(llm_scores("增肌", FakeLLM(reply)))
    assert "plan-muscle 增肌" in seen[0] and "data-trend 趋势解读" in seen[0]
    assert "move-feel" not in seen[0]  # 讲法类不由路由选
    assert "空列表" in seen[0]


def test_chain_uses_routed_skills(monkeypatch: Any) -> None:
    from tests.fakes import route_reply
    from tests.test_turn_flow import Team, agent, run, snapshot_of

    class Picky(Team):
        def __init__(self, skills: Any) -> None:
            super().__init__("nutrition")
            self.skills = skills

        def __call__(self, stage: Any, messages: Any, tools: bool) -> Any:
            if stage == "route":
                return route_reply("pro", "nutrition", (), self.skills)
            return super().__call__(stage, messages, tools)

    _, seen = run(agent(Picky({"nutrition": []}), monkeypatch=monkeypatch, snapshot=snapshot_of()),
                  "肌酸是什么")  # fmt: skip
    assert seen["skills"] == {"nutrition": []} and seen["skills_by"] == {"nutrition": "route"}
    _, seen = run(agent(Picky({"nutrition": ["food-supplement"]}), monkeypatch=monkeypatch,
                        snapshot=snapshot_of()), "肌酸是什么")  # fmt: skip
    assert seen["skills"] == {"nutrition": ["food-supplement"]}
    _, seen = run(
        agent(Picky(None), monkeypatch=monkeypatch, snapshot=snapshot_of()), "肌酸要怎么吃"
    )
    assert seen["skills_by"] == {"nutrition": "rule"} and seen["skills"]["nutrition"]
