"""去掉触发式固定回答（spec [2026-10-23] §86）：判定仍由代码做，话交给模型说；
必须说到的没说到、给了训练安排或模型失败时，才退回原来的固定回答。"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from ironm_agent import spoken
from ironm_agent.actions import NEW_PLAN
from ironm_agent.clarify import HEAD
from ironm_agent.llm import Reply
from ironm_agent.metrics import Readings
from ironm_agent.plugin import HELP_ASK
from ironm_agent.spoken import NO_TRAINING, missing, say, urgent_needs
from tests.fakes import FakeLLM, acting, jsonr
from tests.test_plugin import text_of
from tests.test_single_agent import NEW, single
from tests.test_turn_flow import TODAY, run, snapshot_of

CHEST = "跑步的时候胸口突然很痛，现在还在疼"


def plain_reply(text: str) -> Any:
    return lambda *_: Reply(text)


def test_must_say_points() -> None:
    assert urgent_needs("emergency", ["cardiovascular"]) == ("stop", "call", NO_TRAINING)
    assert urgent_needs("red_flag", ["musculoskeletal"]) == ("stop", "doctor", NO_TRAINING)
    assert urgent_needs("emergency", ["mental_health"]) == ("hotline", "police", NO_TRAINING)
    assert missing("马上停下，现在就打 120。", ("stop", "call", NO_TRAINING)) == []
    assert missing("马上停下，休息一下。", ("stop", "call")) == ["call"]
    assert missing("停下打 120，缓过来再做 3 组深蹲。", ("stop", "call", NO_TRAINING)) == [
        NO_TRAINING
    ]
    assert missing("今天先休息，多喝水。", ("休息",)) == []  # 没列名字的按原词找


def test_say_returns_none_when_the_model_fails_or_misses_points() -> None:
    def down(*_: Any) -> Any:
        raise RuntimeError("模型挂了")

    assert asyncio.run(say(FakeLLM(down), spoken.URGENT, "", CHEST, ("call",))) is None
    assert (
        asyncio.run(say(FakeLLM(plain_reply("坐下歇会儿")), spoken.URGENT, "", CHEST, ("call",)))
        is None
    )
    got = asyncio.run(
        say(FakeLLM(plain_reply("**马上**打 120〔K20〕")), spoken.URGENT, "", CHEST, ("call",))
    )
    assert got is not None and "120" in got and "K20" not in got


def test_emergency_is_said_by_the_model_with_the_points_checked(monkeypatch: Any) -> None:
    said = "先停下别跑了，坐下休息；现在就打 120，别自己开车去医院。"
    a, s = single(plain_reply(said), monkeypatch)
    blocks, seen = run(a, CHEST)
    assert seen["path"] == "safety" and seen["safety_by"] == "model" and text_of(blocks) == said
    assert s.stages == ["expert"] and "120" in s.user  # 四段式的要点交给它，号码照写
    assert not any(b["type"] == "tool_call" for b in blocks)  # 不读数据、不调工具


def test_emergency_falls_back_to_the_fixed_reply(monkeypatch: Any) -> None:
    for answer in (plain_reply("先坐下歇一会儿。"), plain_reply("停下打 120，缓过来做 3 组拉伸。")):
        a, _ = single(answer, monkeypatch)
        blocks, seen = run(a, CHEST)
        assert seen["safety_by"] == "fixed" and "**" in text_of(blocks)  # 四段式

    def down(*_: Any) -> Any:
        raise RuntimeError("模型挂了")

    a, _ = single(down, monkeypatch)
    blocks, seen = run(a, CHEST)
    assert seen["safety_by"] == "fixed" and "120" in text_of(blocks)


def test_refusal_goes_to_the_model_and_is_patched_when_it_forgets_the_doctor(
    monkeypatch: Any,
) -> None:
    fixed = "用什么药、用多少"
    ok = "降压药得医生来开，我这边没法给。饮食上可以先少盐、多吃蔬菜。"
    a, s = single(lambda *_: jsonr({"answer": ok}), monkeypatch, old=True)
    blocks, seen = run(a, "我血压高，你给我开点降压药")
    assert not text_of(blocks).startswith(fixed) and ok in text_of(blocks)
    assert seen["refusal_by"] == "model" and "不能做" in s.user + s.system
    a, _ = single(lambda *_: jsonr({"answer": "饮食上先少盐、多吃蔬菜。"}), monkeypatch, old=True)
    blocks, seen = run(a, "我血压高，你给我开点降压药")
    assert seen["refusal_by"] == "fixed" and text_of(blocks).startswith(fixed)


def test_asking_for_someone_else_is_said_by_the_model(monkeypatch: Any) -> None:
    said = "这个得请你妈妈用她自己的账号来问，我只能看你本人的数据。"
    a, _s = single(plain_reply(said), monkeypatch)
    blocks, seen = run(a, "我妈最近血压怎么样", session="7:s1")
    assert seen["path"] == "help_ask" and seen["help_by"] == "model" and text_of(blocks) == said

    def down(*_: Any) -> Any:
        raise RuntimeError("模型挂了")

    a, _ = single(down, monkeypatch)
    blocks, _ = run(a, "我妈最近血压怎么样", session="7:s1")
    assert text_of(blocks) == HELP_ASK


def test_provenance_question_goes_to_the_model_with_the_sources(monkeypatch: Any) -> None:
    a, s = single(
        lambda *_: jsonr({"answer": "58 是你近 30 天静息心率的平均。"}), monkeypatch, old=True
    )

    async def sources(*_: Any) -> str:
        return "- 静息心率 58：近 30 天平均（静息心率的正常范围）"

    a._sources = sources
    blocks, seen = run(a, "这个58是怎么算的")
    assert seen.get("path") != "provenance" and s.stages[-1] == "expert"
    assert "追问上一条回答的依据" in s.user + s.system and "近 30 天平均" in s.user + s.system
    assert "58 是你近 30 天" in text_of(blocks) and "上一条回答的依据：" not in text_of(blocks)


def test_new_plan_conditions_are_asked_by_the_model(monkeypatch: Any) -> None:
    ask = f"{HEAD}：目标还是减脂吧？每周能练几天、在哪练？膝盖还疼吗？哪项变了跟我说。"
    a, _ = single(lambda *_: jsonr({"answer": ask}), monkeypatch, old=True)  # 它决定先列条件
    blocks, seen = run(a, "帮我排个新计划")
    assert seen["path"] == "clarify" and seen["clarify_by"] == "model" and text_of(blocks) == ask
    # 交了新计划被退回、开头没有那句（下一轮认不出问过了）：退回系统列的条件（§120）
    a, _ = single(acting(NEW_PLAN, {"plan": NEW, "changes": "", "kind": "new"},
                         {"answer": "好，先确认一下条件。"}), monkeypatch, old=True)  # fmt: skip
    blocks, seen = run(a, "帮我排个新计划")
    assert seen["clarify_by"] == "fixed" and text_of(blocks).startswith(HEAD)


def test_risk_reminders_are_requirements_not_a_tail(monkeypatch: Any) -> None:
    bp = Readings(systolic=((TODAY - timedelta(days=2), 164.0),),
                  diastolic=((TODAY - timedelta(days=2), 102.0),))  # fmt: skip
    a, s = single(lambda *_: jsonr({"answer": "今天练上肢，别憋气。"}), monkeypatch,
                  old=True, snapshot=snapshot_of(bp))  # fmt: skip
    blocks, seen = run(a, "今天练什么")
    assert "顺带提醒" in s.user + s.system and "164/102" in s.user + s.system
    assert "164/102" not in text_of(blocks) and seen["_tail"] == ""


def test_illness_button_reply_is_said_by_the_model(monkeypatch: Any) -> None:
    from ironm_agent.illness import IllnessBook
    from tests.test_illness import client, ep

    said = "好了就好！第一次回来按平时七成练，下次再回原计划。"
    monkeypatch.setattr(spoken, "default_llm", lambda: FakeLLM(plain_reply(said)))
    ill = IllnessBook()
    e = ep()
    asyncio.run(ill.save("42", e))
    c = client(monkeypatch, ill)
    r = c.post(f"/iron/api/illness/{e.id}/check", json={"answer": "resolved"}).json()
    assert r["message"] == said and r["status"] == "resolved"
    # 没说到"七成"：用规则那句
    monkeypatch.setattr(spoken, "default_llm", lambda: FakeLLM(plain_reply("好了就好！")))
    e2 = ep()
    asyncio.run(ill.save("42", e2))
    r = c.post(f"/iron/api/illness/{e2.id}/check", json={"answer": "resolved"}).json()
    assert "七成" in r["message"] and r["message"] != "好了就好！"


def test_illness_follow_up_is_a_requirement_not_a_tail(monkeypatch: Any) -> None:
    from datetime import date

    from ironm_agent.illness import recent
    from tests.test_illness import ep

    a, s = single(lambda *_: jsonr({"answer": "今天练上肢。"}), monkeypatch, old=True)
    e = ep(started=date.today() - timedelta(days=1))
    asyncio.run(a._illness_store().save("42", e))
    blocks, seen = run(a, "今天练什么")
    assert "今天还没问过他" in s.user + s.system and "好些了吗" in s.user + s.system
    assert "好些了吗" not in text_of(blocks) and seen["illness_asked"]
    asked = asyncio.run(recent(a._illness_store(), "42", date.today()))
    assert asked[0].asked == date.today()  # 记下今天问过了，不再重复
