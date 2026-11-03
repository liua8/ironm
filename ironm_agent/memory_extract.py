"""从一轮问答里提取记忆（L1）：模型给出增、改、解决的操作，规则逐条核对后才落库。

核对规则（防编造）：
- 每条必须附原话片段，片段要能在用户这句话里找到（给过的建议在回答里找）；
- 内容里的数字只能来自片段（更新时也可以来自被更新的那条）；
- 更新、解决只能指向这个人现有的记忆；模型自己推测的放"待确认"，确认前不用于回答。
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast

from ironm_agent.facts import STRUCTURED, key_of, said_side, structured
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.memory_store import (
    CATEGORIES,
    Category,
    Change,
    Item,
    Origin,
    Status,
    absolute,
    new_id,
    now,
)

_log = logging.getLogger("ironm_agent.memory_extract")

MAX_OPS = 8  # 一轮最多落几条
MAX_ADVICE = 1  # 一轮最多记几条"给过的建议"（只记最关键的那个决定）
MAX_CONTENT = 60  # 一条记忆最多几个字
ANSWER_CHARS = 600  # 给提取看的回答最多几个字

_PROMPT = """你负责替健身教练团队记住"这个用户本人"的情况，供以后回答时参考。根据这一轮对话，决定要新增、更新或标为已解决的记忆。

类别（category 用英文代号）：
- special 特殊情况：孕期、心脏病、糖尿病、高血压、近期做过手术（系统按这一类提醒运动风险）
- injury 伤病与身体状况：伤病的部位和左右、怎么引起、什么动作会疼、医生的诊断与限制（如不建议跳）、慢性病。体态问题（圆肩、驼背、骨盆前倾）不是伤病：他说想改善的记成 goal，只是问怎么改善（「久坐圆肩怎么改善」）不记
- equipment 器械与场地：有哪些器械（几公斤）、在家还是健身房、场地条件。不同的器械各记一条
- schedule 可练时间与作息：哪几天能练、几点、每次多久，几点睡、几点起
- diet 饮食限制与习惯：素食、过敏、不耐受、忌口、正在吃的补剂和剂量、饮食习惯
- preference 喜好与讨厌：喜欢或讨厌的运动、动作、训练方式
- goal 目标：增肌、减脂、力量、耐力等，目标数字和期限，现在的情况（如现在多重）
- style 回答风格：希望回答是什么样（简短、不讲原理、多举例等）
- event 近期事件：最近几天发生、会影响这几天训练的事（练后酸痛、感冒、出差、没睡好等）
- level 训练水平：零基础 / 练了不到 6 个月 / 6 个月到 2 年 / 2 年以上（持续规律地练），加上做过的主要动作和用过的重量（如"练了一年，深蹲 60 公斤"）；变了用 update
- followup 待跟进：教练这一轮答应过的回访或用户要的提醒（如"下周问问膝盖""两周后复测体重"），until 写到期日；quote 从这一轮的对话里摘
- advice 给过的关键建议：教练这一轮针对这个人的情况做出的最关键的那个决定（如把全蹲换成箱式深蹲、练 4 周再看）。每轮最多 1 条；一般的训练原则（组数次数、休息多久、加重规则、热身放松、疼到几分就停、建议就医）不记，只是讲解知识时也不记

规则：
1. 只记用户明确说的、关于他本人的情况。不记：打招呼和闲聊；一般知识提问（问"肌酸怎么吃"不代表他在吃）；别人的情况（"我爸有高血压"是他爸的事）；假设（"如果我膝盖疼怎么办"不代表他膝盖疼）；否定的说法不能记成有（"没有伤病"不能记出任何伤病）；问句里带出的事不等于他有这件事（"肌酐含量高了怎么办""今天不是周一吗"不能记成他肌酐高、今天练什么），问句里顺带说了自己的近况（"我吃了布洛芬能练吗"）可以记那部分。
2. content 是一句简短的陈述，不超过 40 字，保留原话里的具体信息：部位和左右、重量、时间、次数、程度、原因；不加原话里没有的推测和判断（如"未痊愈""没有就医""需要注意"）。数字照原话写，不换算。只写他说了的：教练这一轮怎么安排、建议了什么不写进他的记忆（关键决定记成 advice），也不写"还没说""没问"这类旁白。一句话里说了几类事（目标和器械）分开记。
3. quote 是从用户这一轮的话里一字不差摘出的一段，能支撑这条记忆；advice 的 quote 从教练这一轮的回答里一字不差地摘。
4. 和已有记忆是同一件事的新情况，用 update，target 写那条记忆的编号，content 写合并后的完整新说法（如原来"家里有一对哑铃"，现在说"最重的是 15 公斤"，更新成"家里有一对哑铃，最重 15 公斤"；目标、可练时间、伤病情况变了也用 update）。已经好了、不再适用的，用 resolve，target 写编号，content 写现在的情况；他说好了、结束了、取消了（"身体好了""不出差了"），把还在生效的那几条近况和待跟进都 resolve，不新增"已结束"。改了以前给过的建议（同一件事给了新的量），用 update 指向那条建议。新的、不同的事用 add（新买的器械是另一件器械，用 add，原来的保留）。
5. inferred 只在内容是你根据他的话推测出来、他并没有直接说的时候写 true。能不推测就不推测。
6. 每条写 lasting：long（以后一直要照顾到：习惯、伤病、器械、目标、水平）或 short（只关于某一天、这几天：这顿吃了什么、今天练了什么、今天累、这周出差）；short 的系统记成 event。一顿饭吃了什么、一次训练练了什么不记（饮食记录、训练记录里有）。明显是临时的变化（"这两周出差""下周旅游""最近加班"）记成 event，不要 update 或 resolve 原来的器械、时间和目标；长期的变化（"我换健身房了""现在每天只有半小时"）才 update 原来那条。
7. 没有要记的，输出空列表。

8. event 写 until（到哪天为止，YYYY-MM-DD，含这天），按今天的日期算："这周"写这周日，"这两天"写明天，"这几天"写 3 天后，"下周"写下周日，说了具体日子照写；实在看不出写 7 天后。

只输出 JSON：{"ops": [{"op": "add|update|resolve", "target": "已有记忆的编号（add 不写）", "category": "...", "content": "...", "quote": "...", "inferred": false, "lasting": "long|short", "until": "event 才写"}]}"""

UNTIL_DAYS = 60  # 近况最多记多少天

# 明显是临时的说法（spec [2026-10-23] §55 需求 7）：记成近期事件，不改长期的器械、时间和目标
# 改原来那条时：带这些词的都算临时；新增一条时只认更明确的（"这周买了壶铃"不是临时的）
_TEMPORARY = re.compile(
    r"这两周|这一两周|这几天|这阵子|这段时间|这周|下周|出差|旅游|旅行|度假|回老家|加班|临时|暂时"
)
_SURELY_TEMPORARY = re.compile(r"这两周|这一两周|这几天|出差|旅游|旅行|度假|回老家|临时|暂时")
_LONG_TERM: frozenset[str] = frozenset({"equipment", "schedule", "goal"})
# 长期类别（用户画像）：模型标了 lasting=short 的不进这些，记成近期事件（§103）
_PROFILE: frozenset[str] = frozenset(
    {"goal", "level", "injury", "special", "equipment", "schedule", "diet", "preference", "style"}
)

_STATUS_NAMES = {"active": "有效", "pending": "待确认", "resolved": "已解决"}
_PUNCT = re.compile(r"[\s\W_]+", re.U)
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def norm(text: str) -> str:
    """比较原话片段用：统一全半角，去掉空白和标点。"""
    return _PUNCT.sub("", unicodedata.normalize("NFKC", text)).lower()


_CN_RUN = re.compile(r"[零〇一二两三四五六七八九十百]+")
_CN_DIGIT = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9}  # fmt: skip


def _cn_value(run: str) -> int:
    """ "十二" → 12，"三十" → 30，"一百二十" → 120（只管日常说法里的小数目）。"""
    total, cur = 0, 0
    for ch in run:
        if ch in _CN_DIGIT:
            cur = _CN_DIGIT[ch]
        else:
            total += (cur or 1) * (10 if ch == "十" else 100)
            cur = 0
    return total + cur


def digits(text: str, *, chinese: bool = False) -> set[str]:
    """写出来的数字；chinese=True 时把"一个小时""十二点"里的中文数字也算上（模型常把它们改写成阿拉伯数字）。"""
    plain = unicodedata.normalize("NFKC", text)
    out = {d.rstrip("0").rstrip(".") if "." in d else d for d in _DIGITS.findall(plain)}
    if chinese:
        out |= {str(_cn_value(r)) for r in _CN_RUN.findall(plain)}
    return out


@dataclass(frozen=True)
class Op:
    op: Literal["add", "update", "resolve"]
    category: Category
    content: str
    quote: str
    target: Item | None = None
    inferred: bool = False
    until: date | None = None  # 近况到哪天为止
    data: dict[str, Any] = field(default_factory=dict)  # 伤病、特殊情况的字段（§148）
    key: str = ""


@dataclass
class Extraction:
    changes: list[Change] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)  # 被拒的原因（不含记忆内容，可以进日志）
    failed: str = ""  # 模型没能给出结果的原因


def handles(items: Sequence[Item]) -> dict[str, Item]:
    """给模型看的短编号 m1、m2…（不把内部编号交给模型）。"""
    current = [x for x in items if x.status in ("active", "pending", "resolved")]
    return {f"m{i}": x for i, x in enumerate(current, 1)}


def messages_for(
    items: Mapping[str, Item],
    user_text: str,
    answer: str,
    context: Sequence[str],
    held: Sequence[str] = (),
) -> list[dict[str, Any]]:
    known = "\n".join(
        f"{h}：{x.category}｜{x.content}｜{_STATUS_NAMES.get(x.status, x.status)}"
        for h, x in items.items()
    )
    parts = [f"已有记忆（编号：类别｜内容｜状态）：\n{known or '（无）'}"]
    if context:
        parts.append("这次会话里用户前面说过的话（只用来理解指代，不从这里摘 quote）：\n"
                     + "\n".join(context))  # fmt: skip
    if held:
        parts.append("用户前面说过、还没整理成记忆的话（也可以从这里摘 quote）：\n"
                     + "\n".join(f"用户：{x}" for x in held))  # fmt: skip
    parts.append(f"这一轮：\n用户：{user_text}\n教练：{answer[:ANSWER_CHARS] or '（无）'}")
    today = date.today()
    parts.append(f"今天是 {today.isoformat()}（周{'一二三四五六日'[today.weekday()]}）。")
    return [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]


def _problem(
    raw: Mapping[str, Any],
    items: Mapping[str, Item],
    user_text: str,
    answer: str,
    held: str = "",
    today: date | None = None,
) -> tuple[Op | None, str]:
    kind = raw.get("op")
    if kind not in ("add", "update", "resolve"):
        return None, "未知的操作"
    target = None
    if kind != "add":
        target = items.get(str(raw.get("target") or ""))
        if target is None:
            return None, "更新或解决的目标不存在"
    category = raw.get("category") or (target.category if target else None)
    if category not in CATEGORIES:
        return None, "未知的类别"
    content = str(raw.get("content") or "").strip() or (target.content if target else "")
    if not content:
        return None, "内容是空的"
    if len(content) > MAX_CONTENT:
        return None, "内容太长"
    quote = str(raw.get("quote") or "").strip()
    source = (answer if category == "advice"
              else f"{user_text}\n{held}\n{answer}" if category == "followup"  # 答应的事可能是教练说的
              else f"{user_text}\n{held}")  # fmt: skip
    if len(norm(quote)) < 2 or norm(quote) not in norm(source):
        return None, "原话片段在原文里找不到"
    allowed = digits(quote, chinese=True) | (
        digits(target.content, chinese=True) if target else set()
    )
    if not digits(content) <= allowed:
        return None, "内容里有原话里没有的数字"
    # 某一次的训练、某一顿饭不进训练水平和饮食习惯，最多是当天的近况（§109 需求 5，和 §103 一致）
    once = (
        category in _ONE_OFF_KINDS
        and kind == "add"
        and bool(_ONE_OFF.search(quote))
        and not _HABIT.search(quote)
    )
    if category not in ("advice", "followup"):
        said = f"{user_text}\n{held}\n{target.content if target else ''}"
        content = own_part(content, said, answer)
        if not content:
            return None, "内容是教练说的，不是他说的"
    inferred = raw.get("inferred") is True and category not in ("advice", "followup")
    if category == "injury" and not inferred and _unsaid(content, quote):
        inferred = True  # 左右、诊断词原话里没有：是推测的，先放着等他确认
    if category in _PROFILE_FACTS and kind == "add" and asked_in(quote, f"{user_text}\n{held}"):
        inferred = True  # 问句里带出的（"肌酐高了怎么办"）不等于他有这件事：待确认（§109 需求 2）
    short = (raw.get("lasting") == "short" and category in _PROFILE) or once  # 只关于某一天、这几天
    if short or (
        category in _LONG_TERM
        and (_TEMPORARY.search(quote) if target is not None else _SURELY_TEMPORARY.search(quote))
    ):
        kind, category, target = "add", "event", None  # 临时的变化不覆盖长期记忆
    until = None
    if category == "advice":  # 说今天、明天、这周的建议到那天为止（§109 需求 4）；在写成日期之前看
        until = advice_until(content, today or date.today())
    if category in ("event", "followup"):
        until = until_of(raw.get("until"), today) or (target.until if target else None)
        if until is None and short:  # 只关于这一天：到说的那天为止
            until = today or date.today()
        if until is None and category == "followup":  # 待跟进没写哪天：一周后（§73）
            until = (today or date.today()) + timedelta(days=7)
    if kind == "add" and category == "advice":
        older = same_advice(content, items.values())
        if older is not None:  # 同一件事（蛋白质每天多少）的新建议：取代旧的那条
            kind, target = "update", older
    ended = category == "event" and bool(_ENDED.search(content))
    if kind == "update" and ended:
        kind = "resolve"  # 更新成"已经结束"就是已解决
    if (
        kind == "add" and category == "event" and target is None and not ended
    ):  # 说结束的交给 validate
        same = same_event(content, items.values(), today or date.today())
        if same is not None:  # 同一件事又说了一遍：改原来那条，不新增（§73 需求 3）
            kind, target = "update", same
            until = until or same.until
    data: dict[str, Any] = {}
    key = ""
    if kind == "resolve" and target is not None:  # 结束一条：字段照旧
        data, key = dict(target.data), target.key
    elif category in STRUCTURED:  # 伤病、特殊情况带字段，和原话对不上就退回（§148）
        category, data, why = structured(category, raw, content, quote)
        if why:
            return None, why
        if (target is not None and target.category == category and not data.get("side")
                and data.get("parts") == target.data.get("parts") and target.data.get("side")):  # fmt: skip
            # 改的是同一处、这次没说左右：沿用原来的（复核 11-03）
            data["side"] = target.data["side"]
        key = key_of(category, data)
        side = str(data.get("side") or "")
        if side and not inferred and not said_side(side, quote):
            inferred = True  # 左右原话里没说：推测的，先放着等他确认
        same = next((x for x in items.values() if key and x.key == key
                     and x.status in ("active", "pending") and x is not target), None)  # fmt: skip
        # 同一件事（同部位同侧、同一种特殊情况）说法变了：更新那一条；一样的照旧当成已经记着了。
        # 推测的不顶掉他说过、正生效的那条（复核 11-03）：另记一条待确认
        if (kind == "add" and same is not None and norm(same.content) != norm(content)
                and not (inferred and same.status == "active")):  # fmt: skip
            kind, target = "update", same
        if target is not None and target.category == category:  # 更新时没再交的字段沿用原来那条
            for name in ("kind", "severity", "triggers", "avoid", "codes", "since"):
                if name not in data and name in target.data:
                    data[name] = target.data[name]
        if data.get("kind") == "术后" and not data.get(
            "since"
        ):  # 术后从第一次记的那天算，更新不重新计时
            data["since"] = (today or date.today()).isoformat()
    content = absolute(content, today or date.today())  # "今天"写成日期（§103），数字核对在这之前
    op = Op(cast(Literal["add", "update", "resolve"], kind), cast(Category, category), content,
            quote, target, inferred, until, data, key)  # fmt: skip
    return op, ""


# ---- 只记他说了的（spec [2026-10-23] §109）--------------------------------------------------

_CLAUSE = re.compile(r"[，,；;。]")
_ASIDE = re.compile(r"还没说|没有说|还没问|没问过")  # 记录者的旁白，不是他的情况
_CHAR = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]")
_ONE_OFF_KINDS: frozenset[str] = frozenset({"level", "diet"})
_ONE_OFF = re.compile(
    r"今天|今早|今晚|昨天|昨晚|刚才|刚刚|这顿|这次|早上|中午|晚上|早餐|午餐|晚餐|早饭|午饭|晚饭"
)
_HABIT = re.compile(r"每天|每周|每次|一直|平时|经常|习惯|通常|总是|开始")
_PROFILE_FACTS: frozenset[str] = frozenset({"injury", "special", "goal", "level", "diet"})
_ASKING = re.compile(
    r"[？?]|吗$|呢$|怎么办|怎么改善|怎么|如何|能不能|可不可以|要不要|是不是|为什么|有没有|行不行|会不会"
)


def _cover(text: str, source: str) -> float:
    chars = _CHAR.findall(text)
    return sum(c in source for c in chars) / len(chars) if chars else 1.0


def own_part(content: str, said: str, answer: str) -> str:
    """只留他说了的部分：哪一小句大半不在他的话里、却在教练的回答里，是把教练的话记成了他说的，去掉；
    "还没说"这类旁白也去掉。都去掉了返回空。"""
    keep = []
    for clause in (c.strip() for c in _CLAUSE.split(content)):
        if not clause or _ASIDE.search(clause):
            continue
        coach = _cover(clause, said) < 0.5 and _cover(clause, answer) >= 0.7
        if len(_CHAR.findall(clause)) >= 3 and coach:
            continue
        keep.append(clause)
    return "，".join(keep)


def asked_in(quote: str, text: str) -> bool:
    """原话片段所在的那句话是不是在问（"肌酐含量高了怎么办""今天不是周一吗"）。"""
    key = norm(quote)
    for sentence in re.split(r"(?<=[。！!？?\n])", text):
        if key and key in norm(sentence):
            return bool(_ASKING.search(sentence.strip()))
    return False


_TODAY_WORDS = re.compile(r"今天|今晚|今早|今日|这次|这一次|本次|当天")
_TOMORROW_WORDS = re.compile(r"明天|明早|明晚")
_WEEK_WORDS = re.compile(r"这周|本周|这一周")


def advice_until(content: str, today: date) -> date | None:
    """建议说的是今天、明天、这周：到那天为止；别的不写（按 14 天过期）。"""
    if _TODAY_WORDS.search(content):
        return today
    if _TOMORROW_WORDS.search(content):
        return today + timedelta(days=1)
    if _WEEK_WORDS.search(content):
        return today + timedelta(days=6 - today.weekday())
    return None


# 同一件事的建议：新的取代旧的（§109 需求 4）；只认说了具体量的几件事
_ADVICE_TOPICS = tuple(
    re.compile(p) for p in (r"蛋白", r"千卡|热量|卡路里", r"碳水", r"脂肪", r"喝水|饮水")
)


def same_advice(content: str, items: Iterable[Item]) -> Item | None:
    if not _DIGITS.search(content):
        return None
    topics = [t for t in _ADVICE_TOPICS if t.search(content)]
    for x in sorted(items, key=lambda x: x.created, reverse=True):
        if (
            x.category == "advice"
            and x.status == "active"
            and _DIGITS.search(x.content)
            and any(t.search(x.content) for t in topics)
        ):
            return x
    return None


# 近期事件的种类：同一种、还在有效期里的，算同一件事（§73：出差说 3 遍只有一条）
_EVENT_KINDS = tuple(re.compile(p) for p in (
    r"出差|酒店|外地|回老家", r"旅游|旅行|度假",
    r"感冒|发烧|咳嗽|生病|病了|拉肚子|嗓子|不舒服|难受|肚子|身体",
    r"加班|很忙|太忙|没空|没时间", r"失眠|没睡好|睡不好|熬夜", r"经期|月经|生理期",
))  # fmt: skip


def _same_kind(a: str, b: str) -> bool:
    return any(k.search(a) and k.search(b) for k in _EVENT_KINDS)


def same_event(content: str, items: Iterable[Item], today: date) -> Item | None:
    """已有的、还在有效期里的同一种近期事件（出差、生病、忙……）；没有就是 None。"""
    kinds = [k for k in _EVENT_KINDS if k.search(content)]
    if not kinds:
        return None
    for x in items:
        if x.category != "event" or x.status != "active":
            continue
        if x.until is not None and x.until < today:
            continue
        if x.until is None and (today - x.created.astimezone().date()).days > 7:
            continue
        if any(k.search(x.content) for k in kinds):
            return x
    return None


def until_of(raw: Any, today: date | None = None) -> date | None:
    """近况的到期日：今天到 UNTIL_DAYS 天以内的日期才认，别的当作没写。"""
    try:
        day = date.fromisoformat(str(raw or "").strip()[:10])
    except ValueError:
        return None
    today = today or date.today()
    return day if today <= day <= today + timedelta(days=UNTIL_DAYS) else None


_DIAGNOSIS = re.compile(r"半月板|韧带|撕裂|损伤|骨折|劳损|突出|错位|积液|炎")


def _unsaid(content: str, quote: str) -> bool:
    """伤病内容里的左右和诊断词有没有不在原话里的。"""
    words = [s for s in ("左", "右") if s in content] + _DIAGNOSIS.findall(content)
    return any(w not in quote for w in words)


def validate(
    raw: Mapping[str, Any] | None,
    items: Mapping[str, Item],
    user_text: str,
    answer: str,
    held: Sequence[str] = (),
    today: date | None = None,
) -> tuple[list[Op], list[str]]:
    """核对模型给出的操作，返回通过的操作与被拒的原因。"""
    ops_raw = raw.get("ops") if raw else None
    if not isinstance(ops_raw, list):
        return [], ["输出不是规定格式的 JSON"]
    ops: list[Op] = []
    rejected: list[str] = []
    touched: set[str] = set()
    for one in ops_raw[: MAX_OPS * 2]:
        if not isinstance(one, Mapping):
            rejected.append("操作不是对象")
            continue
        op, problem = _problem(one, items, user_text, answer, "\n".join(held), today)
        if op is None:
            rejected.append(problem)
            continue
        twin = next(
            (i for i, o in enumerate(ops) if op.key and o.key == op.key and o.op != "resolve"), None
        )
        if (
            twin is not None and op.op != "resolve"
        ):  # 同一轮同一件事交了两条：合成一条（复核 11-03）
            first = ops[twin]
            if first.target is not None and op.target is not None and first.target is not op.target:
                rejected.append("同一件事交了两条，改的不是同一条")
                continue
            merged = {**first.data, **op.data}
            for name in ("triggers", "avoid", "codes"):
                both = [*first.data.get(name, []), *op.data.get(name, [])]
                if both:
                    merged[name] = list(dict.fromkeys(both))
            # 他说的那条为准（推测的不顶掉他说的）；两条都是他说的，以后一条为准；都是推测才算推测（复核 11-03）
            keep = op if (not op.inferred or first.inferred) else first
            target = first.target or op.target
            if target is not None and target.id not in touched:
                touched.add(target.id)
            ops[twin] = replace(keep, op="update" if target is not None else "add", target=target,
                                data=merged, inferred=first.inferred and op.inferred)  # fmt: skip
            continue
        if op.target is not None:
            if op.target.id in touched:
                rejected.append("同一条记忆改了两次")
                continue
            touched.add(op.target.id)
        seen = [(x.category, x.content) for x in items.values()]
        seen += [(o.category, o.content) for o in ops if o.op == "add"]
        if op.op == "add" and any(
            c == op.category and norm(t) == norm(op.content) for c, t in seen
        ):
            continue  # 已经记着了，不重复
        if (
            op.op == "add"
            and op.category == "event"
            and any(
                o.op == "add" and o.category == "event" and _same_kind(o.content, op.content)
                for o in ops
            )
        ):
            continue  # 同一轮里同一类近期事件只记一条（§103：同一次发烧记了两条）
        if op.category == "advice" and sum(o.category == "advice" for o in ops) >= MAX_ADVICE:
            rejected.append("给过的建议超过每轮上限")
            continue
        if op.op == "add" and op.category == "event" and _ENDED.search(op.content):
            # 说的是结束、好了、取消了：关掉同一类还在生效的近况和待跟进，不新增"已结束"（§109 需求 3）
            for x in items.values():
                if (x.category in ("event", "followup") and x.status == "active"
                        and x.id not in touched and _same_kind(x.content, op.content)):  # fmt: skip
                    touched.add(x.id)
                    ops.append(Op("resolve", x.category, op.content, op.quote, x))
            continue
        ops += _one_per_code(op, items, touched)
    return ops[:MAX_OPS], rejected


def _one_per_code(op: Op, items: Mapping[str, Item], touched: set[str]) -> list[Op]:
    """一句话里说了几种特殊情况（"有糖尿病和高血压"）：一种一条，各自按代码更新（复核 11-03），
    免得以后单说"高血压控制住了"时把糖尿病一起盖掉。"""
    codes = list(op.data.get("codes") or [])
    if op.category != "special" or op.op != "add" or len(codes) < 2:
        return [op]
    out = []
    for code in codes:
        key = f"special:{code}"
        same = next((x for x in items.values() if x.key == key and x.status in ("active", "pending")
                     and x.id not in touched), None)  # fmt: skip
        if same is not None and norm(same.content) == norm(op.content):
            continue  # 已经记着了
        if same is not None and not (op.inferred and same.status == "active"):
            touched.add(same.id)
            out.append(replace(op, op="update", target=same, data={"codes": [code]}, key=key))
        else:
            out.append(replace(op, data={"codes": [code]}, key=key))
    return out


_ENDED = re.compile(
    r"结束|取消|好了|已好|痊愈|不疼了|不痛了|没事了|恢复了|身体恢复|已恢复|恢复正常|不出差|回来了|不再"
)


def changes_of(ops: Sequence[Op], at: datetime | None = None) -> list[Change]:
    """把核对过的操作变成存储上的改动：改动原来那条 = 旧的标为被取代 + 新增一条。"""
    at = at or now()
    out: list[Change] = []
    for op in ops:
        origin: Origin = (
            "advice" if op.category == "advice" else ("inferred" if op.inferred else "said")
        )
        status: Status = (
            "resolved" if op.op == "resolve" else ("pending" if op.inferred else "active")
        )
        if op.target is not None:
            out.append(Change("status", id=op.target.id, status="superseded"))
        item = Item(new_id(), op.category, op.content, op.quote, origin, status, at, at,
                    op.target.id if op.target else None, op.until, op.data, op.key)  # fmt: skip
        out.append(Change("insert", item=item))
    return out


async def extract(
    llm: LLM,
    items: Sequence[Item],
    user_text: str,
    answer: str,
    context: Sequence[str] = (),
    held: Sequence[str] = (),
) -> Extraction:
    """调一次模型提取这一轮的记忆；模型不可用或输出不对时返回空结果，不向外抛。

    held：前几轮判断为不用提取、先留着的用户原话（spec [2026-10-23] §17），原话片段也可以出自这里。
    """
    known = handles(items)
    try:
        reply = await llm.chat("memory", messages_for(known, user_text, answer, context, held),
                               json_mode=True)  # fmt: skip
    except ModelUnavailable as e:
        return Extraction(failed=f"模型不可用：{e}")
    ops, rejected = validate(parse_json(reply.content), known, user_text, answer, held)
    if rejected:
        _log.info("memory ops rejected: %s", json.dumps(rejected, ensure_ascii=False))
    return Extraction(changes_of(ops), rejected)


# ---- 按需提取（spec [2026-10-23] §17）：先用规则判断这一轮可能含个人信息，才调用模型 ----------------

# 身体不适和近期状况：问句里也多半是在说自己（"感冒了还能去健身吗"）
_HURT = re.compile(r"疼|痛|伤|肿|麻|扭|不舒服|(?<!肌)酸|感冒|发烧|生病|没睡|熬夜|失眠|月经|经期")
_QUESTION = re.compile(
    r"吗|呢|？|\?|怎么|如何|什么|多少|几[次组个天]|要不要|能不能|可不可以|是不是|该不该|哪"
)
