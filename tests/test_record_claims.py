"""标注发现的第 2–4 类：编造个人情况、"停掉"、练后酸痛不是生病、每餐蛋白质（spec [2026-10-23] §49）。"""

from ironm_agent.constraints import Context, annotate, check
from ironm_agent.illness import detect
from ironm_agent.metrics import per_meal_protein

RECORD = "档案：男，30 岁。今天的身体数据：睡眠：最近一晚（今天）7.5 小时。长期记忆：伤病：左膝旧伤，蹲深了会疼"


def kinds(text: str, ctx: Context) -> list[str]:
    return [v.kind for v in check(text, ctx)]


def test_claims_about_the_record_must_match_it() -> None:
    ctx = Context(record=RECORD)
    assert kinds("更像练后酸痛；今天状态也标了差。", ctx) == ["record"]
    assert kinds("今天状态显示为好，可以照常练。", ctx) == ["record"]  # 档案只给数、不定级（§182）
    assert kinds("你档案里只写了膝前痛，判断不了。", Context(record="档案：男，30 岁")) == [
        "record"
    ]
    assert kinds("你档案里写了左膝旧伤，蹲到不疼的深度。", ctx) == []  # 对得上的不算
    assert kinds("你档案里有膝伤，蹲浅一点。", ctx) == []  # 换了说法的同一部位
    asked = Context(record="档案：男，30 岁。这句话里说的疼：膝")  # 这轮问题里说了膝盖疼
    assert kinds("你档案里只有腰痛和膝前痛。", asked) == ["record"]  # 档案里没有腰
    assert kinds("今天状态好，可以照常练。", ctx) == []  # 他自己的判断，不是说档案里标了什么
    assert kinds("今天状态标了差。", Context()) == []  # 没有档案时不核对
    fixed = annotate("更像练后酸痛，今天状态也标了差。今天减量。", ctx)
    assert "标了差" not in fixed and "更像练后酸痛" in fixed and "今天减量" in fixed
    assert check(fixed, ctx) == []


def test_stopping_counts_as_a_limit() -> None:
    sick = Context(sick=True)
    text = "今天停掉大重量和全身训练，只做轻度活动。"
    assert check(text, sick) == [] and annotate(text, sick) == text


def test_soreness_after_training_is_not_illness() -> None:
    assert detect("练完第二天全身酸痛还能练吗") is None
    assert detect("昨天练腿，今天浑身酸痛") is None
    assert detect("全身酸痛，还有点发烧") is not None  # 没说训练、又发烧：照旧算生病


def test_protein_per_meal_is_round_and_consistent() -> None:
    assert per_meal_protein(75) == (20, 30) and per_meal_protein(50) == (20, 25)
    assert per_meal_protein(100) == (25, 40)
