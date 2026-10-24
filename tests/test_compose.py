"""整合后的规则核对：逐句核对数字与所引的资料、数据行；安全官提醒由系统原样附上。"""

import asyncio

from ironm_agent.checks import sentences
from ironm_agent.compose import compose, review
from ironm_agent.experts import Consultation, Opinion
from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply
from ironm_agent.roles import Role
from ironm_agent.tools import Evidence
from tests.fakes import FakeLLM

KB = default_kb()
ENTRIES = {k: e for k in ("K10", "K17") if (e := KB.get(k)) is not None}
SUPPORT = {"r1": [30.0, 54.0, 63.0, 58.2]}


def check(answer: str) -> list[str]:
    return review(answer, support=SUPPORT, entries=ENTRIES, question="我静息心率怎么样")


def test_good_answer_passes() -> None:
    answer = (
        "**结论**\n<statement>你近 30 天静息心率平均 58 次/分<cite>[r1]</cite></statement>，很平稳。\n"
        "肌酸每天 3–5 克即可〔K10〕。"
    )
    assert check(answer) == []


def test_number_cited_to_wrong_entry_fails() -> None:
    # 肌酸剂量出自 K10，却标成了膳食指南 K17
    assert any("K17" in p for p in check("肌酸冲击期每天约 0.3 克/公斤，连续 5–7 天〔K17〕。"))


def test_number_without_any_reference_fails() -> None:
    assert check("肌酸每天 3–5 克就行。")


def test_reference_after_full_stop_belongs_to_previous_sentence() -> None:
    assert sentences("每天 3–5 克。〔K10〕下一句。") == ["每天 3–5 克。〔K10〕", "下一句。"]
    assert check("肌酸每天 3–5 克。〔K10〕") == []


def test_data_number_outside_statement_fails() -> None:
    assert check("你的静息心率平均 58 次/分。")


def test_unknown_row_and_entry_fail() -> None:
    problems = check("<statement>平均 58<cite>[r9]</cite></statement>，见〔K77〕")
    assert any("r9" in p for p in problems) and any("K77" in p for p in problems)


def _consult(role: Role, **fields: object) -> Consultation:
    opinion = Opinion.model_validate({"role": role, "speak": True, **fields}, strict=False)
    return Consultation(opinion, Evidence(entries=dict(ENTRIES)), "spoke")


def test_coach_cannot_add_numbers_no_expert_said() -> None:
    # 整合时写了专业角色都没说过的数字：改一次还不过，这句删掉
    consults = [
        _consult(
            Role.NUTRITION, conclusion="每天 3–5 克〔K10〕", how="随餐吃〔经验〕", basis=("K10",)
        )
    ]
    reply = "肌酸每天 3–5 克〔K10〕。随餐吃，每次配 500 毫升水。"
    composed = asyncio.run(
        compose("肌酸怎么吃", Role.NUTRITION, consults, FakeLLM(lambda *_: Reply(reply)))
    )
    assert "3–5 克〔K10〕" in composed.text and "500" not in composed.text and not composed.degraded


def test_experience_numbers_from_experts_survive_composing() -> None:
    consults = [_consult(Role.TRAINER, conclusion="每周练 3 次就够〔经验〕")]
    composed = asyncio.run(
        compose(
            "一周练几次",
            Role.TRAINER,
            consults,
            FakeLLM(lambda *_: Reply("每周练 3 次就够〔经验〕。")),
        )
    )
    assert composed.text == "每周练 3 次就够〔经验〕。" and not composed.degraded


def test_failed_review_falls_back_to_primary_opinion() -> None:
    consults = [
        _consult(Role.NUTRITION, conclusion="每天 3–5 克〔K10〕", how="随餐吃", basis=("K10",)),
        _consult(Role.TRAINER, conclusion="练前练后都行"),
    ]
    composed = asyncio.run(
        compose("肌酸怎么吃", Role.NUTRITION, consults, FakeLLM(lambda *_: Reply("每天吃 99 克。")))
    )
    assert composed.degraded and "3–5" in composed.text and "练前练后" not in composed.text


def test_data_sentences_reach_the_model_as_placeholders_and_come_back_intact() -> None:
    stmt = "<statement>按你 69.2 公斤算，冲击期每天约 21 克〔K10〕<cite>[r1]</cite></statement>"
    op = Opinion.model_validate(
        {
            "role": Role.NUTRITION,
            "speak": True,
            "conclusion": "每天 3–5 克〔K10〕",
            "for_you": stmt,
        },
        strict=False,
    )
    c = Consultation(op, Evidence(support={"r1": [69.2]}, entries=dict(ENTRIES)), "spoke")
    llm = FakeLLM(lambda *_: Reply("每天 3–5 克〔K10〕。⟦D1⟧。"))
    composed = asyncio.run(compose("肌酸该喝多少", Role.NUTRITION, [c], llm))
    sent = str(llm.seen[0][1][1]["content"])
    assert "⟦D1⟧" in sent and "<statement>" not in sent
    assert not composed.degraded and stmt in composed.text


def test_unknown_placeholder_fails_review() -> None:
    op = Opinion.model_validate(
        {"role": Role.NUTRITION, "speak": True, "conclusion": "每天 3–5 克〔K10〕"}, strict=False
    )
    c = Consultation(op, Evidence(entries=dict(ENTRIES)), "spoke")
    composed = asyncio.run(compose("q", Role.NUTRITION, [c], FakeLLM(lambda *_: Reply("⟦D7⟧"))))
    assert composed.degraded
