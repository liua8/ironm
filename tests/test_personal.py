"""每轮先读的个人基本数据、按体重换算的数字核对、只给用户自己说过的话做上下文。"""

import asyncio
from typing import Any

from ironm_agent.checks import check_text
from ironm_agent.kb import default_kb
from ironm_agent.memory import recent
from ironm_agent.numbers import traced
from ironm_agent.personal import personal_basics
from tests.fakes import FakeHealth

WEIGHT = {
    "indicator": "Body weight",
    "name": "bodyMasss",
    "date": "2026-09-14",
    "value": "69.2",
    "unit": "kg",
    "rid": "r5",
}


def test_basics_become_citable_lines() -> None:
    health = FakeHealth(rows=[WEIGHT])
    p = asyncio.run(personal_basics(health, "42", "42:s"))
    assert p.lines == ("- Body weight：69.2 kg（2026-09-14）[r5]",) and p.support["r5"] == [69.2]
    assert health.asked[0]["view"] == "latest"


def test_basics_failure_is_empty() -> None:
    assert asyncio.run(personal_basics(FakeHealth(fail=True), "42", "42:s")).lines == ()


def test_weight_based_dose_traces_through_data_times_coefficient() -> None:
    k10 = default_kb().get("K10")
    assert k10 is not None
    ok = "<statement>按你 69.2 公斤算，冲击期每天约 21 克〔K10〕<cite>[r5]</cite></statement>"
    assert (
        check_text(ok, support={"r5": [69.2]}, entries={"K10": k10}, question="肌酸该喝多少") == []
    )
    bad = "<statement>按你 69.2 公斤算，每天约 35 克〔K10〕<cite>[r5]</cite></statement>"
    assert check_text(bad, support={"r5": [69.2]}, entries={"K10": k10}, question="q")


def test_knowledge_numbers_are_not_combined_with_each_other() -> None:
    # 资料里有 5 和 4，但 20 不能靠 5×4 凑出来
    assert not traced(20, [5, 4])
    assert traced(21, [], data=[69.2], coefs=[0.3])
    assert traced(2, [], data=[58, 56])


def test_history_has_user_words_and_short_answer_gists(monkeypatch: Any) -> None:
    long_answer = "先把深度控制在不疼的范围" + "，再慢慢加" * 30 + "。\n第二段不带。"

    async def fake_history(owner: str, session: str) -> list[dict[str, Any]]:
        assert (owner, session) == ("1", "abc")
        return [
            {"role": "user", "content": "我想练腿"},
            {"role": "assistant", "content": "第一条回答"},
            {"role": "user", "content": "深蹲怎么做"},
            {"role": "assistant", "content": "第二条回答"},
            {"role": "user", "content": "膝盖有点疼"},
            {"role": "assistant", "content": long_answer},
            {"role": "user", "content": "那它的替代动作呢"},
        ]

    import mirobody.agent.chat.message as message

    monkeypatch.setattr(message, "get_chat_history", fake_history)
    lines = asyncio.run(recent("1:abc", "那它的替代动作呢"))
    # 用户的原话都在；回答只带最近两条的开头一小段，第一条回答不带，本轮的问题不重复
    assert lines[0] == "用户：我想练腿" and "教练（要点）：第一条回答" not in lines
    assert lines[1:3] == ["用户：深蹲怎么做", "教练（要点）：第二条回答"]
    assert lines[-1].startswith("教练（要点）：先把深度") and lines[-1].endswith("…")
    assert len(lines[-1]) <= len("教练（要点）：") + 81 and "第二段" not in lines[-1]
    assert "用户：那它的替代动作呢" not in lines
