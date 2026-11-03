"""整合后的规则核对：逐句核对数字与所引的资料、数据行；安全官提醒由系统原样附上。"""

from ironm_agent.checks import sentences
from ironm_agent.compose import review
from ironm_agent.kb import default_kb

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
