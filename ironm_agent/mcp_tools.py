"""AI 健身管家的工具登记到 mirobody 的工具登记处（spec [2026-10-23] §25 一期）。

登记后同一份工具通过 mirobody 的 MCP 给外部客户端用，mirobody 的 Agent 也能用。写法按 mirobody 的约定：
类名以 Service 结尾，`__tools__` 列出公开的工具，参数按类型标注生成说明，`user_info` 由服务端按登录身份注入。
读个人数据的工具只用注入的身份，不接受模型传入的用户编号；只读，不改数据（改数据要在 App 里确认）。
记忆不开放（含伤病等敏感内容）。日志不写内容。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ironm_agent.protools import registry as pro
from ironm_agent.protools.result import Result

_log = logging.getLogger("ironm_agent.mcp_tools")

NEED_LOGIN = {"success": False, "error": "这个工具要读本人的数据，需要登录后的身份"}

__tools__: tuple[str, ...] = ()  # 模块里的函数不是工具；工具只在下面几个 Service 类里


@dataclass
class Sources:
    """工具要读的存储（测试时整个换掉）。"""

    snapshot: Callable[[str], Awaitable[Any]]
    training: Any
    memory: Any
    meals: Any
    goals: Any
    coach: Any


def sources() -> Sources:
    from ironm_agent import web, web_more
    from ironm_agent.coach_state import default_coach

    return Sources(
        snapshot=web.snapshot_for,
        training=web_more.training_store(),
        memory=web_more.memory_store(),
        meals=web_more.meal_store(),
        goals=web_more.goal_store(),
        coach=default_coach(),
    )


def _uid(user_info: Mapping[str, Any] | None) -> str:
    return str((user_info or {}).get("user_id") or "")


def plain(result: Result) -> str:
    """专业工具的结果写成给人和模型看的文字（不带对话里的 C 编号）。"""
    lines = []
    for f in result.findings:
        extra = "；".join(x for x in (f"怎么算：{f.how}" if f.how else "",
                                     f"依据：{f.source}" if f.source else "") if x)  # fmt: skip
        lines.append(f"- {f.name}：{f.text}" + (f"（{extra}）" if extra else ""))
    lines += [f"- {n}" for n in result.notes]
    return "\n".join(lines) or "没有结果。"


async def _context(user_id: str, src: Sources) -> pro.ToolContext:
    from ironm_agent.casefile import injured_parts

    snap = await src.snapshot(user_id)
    items = [x for x in await src.memory.items(user_id) if x.status == "active"]
    weight = snap.readings.weight

    async def workouts(since: date) -> list[Any]:
        return [x.log for x in await src.training.workouts(user_id, since)]

    return pro.ToolContext.build(
        snap.today,
        goal=snap.profile.goal,
        weight_kg=max(weight, key=lambda p: p[0])[1] if weight else None,
        kcal_target=next(
            (m.value for m in snap.metrics if m.key == "kcal_target" and m.value), None
        ),
        readings=snap.readings,
        injured=injured_parts(items, ""),
        equipment_said=[x.content for x in items if x.category == "equipment"],
        plan=lambda: src.training.plan(user_id),
        workouts=workouts,
        age=snap.profile.age(snap.today),
        profile=snap.profile,
    )


async def _run(
    name: str, user_info: Mapping[str, Any] | None, args: Mapping[str, Any]
) -> dict[str, Any]:
    uid = _uid(user_info)
    if not uid:
        return NEED_LOGIN
    try:
        ctx = await _context(uid, sources())
        result = await pro.run(
            name, ctx, {k: v for k, v in args.items() if v not in (None, "", [])}
        )
    except Exception as e:
        _log.warning("mcp tool failed: tool=%s error_type=%s", name, type(e).__name__)
        return {"success": False, "error": "这次没能算出来，请稍后再试"}
    return {"result": plain(result)}


class FitnessKnowledgeService:
    """健身知识库与动作库（不读个人数据）。"""

    __tools__ = ("search_fitness_knowledge", "search_exercises")

    async def search_fitness_knowledge(self, query: str) -> dict[str, Any]:
        """在健身知识库里查资料：训练、动作、营养、恢复、运动安全方面的指南、立场声明和系统综述。

        Args:
            query: 要查的内容，中文关键词，如"每周训练几次 增肌""肌酸 剂量"。

        Returns:
            最相关的几条资料，每条带编号（K..）、标题、要点和出处；没找到时说明没找到。
        """
        from ironm_agent.kb import DOMAINS, default_kb

        found = default_kb().search(query, DOMAINS - {"library"}, k=4)
        return {
            "result": "\n\n".join(e.as_evidence() for e in found) or "知识库里没有找到相关资料。"
        }

    async def search_exercises(self, query: str) -> dict[str, Any]:
        """在动作库里查动作：做法、要点、常见错误、更容易和更难的替代、什么情况先别做。

        Args:
            query: 动作名或要找的动作类型，如"深蹲""练背 弹力带"。

        Returns:
            最相关的几个动作条目（带编号 K9..）；没找到时说明没找到。
        """
        from ironm_agent.exercises import library_kb

        found = library_kb().search(query, {"library"}, k=3)
        return {
            "result": "\n\n".join(e.as_evidence() for e in found) or "动作库里没有找到这个动作。"
        }


class FitnessToolsService:
    """健身专业计算：按本人的体重、伤病、器械、训练记录计算（读本人的数据，只读）。"""

    __tools__ = ("estimate_strength", "check_training_plan", "plan_templates", "training_patterns",
                 "find_substitutes", "nutrition_calc", "pain_check", "trend_analysis",
                 "explain_trends")  # fmt: skip

    async def estimate_strength(
        self,
        user_info: dict[str, Any],
        weight_kg: float | None = None,
        reps: int | None = None,
        target_reps: int | None = None,
        reps_in_reserve: int | None = None,
        max_kg: float | None = None,
        step_kg: float | None = None,
    ) -> dict[str, Any]:
        """力量计算：给 weight_kg 和 reps 估算最大重量（1RM）；给 target_reps、reps_in_reserve（做完还剩几次）
        和 max_kg（或最近一组的 weight_kg、reps）推出这组该用多重。

        Args:
            weight_kg: 一组用的重量（公斤）。
            reps: 这组做了几次。
            target_reps: 想做几次。
            reps_in_reserve: 做完还剩几次（0–4），默认 2。
            max_kg: 已知的最大重量（公斤）。
            step_kg: 重量最小档位，杠铃 2.5，哑铃常见 1 或 2。
        """
        return await _run("estimate_strength", user_info, dict(weight_kg=weight_kg, reps=reps,
                          target_reps=target_reps, reps_in_reserve=reps_in_reserve, max_kg=max_kg,
                          step_kg=step_kg))  # fmt: skip

    async def check_training_plan(
        self, user_info: dict[str, Any], plan: dict[str, Any]
    ) -> dict[str, Any]:
        """检查一份训练计划：各肌群每周组数与练几次、同一肌群是否连续两天、伤病部位的动作、器械是否齐、
        每次时长，以及和本人当前计划相比改了什么。

        Args:
            plan: 计划，格式 {"title", "goal", "days_per_week", "sessions": [{"day": 1–7, "name", "minutes",
                "items": [{"exercise", "sets", "reps", "load", "note"}]}]}。
        """
        return await _run("check_plan", user_info, {"plan": plan})

    async def plan_templates(
        self,
        user_info: dict[str, Any],
        days_per_week: int | None = None,
        level: str | None = None,
        goal: str | None = None,
        minutes: int | None = None,
        place: str | None = None,
        age: int | None = None,
        weekdays: list[int] | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """选初步方案：按训练水平、目标、每周天数、时长、场地、年龄，从方案库挑出最合适的方案，
        按本人的器械和伤病换成具体动作、排好周几，给出计划草稿、为什么这样排和怎么进阶。

        Args:
            days_per_week: 每周能练几天（1–7）；不填（也不填 name）时列出方案库的全部方案。
            level: none 零基础、lt6m 不到 6 个月、6m-2y 6 个月到 2 年、2y+ 2 年以上。
            goal: health 健康体能、fat_loss 减脂、muscle 增肌、strength 力量、endurance 耐力；不填用档案里的目标。
            minutes: 每次能练几分钟。
            place: gym 健身房、home 在家。
            age: 年龄；不填用档案里的出生日期。
            weekdays: 能练的周几，1 是周一。
            name: 点名要的博主或计划名，如"谭成义"。
        """
        return await _run("plan_templates", user_info, dict(days_per_week=days_per_week, level=level,
                          goal=goal, minutes=minutes, place=place, age=age, weekdays=weekdays,
                          name=name))  # fmt: skip

    async def training_patterns(
        self, user_info: dict[str, Any], days: int | None = 28
    ) -> dict[str, Any]:
        """汇总本人最近 14、28 或 56 天的训练：次数、每周平均、常在周几、每次时长、感受、按计划的完成率、
        常练和常跳过的动作。

        Args:
            days: 14、28 或 56。
        """
        return await _run("training_patterns", user_info, {"days": days})

    async def find_substitutes(
        self,
        user_info: dict[str, Any],
        exercise: str,
        direction: str | None = "any",
        avoid_parts: list[str] | None = None,
    ) -> dict[str, Any]:
        """找替代动作：按同一动作模式、本人有的器械和伤病，找更容易、相近或更难的动作，并写明为什么。

        Args:
            exercise: 要替代的动作名。
            direction: easier（更容易）、similar（相近）、harder（更难）或 any。
            avoid_parts: 要避开的关节编码：joint.knee（膝盖）、joint.lumbar（腰椎）、joint.shoulder（肩关节）、
                joint.wrist（手腕）、joint.ankle（脚踝）、joint.cervical（颈椎）、joint.elbow（手肘）、joint.hip（髋关节）。
        """
        return await _run("find_substitutes", user_info,
                          {"exercise": exercise, "direction": direction, "avoid_parts": avoid_parts})  # fmt: skip

    async def nutrition_calc(
        self,
        user_info: dict[str, Any],
        items: list[str] | None = None,
        training_minutes: int | None = None,
        weight_kg: float | None = None,
    ) -> dict[str, Any]:
        """营养计算（按本人体重）：protein 每天与每餐蛋白质、carbs 按训练量的碳水（需要 training_minutes）、
        creatine 肌酸、caffeine 咖啡因、beta_alanine β-丙氨酸、hydration 运动补水。

        Args:
            items: 要算的项目，从 protein、carbs、creatine、caffeine、beta_alanine、hydration 里选。
            training_minutes: 每天大概练几分钟。
            weight_kg: 体重（公斤）；不填时用健康记录里最新的体重。
        """
        return await _run("nutrition_calc", user_info,
                          {"items": items, "training_minutes": training_minutes, "weight_kg": weight_kg})  # fmt: skip

    async def pain_check(
        self,
        user_info: dict[str, Any],
        score: int | None = None,
        signs: list[str] | None = None,
        part: str | None = "",
    ) -> dict[str, Any]:
        """疼痛判断（运动场景分流，不做诊断）：按疼痛分数（0–10）和就医信号，给出可以继续、减量改动作，
        还是停下就医。

        Args:
            score: 疼痛分数 0–10。
            signs: 就医信号：snap 断裂声、deformity 变形、cannot_bear 不能承重、numbness 麻木刺痛、
                swelling_worse 肿胀加重、worsening 越来越疼、morning_worse 晨起加重。
            part: 哪里疼。
        """
        return await _run("pain_check", user_info, {"score": score, "signs": signs, "part": part})

    async def explain_trends(self, user_info: dict[str, Any]) -> dict[str, Any]:
        """综合解读本人的指标：每项和自己比、和标准比，认出的情况（恢复不够、睡得少、活动量掉了、减得太快等）、
        同期可能有关的原因和建议的调整，每条带出处。"""
        return await _run("explain_trends", user_info, {})

    async def trend_analysis(
        self, user_info: dict[str, Any], indicator: str, days: int = 28
    ) -> dict[str, Any]:
        """本人某个指标在一段时间里的趋势：平均、最高最低、头尾一周的平均、每周变化、变化是否超过日常波动。

        Args:
            indicator: weight、resting_hr、hrv_sdnn、hrv_rmssd、sleep_hours、steps、systolic、diastolic。
            days: 7 到 180 天。
        """
        return await _run("trend_analysis", user_info, {"indicator": indicator, "days": days})


class MyFitnessService:
    """本人的健身数据（只读）：训练计划与记录、今天的饮食、目标进度、管家的当前方案与调整经历。"""

    __tools__ = ("query_my_training", "query_my_meals", "query_my_goal", "query_coach_plan")

    async def query_my_training(
        self, user_info: dict[str, Any], days: int | None = 30
    ) -> dict[str, Any]:
        """本人的训练：当前计划、最近的训练记录（含每组重量和次数）、每个动作的下次目标。

        Args:
            days: 读最近多少天的训练记录（1–120）。
        """
        from ironm_agent.progression import targets

        uid = _uid(user_info)
        if not uid:
            return NEED_LOGIN
        src = sources()
        days = max(1, min(120, days or 30))  # mirobody 没传的参数给 None
        stored = await src.training.plan(uid)
        logs = [
            x.log for x in await src.training.workouts(uid, date.today() - timedelta(days=days))
        ]
        lines = ["当前计划：" + ("；".join(stored.plan.lines()) if stored else "还没有")]
        lines.append(f"最近 {days} 天的训练记录（{len(logs)} 次）：")
        lines += [f"- {x.line()}" for x in sorted(logs, key=lambda x: x.day, reverse=True)]
        try:  # 管家练完后定的下次目标（§132）；读不到照规则
            state = await src.coach.get(uid)
        except Exception:
            state = None
        found = targets(stored.plan if stored else None, logs, state.decided() if state else None)
        if found:
            lines.append("每个动作的下次目标：")
            lines += [f"- {t.line()}" for t in found.values()]
        return {"result": "\n".join(lines)}

    async def query_my_meals(
        self, user_info: dict[str, Any], day: str | None = ""
    ) -> dict[str, Any]:
        """本人某一天的饮食记录、合计的热量和三大营养素，以及每日热量和蛋白质目标。

        Args:
            day: 日期 YYYY-MM-DD，不填为今天。
        """
        from ironm_agent.meals import totals

        uid = _uid(user_info)
        if not uid:
            return NEED_LOGIN
        try:
            when = date.fromisoformat(day) if day else date.today()
        except ValueError:
            return {"success": False, "error": "日期格式应为 YYYY-MM-DD"}
        src = sources()
        meals = await src.meals.day(uid, when)
        t = totals(meals)
        snap = await src.snapshot(uid)
        by = {m.key: m for m in snap.metrics}
        lines = [f"{when.isoformat()} 记了 {len(meals)} 餐，合计约 {t.kcal:g} 千卡、蛋白质 {t.protein_g:g} 克、"
                 f"碳水 {t.carbs_g:g} 克、脂肪 {t.fat_g:g} 克（记录里的营养是估算）"]  # fmt: skip
        lines += [
            f"- {m.meal.kind} {m.meal.name}：约 {round(m.meal.macros.kcal)} 千卡" for m in meals
        ]
        for key in ("kcal_target", "protein_target"):
            m = by.get(key)
            if m is not None and m.value:
                lines.append(f"{m.name}：{m.text}")
        return {"result": "\n".join(lines)}

    async def query_my_goal(self, user_info: dict[str, Any]) -> dict[str, Any]:
        """本人的目标进度：起点、当前、目标体重和日期、按体重趋势预计达成的日期，以及是否该复测。"""
        from ironm_agent.goal import progress

        uid = _uid(user_info)
        if not uid:
            return NEED_LOGIN
        src = sources()
        g = await src.goals.get(uid)
        if g is None:
            return {"result": "还没有设目标体重和日期。"}
        snap = await src.snapshot(uid)
        trend = next((m for m in snap.metrics if m.key == "weight_trend"), None)
        p = progress(g, snap.readings.weight, trend, snap.today)
        lines = [
            f"目标体重 {g.value:g} 公斤，{g.by.isoformat()} 前；起点 {p['start']}，当前 {p['current']}"
        ]
        lines += [x for x in (p["message"], p["missing"], p["pace"], p["retest"]["text"]) if x]
        if p["predicted"]:
            lines.append(f"按现在的速度预计 {p['predicted']} 达成")
        return {"result": "\n".join(lines)}

    async def query_coach_plan(
        self, user_info: dict[str, Any], history: int = 10
    ) -> dict[str, Any]:
        """管家给本人的当前方案（今天的版本、下次目标、热量与蛋白质、目标进度、提醒、待确认的方案，每项带原因
        和依据），以及最近的调整经历（什么时候、因为什么、改了什么）。

        Args:
            history: 读最近多少条调整经历（0–50）。
        """
        uid = _uid(user_info)
        if not uid:
            return NEED_LOGIN
        src = sources()
        state = await src.coach.get(uid)
        if state is None:
            return {"result": "管家还没有给这个人建方案（打开 App 或提问后会建）。"}
        lines = [
            f"当前方案第 {state.version} 版（{state.day.isoformat()} 评估，因为{state.reason}）："
        ]
        mark = {"auto": "", "confirm": "【待确认】", "info": ""}
        lines += [f"- {mark[x.action]}{x.title}" + (f"：{x.why}" if x.why else "")
                  + (f"（依据：{x.basis}）" if x.basis else "") for x in state.items]  # fmt: skip
        changes = await src.coach.history(uid, max(0, min(50, 10 if history is None else history)))
        if changes:
            word = {"added": "新增", "changed": "调整", "removed": "解除"}
            lines.append("最近的调整经历：")
            lines += [
                f"- {c.day.isoformat()} {word[c.change]}：{c.after or c.before}" for c in changes
            ]
        return {"result": "\n".join(lines)}
