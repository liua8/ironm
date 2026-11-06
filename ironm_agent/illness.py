"""生病和身体不适（spec [2026-10-23] §46）：记成一次"生病"，从第二天起每天追问到好，按症状决定当天怎么练，
生病的日子不算缺勤。

认词表、分级、追问、当天怎么练都是规则，不调用模型。内容加密存储，日志只记级别和状态，不记症状原话。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Collection, Sequence
from datetime import date, timedelta
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from ironm_agent.casefile import said
from ironm_agent.ddl import run_ddl

_log = logging.getLogger("ironm_agent.illness")

# 颈部以上 / 没说哪里（只说不舒服，§82）/ 颈部以下或全身 / 发烧（K23）
type Level = Literal["above", "vague", "below", "fever"]
type Status = Literal["open", "better", "resolved", "unconfirmed"]
type Answer = Literal["resolved", "better", "unwell"]
type Mode = Literal["rest", "light", "ease"]  # 休息 / 轻松版 / 病后第一次按约七成

SILENT_DAYS = 3  # 连续这么多天没回答就不再问，这次生病不再当成现在的情况
UNWELL_TIMES = 3  # 连续这么多次"还不舒服"建议就医
FEVER_DAYS = 3  # 发烧这么多天还没好建议就医
EASE = 0.7  # 病后第一次训练按约七成
AFTER_DAYS = 2  # 好了之后这么多天内没做到的组次不触发减重量
RECUR_DAYS, RECUR_TIMES = 28, 2  # 4 周内病了 2 次以上：提示减量
_RANK: dict[Level, int] = {"above": 0, "vague": 0, "below": 1, "fever": 2}

# 症状：名字、说法、级别（K23：颈部以上可以降低强度活动；颈部以下、全身症状和发烧应当休息）
SYMPTOMS: tuple[tuple[str, re.Pattern[str], Level], ...] = (
    ("发烧", re.compile(r"发烧|发热|高烧|低烧|烧到|体温高"), "fever"),
    ("肚子疼", re.compile(r"(?:肚子|胃|腹)[^不没，。]{0,3}(?:疼|痛|不舒服)"), "below"),
    ("拉肚子", re.compile(r"拉肚子|腹泻|闹肚子|拉稀"), "below"),
    ("呕吐", re.compile(r"呕吐|想吐|吐了|恶心"), "below"),
    ("咳嗽", re.compile(r"咳嗽|咳得"), "below"),
    ("胸闷", re.compile(r"胸闷"), "below"),
    ("全身酸痛", re.compile(r"全身酸痛|浑身疼|浑身酸痛|全身疼|肌肉酸痛得厉害"), "below"),
    ("头疼", re.compile(r"头[^不没，。]{0,3}(?:疼|痛|晕)"), "below"),
    ("流鼻涕", re.compile(r"流鼻涕|流涕|鼻塞|打喷嚏"), "above"),
    ("嗓子疼", re.compile(r"(?:嗓子|喉咙|咽)[^不没，。]{0,3}(?:疼|痛|不舒服|哑)"), "above"),
)
# 说的是训练之后（练完、练后、昨天练腿……）：全身酸痛是练后酸痛（§49）
_TRAINED = re.compile(
    r"练完|练后|训练后|训练完|健身后|健身完|运动后|运动完|跑完|锻炼后|撸铁后|(?:昨天|前天|上次)练"
)
# 只说生病了、没说具体症状的：记成"没说哪里"，今天按轻松版，由管家问一句哪里不舒服（§82）
_GENERAL = re.compile(r"感冒|生病|病了|不舒服|难受|着凉")
_GENERAL_OK = re.compile(
    r"(?:膝|腰|肩|腕|踝|脖子|颈)[^，。]{0,4}不舒服"
)  # 关节不舒服是伤痛，不是生病

# 问到病情、转述以前说过的（spec [2026-10-23] §50）："疼不疼""是不是肚子疼""我多久说了肚子疼"
_CLAUSE = re.compile(r"[^，,。！？?；;\n]+")
_ASK_BEFORE = re.compile(
    r"是不是|有没有|多久|什么时候|哪天|几号|说了|说过|提到|讲过|上次说|之前说|昨天说|前天说"
)
_ASK_AFTER = re.compile(
    r"^(?:不(?:疼|痛|舒服|烧)|没(?:有)?(?:疼|痛)|[吗么嘛]|的?记录|的?历史|史)"
)  # "我的生病记录""病史"是在问（§113）


def _asking(pattern: re.Pattern[str], clause: str) -> bool:
    for m in pattern.finditer(clause):
        if _ASK_BEFORE.search(clause[: m.start()]) or _ASK_AFTER.search(clause[m.end() :]):
            return True
    return False


def _reported(pattern: re.Pattern[str], text: str) -> bool:
    """本人在说自己有这个症状：按分句看，问话和转述的分句不算。"""
    return any(said(pattern, c) and not _asking(pattern, c) for c in _CLAUSE.findall(text))


# 用文字回答"好了没"（规则先认，认不出的交给后台提取记忆的模型）
_RESOLVED = re.compile(
    r"(?:已经|都|全)?好了|(?<![疼痛])不(?:疼|痛|拉|难受)|退烧了|没事了|痊愈|好利索|恢复了"
)  # "不疼啊""不疼了"都算；"疼不疼"是问话，不算（§50）
_BETTER = re.compile(r"好多了|好一些|好点了|好一点|轻了|减轻|缓解了|没那么")
_UNWELL = re.compile(
    r"还(?:是|在|会)?(?:有点|有些|一点)?(?:疼|痛|拉|烧|发烧|咳|吐|恶心|晕|不舒服|难受)|没好|更严重|更疼|加重"
)


class Check(BaseModel):
    day: date
    answer: Answer


class Episode(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    symptoms: list[str]
    level: Level
    started: date
    status: Status = "open"
    checks: list[Check] = Field(default_factory=list)
    asked: date | None = None  # 最近一次在对话里追问的日子（每天只问一次）
    light_until: date | None = None  # 说好了但心率还没恢复：到这天为止按轻松版
    ended: date | None = None  # 好了的那天

    @property
    def active(self) -> bool:
        return self.status in ("open", "better")

    def answered(self, day: date) -> bool:
        return any(c.day == day for c in self.checks)

    def last_touch(self) -> date:
        return max([self.started, *(c.day for c in self.checks)])

    def what(self) -> str:
        return "、".join(self.symptoms)


# ---- 认出来、分级 ---------------------------------------------------------------------------


def detect(text: str) -> tuple[list[str], Level] | None:
    """这句话里本人说到的症状和级别；否定的（"没发烧"）、已经好了的、说旁人的不算。"""
    found = [(name, level) for name, pattern, level in SYMPTOMS if _reported(pattern, text)]
    if _TRAINED.search(text):  # 练完全身酸痛是练后酸痛，不是生病（§49）
        found = [(n, lv) for n, lv in found if n != "全身酸痛"]
    if found:
        top = max((lv for _, lv in found), key=_RANK.__getitem__)
        return [n for n, _ in found], top
    if _reported(_GENERAL, text) and not _GENERAL_OK.search(text):
        return ["身体不适"], "vague"
    return None


def reply_of(text: str) -> Answer | None:
    """用文字回答"好了没"：还不舒服优先（"好多了，就是还在拉"算还不舒服）。"""
    if _UNWELL.search(text):
        return "unwell"
    if _BETTER.search(text):
        return "better"
    if _RESOLVED.search(text):
        return "resolved"
    return None


def mentions(text: str) -> bool:
    """这段话（记忆、建议）说的是生病或身体不适。"""
    return any(p.search(text) for _, p, _ in SYMPTOMS) or bool(_GENERAL.search(text))


# ---- 每天的状态 ----------------------------------------------------------------------------


def refresh(ep: Episode, today: date) -> Episode:
    """连续 SILENT_DAYS 天没回答：不再追问，也不再当成现在的情况。"""
    if ep.active and (today - ep.last_touch()).days > SILENT_DAYS:
        return ep.model_copy(update={"status": "unconfirmed"})
    return ep


def end_of(ep: Episode, today: date) -> date:
    """这次生病算到哪天：好了的到好了那天；没确认的到系统不再问的前一天（那几天一直按生病处理）；
    还在进行的到今天。"""
    if ep.ended is not None:
        return ep.ended
    if refresh(ep, today).status == "unconfirmed":
        return ep.last_touch() + timedelta(days=SILENT_DAYS)
    return today


def active(eps: Sequence[Episode], today: date) -> list[Episode]:
    return [e for e in (refresh(x, today) for x in eps) if e.active]


def due(ep: Episode, today: date) -> bool:
    """今天要追问：从第二天起、今天还没回答。"""
    return refresh(ep, today).active and ep.started < today and not ep.answered(today)


def ago(day: date, today: date) -> str:
    n = max(0, (today - day).days)
    return {0: "今天", 1: "昨天", 2: "前天"}.get(n, f"{n} 天前")


def question(ep: Episode, today: date) -> str:
    return f"{ago(ep.started, today)}说{ep.what()}，今天好些了吗？"


def doctor(ep: Episode, today: date) -> str:
    """连续几次还不舒服、或发烧几天还没好：建议就医。"""
    unwell = 0
    for c in reversed(ep.checks):
        if c.answer != "unwell":
            break
        unwell += 1
    fever_days = (today - ep.started).days + 1 if ep.level == "fever" and ep.active else 0
    if unwell >= UNWELL_TIMES or fever_days > FEVER_DAYS:
        return f"{ep.what()}已经好几天了，建议去看医生；想先问问可以找康复恢复师。"
    return ""


def answer(
    ep: Episode, reply: Answer, today: date, *, hr_poor: bool = False
) -> tuple[Episode, str]:
    """按钮或文字回答：更新这次生病，返回给用户的一句话。"""
    checks = [c for c in ep.checks if c.day != today] + [Check(day=today, answer=reply)]
    if reply == "resolved":
        ep = ep.model_copy(update={"checks": checks, "status": "resolved", "ended": today,
                                   "light_until": today if hr_poor else None})  # fmt: skip
        if ep.level == "fever":
            return ep, "好的。发烧刚好，今天再休息一天，明天开始练，第一次按平时的七成。"
        if hr_poor:
            return (
                ep,
                "你说好了，但心率还没回到平时的水平，今天先按轻松版练；下次训练按平时的七成。",
            )
        return ep, "好的，恢复了就好。第一次回来按平时的七成练，下次再回到原计划。"
    status: Status = "better" if reply == "better" else "open"
    ep = ep.model_copy(update={"checks": checks, "status": status})
    hint = doctor(ep, today)
    if reply == "better":
        say = "好，今天按轻松版练，别练到力竭，明天再问你。"
    elif ep.level in ("above", "vague"):
        say = "那今天按轻松版练，或者只做拉伸、散步，明天再问你。"
    else:
        say = "那今天先休息，多喝水、早点睡，明天再问你。"
    return ep, "\n".join(x for x in (say, hint) if x)


def today_mode(
    eps: Sequence[Episode], today: date, *, trained_since: Collection[date] = ()
) -> tuple[Mode, str] | None:
    """今天的训练按生病情况怎么改：休息、轻松版，或病后第一次按约七成。trained_since：练过的日子。"""
    for ep in active(eps, today):
        when = ago(ep.started, today)
        if ep.status == "better":
            return "light", f"{when}说{ep.what()}，今天好一些了"
        if ep.level == "above":
            return "light", f"{when}说{ep.what()}（颈部以上的症状，可以降低强度活动）"
        if ep.level == "vague":  # §82：不由代码定休息
            return "light", (
                f"{when}说有点不舒服，没说哪里：他没问练什么就只关心一句、问哪里不舒服，不主动安排；"
                "问了再给轻松的"
            )
        return "rest", f"{when}说{ep.what()}，今天先休息"
    # 好了的、没确认的（不回答不等于好了，同样按病后第一次七成过渡）
    done = [e for e in (refresh(x, today) for x in eps) if e.status in ("resolved", "unconfirmed")]
    for ep in sorted(done, key=lambda e: end_of(e, today), reverse=True):
        end = end_of(ep, today)
        if ep.status == "resolved" and ep.level == "fever" and end == today:
            return "rest", "发烧刚好，再休息一天"
        if ep.light_until is not None and ep.light_until >= today:
            return "light", "你说好了，但心率还没回到平时的水平"
        if (today - end).days <= 14 and not any(d >= end for d in trained_since):
            return "ease", f"{ep.what()}刚好，病后第一次训练按平时的七成"
    return None


def sick_days(eps: Sequence[Episode], today: date) -> frozenset[date]:
    """生病期间的日子：开始到好了；没回答而不再追问的，到系统不再问的前一天。"""
    days: set[date] = set()
    for e in eps:
        end = end_of(e, today)
        days |= {e.started + timedelta(days=i) for i in range((end - e.started).days + 1)}
    return frozenset(days)


def recovering_days(eps: Sequence[Episode], today: date) -> frozenset[date]:
    """生病期间和好了之后 AFTER_DAYS 天：这些日子没做到的组次不触发自动减重量。"""
    days = set(sick_days(eps, today))
    for e in eps:
        if not refresh(e, today).active:
            end = end_of(e, today)
            days |= {end + timedelta(days=i) for i in range(1, AFTER_DAYS + 1)}
    return frozenset(days)


def recurring(eps: Sequence[Episode], today: date) -> int:
    """最近 4 周开始了几次生病（RECUR_TIMES 次以上要提示减量）。"""
    return sum(1 for e in eps if 0 <= (today - e.started).days < RECUR_DAYS)


async def trained(store: IllnessStore, user_id: str, day: date) -> bool:
    """生病期间打卡练了一次：当作已经好了，结束这次生病、不再追问（§46）。读写失败不影响打卡。"""
    try:
        eps = active(await store.since(user_id, day - timedelta(days=LOOKBACK)), day)
        for ep in eps:
            done, _ = answer(ep, "resolved", day)
            await store.save(user_id, done)
        return bool(eps)
    except Exception as e:
        _log.warning("illness update failed: error_type=%s", type(e).__name__)
        return False


def state_line(eps: Sequence[Episode], today: date) -> str:
    """交给所有角色的一句身体状态（生病还在进行时）。"""
    now = active(eps, today)
    if not now:
        return ""
    e = now[0]
    how = "好一些了" if e.status == "better" else "还没好"
    return f"{e.started.month} 月 {e.started.day} 日开始{e.what()}，现在{how}"


def summary_line(eps: Sequence[Episode], today: date, within: int = 2) -> str:
    """今日状态里的生病一行（spec [2026-10-23] §54）：交给模型，用相对的说法（"昨天说肚子疼"），
    不写日期、不写"现在还没好"这类判断，免得回答照着念（§82）；within 天内好了的写哪天好的。
    只是事实：今天怎么练由管家定（§163）。"""
    now = active(eps, today)
    if now:
        e = now[0]
        return f"生病：{ago(e.started, today)}说{e.what()}" + ("（没说哪里）" if e.level == "vague" else "") + (
            "，后来说好一些了" if e.status == "better" else ""
        )
    done = [e for e in eps if e.status == "resolved" and e.ended and (today - e.ended).days <= within]
    if not done:
        return ""
    e = max(done, key=lambda x: x.ended or x.started)
    return f"生病：{e.what()}{ago(e.ended or e.started, today)}好了"


def merge(eps: Sequence[Episode], symptoms: list[str], level: Level, today: date) -> Episode:
    """正在进行的那次生病里补上新症状；没有就新记一次。"""
    now = active(eps, today)
    if now:
        e = now[0]
        new = [s for s in symptoms if s not in e.symptoms and s != "身体不适"]
        top = max((e.level, level), key=_RANK.__getitem__)
        if e.level == "vague" and level != "vague":  # 补说了具体症状：按说的症状算（§82）
            top = level
        old = [x for x in e.symptoms if not (new and x == "身体不适")]
        return e.model_copy(update={"symptoms": [*old, *new] if new else e.symptoms,
                                    "level": top, "status": "open"})  # fmt: skip
    return Episode(symptoms=symptoms, level=level, started=today)


# ---- 存储 -----------------------------------------------------------------------------------


class IllnessStore(Protocol):
    async def since(self, user_id: str, start: date) -> list[Episode]: ...
    async def save(self, user_id: str, ep: Episode) -> None: ...


class IllnessBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Episode]] = {}

    async def since(self, user_id: str, start: date) -> list[Episode]:
        eps = self.rows.get(user_id, {}).values()
        return sorted(
            (e for e in eps if e.last_touch() >= start or e.active), key=lambda e: e.started
        )

    async def save(self, user_id: str, ep: Episode) -> None:
        self.rows.setdefault(user_id, {})[ep.id] = ep


DDL = """
CREATE TABLE IF NOT EXISTS ironm_illness (
    id         text PRIMARY KEY,
    user_id    text NOT NULL,
    content    text NOT NULL,
    started    date NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgIllness:
    """数据库版：内容用 mirobody 的加密函数加密。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL, "CREATE INDEX IF NOT EXISTS ironm_illness_user ON ironm_illness (user_id, started)")
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def since(self, user_id: str, start: date) -> list[Episode]:
        rows = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_illness"
            " WHERE user_id = :uid AND (started >= :start OR updated_at >= :start) ORDER BY started",
            {"uid": user_id, "start": start - timedelta(days=SILENT_DAYS + 1)},
        )
        return [Episode.model_validate_json(r["content"]) for r in rows]

    async def save(self, user_id: str, ep: Episode) -> None:
        await self._q(
            "INSERT INTO ironm_illness (id, user_id, content, started)"
            " VALUES (:id, :uid, encrypt_content(:c), :started)"
            " ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content, updated_at = now()",
            {"id": ep.id, "uid": user_id, "c": ep.model_dump_json(), "started": ep.started},
        )
        _log.info("illness saved: level=%s status=%s", ep.level, ep.status)


_default: IllnessStore | None = None


def default_illness() -> IllnessStore:
    global _default
    if _default is None:
        _default = PgIllness()
    return _default


LOOKBACK = 63  # 读多久的生病记录（平台期要看 9 周以内、反复生病看 4 周）


async def recent(store: IllnessStore, user_id: str, today: date) -> list[Episode]:
    """读最近的生病记录；读不到时当作没有（不影响作答和页面）。"""
    try:
        return await store.since(user_id, today - timedelta(days=LOOKBACK))
    except Exception as e:
        _log.warning("illness unavailable: error_type=%s", type(e).__name__)
        return []
