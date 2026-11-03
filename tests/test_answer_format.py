"""回答分段与长度（spec [2026-10-23] §38）。"""

from typing import Any

from ironm_agent.answer_format import LIMITS, assemble, drop_said, is_slots, kind_of, slots_prompt
from ironm_agent.experts import _parse
from ironm_agent.roles import Role
from tests.test_plugin import text_of
from tests.test_turn_flow import Coach, agent, run, snapshot_of


def size(text: str) -> int:
    return len("".join(text.split()))


def test_length_and_steps_are_the_agents_call() -> None:
    """§114：不再按关键词把问题分成问数、问怎么做、要详细去定长度和做法条数；交给管家判断，只留总上限。"""
    texts = ("我的 BMI 是多少", "今天有点不舒服", "早餐吃什么比较好", "减脂怎么吃，详细说说")
    assert len({slots_prompt(x) for x in texts}) == 1  # 不管问什么，给管家的写法说明一样
    assert f"不超过 {LIMITS['detail']} 字" in slots_prompt("我的 BMI 是多少")
    assert f"不超过 {LIMITS['card']} 字" in slots_prompt("帮我排个计划", "plan")  # 有卡片的照旧短
    assert kind_of("我的 BMI 是多少") == "fact"  # 关键词分类还在，只是不再用来改管家的输出


def test_answer_first_reason_after_steps_numbered() -> None:
    raw = {
        "answer": "现在不合适",
        "reason": "这周你已经练了 4 次，最近睡得少。",
        "steps": ["先固定每周 4 次，上下肢各两次。", "睡眠回到 7 小时再加第 5 次。"],
        "alert": "",
        "next": "今天休息，明天练下肢。",
    }
    out = assemble(raw, "我一周练六天对吗")
    lines = out.split("\n")
    # §82：两条做法接在答案后面写成句子，不编号
    assert lines[0] == (
        "现在不合适。这周你已经练了 4 次，最近睡得少。先固定每周 4 次，上下肢各两次。睡眠回到 7 小时再加第 5 次。"
    )
    assert not any(x.startswith("1. ") for x in lines) and lines[-1] == "今天休息，明天练下肢。"
    three = assemble({**raw, "steps": [*raw["steps"], "练前热身 10 分钟。"]}, "我一周练六天对吗")
    rows = three.split("\n")
    assert rows[0] == "现在不合适。这周你已经练了 4 次，最近睡得少。"
    assert rows[1].startswith("1. ") and rows[3].startswith("3. ")  # 三条以上才编号


def test_alert_is_not_repeated_and_never_comes_with_a_next_step() -> None:
    told = assemble({"answer": "今天先休息，发烧时不要运动。", "alert": "症状加重就去看医生。",
                     "next": "今晚量一次体温。"}, "我发烧了能练吗")  # fmt: skip
    assert "看医生" not in told and "量一次体温" in told  # 答案已经说了别运动：不再加提醒
    both = assemble({"answer": "可以轻松动一动，慢走 20 分钟。", "alert": "发烧、胸闷就别练了。",
                     "next": "今晚早点睡。"}, "今天有点不舒服，能练吗")  # fmt: skip
    assert "发烧、胸闷就别练了" in both and "早点睡" not in both  # 提醒和下一步不同时出现


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
    long_step = "每组之间休息两分钟，动作慢一点，下放三秒，起身一秒，组数按计划做完再加重" * 6
    raw = {
        "answer": "能练，今天避开压膝盖的动作。",
        "steps": [long_step, long_step, long_step],
        "alert": "肿胀、卡住或打软腿就停下去看医生。",
        "next": "今晚先试一组箱式深蹲。",
    }
    out = assemble(raw, "膝盖疼还能练腿吗")
    assert size(out) <= LIMITS["detail"]
    assert out.startswith("能练") and "打软腿" in out and out.count(long_step) < 3


def test_plain_text_answers_still_work() -> None:
    assert not is_slots({"answer": "一段文字"})
    op = _parse(Role.TRAINER, '{"answer": "一段文字的回答"}', "深蹲怎么做")
    assert op is not None and op.answer == "一段文字的回答"
    op = _parse(
        Role.TRAINER,
        '{"answer": "你的 BMI 是 24.5", "reason": "按 75 公斤、175 厘米算", "steps": [], "next": ""}',
        "我的 BMI 是多少",
    )
    assert op is not None and op.answer == "你的 BMI 是 24.5。按 75 公斤、175 厘米算。"


def test_refusal_is_one_plain_sentence_first_and_the_agent_does_not_repeat_it(
    monkeypatch: Any,
) -> None:
    """拒答交给管家说（§86）；它没提医生时，开头补上固定的一句，不说"这个问题我不能回答"。"""
    t = Coach("饮食上先少盐，多吃蔬菜〔经验〕。")
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "我血压高，你给我开点降压药"
    )
    body = text_of(blocks)
    assert "这个问题我不能回答" not in body
    assert body.startswith("用什么药、用多少") and seen["refusal_by"] == "fixed"
    assert body.count("用什么药、用多少") == 1
    assert "说明这部分不能做" in t.input + t.system  # 要求交给它用自己的话说


def test_risk_note_is_not_repeated_when_the_answer_already_sends_him_to_a_doctor() -> None:
    note = "你 10 月 20 日测的血压是 164/102 mmHg，偏高：加大训练前先找医生评估。"
    assert drop_said(note, "早餐两个鸡蛋加一杯牛奶。") == note
    assert drop_said(note, "先别上大重量：你血压 164/102，先请医生评估。") == ""
    assert drop_said(note, "血压高的人早餐少放盐。") == note  # 提到血压但没让他看医生，提醒照留


def test_stop_reminder_is_the_agents_call() -> None:
    """§114：写不写"疼就停"由管家按情况判断（写法说明里有），代码不再按关键词删。"""
    raw = {
        "answer": "屁股往后坐，膝盖跟着脚尖。",
        "steps": [],
        "alert": "膝盖疼就停下。",
        "next": "",
    }
    assert "疼就停" in assemble(raw, "深蹲怎么做")
    assert "只在他说的情况本身有风险时写" in slots_prompt("深蹲怎么做")


def test_repair_keeps_line_breaks() -> None:
    from ironm_agent.checks import repair

    text = "跑步和力量分开练〔经验〕。你每天热量目标 2896 千卡〔C2〕。\n1. 力量每周 4 次〔经验〕。\n2. 跑步每周 3 次〔经验〕。"
    assert repair(text, support={}, entries={}, question="", calcs={}).count("\n") == 2


def test_long_reason_is_cut_before_listed_items() -> None:
    raw = {
        "answer": "给你 3 个：箱式深蹲、罗马尼亚硬拉、臀桥。",
        "reason": "这三个对膝盖压力小，适合你左膝蹲深会疼。"
        + "罗马尼亚硬拉主要练大腿后侧和臀部，能补上深蹲练不到的部分，" * 14
        + "所以一起练。",
        "steps": [
            "箱式深蹲：身后放椅子，高度定在蹲下不疼的位置，3 组 × 10 次。",
            "罗马尼亚硬拉：双手各拿一只 20 公斤哑铃，屁股往后推，3 组 × 8 次。",
            "臀桥：仰卧屈膝，臀部抬起停 2 秒，3 组 × 12 次。",
        ],
    }
    out = assemble(raw, "推荐几个练腿的动作")
    assert "3. 臀桥" in out and "补上深蹲" not in out


def test_body_state_is_the_agents_call() -> None:
    """§114：问身体状态写几条、写不写成句子由管家判断；代码照它写的拼，不按关键词删做法。"""
    raw = {"answer": "可以，今天轻松动一动。",
           "steps": ["慢走或慢骑 20 分钟，能说话不喘。", "拉伸 10 分钟。", "多喝水，早点睡。"],
           "alert": "发烧、胸闷就别练了。"}  # fmt: skip
    out = assemble(raw, "今天有点不舒服，给我安排一个轻松的锻炼")
    assert "多喝水" in out and any(x.startswith("1. ") for x in out.split("\n"))


def test_just_saying_unwell_is_guided_for_every_question() -> None:
    """§114：只说状况、没问怎么办时怎么回，写在管家每轮都看的说明里，由它判断这句是不是这种。"""
    from ironm_agent import agent

    assert "没问怎么办时，关心一句、问怎么了，不主动给做法和安排" in agent._PROMPT
    raw = {"answer": "怎么了，是哪里不舒服？", "steps": [], "next": ""}
    assert assemble(raw, "今天有点不舒服") == "怎么了，是哪里不舒服？"
