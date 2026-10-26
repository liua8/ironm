"""问天气适不适合运动要回答，不能判成"超出范围"（spec [2026-10-23] §41）。"""

import pytest

from ironm_agent.harness import diagnose
from ironm_agent.routing import _PROMPT, NAMES, KeywordScorer, combine, examples

ZERO = dict.fromkeys(NAMES, 0.0)


@pytest.mark.parametrize(
    "text", ["今天天气适合跑步吗", "明天天气怎么样", "下雨了还能出去骑车吗", "这么热晚上还去练吗"]
)
def test_model_out_of_scope_is_overruled_for_fitness_and_weather(text: str) -> None:
    d = combine(
        text, llm=("out_of_scope", ZERO), keyword=KeywordScorer.build().scores(text), vector=None
    )
    assert d.intent == "pro" and d.roles and d.roles[0].value == "trainer"


@pytest.mark.parametrize("text", ["帮我写一首关于春天的诗", "今天股市怎么样", "帮我写代码"])
def test_unrelated_questions_stay_out_of_scope(text: str) -> None:
    d = combine(
        text, llm=("out_of_scope", ZERO), keyword=KeywordScorer.build().scores(text), vector=None
    )
    assert d.intent == "out_of_scope" and d.roles == ()


def test_prompt_and_examples_cover_weather() -> None:
    assert "天气" in _PROMPT
    assert (
        sum(
            any(w in x for w in ("天气", "下雨", "雾霾", "三十七度"))
            for x in examples().roles["trainer"].examples
        )
        >= 4
    )


def test_declined_scope_is_a_route_signal() -> None:
    [s] = [s for s in diagnose({"route": {"intent": "out_of_scope"}}) if s.kind == "declined_scope"]
    assert s.stage == "route"
    assert not [s for s in diagnose({"route": {"intent": "pro"}}) if s.kind == "declined_scope"]
