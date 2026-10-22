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


def test_safety_caution_is_attached_verbatim_by_system() -> None:
    caution = "有肾脏疾病的人，先问医生再吃。"
    consults = [
        _consult(Role.NUTRITION, conclusion="每天 3–5 克〔K10〕", basis=("K10",)),
        _consult(Role.SAFETY, conclusion="肾病要小心", caution=caution, basis=("K10",)),
    ]
    llm = FakeLLM(lambda *_: Reply("**结论**\n肌酸每天 3–5 克〔K10〕。"))
    composed = asyncio.run(compose("肌酸怎么吃", Role.NUTRITION, consults, llm))
    assert not composed.degraded and composed.safety == caution
    sent = str(llm.seen[0][1][1]["content"])
    assert "肾脏疾病" not in sent  # 安全官的意见不交给模型改写


def test_failed_review_falls_back_to_primary_opinion() -> None:
    consults = [
        _consult(Role.NUTRITION, conclusion="每天 3–5 克〔K10〕", how="随餐吃", basis=("K10",)),
        _consult(Role.PLANNER, conclusion="练前练后都行"),
    ]
    composed = asyncio.run(
        compose("肌酸怎么吃", Role.NUTRITION, consults, FakeLLM(lambda *_: Reply("每天吃 99 克。")))
    )
    assert composed.degraded and "3–5" in composed.text and "练前练后" not in composed.text
