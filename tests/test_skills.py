"""规程与动作库（spec [2026-10-23] §8）。"""

import re

from ironm_agent.exercises import library, library_entries, named_in
from ironm_agent.kb import default_kb
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.skills import pick, prompt_of, skills
from ironm_agent.tools import EXERCISES, Toolbox

FIRST_BATCH = {
    Role.PLANNER: {"新手入门", "增肌", "提升力量", "减脂期训练", "居家与时间有限", "按今天的状态调整",
                   "减量与平台期", "伤后回到训练", "排每周计划"},
    Role.EXERCISE: {"动作教学", "替代动作选择", "疼痛时怎么改动作", "热身"},
    Role.NUTRITION: {"热量与蛋白质目标", "增肌饮食", "减脂饮食", "训练前后吃什么", "补剂评估",
                     "外卖与食堂怎么选", "看照片估算一餐"},
    Role.RECOVERY: {"今天状态判断", "睡眠改善", "酸痛还是受伤", "生病时练不练", "过度训练"},
    Role.DATA: {"趋势解读", "数据缺失时怎么说"},
}  # fmt: skip


def test_first_batch_is_there_and_every_number_has_a_source() -> None:
    kb = default_kb()
    for role, names in FIRST_BATCH.items():
        mine = [x for x in skills() if x.role == role]
        assert {x.name for x in mine} >= names
        assert sum(x.default for x in mine) == 1, role
    for x in skills():
        assert x.steps and all(kb.get(r) is not None for r in x.refs), x.id
        for line in (*x.steps, *x.rules, *x.output, *x.avoid):
            cited = re.findall(r"〔(K\d{2,3})〕", line)
            assert all(c in x.refs for c in cited), (x.id, line)
            if re.search(r"\d", re.sub(r"〔K\d+〕|0–10 分", "", line)):
                assert cited, (x.id, line)  # 规程里的数字都要注明出处


def test_the_right_skills_are_loaded() -> None:
    assert pick(Role.PLANNER, "增肌一周练几次比较好")[0].name == "增肌"
    assert "疼痛时怎么改动作" in [x.name for x in pick(Role.EXERCISE, "膝盖疼还能练腿吗")]
    assert "按今天的状态调整" in [x.name for x in pick(Role.PLANNER, "今天练什么", {"poor"})]
    assert pick(Role.PLANNER, "帮我做个计划", {"plan"})[0].name == "排每周计划"
    assert pick(Role.NUTRITION, "这顿多少热量", {"image"})[0].name == "看照片估算一餐"
    assert len(pick(Role.PLANNER, "帮我排一个增肌计划，今天有点累", {"poor", "plan"})) == 2
    # 都对不上时用默认规程
    assert [x.name for x in pick(Role.DATA, "嗯")] == ["趋势解读"]
    assert "本次装载的规程" in prompt_of(pick(Role.PLANNER, "增肌")) and prompt_of([]) == ""


def test_library_is_citable_like_the_knowledge_base() -> None:
    entries = library_entries()
    assert len(entries) == len(library().exercises) and entries[0].id == "K901"
    assert all(e.level == "library" and e.domains == ("library",) for e in entries)
    squat = next(e for e in entries if e.title == "高脚杯深蹲")
    text = squat.as_evidence()
    assert "做法" in text and "常见错误" in text and "什么情况先别做" in text
    assert 1 <= len(named_in("深蹲时膝盖内扣怎么纠正")) <= 2
    assert {e.title for e in named_in("壶铃摇摆怎么做")} == {"壶铃摇摆"}
    assert named_in("早餐吃什么") == []


def test_exercise_roles_get_the_library_tool_and_prefetch() -> None:
    kb = default_kb()
    coach = Toolbox(SPECS[Role.EXERCISE], kb=kb, health=None, user_id="1", session_id="")
    assert EXERCISES in [s["function"]["name"] for s in coach.schemas()]
    prefetched = coach.prefetch("壶铃摇摆怎么做")
    assert "壶铃摇摆" in prefetched and any(i.startswith("K9") for i in coach.evidence.entries)
    food = Toolbox(SPECS[Role.NUTRITION], kb=kb, health=None, user_id="1", session_id="")
    assert EXERCISES not in [s["function"]["name"] for s in food.schemas()]
    assert all(r in EXPERTS for r in FIRST_BATCH)


def test_knowledge_base_has_at_least_45_entries() -> None:
    kb = default_kb()
    assert len(kb.entries) >= 45
    assert len({e.id for e in kb.entries}) == len(kb.entries)
    assert all(
        e.points and e.source and e.publisher and e.year and e.population for e in kb.entries
    )
