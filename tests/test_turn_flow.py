"""一轮的新流程（spec [2026-10-23] §2–§7）：共享档案、分层接力、数据风险、追问、只请一位时直接作答、预取资料。"""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ironm_agent.casefile import Snapshot
from ironm_agent.clarify import MARK
from ironm_agent.llm import ModelUnavailable, Reply, Stage
from ironm_agent.memory_store import Change, Item, MemoryBook
from ironm_agent.metrics import Profile, Readings
from tests.fakes import jsonr, route_reply, system_of
from tests.test_plugin import agent, shown, text_of

TODAY = date(2026, 10, 23)
T0 = datetime(2026, 10, 20, tzinfo=UTC)
NAMES = {
    "康复恢复师": "recovery",
    "训练教练": "trainer",
    "营养师": "nutrition",
}


class Team:
    """假模型：主教练按 plan 请人；每位角色回答一句带自己名字的结论，并记下自己收到的输入。"""

    def __init__(self, primary: str, helpers: Sequence[str] = (), down: Sequence[str] = ()) -> None:
        self.primary, self.helpers, self.down = primary, list(helpers), set(down)
        self.inputs: dict[str, str] = {}
        self.stages: list[str] = []
        self.compose_input = ""

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        self.stages.append(stage)
        if stage == "route":
            return route_reply("pro", self.primary, self.helpers)
        if stage == "expert":
            system = system_of(messages)
            role = next(v for k, v in NAMES.items() if f"「{k}」" in system)
            if role in self.down:
                raise ModelUnavailable("timeout")
            self.inputs[role] = str(messages[1]["content"])
            said = f"{role} 的结论〔经验〕"
            if "这一轮只请了你一位" in system:
                return jsonr({"answer": said})
            return jsonr({"conclusion": said})
        if stage == "compose":
            self.compose_input = str(messages[-1]["content"])
            return Reply("整合好的回答〔经验〕")
        return jsonr({"ops": []})


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


def test_every_expert_gets_the_same_case_file(monkeypatch: Any) -> None:
    t = Team("trainer", ["nutrition"])
    memory = book(
        ("injury", "左膝旧伤，蹲深了会疼"),
        ("equipment", "一对 20 公斤哑铃"),
        ("diet", "乳糖不耐受"),
    )
    run(
        agent(t, monkeypatch=monkeypatch, memory=memory, snapshot=snapshot_of()),
        "增肌期怎么练怎么吃",
    )

    def case_part(msg: str) -> str:
        start = msg.index("这个人的档案")
        return msg[start : msg.index("\n\n", start)]

    trainer, nutrition = case_part(t.inputs["trainer"]), case_part(t.inputs["nutrition"])
    assert trainer == nutrition and "左膝旧伤" in trainer and "乳糖不耐受" in trainer


def test_later_layers_get_earlier_conclusions_and_same_layer_stays_blind(monkeypatch: Any) -> None:
    t = Team("trainer", ["recovery", "nutrition"])
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "今天练腿怎么安排"
    )
    assert "recovery 的结论" in t.inputs["trainer"] and "recovery 的结论" in t.inputs["nutrition"]
    assert "前面同事" not in t.inputs["recovery"]
    assert "nutrition 的结论" not in t.inputs["trainer"]  # 同一层互相看不到
    assert "trainer 的结论" not in t.inputs["nutrition"]
    assert seen["layers"] == 2 and seen["roles"][0] == "recovery"
    tasks = {b["name"]: b["args"]["任务"] for b in blocks if b["type"] == "tool_call"}
    assert (
        "参考了康复恢复师的结论" in tasks["训练教练"]
        and "参考了康复恢复师的结论" in tasks["营养师"]
    )


def test_a_failed_earlier_layer_does_not_stop_the_next(monkeypatch: Any) -> None:
    t = Team("trainer", ["recovery"], down=["recovery"])
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "今天练腿怎么安排"
    )
    assert seen["statuses"] == ["failed", "spoke"] and "trainer" in t.inputs
    assert "前面同事" not in t.inputs["trainer"] and text_of(blocks)


def test_one_expert_answers_directly_without_composing(monkeypatch: Any) -> None:
    t = Team("trainer")
    blocks, seen = run(agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "深蹲怎么做")
    assert "compose" not in t.stages and seen["path"] == "answer"
    assert text_of(blocks) == "trainer 的结论"
    assert "系统按问题先查好的资料" in t.inputs["trainer"]  # 预取的资料在第一次调用前就给了


def test_very_high_blood_pressure_blocks_training_but_not_food(monkeypatch: Any) -> None:
    bp = Readings(
        systolic=((TODAY - timedelta(days=2), 186.0),),
        diastolic=((TODAY - timedelta(days=2), 114.0),),
    )
    t = Team("trainer")
    blocks, seen = run(agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(bp)), "今天练什么")
    assert seen["path"] == "risk" and t.stages == []  # 固定的提醒，整轮不调用模型
    assert "186/114" in text_of(blocks) and "这一轮先不给训练安排" in text_of(blocks)
    food = Team("nutrition")
    blocks, seen = run(agent(food, monkeypatch=monkeypatch, snapshot=snapshot_of(bp)), "早餐吃什么")
    # 先答早餐；血压提醒在首页，问饮食时对话里不再附（spec [2026-10-23] §42）
    assert seen["path"] == "answer" and text_of(blocks).startswith("nutrition 的结论")
    assert "186/114" not in text_of(blocks)


def test_risk_note_shows_once_per_session(monkeypatch: Any) -> None:
    bp = Readings(
        systolic=((TODAY - timedelta(days=3), 164.0),),
        diastolic=((TODAY - timedelta(days=3), 102.0),),
    )
    t = Team("trainer")
    a = agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(bp))
    first, _ = run(a, "深蹲怎么加重量")
    assert "164/102" in text_of(first)

    async def told(*_: str) -> list[str]:
        return ["用户：深蹲怎么加重量", "教练（要点）：" + text_of(first)[:80]]

    async def said_before(_: str) -> str:
        return text_of(first)

    food, _ = run(
        agent(Team("nutrition"), monkeypatch=monkeypatch, snapshot=snapshot_of(bp)), "早餐吃什么"
    )
    assert "164/102" not in text_of(food)  # 问饮食不附，提醒在首页（§42）

    a._history, a._earlier = told, said_before
    again, _ = run(a, "那卧推呢")
    assert "164/102" not in text_of(again)
    assert "最近血压偏高：不安排大重量" in t.inputs["trainer"]  # 约束仍在，只是不再在开头提醒


def test_new_user_asking_for_a_plan_is_asked_first(monkeypatch: Any) -> None:
    t = Team("trainer")
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of(profile=Profile())),
        "帮我做个训练计划",
    )
    assert seen["path"] == "clarify" and t.stages == [] and MARK in text_of(blocks)  # 不调用模型

    async def asked(*_: str) -> list[str]:
        return ["用户：帮我做个训练计划", "教练（要点）：" + text_of(blocks)[:80]]

    a = agent(Team("nutrition"), monkeypatch=monkeypatch, snapshot=snapshot_of(profile=Profile()))
    a._history = asked
    _, seen = run(a, "你定吧")
    assert (
        seen["path"] == "answer" and seen["roles"][0] == "trainer"
    )  # 回答追问的那一轮一定请训练规划


def test_poor_readiness_constrains_the_answer(monkeypatch: Any) -> None:
    tired = Readings(
        sleep_hours=steady(7.3, last=[4.6, 4.8, 4.5]), resting_hr=steady(58, last=[65, 66, 67])
    )

    class Heavy(Team):
        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "expert":
                self.stages.append(stage)
                self.inputs["trainer"] = str(messages[1]["content"])
                return jsonr({"answer": "今天上大重量深蹲 5 组〔经验〕"})
            if stage == "compose":  # 改写也没改掉
                self.stages.append(stage)
                return Reply("今天上大重量深蹲 5 组〔经验〕")
            return super().__call__(stage, messages, tools)

    t = Heavy("trainer")
    gym = book(("equipment", "在健身房练"), ("schedule", "一周四练，每次一小时"))  # 信息够，不追问
    a = agent(t, monkeypatch=monkeypatch, memory=gym, snapshot=snapshot_of(tired))
    blocks, seen = run(a, "今天练什么")
    assert "今天的身体状态：差" in t.inputs["trainer"]
    assert (
        seen["readiness"] == "poor"
        and seen["constraints"] == ["readiness"]
        and seen["constraint_fixed"]
    )
    assert "大重量（今天状态不好：先别做）" in text_of(blocks)


def test_same_layer_starts_together_and_shows_loaded_skills(monkeypatch: Any) -> None:
    t = Team("trainer", ["nutrition"])
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "增肌期怎么练怎么吃"
    )
    kinds = [
        (b["type"], b.get("id") or b.get("tool_call_id"))
        for b in blocks
        if b["type"] in ("tool_call", "tool_result")
    ]
    first_done = next(
        i for i, (k, cid) in enumerate(kinds) if k == "tool_result" and cid != "coach"
    )
    assert {cid for k, cid in kinds[:first_done] if k == "tool_call"} >= {"role-0", "role-1"}
    tasks = {b["name"]: b["args"]["任务"] for b in blocks if b["type"] == "tool_call"}
    assert "（规程：增肌" in tasks["训练教练"] and "（规程：增肌饮食" in tasks["营养师"]
    assert seen["skills"]["trainer"][0] == "plan-muscle"


def test_routing_runs_while_the_data_is_still_being_read(monkeypatch: Any) -> None:
    order: list[str] = []

    async def slow(_: str) -> Snapshot:
        order.append("snapshot-start")
        await asyncio.sleep(0.05)
        order.append("snapshot-done")
        return Snapshot(Profile(goal="muscle"), Readings(), (), TODAY)

    class Spy(Team):
        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "route":
                order.append("route")
            return super().__call__(stage, messages, tools)

    run(agent(Spy("nutrition"), monkeypatch=monkeypatch, snapshot=slow), "早餐吃什么")
    assert order.index("route") < order.index("snapshot-done")  # 读数据和调度同时进行


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

    class Data(Team):
        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "expert":
                return jsonr({"answer": f"你的 BMI 是 {value}，属于超重〔C{bmi}〕。"})
            return super().__call__(stage, messages, tools)

    blocks, _ = run(
        agent(Data("nutrition"), monkeypatch=monkeypatch, snapshot=snap), "我的 BMI 是多少"
    )
    sources = next(
        b["content"]
        for b in blocks
        if b["type"] == "tool_result" and b["tool_call_id"] == "sources"
    )
    assert "计算" in sources and "BMI" in sources and f"BMI 是 {value}" in text_of(blocks)


def test_missing_plan_json_is_written_in_a_second_call(monkeypatch: Any) -> None:
    from ironm_agent.training import TrainingBook

    plan = {"title": "三练", "days_per_week": 1, "sessions": [{"day": 1, "name": "全身", "items": [{"exercise": "臀桥", "sets": 3, "reps": "12"}]}]}  # fmt: skip

    class Forgetful(Team):
        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "expert" and "没有按格式写出" in system_of(messages):
                self.stages.append("write")
                return jsonr({"plan": plan, "changes": "新排的"})
            if stage == "expert":
                self.stages.append("expert")
                return jsonr({"answer": "给你排了每周一练的全身计划〔经验〕。"})  # 忘了写 plan
            return super().__call__(stage, messages, tools)

    t = Forgetful("trainer")
    a = agent(
        t,
        monkeypatch=monkeypatch,
        memory=book(("equipment", "家里有哑铃"), ("schedule", "每周练一次")),
        snapshot=snapshot_of(),
    )
    a._training = TrainingBook()
    blocks, seen = run(a, "帮我排一个每周 1 练的计划，你定")
    assert seen["task"] == "plan" and seen["preview"] == "plan" and seen.get("preview_retry")
    assert "write" in t.stages and any(str(b.get("id", "")).startswith("card-") for b in blocks)
    assert "点「确认」才会保存" in text_of(blocks)


def test_very_high_blood_pressure_does_not_block_food_or_sleep(monkeypatch: Any) -> None:
    """独立审查："运动后吃什么"因为含"运动"被拦；问睡眠请到恢复也被拦。"""
    bp = Readings(
        systolic=((TODAY - timedelta(days=2), 186.0),),
        diastolic=((TODAY - timedelta(days=2), 114.0),),
    )
    for question, role in (("运动后吃什么", "nutrition"), ("最近睡不好怎么办", "recovery")):
        _, seen = run(
            agent(Team(role), monkeypatch=monkeypatch, snapshot=snapshot_of(bp)), question
        )
        assert seen["path"] == "answer", question


def test_answering_today_question_does_not_make_a_weekly_plan(monkeypatch: Any) -> None:
    async def asked(*_: str) -> list[str]:
        return ["用户：今天练什么", f"教练（要点）：先确认两件事…{MARK}，我先按…"]

    a = agent(Team("trainer"), monkeypatch=monkeypatch, snapshot=snapshot_of(profile=Profile()))
    a._history = asked
    blocks, seen = run(a, "你定吧")
    assert seen["path"] == "answer" and seen["task"] is None
    assert not any(str(b.get("id", "")).startswith("card-") for b in blocks)


def test_how_to_question_teaches_with_feel_cues(monkeypatch: Any) -> None:
    """体感讲解（spec [2026-10-23] §8）：动作教练装载体感讲解，预取的动作库资料带体感提示。"""

    class Spy(Team):
        system = ""

        def __call__(
            self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool
        ) -> Reply:
            if stage == "expert":
                self.system = system_of(messages)
            return super().__call__(stage, messages, tools)

    t = Spy("trainer")
    blocks, seen = run(
        agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), "卧推的时候肩胛骨要怎么收紧"
    )
    tasks = {b["name"]: b["args"]["任务"] for b in blocks if b["type"] == "tool_call"}
    assert "体感讲解" in tasks["训练教练"] and "move-feel" in seen["skills"]["trainer"]
    assert "【体感讲解】" in t.system and "腋下夹着一张纸" in t.system
    assert "体感提示：" in t.inputs["trainer"]
    # 不是问怎么做，但点到了动作库里的动作：也装载；没点到动作就不装载
    _, seen = run(agent(Spy("trainer"), monkeypatch=monkeypatch, snapshot=snapshot_of()),
                  "卧推的时候肩膀前面疼怎么办")  # fmt: skip
    assert "move-feel" in seen["skills"]["trainer"]
    _, seen = run(agent(Spy("trainer"), monkeypatch=monkeypatch, snapshot=snapshot_of()),
                  "膝盖疼换什么动作")  # fmt: skip
    assert "move-feel" not in seen["skills"]["trainer"]


def test_mixed_questions_bring_in_the_other_role(monkeypatch: Any) -> None:
    """问题明确点到另一个领域时把那个领域的角色加上（spec [2026-10-23] §42）。"""
    from ironm_agent.coverage import missing_roles
    from ironm_agent.roles import Role

    ask = "准备跑半马，跑步和力量训练怎么搭配，饮食上要注意什么"
    assert missing_roles(ask, [Role.TRAINER]) == [Role.NUTRITION]
    assert missing_roles("昨晚只睡了 5 小时，今天还按计划练大重量吗", [Role.TRAINER]) == [
        Role.RECOVERY
    ]
    assert missing_roles("深蹲怎么做", [Role.TRAINER]) == []
    t = Team("trainer")
    _, seen = run(agent(t, monkeypatch=monkeypatch, snapshot=snapshot_of()), ask)
    assert "nutrition" in seen["roles"] and seen["roles_added"] == ["nutrition"]
