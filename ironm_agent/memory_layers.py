"""单 Agent 的四层记忆（spec [2026-10-23] §73）：工作记忆、会话摘要、情景记忆、用户画像。

- 用户画像：长期的情况（目标、水平、伤病、器械、时间、饮食、喜好、回答风格），每行写更新日期和来源，推测的带"？"；
- 情景记忆：发生过的事（近期事件、给过的建议、待跟进），只追加；每轮只带还在影响训练的；
- 该问的：过了结束日没听他说结束的近况、刚推测还没确认的、到期的待跟进（他要的、管家记的），最多 3 条；
  代码每天生成的"该问的"（反复疼、练得远少于计划、很久没确认）去掉了（§182）：以前生成的不再带；
- 很久没确认的记忆：器械、可练时间、训练水平 90 天、伤病 60 天没更新的，带上次确认的日期列给管家（事实，最多 3 条），
  问不问由管家定；
- 查记忆工具：按关键词、天数（传入 similar 时再加上语义相似）查全部记忆，含已结束、被取代的。

每轮只常驻目标和安全相关的几类，其余按这一轮的决定取（spec 2026-10-30 记忆改进）：日程、饮食、偏好
不再全量拼进提示词，条目多了也不稀释注意力；没给决定时（测试、旧调用）仍全带。
画像、情景还是存在 ironm_memory 里（同一张表、同一套核对），这里只管怎么分层、怎么拼给 Agent。
不调用模型。
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ironm_agent.memory_extract import norm
from ironm_agent.memory_store import CATEGORIES, Category, Item, absolute
from ironm_agent.memory_view import advice_expired, faded, fading

PROFILE: tuple[str, ...] = (
    "goal",
    "level",
    "injury",
    "special",
    "equipment",
    "schedule",
    "diet",
    "preference",
    "style",
)
# 每轮常驻：目标、伤病、器械、训练水平、回答风格（都是短行，且几乎每类回答都要用）。
# 日程、饮食、偏好按这一轮的决定取（DECISION），避免把整本档案塞进提示词。
ALWAYS: tuple[Category, ...] = ("goal", "injury", "special", "equipment", "level", "style")
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
COVER_MIN = 0.5  # 查询词的两字片段有一半出现在记忆里，算说法相近（§159，不加依赖）
# 查旧记忆时同一类的说法（§159）：查"出差"也找"去上海开会"，查"睡眠"也找"熬夜"
_RECALL_KINDS = tuple(re.compile(p) for p in (
    r"出差|酒店|外地|回老家|开会|培训|外出", r"旅游|旅行|度假",
    r"感冒|发烧|咳嗽|生病|病了|拉肚子|嗓子|不舒服|难受",
    r"加班|很忙|太忙|没空|没时间", r"失眠|没睡好|睡不好|熬夜|睡眠|睡觉", r"经期|月经|生理期|大姨妈",
    r"器械|哑铃|壶铃|弹力带|杠铃|单杠|健身房",
))  # fmt: skip
RELATED_MAX = 8  # 同一处身体、同一类事最多补几条（复核 11-04：别把关键词命中的挤出去）
AUTO = "auto:"  # 以前代码每天生成的该问的（evidence 带这个前缀）：§182 起不再生成、也不再带
PENDING_DAYS = 3  # 推测的几天内带着问一句，过了还没确认就不再带（§154）
STALE_DAYS: dict[str, int] = {"equipment": 90, "schedule": 90, "level": 90, "injury": 60}  # 多久没更新算很久没确认
STALE_MAX = 3  # 很久没确认的最多列几条（最久的在前）


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
    stale: list[str] = field(default_factory=list)  # 很久没确认的记忆和上次确认的日期（事实，§182）

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
                "这一轮回答要用到其中说的推测的、很久没确认的那条（比如按那份器械排训练），就照它答完在最后加一句问还是不是这样；"
                "提了或他答了，用编号标为已解决）：\n" + "\n".join(self.asks)
            )
        if self.stale:
            parts.append(
                "很久没确认的记忆（括号里是上次确认的日期；问不问、什么时候问由你定，"
                "他说还是这样就 confirm、变了就 update、好了就 resolve）：\n" + "\n".join(self.stale)
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
    guesses: list[str] = []

    def handle(x: Item) -> str:
        nonlocal n
        n += 1
        h = f"m{n}"
        out.handles[h] = x
        return h

    from ironm_agent.latest import shadowed

    gone = shadowed(items)  # 同一件事以最近的为准（§113）
    live = [x for x in items if x.status != "superseded" and x.id not in gone]
    cats = (
        set(PROFILE)
        if focus is None
        else set(ALWAYS) | {c for f in focus for c in DECISION.get(f, ())}
    )
    for x in sorted((x for x in live if x.category in cats),
                    key=lambda x: (PROFILE.index(x.category), x.updated)):  # fmt: skip
        if x.status == "resolved" and x.category != "injury":
            continue  # 旧伤好了还带着（写明已好），别的已解决的长期情况不带
        if x.status == "pending" and (today - _day(x)).days > PENDING_DAYS:
            continue  # 推测的过了几天没确认：不再当事实带（§154），查记忆还查得到
        if faded(x, today):
            continue  # 喜好这类四个月没再提：不带了（§157），查记忆还查得到
        mark = "？" if x.status == "pending" else ""
        state = "（已好）" if x.status == "resolved" else ""
        src = "推测的" if x.status == "pending" else "你说的" if x.origin != "data" else "训练记录"
        h = handle(x)
        stale = (
            "，很久没确认"
            if _unconfirmed(x, today)  # 只写事实（§182），列在"很久没确认的记忆"里
            else "，两个月前说的：用到时可以顺带问一句还是不是这样"
            if fading(x, today)
            else ""
        )  # §157
        out.profile.append(f"{h}｜{CATEGORIES[x.category]}{state}：{said(x)}{mark}"
                           f"（{_md(x.updated.astimezone().date())}，{src}{stale}）")  # fmt: skip
        if x.status == "pending":
            guesses.append(f"{h}｜推测他「{said(x)}」，还没确认：合适时问一句对不对（对就 confirm {h}，不对就 resolve {h}）")

    for x in sorted((x for x in live if x.category == "event" and x.status == "active"), key=_day):
        end = event_end(x)
        if end >= today:
            until = f"，到{_md(end)}" if x.until else ""
            out.episodes.append(f"{handle(x)}｜{said(x)}（{_md(_day(x))}说的{until}）")
        elif (today - end).days <= ASK_GRACE:
            out.asks.append(
                f"{handle(x)}｜「{said(x)}」说到{_md(end)}为止，没听他说结束：可以问一句是不是结束了"
            )
    advice = [x for x in live if x.category == "advice" and x.status == "active"
              and not advice_expired(x, today)]  # 过期的建议不再带（§109）  # fmt: skip
    for x in sorted(advice, key=_day)[-ADVICE_KEEP:]:
        out.episodes.append(f"{handle(x)}｜给过的建议：{said(x)}（{_md(_day(x))}）")

    due = [x for x in live if x.category == "followup" and x.status == "active" and x.until
           and x.until <= today and (today - x.until).days <= DUE_KEEP]  # fmt: skip
    for x in sorted(due, key=lambda x: x.until or today):
        if x.evidence.startswith(AUTO):  # 以前代码每天生成的（§182 去掉了）：不再带，数据不删
            continue
        out.asks.append(f"{handle(x)}｜{said(x)}（{_md(x.until or today)}到期）")
    out.asks += guesses  # 到期的跟进（他要的提醒）排在推测的前面（复核 11-03）
    out.asks = out.asks[:ASK_MAX]
    shown = {x.id: h for h, x in out.handles.items()}
    for x in unconfirmed(live, today):
        h = shown.get(x.id) or handle(x)
        out.stale.append(f"{h}｜{CATEGORIES[x.category]}：{said(x)}（{_md(x.updated.astimezone().date())}）")
    return out


def _unconfirmed(x: Item, today: date) -> bool:
    """很久没确认：器械、可练时间、训练水平 90 天、伤病 60 天没更新（更新日期就是上次确认的日子，§154）；
    训练记录推出来的、系统写的不算。"""
    return (
        x.status == "active"
        and x.category in STALE_DAYS
        and x.origin not in ("data", "system")
        and (today - x.updated.astimezone().date()).days >= STALE_DAYS[x.category]
    )


def unconfirmed(items: Sequence[Item], today: date, limit: int = STALE_MAX) -> list[Item]:
    """很久没确认的记忆（事实，§182）：被取代的、同一件事有更新说法的不算；最久的在前，最多 limit 条。"""
    from ironm_agent.latest import shadowed

    gone = shadowed(items)
    old = [x for x in items if x.status != "superseded" and x.id not in gone and _unconfirmed(x, today)]
    return sorted(old, key=lambda x: x.updated)[:limit]


def unconfirmed_lines(items: Sequence[Item], today: date, limit: int = STALE_MAX) -> list[str]:
    """给管家复盘看的一行一条："器械：家里有一对哑铃（上次确认 6月1日，95 天前）"。"""
    out = []
    for x in unconfirmed(items, today, limit):
        day = x.updated.astimezone().date()
        out.append(f"{CATEGORIES[x.category]}：{said(x)}（上次确认 {_md(day)}，{(today - day).days} 天前）")
    return out


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
    hits.sort(key=lambda x: x.created, reverse=True)  # 关键词命中的排前面，补的跟在后面（复核 11-04）
    if q:  # 关键词没对上的：同一处身体、同一类事、说法相近的也算（§159）
        hits += _related(query, [x for x in items if _day(x) >= start and x not in hits])
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


def _related(query: str, pool: Sequence[Item]) -> list[Item]:
    from ironm_agent.facts import parts_in

    codes = set(parts_in(query))
    kinds = [k for k in _RECALL_KINDS if k.search(query)]
    near = sorted((x for x in pool
                   if (codes and codes & {*(x.data.get("parts") or []), *parts_in(x.content)})
                   or any(k.search(x.content) for k in kinds)), key=lambda x: x.created, reverse=True)[:RELATED_MAX]  # fmt: skip
    grams = _grams(query)
    rest = [x for x in pool if x not in near]
    fuzzy = sorted(((len(grams & _grams(x.content)) / len(grams), x) for x in rest if grams),
                   key=lambda t: -t[0])  # fmt: skip
    return near + [x for score, x in fuzzy if score >= COVER_MIN][:SEMANTIC_MAX]


def _grams(text: str) -> set[str]:
    t = norm(text)
    return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set(t)


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
    load: Callable[[], Awaitable[Sequence[Item]]] | None = None,
) -> Any:
    """load：查的时候才去库里取全部（含归档了的历史，§157）；取不到就用这一轮已经取的。"""

    async def run(box: Any, args: Mapping[str, Any]) -> str:
        try:
            days = int(args.get("days") or 90)
        except (TypeError, ValueError):
            days = 90
        pool = items
        if load is not None:
            try:
                pool = await load()
            except Exception:  # 库读不到：用这一轮已经取的
                pool = items
        return search(pool, str(args.get("query") or ""), days, today, similar=similar)

    return run
