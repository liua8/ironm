"""回答分段与长度（spec [2026-10-23] §38）。"""

from typing import Any

from ironm_agent.answer_format import LIMITS, assemble, drop_said, is_slots, kind_of, slots_prompt
from ironm_agent.experts import _SOLO_FIELDS, _parse
from ironm_agent.roles import Role
from tests.test_plugin import text_of
from tests.test_turn_flow import Team, agent, run, snapshot_of


def size(text: str) -> int:
    return len("".join(text.split()))


def test_question_kinds_set_the_length() -> None:
    assert kind_of("我的 BMI 是多少") == "fact" and kind_of("我的血糖正常吗") == "fact"
    assert kind_of("早餐吃什么比较好") == "howto" and kind_of("膝盖疼还能练腿吗") == "howto"
    assert kind_of("我最近睡得怎么样") == "fact"
    assert kind_of("帮我排个计划", "plan") == "card" and kind_of("今天练了深蹲", "log") == "card"
    assert kind_of("减脂怎么吃，详细说说") == "detail"
    assert LIMITS["fact"] < LIMITS["howto"] < LIMITS["detail"] and LIMITS["card"] < LIMITS["fact"]
    assert "不超过 120 字" in slots_prompt("我的 BMI 是多少")


def test_answer_first_reason_after_steps_numbered() -> None:
    out = assemble(
        {
            "answer": "现在不合适",
            "reason": "这周你已经练了 4 次，最近睡得少。",
            "steps": ["先固定每周 4 次，上下肢各两次。", "睡眠回到 7 小时再加第 5 次。"],
            "alert": "",
            "next": "今天休息，明天练下肢。",
        },
        "我一周练六天对吗",
    )
    lines = out.split("\n")
    assert lines[0] == "现在不合适。这周你已经练了 4 次，最近睡得少。"
    assert lines[1].startswith("1. ") and lines[2].startswith("2. ")
    assert lines[-1] == "今天休息，明天练下肢。"


def test_next_step_that_repeats_is_dropped_and_single_step_is_not_numbered() -> None:
    out = assemble(
        {
            "answer": "先别上大重量深蹲，先找医生评估血压。",
            "steps": ["高脚杯深蹲 3 组 × 10 次，选还能再做 2 次的重量。"],
            "next": "先找医生评估血压，再说大重量。",
        },
        "我想开始练大重量深蹲",
    )
    assert not any(x.startswith("1. ") for x in out.split("\n"))
    assert out.count("先找医生评估血压") == 1


def test_too_long_drops_later_steps_but_keeps_answer_and_alert() -> None:
    long_step = "每组之间休息两分钟，动作慢一点，下放三秒，起身一秒，组数按计划做完再加重" * 2
    raw = {
        "answer": "能练，今天避开压膝盖的动作。",
        "steps": [long_step, long_step, long_step],
        "alert": "肿胀、卡住或打软腿就停下去看医生。",
        "next": "今晚先试一组箱式深蹲。",
    }
    out = assemble(raw, "膝盖疼还能练腿吗")
    assert size(out) <= LIMITS["howto"]
    assert out.startswith("能练") and "打软腿" in out and out.count(long_step) < 3


def test_plain_text_answers_still_work() -> None:
    assert not is_slots({"answer": "一段文字"})
    op = _parse(Role.TRAINER, '{"answer": "一段文字的回答"}', _SOLO_FIELDS, "深蹲怎么做")
    assert op is not None and op.answer == "一段文字的回答"
    op = _parse(
        Role.TRAINER,
        '{"answer": "你的 BMI 是 24.5", "reason": "按 75 公斤、175 厘米算", "steps": [], "next": ""}',
        _SOLO_FIELDS,
        "我的 BMI 是多少",
    )
    assert op is not None and op.answer == "你的 BMI 是 24.5。按 75 公斤、175 厘米算。"


def test_refusal_is_one_plain_sentence_first_and_experts_do_not_repeat_it(monkeypatch: Any) -> None:
    t = Team("recovery")
    blocks, _ = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "我血压高，你给我开点降压药"
    )
    body = text_of(blocks)
    assert "这个问题我不能回答" not in body
    assert body.startswith("用什么药、用多少")
    assert "不要再复述" in t.inputs["recovery"]


def test_risk_note_is_not_repeated_when_the_answer_already_sends_him_to_a_doctor() -> None:
    note = "你 10 月 20 日测的血压是 164/102 mmHg，偏高：加大训练前先找医生评估。"
    assert drop_said(note, "早餐两个鸡蛋加一杯牛奶。") == note
    assert drop_said(note, "先别上大重量：你血压 164/102，先请医生评估。") == ""
    assert drop_said(note, "血压高的人早餐少放盐。") == note  # 提到血压但没让他看医生，提醒照留
