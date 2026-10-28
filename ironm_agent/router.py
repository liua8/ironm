"""调度用的公共部分（Route、身体不适与特殊人群的判断、按关键词调度）。

作答链路已改用 routing.py 的三路打分路由（spec [2026-10-23] §16）；这里的 route() 只留给路由测评做对照（原来的主教练调度）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.roles import EXPERTS, SPECS, Role

type Intent = Literal["chat", "app", "pro", "out_of_scope"]
type Concern = Literal["discomfort", "special"]

MAX_HELPERS = 2

# 提到这些说法时，一律按专业问题处理
_DISCOMFORT = (
    "疼",
    "痛",
    "不舒服",
    "受伤",
    "扭",
    "麻",
    "肿",
    "头晕",
    "恶心",
    "喘不上",
    "心慌",
    "抽筋",
)
_SPECIAL = ("怀孕", "孕", "产后", "哺乳", "高血压", "糖尿病", "心脏", "肾", "未成年", "岁的孩子", "老人",
            "哮喘", "手术", "吃药", "服药")  # fmt: skip
_APP_WORDS = ("怎么用", "这个app", "这个应用", "你能做什么", "你是谁", "功能")
_CHAT_WORDS = ("你好", "您好", "谢谢", "早上好", "晚上好", "哈哈", "再见", "在吗")


class Route(ContractModel):
    intent: Intent
    concerns: tuple[Concern, ...] = ()
    primary: Role | None = None
    helpers: tuple[Role, ...] = ()
    reason: str = ""
    by: Literal["model", "keywords", "rule", "weighted"]
    problems: tuple[str, ...] = ()  # 模型方案没通过的原因（改按关键词时记下）
    # 路由给角色选的规程（spec [2026-10-23] §21）；没写的角色按规则选
    skills: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    unsure: str = ""  # 路由没把握，给了管家的原因：follow_up / disagree（§56）

    def experts(self) -> tuple[Role, ...]:
        """这一轮要请的专业 Agent：主责与辅助；康复恢复师排在训练教练之前。"""
        if self.intent != "pro" or self.primary is None:
            return ()
        roles = [self.primary, *self.helpers]
        if Role.RECOVERY in roles and Role.TRAINER in roles:
            roles.remove(Role.RECOVERY)
            roles.insert(roles.index(Role.TRAINER), Role.RECOVERY)
        return tuple(roles)


def concerns_of(text: str) -> tuple[Concern, ...]:
    out: list[Concern] = []
    if any(w in text for w in _DISCOMFORT):
        out.append("discomfort")
    if any(w in text for w in _SPECIAL):
        out.append("special")
    return tuple(out)


def keyword_route(text: str, problems: Sequence[str] = ()) -> Route:
    """按关键词打分调度：命中最多的为主责，其次的最多两个为辅助。"""
    lowered = text.lower().replace(" ", "")
    concerns = concerns_of(lowered)
    scores = {r: sum(1 for w in SPECS[r].keywords if w in lowered) for r in EXPERTS}
    ranked = sorted(
        (r for r in EXPERTS if scores[r] > 0), key=lambda r: (-scores[r], EXPERTS.index(r))
    )
    if not ranked and not concerns:
        if any(w in lowered for w in _APP_WORDS):
            return Route(intent="app", by="keywords", problems=tuple(problems))
        if any(w in lowered for w in _CHAT_WORDS) and len(lowered) <= 12:
            return Route(intent="chat", by="keywords", problems=tuple(problems))
    if not ranked:
        ranked = [Role.RECOVERY if concerns else Role.TRAINER]
    return Route(
        intent="pro",
        concerns=concerns,
        primary=ranked[0],
        helpers=tuple(ranked[1 : 1 + MAX_HELPERS]),
        reason="按问题里的关键词选择",
        by="keywords",
        problems=tuple(problems),
    )


def validate(raw: dict[str, object], text: str) -> tuple[Route | None, list[str]]:
    """检查模型给出的调度方案；返回方案与问题清单（有问题时方案为 None）。"""
    problems: list[str] = []
    intent = raw.get("intent")
    if intent not in ("chat", "app", "pro", "out_of_scope"):
        return None, [f"未知的问题类型：{intent!r}"]
    concerns = tuple(dict.fromkeys([*concerns_of(text), *_concerns(raw.get("concerns"))]))
    if concerns and intent != "pro":
        intent = "pro"  # 提到身体不适或特殊人群，一律按专业问题处理
    if intent != "pro":
        return Route(
            intent=intent, concerns=concerns, reason=str(raw.get("reason", "")), by="model"
        ), []
    names = {r.value for r in EXPERTS}
    primary = raw.get("primary")
    helpers_raw = raw.get("helpers") or []
    if not isinstance(helpers_raw, list):
        helpers_raw = []
    if primary not in names:
        problems.append(f"主责不在名单里：{primary!r}")
    bad = [h for h in helpers_raw if h not in names]
    if bad:
        problems.append(f"辅助不在名单里：{bad}")
    if len(helpers_raw) > MAX_HELPERS:
        problems.append(f"辅助超过 {MAX_HELPERS} 个")
    if problems:
        return None, problems
    helpers = tuple(dict.fromkeys(Role(h) for h in helpers_raw if h != primary))
    return (
        Route(
            intent="pro",
            concerns=concerns,
            primary=Role(str(primary)),
            helpers=helpers,
            reason=str(raw.get("reason", "")),
            by="model",
        ),
        [],
    )


def _concerns(value: object) -> list[Concern]:
    if not isinstance(value, list):
        return []
    return [c for c in ("discomfort", "special") if c in value]


_PROMPT = """你是健身 App 的主教练，负责理解用户的问题，并决定请哪些专业角色来回答。

专业角色（只能从这里选，用英文代号）：
{roles}

请判断：
1. intent：chat（打招呼、闲聊、鼓励）、app（问 App 怎么用、你能做什么）、pro（训练、动作、饮食、恢复、身体数据、健康安全相关的专业问题）、out_of_scope（与健身健康无关）。拿不准时选 pro。
2. concerns：这句话是否涉及 discomfort（身体不适、疼痛、受伤）或 special（怀孕、慢病、用药、未成年、老人等特殊人群），可以为空列表。
3. intent 为 pro 时：primary 选 1 个最该负责的角色；helpers 只在问题明确跨到另一个领域时才加（比如同时问训练和饮食），一般为空，最多 2 个——每多请一位，用户就要多等。
   - 身体正不舒服、正疼、生病的问题，primary 或 helpers 里要有 recovery；
   - 问到"我的"数据时按领域选：体重、体脂选 nutrition；睡眠、心率、心率变异性、血压选 recovery；步数、力量进步选 trainer；
   - 这个人的伤病史、今天的身体状态、器械和时间，系统已经整理成档案交给每位角色，不需要为此多请 recovery；
   - 安排训练、排计划、动作怎么做、替代动作都由 trainer 负责。
4. reason：一句话说明理由。

最近的对话（用于理解指代，可能为空）：
{history}

{persona}

只输出 JSON：{{"intent": "...", "concerns": [], "primary": "...", "helpers": [], "reason": "..."}}"""


async def route(text: str, history: Sequence[str], llm: LLM, persona: str = "") -> Route:
    """persona：这个人的画像（长期记忆排成的清单），帮助判断该请谁，比如有伤病时请康复恢复师。"""
    roles = "\n".join(f"- {r.value}：{SPECS[r].name}，{SPECS[r].duty}" for r in EXPERTS)
    prompt = _PROMPT.format(
        roles=roles,
        history="\n".join(history[-6:]) or "（无）",
        persona=(persona + "\n（只用来理解他的问题；这些情况各角色都看得到）") if persona else "",
    )
    try:
        reply = await llm.chat(
            "route",
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            json_mode=True,
        )
    except ModelUnavailable as e:
        return keyword_route(text, [f"模型不可用：{e}"])
    raw = parse_json(reply.content)
    if raw is None:
        return keyword_route(text, ["调度结果不是 JSON"])
    result, problems = validate(raw, text)
    return result if result is not None else keyword_route(text, problems)
