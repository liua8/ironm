"""一轮的流程（spec [2026-10-23] §2–§7、§67）：共享档案、数据风险、追问、单 Agent 直接作答、预取资料。"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.casefile import Snapshot
from ironm_agent.clarify import HEAD, MARK
from ironm_agent.llm import ModelUnavailable, Reply, Stage
from ironm_agent.memory_store import Change, Item, MemoryBook
from ironm_agent.metrics import Profile, Readings
from tests.fakes import jsonr, system_of
from tests.test_plugin import agent, shown, text_of

TODAY = date(2026, 10, 23)
T0 = datetime(2026, 10, 20, tzinfo=UTC)


class Coach:
    """假模型（单 Agent）：作答环节回答一句（extra 是 JSON 里另加的字段），记下收到的系统提示和输入；
    选规程环节给不出合格的结果，退回按关键词选（§75）；约束改写环节照原样再说一遍。"""

    def __init__(
        self, answer: str = "管家的回答〔经验〕", down: bool = False, **extra: Any
    ) -> None:
        self.answer, self.down, self.extra = answer, down, extra
        self.stages: list[str] = []
        self.system = ""
        self.input = ""
        self.seen: list[str] = []  # 每次作答环节收到的系统提示和输入

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        self.stages.append(stage)
        if stage == "route":
            return Reply("不是 JSON")
        if self.down:
            raise ModelUnavailable("timeout")
        if stage == "compose":
            return Reply(self.answer)
        if stage != "expert":
            return jsonr({"ops": []})
        self.system = system_of(messages)
        self.input = str(messages[1]["content"]) if len(messages) > 1 else ""
        self.seen.append(self.system + "\n" + self.input)
        return jsonr({"answer": self.answer, **self.extra})


def steady(
    base: float, days: int = 40, last: Sequence[float] = ()
) -> tuple[tuple[date, float], ...]:
    values = [base + (0.5 if i % 2 else -0.5) for i in range(days)]
    if last:
        values[-len(last) :] = list(last)
    return tuple((TODAY - timedelta(days=days - 1 - i), v) for i, v in enumerate(values))


def snapshot_of(readings: Readings | None = None, profile: Profile | None = None) -> Any:
    async def read(_: str) -> Snapshot:
        return Snapshot(profile or Profile(goal="muscle"), readings or Readings(), (), TODAY)

    return read


def run(a: Any, text: str, session: str = "42:s1") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seen: dict[str, Any] = {}
    a._observe, a._remember_on = seen.update, False

    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": text}]
        return shown([b async for b in a.generate_response("42", msgs, session_id=session)])

    return asyncio.run(go()), seen


def book(*items: tuple[str, str]) -> MemoryBook:
    b = MemoryBook()
    asyncio.run(
        b.apply(
            "42",
            [
                Change("insert", item=Item(c[:4], k, c, c, "said", "active", T0, T0))
                for k, c in items
            ],
        )
    )  # type: ignore[arg-type]
    return b


def tasks_of(blocks: list[dict[str, Any]]) -> dict[str, str]:
    return {b["name"]: b["args"]["任务"] for b in blocks if b["type"] == "tool_call"}


def cards(blocks: list[dict[str, Any]]) -> bool:
    return any(str(b.get("id", "")).startswith("card-") for b in blocks)


BP_HIGH = Readings(
    systolic=((TODAY - timedelta(days=2), 186.0),),
    diastolic=((TODAY - timedelta(days=2), 114.0),),
)


def test_one_agent_answers_directly_without_composing(monkeypatch: Any) -> None:
    t = Coach("屁股往后坐，膝盖跟着脚尖〔经验〕")
    blocks, seen = run(agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "深蹲怎么做")
    assert "compose" not in t.stages and seen["path"] == "answer"
    assert text_of(blocks) == "屁股往后坐，膝盖跟着脚尖"
    assert "系统按问题先查好的资料" in t.input  # 预取的资料在第一次调用前就给了


def test_very_high_blood_pressure_blocks_training_but_not_food(monkeypatch: Any) -> None:
    t = Coach("今天练腿，深蹲 4 组〔经验〕")  # 没说先别运动、尽快就医
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(BP_HIGH)), "今天练什么"
    )
    assert seen["path"] == "risk" and seen["risk_by"] == "fixed"  # 退回固定的提醒
    assert "186/114" in text_of(blocks) and "这一轮先不给训练安排" in text_of(blocks)
    assert "深蹲 4 组" not in text_of(blocks)
    food = Coach("早餐一碗燕麦加两个鸡蛋〔经验〕")
    blocks, seen = run(
        agent(food, monkeypatch=monkeypatch, snapshot=snapshot_of(BP_HIGH)), "早餐吃什么"
    )
    # 先答早餐；血压提醒在首页，问饮食时对话里不再附（spec [2026-10-23] §42）
    assert seen["path"] == "answer" and text_of(blocks).startswith("早餐一碗燕麦加两个鸡蛋")
    assert "186/114" not in text_of(blocks)


def test_risk_note_shows_once_per_session(monkeypatch: Any) -> None:
    """偏高的提醒交给模型顺带说（§86）；本会话说过的不再要求，约束仍在档案里。"""
    bp = Readings(
        systolic=((TODAY - timedelta(days=3), 164.0),),
        diastolic=((TODAY - timedelta(days=3), 102.0),),
    )
    remind = "回答涉及训练时要顺带提醒到（本会话说过的不用重复）"
    note = "你 10 月 20 日测的血压是 164/102 mmHg，偏高：加大训练前先找医生评估；训练时别憋气、不做大重量。"
    t = Coach(f"深蹲每周加 2.5 公斤〔经验〕。{note}")
    a = agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(bp))
    first, _ = run(a, "深蹲怎么加重量")
    assert remind in t.system + t.input and note in t.system + t.input
    assert "164/102" in text_of(first)

    async def told(*_: str) -> list[str]:
        return ["用户：深蹲怎么加重量", "教练（要点）：" + text_of(first)[:80]]

    async def said_before(_: str) -> str:
        return text_of(first)

    a._history, a._earlier = told, said_before
    t.answer = "卧推每周加 1 公斤〔经验〕。"
    again, _ = run(a, "那卧推呢")
    assert "164/102" not in text_of(again) and remind not in t.system + t.input
    assert "最近血压偏高：不安排大重量" in t.input  # 约束仍在，只是不再要求提醒


def test_new_user_asking_for_a_plan_is_asked_first(monkeypatch: Any) -> None:
    t = Coach("好，先确认一下条件。", action="new_plan")
    a = agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(profile=Profile()))
    blocks, seen = run(a, "帮我做个训练计划")
    assert seen["path"] == "clarify" and HEAD in text_of(blocks) and not cards(blocks)
    assert t.stages.count("expert") == 1  # 只问不排：不出预览、不补写计划


def test_poor_readiness_constrains_the_answer(monkeypatch: Any) -> None:
    tired = Readings(
        sleep_hours=steady(7.3, last=[4.6, 4.8, 4.5]), resting_hr=steady(58, last=[65, 66, 67])
    )
    t = Coach("今天上大重量深蹲 5 组〔经验〕")  # 改写也没改掉
    gym = book(("equipment", "在健身房练"), ("schedule", "一周四练，每次一小时"))
    a = agent(t, monkeypatch=monkeypatch, memory=gym, snapshot=snapshot_of(tired))
    blocks, seen = run(a, "今天练什么")
    assert "今天的身体状态：差" in t.input
    assert (
        seen["readiness"] == "poor"
        and seen["constraints"] == ["readiness"]
        and seen["constraint_fixed"]
    )
    assert "大重量（今天状态不好：先别做）" in text_of(blocks)


def test_loaded_skills_are_shown_while_answering(monkeypatch: Any) -> None:
    t = Coach()
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "增肌期怎么练怎么吃"
    )
    task = tasks_of(blocks)["管家"]
    loaded = seen["skills"]["general"]
    assert loaded and "（规程：" in task
    from ironm_agent.skills import by_id

    for x in loaded:
        skill = by_id(x)
        assert skill is not None and skill.name in task and f"【{skill.name}】" in t.system


def test_cited_case_file_numbers_show_up_in_sources(monkeypatch: Any) -> None:
    from ironm_agent.metrics import compute_all

    profile = Profile(
        height_cm=175, birth=date(1996, 3, 15), sex="male", goal="muscle", activity="moderate"
    )
    readings = Readings(weight=steady(75, days=30))
    metrics = tuple(compute_all(readings, profile, TODAY))
    bmi = next(i for i, m in enumerate(metrics, start=1) if m.key == "bmi")
    value = metrics[bmi - 1].value

    async def snap(_: str) -> Snapshot:
        return Snapshot(profile, readings, metrics, TODAY)

    t = Coach(f"你的 BMI 是 {value}，属于超重〔C{bmi}〕。")
    blocks, _ = run(agent(t, monkeypatch=monkeypatch, snapshot=snap), "我的 BMI 是多少")
    sources = next(
        b["content"]
        for b in blocks
        if b["type"] == "tool_result" and b["tool_call_id"] == "sources"
    )
    assert "计算" in sources and "BMI" in sources and f"BMI 是 {value}" in text_of(blocks)


def test_missing_plan_json_is_written_in_a_second_call(monkeypatch: Any) -> None:
    from ironm_agent.training import TrainingBook

    plan = {"title": "一练", "days_per_week": 1, "sessions": [{"day": 1, "name": "全身", "items": [{"exercise": "臀桥", "sets": 3, "reps": "12"}]}]}  # fmt: skip

    class Forgetful(Coach):
        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "expert" and "不用写给用户的文字" in system_of(messages):
                self.stages.append("write")
                return jsonr({"plan": plan, "changes": "新排的"})
            return super().__call__(stage, messages, tools)  # 只写了文字，忘了写 plan

    t = Forgetful("给你排了每周一练的全身计划〔经验〕。")
    a = agent(
        t,
        monkeypatch=monkeypatch,
        memory=book(("equipment", "家里有哑铃"), ("schedule", "每周练一次")),
        snapshot=snapshot_of(),
    )
    a._training = TrainingBook()

    async def asked(*_: str) -> list[str]:
        return ["用户：帮我排一个每周 1 练的计划", f"教练（要点）：{HEAD}目标、场景、器械……"]

    a._history = asked
    blocks, seen = run(a, "按这个排")
    assert seen["task"] == "plan" and seen["preview"] == "plan" and seen.get("preview_retry")
    assert "write" in t.stages and cards(blocks)
    assert "点「确认」才会保存" in text_of(blocks)


def test_very_high_blood_pressure_does_not_block_food_or_sleep(monkeypatch: Any) -> None:
    """独立审查："运动后吃什么"因为含"运动"被拦；问睡眠也被拦。"""
    for question in ("运动后吃什么", "最近睡不好怎么办"):
        _, seen = run(
            agent(Coach(), monkeypatch=monkeypatch, snapshot=snapshot_of(BP_HIGH)), question
        )
        assert seen["path"] == "answer", question


def test_answering_today_question_does_not_make_a_weekly_plan(monkeypatch: Any) -> None:
    async def asked(*_: str) -> list[str]:
        return ["用户：今天练什么", f"教练（要点）：先确认两件事…{MARK}，我先按…"]

    a = agent(Coach(), monkeypatch=monkeypatch, snapshot=snapshot_of(profile=Profile()))
    a._history = asked
    blocks, seen = run(a, "你定吧")
    assert seen["path"] == "answer" and seen["task"] is None and not cards(blocks)


def test_how_to_question_teaches_with_feel_cues(monkeypatch: Any) -> None:
    """动作教学（§8、§88：体感讲解并进了动作教学）：装载动作教学，预取的动作库资料带体感提示。"""
    t = Coach()
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "卧推的时候肩胛骨要怎么收紧"
    )
    assert "动作教学" in tasks_of(blocks)["管家"] and "move-coach" in seen["skills"]["general"]
    assert (
        "【动作教学】（决策卡）" in t.system and "取「怎么讲」一节的对照" in t.system
    )  # 对照表按节取（§99）
    assert "体感提示：" in t.input
    # 换动作也是同一份
    _, seen = run(agent(Coach(), monkeypatch=monkeypatch, snapshot=snapshot_of()),
                  "膝盖疼换什么动作")  # fmt: skip
    assert "move-coach" in seen["skills"]["general"]
