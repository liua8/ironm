"""单 Agent + Skill（spec [2026-10-23] §67）：一个 Agent 作答，Skill 跨领域装，工具按需调，动作由它给出。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from ironm_agent.agent import APP_HELP, LOAD_SKILL
from ironm_agent.clarify import HEAD
from ironm_agent.llm import Reply, Stage
from ironm_agent.metrics import Readings
from ironm_agent.training import TrainingBook
from tests.fakes import call, jsonr, system_of, tool_results
from tests.test_plan_ops import plan
from tests.test_plugin import agent, text_of
from tests.test_turn_flow import TODAY, run, snapshot_of

type Answer = Callable[[str, str, list[str]], Reply]


class Solo:
    """假模型：只应该有作答这一个环节；按这一轮用户的话回答，记下系统提示和工具结果。"""

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.stages: list[str] = []
        self.system = ""
        self.user = ""

    def __call__(self, stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        self.stages.append(stage)
        assert stage == "expert", stage  # 单 Agent 没有路由、整合
        self.system = system_of(messages)
        self.user = str(messages[1]["content"])
        return self.answer(self.system, self.user, tool_results(messages))


def single(
    answer: Answer, monkeypatch: Any, *, seeded: bool = False, **kw: Any
) -> tuple[Any, Solo]:
    s = Solo(answer)
    a = agent(s, monkeypatch=monkeypatch, snapshot=kw.pop("snapshot", snapshot_of()))
    a._mode = "single"
    store = TrainingBook()  # 不连数据库
    if seeded:
        store.seed("42", plan())
    a._training = store
    return a, s


def cards(blocks: list[dict[str, Any]]) -> list[str]:
    return [str(b["id"]) for b in blocks if str(b.get("id", "")).startswith("card-")]


def test_chat_is_answered_by_the_model_not_a_fixed_line(
    monkeypatch: Any, model_only_router: Any
) -> None:
    # 语义相似总说很像：也不按它硬装规程（"你好"曾被装上"今天状态判断"）
    monkeypatch.setattr(model_only_router, "similar", lambda _t, c: [0.9] * len(c), raising=False)
    a, s = single(lambda *_: jsonr({"answer": "你好！今天想聊训练还是吃的？"}), monkeypatch)
    blocks, seen = run(a, "你好")
    assert text_of(blocks).startswith("你好！今天想聊训练还是吃的") and s.stages == ["expert"]
    assert seen["agent"] == "single" and seen["path"] == "answer" and "route" not in seen
    assert next(b["name"] for b in blocks if b["type"] == "tool_call") == "管家"
    assert seen["skills"]["general"] == [] and "判断规则" not in s.system  # 闲聊不硬装规程
    assert "打招呼、道谢、闲聊时只写 answer" in s.system


def test_cross_domain_question_loads_skills_and_rules_of_both(monkeypatch: Any) -> None:
    a, s = single(
        lambda *_: jsonr({"answer": "每周 3 次力量，热量按目标吃〔经验〕。"}), monkeypatch
    )
    _, seen = run(a, "减脂期怎么练怎么吃")
    assert "训练的判断规则" in s.system and "饮食的判断规则" in s.system
    assert "转给谁" not in s.system  # 单 Agent 不转给别人
    loaded = seen["skills"]["general"]
    assert any(x.startswith("plan-") or "train" in x for x in loaded) and len(loaded) <= 4


def test_agent_can_load_another_skill_and_cite_it(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        assert "plan-muscle" in system  # 目录里看得到全部规程
        if not results:
            return call(LOAD_SKILL, id="plan-muscle")
        assert "【增肌】" in results[0]
        return jsonr({"answer": "增肌每个肌群每周 10 组以上〔K04〕。"})

    a, _ = single(answer, monkeypatch)
    blocks, seen = run(a, "我想长点肉")
    assert "每周 10 组以上" in text_of(blocks) and seen["tools"] == [LOAD_SKILL]
    assert not seen["_experts"][0]["repaired"]  # 装上的规程的依据能通过核对


def test_app_question_uses_the_guide_tool(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(APP_HELP)
        assert "使用说明" in results[0]
        return jsonr({"answer": "在首页点今天的训练就能打卡。"})

    a, _ = single(answer, monkeypatch)
    blocks, seen = run(a, "怎么打卡")
    assert "打卡" in text_of(blocks) and seen["tools"] == [APP_HELP]


def test_edit_written_by_the_agent_is_applied_as_a_preview(monkeypatch: Any) -> None:
    ops = [{"kind": "swap", "day": 3, "exercise": "侧平举", "to": "俯卧撑", "why": "你要求的"}]
    a, _ = single(lambda *_: jsonr({"answer": "周三的侧平举换成俯卧撑了。", "ops": ops}), monkeypatch,
                  seeded=True)  # fmt: skip
    blocks, seen = run(a, "把周三的侧平举换成俯卧撑")
    assert seen["action"] == "edit" and seen["plan_ops"]["by"] == "model" and cards(blocks)


def test_question_without_action_leaves_the_plan_alone(monkeypatch: Any) -> None:
    a, _ = single(lambda *_: jsonr({"answer": "屁股往后坐，膝盖跟着脚尖〔K25〕。"}), monkeypatch,
                  seeded=True)  # fmt: skip
    blocks, seen = run(a, "箱式深蹲怎么做")
    assert seen["action"] == "none" and not cards(blocks) and "plan_ops" not in seen


NEW = {"title": "居家减脂三练", "goal": "减脂", "days_per_week": 3, "sessions": [
    {"day": 1, "name": "全身 A", "minutes": 45, "items": [
        {"exercise": "高脚杯深蹲", "sets": 3, "reps": "10–12"}, {"exercise": "单臂哑铃划船", "sets": 3, "reps": "10–12"}]},
    {"day": 3, "name": "全身 B", "minutes": 45, "items": [
        {"exercise": "罗马尼亚硬拉", "sets": 3, "reps": "10–12"}, {"exercise": "哑铃卧推", "sets": 3, "reps": "8–12"}]},
    {"day": 5, "name": "全身 C", "minutes": 45, "items": [
        {"exercise": "箱式深蹲", "sets": 3, "reps": "10–12"}, {"exercise": "哑铃推举", "sets": 3, "reps": "8–12"}]},
]}  # fmt: skip


def test_new_plan_is_confirmed_first_then_built(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if '"action": "new_plan"' in system:  # 还没确认：只说要排新计划
            return jsonr({"answer": "好，先确认一下条件。", "action": "new_plan"})
        return jsonr({"answer": "为了减脂：每周 3 次全身力量〔经验〕。", "plan": NEW})

    a, s = single(answer, monkeypatch)
    first, seen = run(a, "给我一份训练计划")
    assert seen["path"] == "clarify" and HEAD in text_of(first) and not cards(first)

    async def asked(*_: str) -> list[str]:
        return ["用户：给我一份训练计划", "教练（要点）：" + text_of(first)[:200]]

    a._history = asked
    blocks, seen = run(a, "按这个排")
    assert seen["action"] == "plan" and cards(blocks)
    assert "用户刚回答了排计划前的确认" in s.user  # 确认过的条件按回答来排
    assert "上一轮你列了排新计划要用的条件" in s.system  # 这一轮要把计划写进 plan


def test_plan_written_before_confirming_is_held_back(monkeypatch: Any) -> None:
    a, _ = single(lambda *_: jsonr({"answer": "给你排好了。", "plan": NEW}), monkeypatch)
    blocks, seen = run(a, "帮我做个计划")
    assert seen["path"] == "clarify" and HEAD in text_of(blocks) and not cards(blocks)


def test_logging_a_workout_gives_a_record_preview(monkeypatch: Any) -> None:
    log = {"day": TODAY.isoformat(), "session": "", "done": True, "rpe": None, "minutes": None,
           "note": "", "items": [{"exercise": "深蹲", "sets": 5, "reps": "5", "weight_kg": 60, "done_sets": []}]}  # fmt: skip
    a, _ = single(lambda *_: jsonr({"answer": "记下了，下次试 62.5 公斤〔经验〕。", "log": log}),
                  monkeypatch)  # fmt: skip
    blocks, seen = run(a, "今天练了深蹲 5 组 5 次 60 公斤")
    assert seen["action"] == "log" and cards(blocks)


def test_data_risk_still_blocks_training_without_calling_the_model(monkeypatch: Any) -> None:
    bp = Readings(systolic=((TODAY - timedelta(days=2), 186.0),),
                  diastolic=((TODAY - timedelta(days=2), 114.0),))  # fmt: skip
    a, s = single(lambda *_: jsonr({"answer": "x"}), monkeypatch, snapshot=snapshot_of(bp))
    blocks, seen = run(a, "今天练什么")
    assert seen["path"] == "risk" and s.stages == [] and "186/114" in text_of(blocks)


def test_several_tools_in_one_turn_then_answer(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if not results:
            return call(APP_HELP)
        if len(results) == 1:
            return call(LOAD_SKILL, id="plan-muscle")
        assert "使用说明" in results[0] and "【增肌】" in results[1]
        return jsonr({"answer": "增肌每个肌群每周 10 组以上〔K04〕，在计划页能看到每天的组数。"})

    a, s = single(answer, monkeypatch)
    blocks, seen = run(a, "我想增肌，计划在哪看")
    assert seen["tools"] == [APP_HELP, LOAD_SKILL] and "10 组以上" in text_of(blocks)
    assert s.stages == ["expert"] * 3


def test_tool_loop_is_capped_and_answers_from_what_it_has(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if results and "不要再查了" in results[-1]:
            return jsonr({"answer": "增肌每个肌群每周 10 组以上〔K04〕。"})
        return call(LOAD_SKILL, id="plan-muscle")  # 一直想再查

    a, s = single(answer, monkeypatch)
    blocks, seen = run(a, "我想长点肉")
    assert "10 组以上" in text_of(blocks) and seen["_experts"][0]["forced"]
    assert len(s.stages) <= 7  # 不会无限循环


BP = Readings(systolic=((TODAY - timedelta(days=2), 186.0),),
              diastolic=((TODAY - timedelta(days=2), 114.0),))  # fmt: skip


def test_data_risk_blocks_a_plan_request_before_the_model(monkeypatch: Any) -> None:
    a, s = single(lambda *_: jsonr({"answer": "好，先确认一下条件。", "action": "new_plan"}),
                  monkeypatch, snapshot=snapshot_of(BP))  # fmt: skip
    blocks, seen = run(a, "帮我排个计划")  # 不带"练"字，原来认不出、照样调用模型
    assert seen["path"] == "risk" and s.stages == [] and "186/114" in text_of(blocks)


def test_data_risk_drops_an_edit_without_claiming_it_was_done(monkeypatch: Any) -> None:
    ops = [{"kind": "move", "day": 3, "to_day": 4, "why": "你要求的"}]
    a, s = single(lambda *_: jsonr({"answer": "已经把周三挪到周四了。", "ops": ops}), monkeypatch,
                  seeded=True, snapshot=snapshot_of(BP))  # fmt: skip
    blocks, seen = run(a, "周三那次挪到周四")  # 规则认不出是训练问题：模型给了改动
    assert s.stages == ["expert"] and seen["action_dropped"] == "risk" and seen["path"] == "risk"
    assert "已经把" not in text_of(blocks) and "186/114" in text_of(blocks) and not cards(blocks)


def test_whole_plan_written_as_an_edit_is_previewed_when_a_plan_exists(monkeypatch: Any) -> None:
    a, _ = single(lambda *_: jsonr({"answer": "改成三练全身了〔经验〕。", "plan": NEW}), monkeypatch,
                  seeded=True)  # fmt: skip
    blocks, seen = run(a, "把训练改成三练全身")  # 换分化：完整写出 plan，不是要重排
    assert seen["action"] == "edit" and seen.get("path") != "clarify" and cards(blocks)


def test_plan_after_confirming_is_written_by_the_fallback_when_missing(monkeypatch: Any) -> None:
    def answer(system: str, user: str, results: list[str]) -> Reply:
        if "不用写给用户的文字" in system:  # 补写计划（只要 JSON）
            return jsonr({"plan": NEW})
        return jsonr({"answer": "为了减脂：每周 3 次全身力量〔经验〕。"})  # 只写了文字

    a, _ = single(answer, monkeypatch)

    async def asked(*_: str) -> list[str]:
        return ["用户：给我一份训练计划", f"教练（要点）：{HEAD}目标、场景、器械、时间、伤病……"]

    a._history = asked
    blocks, seen = run(a, "按这个排")
    assert seen["action_forced"] == "confirmed" and seen["preview_retry"] and cards(blocks)


def test_reply_right_after_a_plan_preview_is_read_as_about_the_preview(monkeypatch: Any) -> None:
    a, s = single(lambda *_: jsonr({"answer": "是预览里哪里不行：动作、天数还是时长？"}), monkeypatch,
                  seeded=True)  # fmt: skip

    async def previewed(*_: str) -> list[str]:
        return ["用户：帮我排一个训练计划", f"教练（全文）：{HEAD}①目标……③器械……",
                "用户：我在健身房练", "教练（全文）：每周 3 练……\n\n下面是计划预览，点「确认」才会保存，保存后也能撤销。"]  # fmt: skip

    a._history = previewed
    run(a, "都不好")
    assert "他这句先当成对这份预览的回应" in s.user
    a._history = lambda *_: _empty()
    run(a, "都不好")
    assert "他这句先当成对这份预览的回应" not in s.user  # 上一轮没给预览时不加


async def _empty() -> list[str]:
    return []
