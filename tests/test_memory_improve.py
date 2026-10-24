"""记忆改进（spec [2026-10-23] §17）：按需提取、训练记录得出的偏好、记忆多时按优先级读取。不调用真实模型。"""

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ironm_agent import memory_extract
from ironm_agent.memory_extract import hold, take_held, validate, worth_extracting
from ironm_agent.memory_prefs import aspect_of, changes_for, derive, refresh
from ironm_agent.memory_store import Change, Item, MemoryBook
from ironm_agent.memory_view import MAX_FACTS, Recall
from ironm_agent.training import LogItem, Plan, TrainingBook, WorkoutLog
from ironm_agent.yamlfile import load_yaml

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 24)
T0 = datetime(2026, 10, 1, 9).astimezone()


# ---- 按需提取 ---------------------------------------------------------------------------------


def test_pure_questions_are_not_extracted() -> None:
    for text in (
        "深蹲怎么做",
        "肌酸要怎么吃",
        "增肌一周练几次比较好",
        "你好，今天天气不错",
        "壶铃摇摆怎么做",
    ):
        assert not worth_extracting(text), text
    for text in ("我左膝有旧伤", "你回答简短点，别列一大堆", "家里只有一对哑铃", "工作日只能晚上 8 点以后练",
                 "感冒了还能去健身吗", "最重的是 15 公斤", "更正一下，不是左膝，是右膝"):  # fmt: skip
        assert worth_extracting(text), text
    assert worth_extracting("帮我排个计划", "plan") and worth_extracting("好的", "log")


def test_memory_eval_turns_that_are_skipped_carry_no_facts() -> None:
    """记忆考题里判为不用提取的轮次，只能出自"本来就不该记任何事"的情景（none: true）。"""
    cases = load_yaml(ROOT / "evals/memory/cases.yaml")["cases"]  # type: ignore[index]
    skipped = [
        (c["id"], bool(c.get("none")), t[0])
        for c in cases
        for t in c["turns"]
        if not isinstance(t, str) and not worth_extracting(t[0])
    ]
    assert skipped and all(none for _, none, _ in skipped), skipped


def test_held_lines_can_be_quoted_later() -> None:
    memory_extract._HELD.clear()
    for i in range(6):
        hold("s1", f"第{i}句")
    assert take_held("s1") == ["第2句", "第3句", "第4句", "第5句"] and take_held("s1") == []
    raw = {
        "ops": [
            {
                "op": "add",
                "category": "equipment",
                "content": "家里有一根弹力带",
                "quote": "家里有一根弹力带",
            }
        ]
    }
    assert validate(raw, {}, "那周末呢", "好的")[0] == []  # 原话不在这一轮里：不记
    ops, _ = validate(raw, {}, "那周末呢", "好的", held=["对了，家里有一根弹力带"])
    assert [o.content for o in ops] == ["家里有一根弹力带"]  # 出自先留着的那句：可以记


def test_skipped_turn_is_held_and_sent_with_the_next_extraction(monkeypatch: Any) -> None:
    from tests.test_turn_flow import Team, agent

    memory_extract._HELD.clear()
    seen: list[str] = []

    class Spy(Team):
        def __call__(self, stage: Any, messages: Any, tools: bool) -> Any:
            if stage == "memory":
                seen.append(str(messages[-1]["content"]))
                from tests.fakes import jsonr

                return jsonr({"ops": []})
            return super().__call__(stage, messages, tools)

    a = agent(Spy("exercise"), monkeypatch=monkeypatch, memory=MemoryBook())

    async def go(text: str) -> Any:
        blocks = [
            b
            async for b in a.generate_response(
                "42", [{"role": "user", "content": text}], session_id="42:s9"
            )
        ]
        await a.settle()
        return blocks

    asyncio.run(go("深蹲怎么做"))
    assert seen == []  # 纯提问：没调用模型提取
    asyncio.run(go("我左膝有旧伤，深蹲要注意什么"))
    assert len(seen) == 1 and "深蹲怎么做" in seen[0] and "还没整理成记忆的话" in seen[0]


# ---- 训练记录得出的偏好 -------------------------------------------------------------------------


def logs_on(weekdays: tuple[int, ...], weeks: int = 4, **kw: Any) -> list[WorkoutLog]:
    out = []
    for back in range(weeks * 7):
        d = TODAY - timedelta(days=back)
        if d.isoweekday() in weekdays:
            out.append(WorkoutLog(day=d, **kw))
    return out


def test_derive_days_minutes_frequency_intensity() -> None:
    prefs = derive(logs_on((2, 4), minutes=40, rpe=6), TODAY)
    assert prefs["days"].content == "通常在周二、周四练" and prefs["days"].category == "schedule"
    assert "8 次" in prefs["days"].evidence and prefs["days"].evidence.startswith(
        "训练记录（days）："
    )
    assert prefs["minutes"].content == "每次通常练 40 分钟左右"
    assert prefs["frequency"].content == "每周大约练 2 次"
    assert prefs["intensity"].content.startswith("训练时用力程度偏中低")
    hard = derive(logs_on((1, 3, 5), rpe=9), TODAY)
    assert hard["intensity"].content.startswith("训练时常练到很吃力")
    assert derive(logs_on((2,), weeks=2), TODAY) == {}  # 只有 2 次：不够 6 次，不记


def test_derive_skipped_exercise() -> None:
    plan = Plan.model_validate(
        {"title": "x", "days_per_week": 2, "sessions": [
            {"day": 2, "name": "腿", "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"},
                                              {"exercise": "后撤弓步", "sets": 3, "reps": "10"}]},
            {"day": 4, "name": "全身", "items": [{"exercise": "俯卧撑", "sets": 3, "reps": "10"}]}]}
    )  # fmt: skip
    logs = logs_on((2,), items=[LogItem(exercise="高脚杯深蹲", sets=3)]) + logs_on(
        (4,), items=[LogItem(exercise="俯卧撑", sets=3)]
    )
    assert derive(logs, TODAY, plan=plan)["skips"].content == "计划里的后撤弓步常跳过"


def data_item(
    aspect: str, content: str, *, updated: datetime = T0, category: str = "schedule"
) -> Item:
    return Item(
        f"d-{aspect}", category, content, f"训练记录（{aspect}）：……", "data", "active", T0, updated
    )  # type: ignore[arg-type]


def test_changes_insert_touch_and_stable_replace() -> None:
    now_ = derive(logs_on((2, 4)), TODAY)
    inserted = changes_for([], now_, {})
    assert {c.item.content for c in inserted if c.item} >= {"通常在周二、周四练"}
    assert all(c.item.origin == "data" for c in inserted if c.item)
    same = changes_for([data_item("days", "通常在周二、周四练")], {"days": now_["days"]}, {})
    assert same == [Change("status", id="d-days", status="active")]  # 还被支持：刷新时间
    unstable = changes_for([data_item("days", "通常在周一、周三练")], {"days": now_["days"]}, {})
    assert unstable == []  # 最近 14 天还不是新规律：不替换
    stable = changes_for(
        [data_item("days", "通常在周一、周三练")], {"days": now_["days"]}, {"days": now_["days"]}
    )
    assert stable[0] == Change("status", id="d-days", status="superseded")
    assert stable[1].item is not None and stable[1].item.supersedes == "d-days"


def test_user_said_schedule_wins() -> None:
    said = Item(
        "s1", "schedule", "工作日晚上 8 点以后练", "工作日晚上 8 点以后练", "said", "active", T0, T0
    )
    out = changes_for(
        [said, data_item("days", "通常在周一、周三练")], derive(logs_on((2, 4)), TODAY), {}
    )
    assert Change("status", id="d-days", status="superseded") in out
    assert not any(c.item and c.item.category == "schedule" for c in out)


def test_data_prefs_expire_after_56_days_without_support() -> None:
    at = datetime(2026, 12, 1, 9).astimezone()
    old = data_item("days", "通常在周二练", updated=at - timedelta(days=57))
    fresh = data_item("minutes", "每次通常练 40 分钟左右", updated=at - timedelta(days=3))
    assert [x.id for x in Recall.of([old, fresh], at).items] == ["d-minutes"]


def test_refresh_writes_prefs_and_respects_pause() -> None:
    memory, training = MemoryBook(), TrainingBook()
    for log in logs_on((2, 4), minutes=45):
        asyncio.run(training.log("42", log))
    changes = asyncio.run(refresh("42", memory, training, TODAY))
    items = asyncio.run(memory.items("42"))
    assert changes and {x.content for x in items} >= {
        "通常在周二、周四练",
        "每次通常练 45 分钟左右",
    }
    assert all(aspect_of(x) for x in items)
    asyncio.run(memory.set_paused("7", True))
    for log in logs_on((2, 4)):
        asyncio.run(training.log("7", log))
    assert asyncio.run(refresh("7", memory, training, TODAY)) == []


def test_checkin_triggers_refresh(monkeypatch: Any) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    calls: list[str] = []
    monkeypatch.setattr(web, "refresh_later", lambda uid, m, t: calls.append(uid))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web.training_store] = TrainingBook
    app.dependency_overrides[web.memory_store] = MemoryBook
    assert (
        TestClient(app).post("/iron/api/workouts", json={"session": "腿", "rpe": 6}).status_code
        == 200
    )
    assert calls == ["42"]


# ---- 记忆多时按优先级读取 -----------------------------------------------------------------------


def test_recall_trims_by_priority_when_too_many() -> None:
    items = [Item(f"i{i}", "injury", f"伤病{i}", "x", "said", "active", T0, T0) for i in range(5)]
    items += [
        Item(f"e{i}", "event", f"事件{i}", "x", "said", "active", T0, T0 + timedelta(minutes=i))
        for i in range(20)
    ]
    items += [
        Item(f"q{i}", "equipment", f"器械{i}", "x", "said", "active", T0, T0) for i in range(30)
    ]
    items += [
        Item(f"p{i}", "preference", f"喜好{i}", "x", "said", "active", T0, T0) for i in range(30)
    ]
    at = datetime(2026, 10, 2, 9).astimezone()
    r = Recall.of(items, at)
    cats = [x.category for x in r.items]
    assert len(r.items) <= MAX_FACTS and r.dropped == len(items) - len(r.items)
    assert cats.count("injury") == 5  # 伤病全部保留
    assert cats.count("equipment") == 10 and cats.count("event") <= 5
    assert "e19" in {x.id for x in r.items}  # 同类里保留最近的
    small = Recall.of(items[:10], at)
    assert small.dropped == 0 and len(small.items) == 10
