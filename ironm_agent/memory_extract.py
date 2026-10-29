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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast

from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.memory_store import (
    CATEGORIES,
    Category,
    Change,
    Item,
    Origin,
    Status,
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
- injury 伤病与身体状况：伤病的部位和左右、怎么引起、什么动作会疼、医生的诊断与限制（如不建议跳）、慢性病
- equipment 器械与场地：有哪些器械（几公斤）、在家还是健身房、场地条件。不同的器械各记一条
- schedule 可练时间与作息：哪几天能练、几点、每次多久，几点睡、几点起
- diet 饮食限制与习惯：素食、过敏、不耐受、忌口、正在吃的补剂和剂量、饮食习惯
- preference 喜好与讨厌：喜欢或讨厌的运动、动作、训练方式
- goal 目标：增肌、减脂、力量、耐力等，目标数字和期限，现在的情况（如现在多重）
- style 回答风格：希望回答是什么样（简短、不讲原理、多举例等）
- event 近期事件：最近几天发生、会影响这几天训练的事（练后酸痛、感冒、出差、没睡好等）
- advice 给过的关键建议：教练这一轮针对这个人的情况做出的最关键的那个决定（如把全蹲换成箱式深蹲、练 4 周再看）。每轮最多 1 条；一般的训练原则（组数次数、休息多久、加重规则、热身放松、疼到几分就停、建议就医）不记，只是讲解知识时也不记

规则：
1. 只记用户明确说的、关于他本人的情况。不记：打招呼和闲聊；一般知识提问（问"肌酸怎么吃"不代表他在吃）；别人的情况（"我爸有高血压"是他爸的事）；假设（"如果我膝盖疼怎么办"不代表他膝盖疼）；否定的说法不能记成有（"没有伤病"不能记出任何伤病）。
2. content 是一句简短的陈述，不超过 40 字，保留原话里的具体信息：部位和左右、重量、时间、次数、程度、原因；不加原话里没有的推测和判断（如"未痊愈""没有就医""需要注意"）。数字照原话写，不换算。
3. quote 是从用户这一轮的话里一字不差摘出的一段，能支撑这条记忆；advice 的 quote 从教练这一轮的回答里一字不差地摘。
4. 和已有记忆是同一件事的新情况，用 update，target 写那条记忆的编号，content 写合并后的完整新说法（如原来"家里有一对哑铃"，现在说"最重的是 15 公斤"，更新成"家里有一对哑铃，最重 15 公斤"；目标、可练时间、伤病情况变了也用 update）。已经好了、不再适用的，用 resolve，target 写编号，content 写现在的情况。新的、不同的事用 add（新买的器械是另一件器械，用 add，原来的保留）。
5. inferred 只在内容是你根据他的话推测出来、他并没有直接说的时候写 true。能不推测就不推测。
6. 明显是临时的变化（"这两周出差""下周旅游""最近加班"）记成 event，不要 update 或 resolve 原来的器械、时间和目标；长期的变化（"我换健身房了""现在每天只有半小时"）才 update 原来那条。
7. 没有要记的，输出空列表。

8. event 写 until（到哪天为止，YYYY-MM-DD，含这天），按今天的日期算："这周"写这周日，"这两天"写明天，"这几天"写 3 天后，"下周"写下周日，说了具体日子照写；实在看不出写 7 天后。

只输出 JSON：{"ops": [{"op": "add|update|resolve", "target": "已有记忆的编号（add 不写）", "category": "...", "content": "...", "quote": "...", "inferred": false, "until": "event 才写"}]}"""

UNTIL_DAYS = 60  # 近况最多记多少天

# 明显是临时的说法（spec [2026-10-23] §55 需求 7）：记成近期事件，不改长期的器械、时间和目标
# 改原来那条时：带这些词的都算临时；新增一条时只认更明确的（"这周买了壶铃"不是临时的）
_TEMPORARY = re.compile(
    r"这两周|这一两周|这几天|这阵子|这段时间|这周|下周|出差|旅游|旅行|度假|回老家|加班|临时|暂时"
)
_SURELY_TEMPORARY = re.compile(r"这两周|这一两周|这几天|出差|旅游|旅行|度假|回老家|临时|暂时")
_LONG_TERM: frozenset[str] = frozenset({"equipment", "schedule", "goal"})

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
    source = answer if category == "advice" else f"{user_text}\n{held}"
    if len(norm(quote)) < 2 or norm(quote) not in norm(source):
        return None, "原话片段在原文里找不到"
    allowed = digits(quote, chinese=True) | (
        digits(target.content, chinese=True) if target else set()
    )
    if not digits(content) <= allowed:
        return None, "内容里有原话里没有的数字"
    inferred = raw.get("inferred") is True and category != "advice"
    if category == "injury" and not inferred and _unsaid(content, quote):
        inferred = True  # 左右、诊断词原话里没有：是推测的，先放着等他确认
    if category in _LONG_TERM and (
        _TEMPORARY.search(quote) if target is not None else _SURELY_TEMPORARY.search(quote)
    ):
        kind, category, target = "add", "event", None  # 临时的变化不覆盖长期记忆
    op = Op(cast(Literal["add", "update", "resolve"], kind), cast(Category, category), content,
            quote, target, inferred, until_of(raw.get("until"), today) or (target.until if target else None) if category == "event" else None)  # fmt: skip
    return op, ""


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
        if op.category == "advice" and sum(o.category == "advice" for o in ops) >= MAX_ADVICE:
            rejected.append("给过的建议超过每轮上限")
            continue
        ops.append(op)
    return ops[:MAX_OPS], rejected


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
                    op.target.id if op.target else None, op.until)  # fmt: skip
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

# 中文常常省略"我"（"工作日只能晚上 8 点以后练"），所以不要求出现"我"：提到这些内容、又不是纯粹的知识提问，就提取
_CUES = re.compile(
    r"伤|疼|痛|(?<!肌)酸|麻|肿|扭|骨折|手术|膝|腰|肩|颈|脖子|踝|腕|髋|心脏|心律|血压|血糖|糖尿病|哮喘|怀孕|孕|产后"
    r"|哑铃|杠铃|壶铃|弹力带|拉力带|器械|健身房|在家|家里|单杠|跑步机|单车|椭圆机|公斤|斤|kg|千克"
    r"|点|分钟|小时|周末|工作日|早上|晚上|中午|下班|上班|每天|每周|周[一二三四五六日天]"
    r"|素食|吃素|过敏|不耐受|忌口|不吃|不喝|补剂|肌酸|蛋白粉|鱼油|咖啡"
    r"|喜欢|讨厌|不想|不爱|受不了|无聊|目标|想增|想减|增肌|减脂|减肥|减到|瘦到|练到|体重|身高|岁"
    r"|出差|旅游|感冒|发烧|生病|没睡|熬夜|失眠|月经|经期|习惯|医生|诊断|好多了|好了"
)
# 说的是自己、而且是眼下或过去的情况
_PERSONAL = re.compile(
    r"我|俺|自己|咱|家里|家人|今天|昨天|前天|最近|这周|这个月|这两|现在|以前|之前|一直|刚|已经|更正|改成"
)
# 身体不适和近期状况：问句里也多半是在说自己（"感冒了还能去健身吗"）
_HURT = re.compile(r"疼|痛|伤|肿|麻|扭|不舒服|(?<!肌)酸|感冒|发烧|生病|没睡|熬夜|失眠|月经|经期")
_QUESTION = re.compile(
    r"吗|呢|？|\?|怎么|如何|什么|多少|几[次组个天]|要不要|能不能|可不可以|是不是|该不该|哪"
)
# 没说"我"也是在讲自己的情况
_STRONG = re.compile(r"旧伤|受过伤|做过.{0,4}手术|骨折过|过敏|不耐受|吃素|素食|怀孕|孕期|产后")
# 对回答方式的要求
_STYLE = re.compile(
    r"(回答|说话|讲|回复|解释).{0,6}(简短|短点|短一点|详细|别太长|少点|多举例|直接|通俗)"
    r"|别(给我)?列|说重点|简单点|太长了|啰嗦|别讲原理"
)
HELD_MAX = 4  # 一个会话最多留几句没提取的话
_HELD: dict[str, list[str]] = {}
_HELD_SESSIONS = 500


def worth_extracting(text: str, task: str | None = None) -> bool:
    """这一轮有没有可能含要记的个人信息；排计划、记训练时可能有"给过的建议"，也提取。"""
    if task in ("plan", "log"):
        return True
    if _STYLE.search(text) or _STRONG.search(text) or _HURT.search(text):
        return True
    if not _CUES.search(text):
        return False
    return bool(_PERSONAL.search(text)) or not _QUESTION.search(text)


def hold(session_id: str, text: str) -> None:
    """判断为不用提取的话先留着，下次提取时一起交给模型（防止误判漏记）。"""
    if not session_id:
        return
    lines = _HELD.pop(session_id, [])
    lines = [*lines, text][-HELD_MAX:]
    _HELD[session_id] = lines
    while len(_HELD) > _HELD_SESSIONS:  # 只留最近活跃的会话
        _HELD.pop(next(iter(_HELD)))


def take_held(session_id: str) -> list[str]:
    return _HELD.pop(session_id, []) if session_id else []
