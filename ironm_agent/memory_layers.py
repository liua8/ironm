"""单 Agent 的四层记忆（spec [2026-10-23] §73）：工作记忆、会话摘要、情景记忆、用户画像。

- 用户画像：长期的情况（目标、水平、伤病、器械、时间、饮食、喜好、回答风格），每行写更新日期和来源，推测的带"？"；
- 情景记忆：发生过的事（近期事件、给过的建议、待跟进），只追加；每轮只带还在影响训练的；
- 该问的：过了结束日没听他说结束的近况、到期的待跟进、每天检查出来的（反复疼、练得远少于计划），最多 3 条；
- 查记忆工具：按关键词、天数（传入 similar 时再加上语义相似）查全部记忆，含已结束、被取代的。

每轮只常驻目标和安全相关的几类，其余按这一轮的决定取（spec 2026-10-30 记忆改进）：日程、饮食、偏好
不再全量拼进提示词，条目多了也不稀释注意力；没给决定时（测试、旧调用）仍全带。
画像、情景还是存在 ironm_memory 里（同一张表、同一套核对），这里只管怎么分层、怎么拼给 Agent、每天检查什么。
不调用模型。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ironm_agent.memory_extract import norm
from ironm_agent.memory_store import CATEGORIES, Category, Change, Item, absolute, new_id, now
from ironm_agent.protools.movement import JOINT_NAMES
from ironm_agent.training import Plan, WorkoutLog

PROFILE: tuple[str, ...] = (
    "goal",
    "level",
    "injury",
    "equipment",
    "schedule",
    "diet",
    "preference",
    "style",
)
# 每轮常驻：目标、伤病、器械、训练水平、回答风格（都是短行，且几乎每类回答都要用）。
# 日程、饮食、偏好按这一轮的决定取（DECISION），避免把整本档案塞进提示词。
ALWAYS: tuple[Category, ...] = ("goal", "injury", "equipment", "level", "style")
DECISION: dict[str, tuple[Category, ...]] = {
    "train": ("schedule", "preference"),
    "plan": ("schedule", "preference"),
    "eat": ("diet", "preference"),
    "recover": ("schedule", "diet"),
    "data": ("diet",),
}
EVENT_DAYS = 7  # 没写到哪天为止的近况，影响训练几天
ASK_GRACE = 3  # 过了结束日几天内问一句"结束了吗"，之后当已结束
DUE_KEEP = 7  # 到期的待跟进过期几天后不再带
ASK_MAX = 3  # 每轮最多带几条该问的
ADVICE_KEEP = 3  # 情景里带最近几条给过的建议
SEMANTIC_MIN = 0.42  # 语义召回的最低相似度（fastembed 余弦）
SEMANTIC_MAX = 5  # 一次最多补几条语义命中
PAIN_DAYS, PAIN_TIMES = 30, 3  # 30 天里说疼 3 天以上，问要不要记成长期的
GAP_WEEKS = 3  # 连续几周都练不到计划的一半，问要不要改得更现实
AUTO = "auto:"  # 系统生成的该问的：evidence 里放这个前缀加去重键


def _day(x: Item) -> date:
    return x.created.astimezone().date()


def _md(d: date) -> str:
    return f"{d.month}月{d.day}日"


def said(x: Item) -> str:
    """交给模型的内容：存的"今天、昨天"按说的那天换成日期（§103，旧记忆不用改数据）。"""
    return absolute(x.content, _day(x))


def event_end(x: Item) -> date:
    """近况到哪天为止：写了就照写，没写按说的那天起 7 天。"""
    return x.until or _day(x) + timedelta(days=EVENT_DAYS)  # 和 memory_view.expired 一致


@dataclass
class Layers:
    """这一轮交给 Agent 的记忆：编号（更新、标为已解决时用）和拼好的文字。"""

    handles: dict[str, Item] = field(default_factory=dict)
    profile: list[str] = field(default_factory=list)
    episodes: list[str] = field(default_factory=list)
    asks: list[str] = field(default_factory=list)

    def text(self, today: date, summaries: Sequence[str] = ()) -> str:
        """日期在档案里已经写了，这里不再重复（§96）。"""
        parts = [
            "用户画像（长期的情况；编号｜类别：内容（更新日期，来源）；带？的是推测，不当事实用，合适时问一句确认）：\n"
            + ("\n".join(self.profile) or "（还没有）"),
            "情景记忆（最近发生、还在影响训练的事和给过的建议；更早的用 recall_memory 查）：\n"
            + ("\n".join(self.episodes) or "（没有）"),
        ]
        if self.asks:
            parts.append(
                "该问的、到期的跟进（由你决定这一轮提不提：一次最多提一件；他在问急事、说身体不适时不提；"
                "提了或他答了，用编号标为已解决）：\n" + "\n".join(self.asks)
            )
        if summaries:
            parts.append(
                "之前的会话（摘要，只用来接上话，不当成这次的问题）：\n" + "\n".join(summaries)
            )
        return "\n\n".join(parts)


def layers(items: Sequence[Item], today: date, focus: Collection[str] | None = None) -> Layers:
    """把这个人的记忆分成画像、情景、该问的。被取代的不带；推测的只在画像里带"？"。

    focus 是这一轮的决定（train / plan / eat / recover / data）。None 表示没给决定，画像全带（旧行为）；
    给了就只带 ALWAYS 里的几类，加上这些决定各自要的类别（DECISION）。
    """
    out = Layers()
    n = 0

    def handle(x: Item) -> str:
        nonlocal n
        n += 1
        h = f"m{n}"
        out.handles[h] = x
        return h

    live = [x for x in items if x.status != "superseded"]
    cats = (
        set(PROFILE)
        if focus is None
        else set(ALWAYS) | {c for f in focus for c in DECISION.get(f, ())}
    )
    for x in sorted((x for x in live if x.category in cats),
                    key=lambda x: (PROFILE.index(x.category), x.updated)):  # fmt: skip
        if x.status == "resolved" and x.category != "injury":
            continue  # 旧伤好了还带着（写明已好），别的已解决的长期情况不带
        mark = "？" if x.status == "pending" else ""
        state = "（已好）" if x.status == "resolved" else ""
        src = "推测的" if x.status == "pending" else "你说的" if x.origin != "data" else "训练记录"
        out.profile.append(f"{handle(x)}｜{CATEGORIES[x.category]}{state}：{said(x)}{mark}"
                           f"（{_md(x.updated.astimezone().date())}，{src}）")  # fmt: skip

    for x in sorted((x for x in live if x.category == "event" and x.status == "active"), key=_day):
        end = event_end(x)
        if end >= today:
            until = f"，到{_md(end)}" if x.until else ""
            out.episodes.append(f"{handle(x)}｜{said(x)}（{_md(_day(x))}说的{until}）")
        elif (today - end).days <= ASK_GRACE:
            out.asks.append(
                f"{handle(x)}｜「{said(x)}」说到{_md(end)}为止，没听他说结束：可以问一句是不是结束了"
            )
    advice = [x for x in live if x.category == "advice" and x.status == "active"]
    for x in sorted(advice, key=_day)[-ADVICE_KEEP:]:
        out.episodes.append(f"{handle(x)}｜给过的建议：{said(x)}（{_md(_day(x))}）")

    due = [x for x in live if x.category == "followup" and x.status == "active" and x.until
           and x.until <= today and (today - x.until).days <= DUE_KEEP]  # fmt: skip
    for x in sorted(due, key=lambda x: x.until or today):
        out.asks.append(f"{handle(x)}｜{said(x)}（{_md(x.until or today)}到期）")
    out.asks = out.asks[:ASK_MAX]
    return out


# ---- 每天检查一次（不调用模型）：生成"该问的" --------------------------------------------------------


def _auto(key: str, content: str, today: date) -> Change:
    at = now()
    return Change("insert", item=Item(new_id(), "followup", content, AUTO + key, "system", "active",
                                      at, at, None, today))  # fmt: skip


def daily_asks(
    items: Sequence[Item],
    pains: Sequence[tuple[str, date]],
    plan: Plan | None,
    logs: Sequence[WorkoutLog],
    today: date,
) -> list[Change]:
    """反复说疼、画像里还没有这处伤病 → 问要不要记成长期的；计划每周 N 练、连续几周都不到一半 → 问要不要改。
    同一个去重键 30 天内不重复生成。"""
    seen = {x.evidence for x in items if x.category == "followup" and x.evidence.startswith(AUTO)
            and (today - _day(x)).days <= 30}  # fmt: skip
    out: list[Change] = []
    profile = " ".join(
        x.content for x in items if x.category == "injury" and x.status != "superseded"
    )
    days = Counter(code for code, _ in {(c, d) for c, d in pains if (today - d).days < PAIN_DAYS})
    for code, n in days.items():
        name = JOINT_NAMES.get(code, "")
        key = f"pain:{code}"
        if n < PAIN_TIMES or not name or AUTO + key in seen or _short(name) in profile:
            continue
        out.append(
            _auto(
                key,
                f"最近一个月有 {n} 天说{name}疼：问一句是不是一直有，要不要记成长期的伤病（他确认了才写进画像）",
                today,
            )
        )
    if plan is not None and plan.days_per_week:
        want = plan.days_per_week
        monday = today - timedelta(days=today.weekday())
        weeks = [monday - timedelta(days=7 * (k + 1)) for k in range(GAP_WEEKS)]
        done = [
            sum(1 for x in logs if x.done and w <= x.day < w + timedelta(days=7)) for w in weeks
        ]
        key = f"gap:{weeks[0].isoformat()}"
        if all(d * 2 < want for d in done) and not any(s.startswith(AUTO + "gap:") for s in seen):
            got = "、".join(str(d) for d in reversed(done))
            out.append(
                _auto(
                    key,
                    f"计划每周练 {want} 次，最近 {GAP_WEEKS} 周分别练了 {got} 次：问一句要不要改成更现实的安排（只问，不改计划）",
                    today,
                )
            )
    return out


def _short(name: str) -> str:
    """关节名的简称，用来看画像里是不是已经有这处伤病：膝盖 → 膝，手腕 → 腕，腰椎 → 腰，脚踝 → 踝。"""
    for w in ("关节", "手", "椎", "盖", "脚"):
        name = name.replace(w, "")
    return name


# ---- 查记忆工具 ------------------------------------------------------------------------------


def search(
    items: Sequence[Item],
    query: str,
    days: int,
    today: date,
    limit: int = 20,
    similar: Callable[[str, Sequence[str]], Sequence[float]] | None = None,
) -> str:
    """按关键词（空就是全部）、最近几天查记忆，含已结束、被取代的，新的在前。

    传了 similar（本机向量）时再加一路语义召回：说法和记忆对不上但意思相近的也能查到
    （spec 2026-10-30 记忆改进），关键词命中排前面，语义命中补在后面。
    """
    q = norm(query)
    start = today - timedelta(days=max(1, min(days, 365)))
    hits = [x for x in items if _day(x) >= start and (not q or q in norm(x.content)
                                                       or q in norm(CATEGORIES[x.category]))]  # fmt: skip
    if q and similar is not None:
        pool = [x for x in items if _day(x) >= start]
        if pool:
            try:
                sims = similar(query, [f"{CATEGORIES[x.category]}：{x.content}" for x in pool])
            except Exception:  # 向量模型不可用：照旧只用关键词
                sims = []
            extra = [x for x, score in sorted(zip(pool, sims, strict=True), key=lambda t: -t[1])
                     if score >= SEMANTIC_MIN and x not in hits]  # fmt: skip
            hits += extra[:SEMANTIC_MAX]
    hits.sort(key=lambda x: x.created, reverse=True)
    if not hits:
        return "没有查到。"
    state = {
        "active": "",
        "pending": "（推测，未确认）",
        "resolved": "（已结束）",
        "superseded": "（已被更新）",
    }
    return "\n".join(f"{_md(_day(x))}｜{CATEGORIES[x.category]}：{said(x)}{until(x)}{state.get(x.status, '')}"
                     for x in hits[:limit])  # fmt: skip


def until(x: Item) -> str:
    return f"（到{_md(x.until)}）" if x.until and x.category in ("event", "followup") else ""


RECALL = "recall_memory"
RECALL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": RECALL,
        "description": "查这个人以前的记忆（含已结束、已被更新的）：以前的伤病、生病、出差、给过的建议、答应过的事。"
        "问到「上次」「以前」「为什么那时候」时用。",
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {"type": "string", "description": "关键词，如 膝盖、出差；空字符串查全部"},
                "days": {"type": "integer", "description": "查最近多少天，默认 90"},
            },
            "required": ["query"],
        },
    },
}


def recall_tool(
    items: Sequence[Item],
    today: date,
    similar: Callable[[str, Sequence[str]], Sequence[float]] | None = None,
) -> Any:
    async def run(box: Any, args: Mapping[str, Any]) -> str:
        try:
            days = int(args.get("days") or 90)
        except (TypeError, ValueError):
            days = 90
        return search(items, str(args.get("query") or ""), days, today, similar=similar)

    return run
