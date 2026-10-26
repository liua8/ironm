"""化验和体检报告可以解读、不给意见（spec [2026-10-23] §39）。"""

import pytest

from ironm_agent.frameworks import framework
from ironm_agent.roles import Role
from ironm_agent.safety.refusals import detect
from ironm_agent.skills import skills


@pytest.mark.parametrize(
    "text",
    ["帮我解读我的一些健康指标", "解读指标你不会吗", "化验单怎么看", "我尿酸偏高吗", "我的体检报告正常吗",
     "血脂报告什么意思", "为什么要判断我是不是得了疾病"],
)  # fmt: skip
def test_reading_values_is_not_refused(text: str) -> None:
    assert detect(text).kinds == ()


@pytest.mark.parametrize(
    "text",
    ["我这是不是痛风", "帮我诊断一下", "尿酸偏高严重吗", "体检报告有问题吗", "化验单上这几项是什么病",
     "肝功能偏高怎么办", "帮我诊断一下，我膝盖疼是不是半月板撕裂"],
)  # fmt: skip
def test_asking_for_a_medical_opinion_is_still_refused(text: str) -> None:
    assert detect(text).kinds == ("diagnosis",)


def test_refusal_wording_and_role_rules() -> None:
    from ironm_agent.plugin import _replies

    said = _replies().refusals["diagnosis"]
    assert said.startswith("我不能判断你是不是得了某种病") and "解读" not in said and "医生" in said
    lab = next(x for x in skills() if x.name == "化验指标怎么看")
    for text in (framework(Role.RECOVERY), "\n".join(lab.rules)):
        assert "不给健康意见" in text and "问医生" in text


def test_general_words_count_as_asking_about_records() -> None:
    """没点名具体指标，只说"指标""化验""体检报告"，也算问自己的数据。"""
    from ironm_agent.indicators import record_kinds

    assert record_kinds("帮我解读我的一些健康指标") == {"lab", "metric"}
    assert record_kinds("帮我看看化验单") == {"lab"} and record_kinds("体检报告怎么看") == {"lab"}
    assert record_kinds("我肌酐高嘛") == {"lab"} and record_kinds("我体脂指标高吗") == {"metric"}
    assert record_kinds("上周的训练报告") == set() and record_kinds("今天练什么") == set()


def test_routed_pain_skills_are_dropped_on_data_questions() -> None:
    """问自己的数据时，路由挑的伤痛、减量规程不装（记忆里的伤病照样写在共享档案里）。"""
    from ironm_agent.skills import choose

    got, _ = choose(Role.RECOVERY, "帮我解读我的一些健康指标", {"lab", "metric"},
                    routed=["rest-pain", "rest-return"], drop={"injury", "poor"})  # fmt: skip
    ids = [x.id for x in got if not x.style]
    assert ids[:2] == ["data-trend", "data-labs"] or set(ids[:2]) == {"data-trend", "data-labs"}
    assert "rest-pain" not in ids and "rest-return" not in ids
    kept, _ = choose(Role.RECOVERY, "膝盖疼还能练吗", {"injury"}, routed=["rest-pain"])
    assert "rest-pain" in [x.id for x in kept]


@pytest.mark.parametrize(
    ("text", "hurt"),
    [("我尿酸偏高严重吗", False), ("乳酸阈怎么测", False), ("喝酸奶好吗", False), ("腿酸还能练吗", True),
     ("肌肉酸痛怎么缓解", True), ("膝盖疼还能练吗", True)],
)  # fmt: skip
def test_acid_in_indicator_names_is_not_soreness(text: str, hurt: bool) -> None:
    """尿酸、乳酸里的"酸"不算身体不适；腿酸、酸痛照旧算。"""
    from ironm_agent.plugin import _HURT

    assert bool(_HURT.search(text)) is hurt
