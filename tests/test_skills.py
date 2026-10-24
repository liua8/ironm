"""规程与动作库（spec [2026-10-23] §8）。"""

import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from ironm_agent.compose import _PROMPT, _REVISE
from ironm_agent.exercises import feel_cues, library, library_entries, named_in
from ironm_agent.kb import default_kb
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.skills import pick, prompt_of, skills
from ironm_agent.tools import EXERCISES, Toolbox

FIRST_BATCH = {
    Role.TRAINER: {"新手入门", "增肌", "提升力量", "减脂期训练", "居家与时间有限", "按今天的状态调整",
                   "减量与平台期", "中断后回归", "排每周计划", "动作教学", "替代动作选择", "热身", "有氧耐力",
                   "坚持与习惯"},
    Role.NUTRITION: {"热量与蛋白质目标", "增肌饮食", "减脂饮食", "训练前后吃什么", "补剂评估",
                     "外卖与食堂怎么选", "看照片估算一餐", "饮食坚持"},
    Role.RECOVERY: {"今天状态判断", "睡眠改善", "酸痛还是受伤", "生病时练不练", "过度训练",
                    "疼痛时怎么改动作", "伤后回到训练", "就医信号"},
}  # fmt: skip
SHARED = {"趋势解读", "数据缺失时怎么说"}


def test_first_batch_is_there_and_every_number_has_a_source() -> None:
    kb = default_kb()
    for role, names in FIRST_BATCH.items():
        mine = [x for x in skills() if x.role == role]
        assert {x.name for x in mine} >= names
        assert sum(x.default for x in mine) == 1, role
    assert {x.name for x in skills() if x.shared} == SHARED
    assert len({x.name for x in skills()}) == len(skills())  # 名字不重复
    for x in skills():
        assert x.steps and all(kb.get(r) is not None for r in x.refs), x.id
        for line in (*x.steps, *x.rules, *x.output, *x.avoid):
            cited = re.findall(r"〔(K\d{2,3})〕", line)
            assert all(c in x.refs for c in cited), (x.id, line)
            if re.search(r"\d", re.sub(r"〔K\d+〕|0–10 分", "", line)):
                assert cited, (x.id, line)  # 规程里的数字都要注明出处


def test_the_right_skills_are_loaded() -> None:
    assert pick(Role.TRAINER, "增肌一周练几次比较好")[0].name == "增肌"
    assert "疼痛时怎么改动作" in [x.name for x in pick(Role.RECOVERY, "膝盖疼还能练腿吗")]
    assert "按今天的状态调整" in [x.name for x in pick(Role.TRAINER, "今天练什么", {"poor"})]
    assert pick(Role.TRAINER, "帮我做个计划", {"plan"})[0].name == "排每周计划"
    assert pick(Role.NUTRITION, "这顿多少热量", {"image"})[0].name == "看照片估算一餐"
    assert len(pick(Role.TRAINER, "帮我排一个增肌计划，今天有点累", {"poor", "plan"})) == 2
    # 新增的小领域
    assert pick(Role.TRAINER, "跑步一周跑几次")[0].name == "有氧耐力"
    assert pick(Role.TRAINER, "总是坚持不下去怎么办")[0].name == "坚持与习惯"
    assert pick(Role.TRAINER, "停了一个月，好久没练了")[0].name == "中断后回归"
    assert pick(Role.NUTRITION, "晚上总是管不住嘴")[0].name == "饮食坚持"
    assert "伤后回到训练" in [x.name for x in pick(Role.RECOVERY, "伤好了什么时候能练")]
    assert pick(Role.RECOVERY, "跑步时胸闷心慌要去医院吗")[0].name == "就医信号"
    # 共享的数据解读三个角色都能装载，全能教练（对照组）不装
    assert all("趋势解读" in [x.name for x in pick(r, "我最近体重的趋势")] for r in EXPERTS)
    assert pick(Role.GENERAL, "我最近体重的趋势") == []
    # 都对不上时用默认规程
    assert [x.name for x in pick(Role.RECOVERY, "嗯")] == ["今天状态判断"]
    assert "本次装载的规程" in prompt_of(pick(Role.TRAINER, "增肌")) and prompt_of([]) == ""


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
    coach = Toolbox(SPECS[Role.TRAINER], kb=kb, health=None, user_id="1", session_id="")
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


# 体感讲解（spec [2026-10-23] §8）：普通人听不懂的解剖术语
JARGON = ("后缩", "前伸", "回旋", "外旋", "内旋", "外展", "内收", "离心", "向心", "伸髋", "屈髋", "髋铰链",
          "跖屈", "背屈", "腘绳肌", "竖脊肌", "股四头肌", "臀大肌", "臀中肌", "背阔肌", "三角肌", "肱二头肌",
          "肱三头肌", "腹横肌", "斜方肌", "肩袖", "腹压", "骨盆", "代偿", "中立")  # fmt: skip


def test_how_to_questions_load_the_feel_skill_on_top() -> None:
    def names(text: str, triggers: frozenset[str] = frozenset()) -> list[str]:
        return [x.name for x in pick(Role.TRAINER, text, triggers)]

    for text in ("卧推时肩胛骨怎么收紧", "引体向上怎么发力", "深蹲怎么做",
                 "深蹲我没看懂，请用大白话、打个比方再给我讲讲怎么做，最容易做错的地方是什么"):  # fmt: skip
        assert "体感讲解" in names(text), text
    # 讲法规程不占名额；疼痛怎么改动作归康复恢复师（spec [2026-10-23] §20）
    both = names("膝盖疼的时候深蹲怎么做", frozenset({"injury"}))
    assert "动作教学" in both and both[-1] == "体感讲解" and "疼痛时怎么改动作" not in both
    rehab = [x.name for x in pick(Role.RECOVERY, "膝盖疼的时候深蹲怎么做", {"injury"})]
    assert rehab[0] == "疼痛时怎么改动作" and "体感讲解" not in rehab
    # 问题里点到了动作库里的动作（move）：训练教练讲动作时也用体感描述
    sore = names("卧推的时候肩膀前面疼怎么办", frozenset({"injury", "move"}))
    assert sore[-1] == "体感讲解"
    for text in ("膝盖疼换什么动作", "练前热身做什么"):
        assert "体感讲解" not in names(text), text
    assert names("嗯") == ["按今天的状态调整"]  # 都对不上时仍是默认规程，体感讲解不当默认
    for other in (Role.NUTRITION, Role.RECOVERY):  # 只给训练教练
        assert "体感讲解" not in [x.name for x in pick(other, "深蹲怎么做")]
    prompt = prompt_of(pick(Role.TRAINER, "卧推时肩胛骨怎么收紧"))
    assert "【体感讲解】" in prompt and "腋下夹着一张纸" in prompt


def test_every_exercise_has_plain_feel_cues() -> None:
    cues = feel_cues()
    assert set(cues) == {x.id for x in library().exercises}
    for eid, items in cues.items():
        assert 1 <= len(items) <= 3, eid
        for c in items:
            assert not [w for w in JARGON if w in c.cue], (eid, c.cue)
            assert not re.search(r"\d", c.cue), (eid, c.cue)  # 说给人听的话里不写需要出处的数字
    assert any("腋下夹着一张纸" in c.cue for c in cues["dumbbell-bench-press"])
    bench = next(e for e in library_entries() if e.title == "哑铃卧推")
    assert "体感提示：想象腋下夹着一张纸" in bench.as_evidence()


def test_feel_cues_must_match_the_library(tmp_path: Path) -> None:
    path = tmp_path / "feel.yaml"
    path.write_text(
        'version: "0"\nreview: x\nfeel:\n  push-up:\n    - {cue: 身体像一块木板, replaces: 躯干一条直线}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="对不上"):
        feel_cues(path)


def test_compose_and_revise_keep_the_analogies() -> None:
    assert "类比和体感描述" in _PROMPT and "不要改回解剖术语" in _PROMPT
    assert "类比和体感描述" in _REVISE and "不改回解剖术语" in _REVISE


def test_similar_picks_when_no_phrase_matches() -> None:
    """说法都对不上时，用本机向量模型选最像的一份（spec [2026-10-23] §20）；模型不可用时仍用默认规程。"""
    asked: list[list[str]] = []

    def similar(text: str, candidates: Sequence[str]) -> list[float]:
        asked.append(list(candidates))
        return [1.0 if c.startswith("增肌：") else 0.1 for c in candidates]

    assert [x.name for x in pick(Role.TRAINER, "想把胳膊练粗一点", (), similar)] == ["增肌"]
    assert all("：" in c for c in asked[0]) and not any(c.startswith("体感讲解") for c in asked[0])
    assert pick(Role.TRAINER, "增肌一周练几次", (), similar)[0].name == "增肌" and len(asked) == 1
    assert [x.name for x in pick(Role.TRAINER, "想把胳膊练粗一点", (), lambda *_: None)] == [
        "按今天的状态调整"
    ]


def test_choose_follows_route_and_adds_rule_required() -> None:
    """路由选的规程（空列表就不装），加上路由看不到的系统情况要求的（spec [2026-10-23] §21）。"""
    from ironm_agent.skills import catalog, choose, valid_for

    got, by = choose(Role.NUTRITION, "肌酸是什么", (), None, ())
    assert got == [] and by == "route"
    got, _ = choose(
        Role.TRAINER, "帮我排个增肌计划", {"plan"}, None, ("plan-muscle", "plan-newbie")
    )
    assert [x.id for x in got] == ["plan-weekly", "plan-muscle"]  # 规则要求的在前，最多 2 份
    got, _ = choose(Role.NUTRITION, "这碗面多少热量", {"image"}, None, ())
    assert [x.id for x in got] == ["food-photo"]  # 附了图片：路由说不用也要装
    got, _ = choose(Role.TRAINER, "卧推时肩胛骨怎么收紧", {"move"}, None, ("move-teach",))
    assert [x.id for x in got] == ["move-teach", "move-feel"]  # 讲法类照旧按规则装
    got, by = choose(Role.TRAINER, "增肌一周练几次", (), None, None)
    assert by == "rule" and got[0].name == "增肌"  # 路由没选：按规则
    assert valid_for(Role.RECOVERY, ["data-trend", "rest-sleep", "plan-muscle"]) == (
        "data-trend",
        "rest-sleep",
    )
    text = catalog()
    assert "trainer（训练教练）：" in text and "move-feel" not in text
    assert "data-trend 趋势解读：问自己某项数据" in text.split("三个角色都能用：")[1]


def test_every_skill_says_when_to_use_and_not() -> None:
    """什么时候用、什么时候不用（spec [2026-10-23] §22）；not_for 点到的规程都存在（加载时检查）。"""
    from ironm_agent.skills import catalog

    names = {x.name for x in skills()}
    for x in skills():
        assert x.use and x.use in x.brief(), x.id
        assert all(n in names for n in re.findall(r"「([^」]+)」", x.not_for)), x.id
    text = catalog()
    sleep = next(x for x in skills() if x.id == "rest-sleep")
    assert sleep.use in text and "（不用于：" in text and "「数据缺失时怎么说」" in sleep.not_for
