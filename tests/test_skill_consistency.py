"""规程内容纠错（spec [2026-10-23] §100）：示例、正文、基础规程、代码里的同一件事说法一致。"""

from __future__ import annotations

import re

from ironm_agent import casefile, constraints
from ironm_agent.protools import pain
from ironm_agent.skills import by_id, skills


def _text(skill_id: str) -> str:
    x = by_id(skill_id)
    assert x is not None
    return x.text(full=True) + "\n" + x.card


def _examples(skill_id: str) -> str:
    return _text(skill_id).split("## 示例", 1)[1]


def test_pain_limit_matches_the_pain_check_tool() -> None:
    assert pain.ALLOWED == 5
    body = _text("pain-injury")
    assert "医生确认过的慢性" not in body and "已经看过医生、确认是慢性" not in body
    assert "像受伤的" in body and "不超过 5 分" in body
    assert "不超过 5 分" in by_id("train-core").text(["injury"])  # type: ignore[union-attr]
    rest = by_id("rest-core").text(["injury"])  # type: ignore[union-attr]
    assert (
        "pain_check" in rest and "医生确认过的慢性" not in rest
    )  # 恢复基础指向工具，不另立标准（§101）


def test_sick_day_examples_wait_seven_days_after_fever() -> None:
    for line in _examples("readiness-adjust").splitlines():
        if "退烧" in line:
            assert "满 7 天" in line, line


def test_pregnancy_lying_on_the_back_is_said_one_way() -> None:
    """回答约束核对一律不安排仰卧（改侧卧或上斜）；规程、基础规程、档案提示都这样说。"""
    strict = re.compile(r"不安排仰卧|避开仰卧|不做仰卧|避免仰卧")
    assert strict.search(constraints.PREGNANCY.fix)
    places = [x.text(["pregnancy"], full=True) for x in skills()]
    places += list(casefile.RISK_BRIEFS.values()) + [x[2] for x in casefile._MEMORY_RISKS]
    for text in places:
        for line in text.splitlines():
            if re.search(r"孕", line) and re.search(r"平躺|仰卧", line):
                assert strict.search(line), line


def test_sleep_advice_cites_what_the_source_says() -> None:
    rest = by_id("rest-core")  # 恢复与睡眠并进恢复基础（§101）
    assert rest is not None and "〔K113〕" in rest.text()
    assert not any("最常见的原因" in x.text(full=True) for x in skills())


# 独立审查查到、核对资料原文后属实的（§100 需求 3）：改掉的说法不能再回来
GONE = [
    ("log-review", "按 2 次算"),  # K79：人会少估余力，不是多估
    ("log-review", "82.5"),  # 一次做满就加重；K03 要连续两次
    ("intake-assess", "那可以从低到中等强度开始"),  # 没问症状就下结论
    ("data-read", "停练一周后复查"),  # 不定复查方案
    ("pain-injury", "3–5 天就好"),  # K08：5–7 天内消退
    ("progress-plateau", "67.5"),  # 减量后按原来的重量
    ("readiness-adjust", "不做到力竭〔K28〕"),  # 力竭是 K29
    ("special-groups", "低冲击的开始〔K66〕"),  # K66 讲的是间歇和持续有氧
    ("diet-plan", "0.4 公斤上下就是对的〔K16〕"),  # K16 是 0.5–0.9 公斤
    ("comeback", "能练 2 次更好〔K85〕"),  # K85 没有这个结论
]


def test_review_findings_stay_fixed() -> None:
    for sid, phrase in GONE:
        assert phrase not in _text(sid), (sid, phrase)
    log = by_id("log-review")
    assert log is not None and "连续两次" in log.card and "连续两次" in log.body  # 加重条件按 K03
    for x in skills():  # 说话测试的依据是 K67；K93 只说心率不可靠
        assert "说话测试〔K93〕" not in x.text(full=True) + x.card, x.id


def test_balance_advice_from_k01_names_65() -> None:
    from ironm_agent.special import SENIOR, plan_problems
    from ironm_agent.training import Plan

    lines = [ln for x in skills() for ln in (x.text(full=True) + "\n" + x.card).splitlines()]
    plan = Plan.model_validate({"title": "x", "days_per_week": 1, "sessions": [
        {"day": 1, "name": "x", "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "8"}]}]})  # fmt: skip
    lines += plan_problems(plan, {SENIOR})[1]
    for ln in lines:
        if (
            "平衡" in ln and "〔K01〕" in ln and not ln.startswith("答：")
        ):  # 示例里问的人年龄已经给了
            assert "65 岁" in ln, ln
