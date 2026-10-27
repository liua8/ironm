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
    """最近 10 句原话、4 条回答要点（各 150 字）、上一条回答全文（spec [2026-10-23] §53）。"""
    long_answer = "先把深度控制在不疼的范围" + "，再慢慢加" * 40 + "。\n1. 第二段也要在"
    rows: list[dict[str, Any]] = []
    for i in range(1, 13):
        rows.append({"role": "user", "content": f"第{i}句"})
        rows.append({"role": "assistant", "content": f"第{i}条回答" + "很长" * 100})
    rows[-1] = {"role": "assistant", "content": long_answer}
    rows.append({"role": "user", "content": "那它的替代动作呢"})

    async def fake_history(owner: str, session: str) -> list[dict[str, Any]]:
        assert (owner, session) == ("1", "abc")
        return rows

    import mirobody.agent.chat.message as message

    monkeypatch.setattr(message, "get_chat_history", fake_history)
    lines = asyncio.run(recent("1:abc", "那它的替代动作呢"))
    users = [x for x in lines if x.startswith("用户：")]
    coach = [x for x in lines if x.startswith("教练（要点）：")]
    assert users[0] == "用户：第3句" and len(users) == 10  # 第 1、2 句不带，本轮的问题不重复
    assert "用户：那它的替代动作呢" not in lines
    assert len(coach) == 4 and coach[0].startswith("教练（要点）：第9条回答")
    assert all(len(x) <= len("教练（要点）：") + 151 for x in coach[:-1])
    assert coach[-1].startswith("教练（要点）：先把深度") and "第二段也要在" in coach[-1]
    assert len(coach[-1]) > len("教练（要点）：") + 151  # 上一条回答给全文


def test_last_answer_is_cut_at_800_chars() -> None:
    from ironm_agent.memory import LAST_CHARS, _whole

    out = _whole("第一段\n" + "字" * 2000)
    assert out.startswith("第一段 ") and out.endswith("…") and len(out) == LAST_CHARS + 1
