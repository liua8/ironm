"""身体部位编码表（spec [2026-10-23] §57 需求 1）。"""

from pathlib import Path

import pytest

from ironm_agent.body import (
    CODES_PATH,
    BodyTable,
    CodeFile,
    Node,
    joint_code,
    muscle_codes,
    name,
    table,
)
from ironm_agent.yamlfile import load_yaml, load_yaml_text

FEDB_GROUPS = {
    "abdominals", "adductors", "biceps", "calves", "chest", "forearms", "glutes", "hamstrings", "lats",
    "lower back", "middle back", "neck", "quadriceps", "shoulders", "traps", "triceps",
}  # fmt: skip


def test_counts_per_level() -> None:
    t = table()
    assert [len(t.of_level(lv)) for lv in ("part", "group", "muscle", "joint")] == [7, 17, 28, 8]


def test_every_code_has_name_and_one_parent_of_the_right_level() -> None:
    t = table()
    for n in t.nodes.values():
        assert n.name
        if n.level == "part":
            assert n.parent is None
        else:
            up = t.node(n.parent or "")
            assert up.level == {"group": "part", "muscle": "group", "joint": "part"}[n.level]


def test_groups_follow_free_exercise_db_except_abductors() -> None:
    t = table()
    assert {n.fedb for n in t.of_level("group") if n.fedb} == FEDB_GROUPS
    assert t.lookup("abductors").code == "muscle.glute_med"  # type: ignore[union-attr]
    assert t.lookup("髋外展").code == "muscle.glute_med"  # type: ignore[union-attr]


def test_every_group_has_muscles_and_every_part_has_groups() -> None:
    t = table()
    for g in t.of_level("group"):
        assert t.muscles_under(g.code), g.code
    for p in t.of_level("part"):
        assert any(c.level == "group" for c in t.children(p.code)), p.code


@pytest.mark.parametrize(
    ("word", "code"),
    [
        ("屁股", "group.glutes"),
        ("大腿后面", "muscle.hamstrings"),
        ("翅膀", "muscle.lats"),
        ("拜拜肉", "muscle.triceps"),
        ("肩膀前面", "muscle.anterior_delt"),
        ("背", "part.back"),
        ("膝盖", "joint.knee"),
        ("三角肌锁骨部", "muscle.anterior_delt"),  # 正式名也能查
        ("ＬＡＴＳ", "group.lats"),  # 全角、大小写
        ("大腿 后侧", "muscle.hamstrings"),  # 空格
    ],
)
def test_lookup_lands_on_finest_level(word: str, code: str) -> None:
    n = table().lookup(word)
    assert n is not None and n.code == code


@pytest.mark.parametrize(
    "name", ["股四头肌", "腘绳肌", "肱三头肌", "背阔肌", "内收肌", "前臂", "颈部肌群"]
)
def test_group_and_its_only_muscle_with_same_name_lands_on_muscle(name: str) -> None:
    n = table().lookup(name)
    assert n is not None and n.level == "muscle"


@pytest.mark.parametrize("word", ["腰", "肚子", "胸口", "手指", "", "随便"])
def test_unknown_or_ambiguous_word_returns_none(word: str) -> None:
    assert table().lookup(word) is None


def test_rollup_and_within() -> None:
    t = table()
    back = {m.code for m in t.muscles_under("part.back")}
    assert back == {"muscle.upper_traps", "muscle.mid_lower_traps", "muscle.rhomboids", "muscle.lats",
                    "muscle.erector_spinae"}  # fmt: skip
    assert [a.code for a in t.ancestors("muscle.glute_med")] == ["group.glutes", "part.leg"]
    assert t.within("muscle.glute_med", "part.leg")
    assert t.within("joint.knee", "part.leg")
    assert not t.within("muscle.lats", "part.leg")


def test_uberon_ids_are_unique_where_given() -> None:
    ids = [n.uberon for n in table().nodes.values() if n.uberon]
    assert len(ids) == len(set(ids))


def _build(yaml_text: str) -> BodyTable:
    return BodyTable(CodeFile.model_validate(load_yaml_text(yaml_text), strict=False).nodes)


BASE = """
version: "0"
review: x
nodes:
  - {code: part.leg, level: part, name: 腿}
  - {code: group.glutes, level: group, parent: part.leg, name: 臀}
  - {code: muscle.glute_max, level: muscle, parent: group.glutes, name: 臀大肌}
"""


def test_valid_minimal_table_loads() -> None:
    assert _build(BASE).lookup("臀大肌") == Node(code="muscle.glute_max", level="muscle", name="臀大肌",
                                                parent="group.glutes")  # fmt: skip


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            "  - {code: muscle.glute_max, level: muscle, parent: group.glutes, name: 又一个}",
            "编码重复",
        ),
        ("  - {code: muscle.glute_med, level: muscle, parent: part.leg, name: 臀中肌}", "上级不对"),
        (
            "  - {code: muscle.glute_med, level: muscle, parent: group.nope, name: 臀中肌}",
            "上级不对",
        ),
        (
            "  - {code: joint.knee, level: muscle, parent: group.glutes, name: 膝}",
            "编码和层级对不上",
        ),
        (
            "  - {code: muscle.glute_med, level: muscle, parent: group.glutes, name: 臀中肌, says: [臀大肌]}",
            "同时指",
        ),
    ],
)
def test_bad_tables_are_rejected(extra: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _build(BASE + extra + "\n")


def test_shipped_file_is_marked_as_draft() -> None:
    data = CodeFile.model_validate(load_yaml(Path(CODES_PATH)), strict=False)
    assert data.review == "claude_draft"


# ---- 需求 2：动作库和现有数据改用编码 ----------------------------------------------------------


def test_every_strength_move_has_a_main_muscle_and_codes_are_valid() -> None:
    from ironm_agent.protools.movement import moves

    t = table()
    for mv in moves():
        for code in (*mv.tag.muscles, *mv.tag.assist):
            assert t.node(code).level == "muscle"
        for code in mv.tag.groups:
            assert t.node(code).level in ("part", "group")
        for code in (*mv.tag.stress, *mv.tag.friendly):
            assert t.node(code).level == "joint"
        if mv.tag.pattern not in ("cardio", "stretch", "plyo"):
            assert mv.tag.muscles, mv.name


def test_incline_press_works_upper_chest_and_flat_press_lower() -> None:
    from ironm_agent.protools.movement import find

    incline, flat = find("上斜哑铃卧推"), find("哑铃卧推")
    assert incline is not None and incline.tag.muscles[0] == "muscle.pec_major_upper"
    assert flat is not None and flat.tag.muscles[0] == "muscle.pec_major_lower"


def test_bad_tag_codes_are_rejected() -> None:
    from pydantic import ValidationError

    from ironm_agent.protools.movement import Tag

    for bad in (
        {"pattern": "squat", "muscles": ["股四头肌"]},
        {"pattern": "squat", "muscles": ["group.quadriceps"]},
        {"pattern": "squat", "groups": ["muscle.quadriceps"]},
        {"pattern": "squat", "stress": ["knee"]},
        {"pattern": "squat", "muscles": ["muscle.quadriceps"], "assist": ["muscle.quadriceps"]},
    ):
        with pytest.raises(ValidationError):
            Tag.model_validate(bad, strict=False)


def test_weekly_set_groups_keep_their_old_names() -> None:
    from ironm_agent.protools.plan_check import MAJOR

    names = {n.name for n in table().nodes.values()}
    assert set(MAJOR) <= names
    assert [
        name(c)
        for c in ("part.chest", "part.back", "group.quadriceps", "group.glutes", "part.shoulder")
    ] == list(MAJOR)


@pytest.mark.parametrize(
    ("stored", "codes"),
    [
        ("muscle.lats", ("muscle.lats",)),
        ("股四头肌", ("muscle.quadriceps",)),
        ("胸大肌", ("muscle.pec_major_upper", "muscle.pec_major_lower")),
        ("斜方肌", ("muscle.upper_traps", "muscle.mid_lower_traps")),
        ("小腿", ("muscle.gastrocnemius", "muscle.soleus", "muscle.tibialis_anterior")),
        ("group.glutes", ()),
        ("不认识", ()),
    ],
)
def test_old_muscle_names_become_codes(stored: str, codes: tuple[str, ...]) -> None:
    assert muscle_codes(stored) == codes


def test_old_joint_keys_become_codes() -> None:
    assert [joint_code(x) for x in ("knee", "back", "neck", "joint.hip", "muscle.lats", "hand")] == [
        "joint.knee", "joint.lumbar", "joint.cervical", "joint.hip", None, None,
    ]  # fmt: skip


def test_old_records_read_as_codes() -> None:
    import asyncio
    from datetime import date

    from ironm_agent.muscle_feel import FeelBook
    from ironm_agent.triggers import PainBook

    day = date(2026, 10, 20)
    feel = FeelBook()
    feel.rows["1"] = [
        ("胸大肌", "sore", day),
        ("muscle.pec_major_upper", "fine", day),
        ("没这块", "sore", day),
    ]
    got = asyncio.run(feel.latest("1"))
    assert got == {"muscle.pec_major_upper": ("fine", day), "muscle.pec_major_lower": ("sore", day)}
    pain = PainBook()
    pain.rows["1"] = [("knee", day), ("joint.lumbar", day), ("hand", day)]
    assert asyncio.run(pain.since("1", day)) == [("joint.knee", day), ("joint.lumbar", day)]


def test_recovery_days_follow_the_spec_groups() -> None:
    from ironm_agent.protools.recovery import ARMS, BASE_DAYS, DAILY

    assert set(BASE_DAYS) == {n.code for n in table().of_level("muscle")}
    two = {m for m, d in BASE_DAYS.items() if d == 2}
    assert two == {"muscle.quadriceps", "muscle.glute_max", "muscle.adductors", "muscle.hamstrings",
                   "muscle.erector_spinae", "muscle.hip_flexors"}  # fmt: skip
    assert all(d == 1 for m, d in BASE_DAYS.items() if m not in two)
    assert {"muscle.gastrocnemius", "muscle.soleus", "muscle.tibialis_anterior", "muscle.glute_med",
                     "muscle.rectus_abdominis", "muscle.obliques", "muscle.serratus_anterior", "muscle.neck"} == DAILY  # fmt: skip
    assert {m.code for m in table().muscles_under("part.arm")} == ARMS
