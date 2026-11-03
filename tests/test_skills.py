"""规程与动作库（spec [2026-10-23] §8）。"""

import re
from pathlib import Path

import pytest

from ironm_agent.compose import _REVISE
from ironm_agent.exercises import feel_cues, library, library_entries, named_in
from ironm_agent.kb import default_kb
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.skills import catalog_any, pick_any, prompt_of, skills
from ironm_agent.tools import EXERCISES, Toolbox

# §88 起讲内容的规程是 16 份文件夹规程（热身拉伸、坚持删掉，动作教学和体感讲解合成一份）；
# §101 起 14 份：按状态调整和生病期间合成今天练不练，恢复与睡眠并进恢复基础
# §110 起 11 份：有氧与体能、特殊人群并进训练基础的参考段，补剂与用药并进饮食基础的参考段
# §111 起 8 个工作流：目标设定、中断后回归、进展与平台期分别并进建档与目标、排训练计划、记训练与复盘
FIRST_BATCH = {
    Role.TRAINER: {"建档与目标", "排训练计划", "动作教学", "记训练与复盘", "今天练不练"},
    Role.NUTRITION: {"饮食方案"},
    Role.RECOVERY: {"伤痛处理"},
}  # fmt: skip
SHARED = {"数据与化验解读"}


def test_first_batch_is_there_and_every_number_has_a_source() -> None:
    kb = default_kb()
    for role, names in FIRST_BATCH.items():
        mine = [x for x in skills() if x.role == role]
        assert {x.name for x in mine} >= names
        assert sum(x.default for x in mine) <= 1, role  # default 运行时已不用（§101）
    assert {x.name for x in skills() if x.shared} == SHARED
    assert len({x.name for x in skills()}) == len(skills())  # 名字不重复
    for x in skills():
        if x.body:  # 文件夹规程（§76）另有测试
            continue
        if x.core:  # 基础规程（§74）：原来角色提示词里的判断规则，引用的编号都在依据库里
            every = ("injury", "pregnancy", "bp", "diabetes", "cardiac", "poor")
            assert x.order and x.rules and all(kb.get(r) is not None for r in x.refs_for(every)), (
                x.id
            )
            continue
        assert x.steps and all(kb.get(r) is not None for r in x.refs), x.id
        for line in (*x.steps, *x.rules, *x.output, *x.avoid):
            cited = re.findall(r"〔(K\d{2,4})〕", line)
            assert all(c in x.refs for c in cited), (x.id, line)
            if re.search(r"\d", re.sub(r"〔K\d+〕|0–10 分", "", line)):
                assert cited, (x.id, line)  # 规程里的数字都要注明出处


def test_the_right_skills_are_loaded() -> None:
    """路由出错时退回的按说法选（pick_any）：情况要求的排前面，都对不上时不硬装。"""

    def names(text: str, triggers: frozenset[str] = frozenset()) -> list[str]:
        return [x.name for x in pick_any(text, triggers)]

    assert "排训练计划" in names("增肌一周练几次比较好")
    assert "伤痛处理" in names("膝盖疼还能练腿吗")
    assert names("今天练什么", frozenset({"poor"}))[1] == "今天练不练"  # 训练基础排最前
    assert "饮食方案" in names("这顿多少热量", frozenset({"image"}))
    assert "训练基础" in names("跑步一周跑几次")  # 有氧在训练基础的参考段里（§110）
    assert "排训练计划" in names("停了一个月，好久没练了")  # §111 回归并进排计划
    assert "数据与化验解读" in names("我最近体重的趋势")
    assert "动作教学" in names("卧推时肩胛骨怎么收紧") and "动作教学" in names(
        "没有杠铃深蹲换成什么"
    )
    assert "饮食方案" in names("最近体重不降怎么办") and names("我两百斤能跑步吗") == []
    # 路由出错、关键词又对不上时不硬装：管家看目录（"train-core：训练原则、有氧、特殊人群"）自己装（§110）
    assert "train-core：训练原则、有氧、特殊人群" in catalog_any()
    assert "记训练与复盘" in names("今天跑了5公里，35分钟")
    assert not {"坚持与动力", "柔韧、热身与体态"} & {x.name for x in skills()}  # 模型直接答（§88）
    assert names("嗯") == []  # 都对不上不硬装，由它看目录自己装
    assert "本次装载的规程" in prompt_of(pick_any("增肌")) and prompt_of([]) == ""


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


def test_revise_keeps_the_analogies() -> None:
    assert "类比和体感描述" in _REVISE and "不改回解剖术语" in _REVISE


def test_every_skill_says_when_to_use_and_not() -> None:
    """什么时候用、什么时候不用（spec [2026-10-23] §22）；not_for 点到的规程都存在（加载时检查）。"""
    from ironm_agent.skill_route import catalog  # 选规程时给模型看的目录（§75）

    names = {x.name for x in skills()}
    for x in skills():
        assert x.use, x.id
        assert all(n in names for n in re.findall(r"「([^」]+)」", x.not_for)), x.id
    text = catalog()
    today = next(x for x in skills() if x.id == "readiness-adjust")
    assert (
        today.use in text
        and f"{today.use}；不用于：" in text
        and "「伤痛处理」" in today.not_for
    )
