"""模型、关键字、语义向量三路打分路由（spec [2026-10-23] §16，先测再换，还没接进作答链路）。

每一路给 5 个专业角色各打一个 0–1 的分，按 7:2:1 加权：
- 模型：只做分类打分（问题类型 + 每个角色的相关程度），不安排任务；
- 关键字：各角色关键词库上的 BM25（中文取单字和相邻两字），加常见句式的命中；按最高分归一；
- 语义向量：本机中文小模型（bge-small-zh）算问题与各角色例句的最高相似度；按各角色之间的高低归一。
取加权最高的为主责；其他角色得分不低于 0.6、且与最高分相差不超过 0.2 的一起请，人数不设上限。
某一路不可用时，其余几路按原来的比例重新分配权重。
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, NamedTuple

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.roles import EXPERTS, SPECS, Role
from ironm_agent.router import concerns_of
from ironm_agent.skills import catalog, valid_for
from ironm_agent.yamlfile import load_yaml

_log = logging.getLogger("ironm_agent.routing")

EXAMPLES_PATH = Path(__file__).with_name("route_examples.yaml")
MODEL_DIR = Path(__file__).resolve().parents[1] / "data" / "models"  # 本机模型文件，不进仓库
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"

type Channel = Literal["llm", "keyword", "vector"]
type Intent = Literal["pro", "chat", "app", "out_of_scope"]
WEIGHTS: dict[str, float] = {"llm": 0.7, "keyword": 0.2, "vector": 0.1}
JOIN_MIN = 0.6  # 其他角色得分不低于这个才一起请
JOIN_GAP = 0.2  # 并且和最高分相差不超过这个
PATTERN_BONUS = 2.0  # 命中一个句式，相当于 BM25 里多少分
CHAT_MAX = 12  # 闲聊的话一般很短；长句里带个"谢谢"仍按专业问题
NAMES = [r.value for r in EXPERTS]


class RoleExamples(ContractModel):
    keywords: tuple[str, ...] = Field(min_length=1)
    patterns: tuple[str, ...] = ()
    examples: tuple[str, ...] = Field(min_length=1)


class ExampleFile(ContractModel):
    version: str
    review: str
    roles: dict[str, RoleExamples]
    intents: dict[str, tuple[str, ...]]


@cache
def examples(path: Path = EXAMPLES_PATH) -> ExampleFile:
    out = ExampleFile.model_validate(load_yaml(path), strict=False)
    if set(out.roles) != set(NAMES):
        raise ValueError(f"例句库的角色对不上：{sorted(set(out.roles) ^ set(NAMES))}")
    return out


# ---- 关键字：BM25 -----------------------------------------------------------------------------

_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]+")


def tokens(text: str) -> list[str]:
    """中文取单字和相邻两字，英文和数字按词。"""
    out: list[str] = []
    for t in _TOKEN.findall(text.lower()):
        if "一" <= t[0] <= "鿿":
            out.extend(t)
            out.extend(a + b for a, b in pairwise(t))
        else:
            out.append(t)
    return out


@dataclass
class KeywordScorer:
    """每个角色的关键词合成一篇"文档"；每个关键词单独切词，不让两个词拼出不存在的组合。"""

    k1: float = 1.2
    b: float = 0.75
    docs: dict[str, Counter[str]] = field(default_factory=dict)
    patterns: dict[str, list[re.Pattern[str]]] = field(default_factory=dict)

    @classmethod
    def build(cls, lib: ExampleFile | None = None) -> KeywordScorer:
        lib = lib or examples()
        s = cls()
        for name, r in lib.roles.items():
            bag: Counter[str] = Counter()
            for kw in r.keywords:
                bag.update(set(tokens(kw)))
            s.docs[name] = bag
            s.patterns[name] = [re.compile(p) for p in r.patterns]
        return s

    def raw(self, text: str) -> dict[str, float]:
        q = set(tokens(text))
        n = len(self.docs)
        avg = sum(sum(d.values()) for d in self.docs.values()) / n
        out: dict[str, float] = {}
        for name, d in self.docs.items():
            length = sum(d.values())
            score = 0.0
            for t in q:
                tf = d.get(t, 0)
                if not tf:
                    continue
                df = sum(1 for other in self.docs.values() if t in other)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                score += (
                    idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / avg))
                )
            score += PATTERN_BONUS * sum(1 for p in self.patterns[name] if p.search(text))
            out[name] = score
        return out

    def scores(self, text: str) -> dict[str, float]:
        return _by_max(self.raw(text))


def _by_max(raw: Mapping[str, float]) -> dict[str, float]:
    top = max(raw.values(), default=0.0)
    return {k: (v / top if top > 0 else 0.0) for k, v in raw.items()}


def keyword_intent(text: str, lib: ExampleFile | None = None) -> Intent | None:
    """模型不可用时，关键字对问题类型的判断：命中超出范围、App 用法的词；或者很短的一句闲聊。"""
    lib = lib or examples()
    lowered = text.lower().replace(" ", "")
    found: Intent
    for found in ("out_of_scope", "app", "chat"):
        hit = any(w.lower() in lowered for w in lib.intents.get(found, ()))
        if hit and (found != "chat" or len(lowered) <= CHAT_MAX):
            return found
    return None


# ---- 语义向量：本机中文小模型 ------------------------------------------------------------------


class VectorScorer:
    """例句的向量在第一次用到时算好；之后每轮只算问题的向量。"""

    def __init__(self, lib: ExampleFile | None = None, model: Any = None) -> None:
        self.lib = lib or examples()
        self._model = model
        self._matrix: Any = None
        self._owner: list[str] = []
        self._cands: dict[tuple[str, ...], Any] = {}

    def _load(self) -> None:
        if self._matrix is not None:
            return
        import numpy as np

        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(EMBED_MODEL, cache_dir=str(MODEL_DIR))
        texts: list[str] = []
        for name, r in self.lib.roles.items():
            texts += list(r.examples)
            self._owner += [name] * len(r.examples)
        m = np.array(list(self._model.embed(texts)), dtype="float32")
        self._matrix = m / np.linalg.norm(m, axis=1, keepdims=True)

    def raw(self, text: str) -> dict[str, float]:
        import numpy as np

        self._load()
        v = np.array(next(iter(self._model.embed([text]))), dtype="float32")
        sims = self._matrix @ (v / np.linalg.norm(v))
        out = dict.fromkeys(self.lib.roles, -1.0)
        for name, sim in zip(self._owner, sims.tolist(), strict=True):
            out[name] = max(out[name], float(sim))
        return out

    def similar(self, text: str, candidates: Sequence[str]) -> list[float]:
        """问题和几段文字各自的相似度（Skill 选择的兜底用，spec [2026-10-23] §20）；候选文字的向量算一次后记住。"""
        import numpy as np

        self._load()
        key = tuple(candidates)
        if key not in self._cands:
            m = np.array(list(self._model.embed(list(key))), dtype="float32")
            self._cands[key] = m / np.linalg.norm(m, axis=1, keepdims=True)
        v = np.array(next(iter(self._model.embed([text]))), dtype="float32")
        return [float(x) for x in (self._cands[key] @ (v / np.linalg.norm(v))).tolist()]

    def scores(self, text: str) -> dict[str, float]:
        """各角色之间按高低归一：最像的 1，最不像的 0。"""
        raw = self.raw(text)
        lo, hi = min(raw.values()), max(raw.values())
        return {k: ((v - lo) / (hi - lo) if hi > lo else 0.0) for k, v in raw.items()}


# ---- 模型：只做分类打分 ------------------------------------------------------------------------

_PROMPT = """你是健身 App "AI 健身管家"的问题分类器。只做分类，不回答问题。

专业角色：
{roles}

请判断：
1. intent：pro（训练、动作、饮食、恢复、身体数据、健康安全相关的专业问题）、chat（打招呼、闲聊、道谢）、app（问 App 怎么用、你是谁、用的什么模型）、out_of_scope（与健身健康无关）。拿不准时选 pro。
2. scores：每个专业角色和这个问题的相关程度，0 到 1 之间：最该负责的接近 1；问题明确涉及它的领域就给 0.6 以上；只是沾边给 0.3 以下；无关给 0。
   - 问到"我的"数据时按领域给分：体重、体脂给 nutrition；睡眠、心率、心率变异性、血压给 recovery；步数、力量进步给 trainer。
   - 身体正疼、受伤、生病时，recovery 给 0.6 以上。
3. skills：给分 0.6 以上的角色，从下面它能用的规程里选这一轮要用的（最多 2 个，写编号）；问题简单、规程用不上（比如问一个名词是什么意思、只查一个数），给空列表 []。问他自己的化验、体检或测量数据（高不高、正常吗、怎么样）时，选三个角色都能用的数据规程（data-labs 化验指标、data-trend 趋势、data-missing 没数据），不要选伤痛、伤后回归或训练安排类的规程。

各角色能用的规程（编号 名字：什么时候用（不用于：容易混的情况该用哪个））：
{skills}

最近的对话（用于理解指代，可能为空）：
{history}

{persona}

只输出 JSON：{{"intent": "pro", "scores": {{{keys}}}, "skills": {{"角色代号": ["规程编号"]}}}}"""


class LLMResult(NamedTuple):
    intent: Intent
    scores: dict[str, float]
    skills: dict[str, tuple[str, ...]]  # 角色 → 路由选的规程编号（空表示不装；没写的角色由规则选）


async def llm_scores(
    text: str, llm: LLM, history: Sequence[str] = (), persona: str = ""
) -> LLMResult | None:
    """persona：这个人的画像（有效记忆排成的清单），帮助判断，比如有伤病时恢复更相关。"""
    roles = "\n".join(f"- {r.value}：{SPECS[r].name}，{SPECS[r].duty}" for r in EXPERTS)
    prompt = _PROMPT.format(
        roles=roles,
        history="\n".join(history[-6:]) or "（无）",
        keys=", ".join(f'"{n}": 0' for n in NAMES),
        skills=catalog(),
        persona=(persona + "\n（只用来判断该请谁）") if persona else "",
    )
    try:
        reply = await llm.chat(
            "route",
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            json_mode=True,
        )
    except ModelUnavailable:
        return None
    raw = parse_json(reply.content) or {}
    intent = raw.get("intent")
    scores = raw.get("scores")
    if intent not in ("pro", "chat", "app", "out_of_scope") or not isinstance(scores, dict):
        return None
    out: dict[str, float] = {}
    for n in NAMES:
        v = scores.get(n, 0)
        out[n] = min(1.0, max(0.0, float(v))) if isinstance(v, int | float) else 0.0
    picked = raw.get("skills")
    chosen: dict[str, tuple[str, ...]] = {}
    if isinstance(picked, dict):
        for n in NAMES:
            ids = picked.get(n)
            if isinstance(ids, list):
                chosen[n] = valid_for(Role(n), ids)
    return LLMResult(intent, out, chosen)


# ---- 合在一起 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    intent: Intent
    roles: tuple[Role, ...] = ()  # 主责在前；康复恢复师排在训练教练之前
    weighted: dict[str, float] = field(default_factory=dict)
    channels: dict[str, dict[str, float]] = field(
        default_factory=dict
    )  # 各路的分（不可用的不在里面）
    weights: dict[str, float] = field(default_factory=dict)  # 实际用的权重
    concerns: tuple[str, ...] = ()
    skills: dict[str, tuple[str, ...]] = field(default_factory=dict)  # 请到的角色里路由选了规程的

    @property
    def primary(self) -> Role | None:
        return self.roles[0] if self.roles else None

    def log(self) -> dict[str, Any]:
        """运行记录：各路的分和加权结果，不含用户原话。"""
        return {
            "intent": self.intent,
            "roles": [r.value for r in self.roles],
            "weights": self.weights,
            "weighted": {k: round(v, 2) for k, v in self.weighted.items()},
            "channels": {
                c: {k: round(v, 2) for k, v in s.items()} for c, s in self.channels.items()
            },
            "skills": {k: list(v) for k, v in self.skills.items()},
        }


def combine(
    text: str,
    *,
    llm: LLMResult | tuple[Intent, Mapping[str, float]] | None,
    keyword: Mapping[str, float] | None,
    vector: Mapping[str, float] | None,
) -> Decision:
    channels: dict[str, dict[str, float]] = {}
    if llm is not None:
        channels["llm"] = dict(llm[1])
    if keyword is not None:
        channels["keyword"] = dict(keyword)
    if vector is not None:
        channels["vector"] = dict(vector)
    total = sum(WEIGHTS[c] for c in channels)
    weights: dict[str, float] = {c: WEIGHTS[c] / total for c in channels} if total else {}
    concerns = concerns_of(text.lower().replace(" ", ""))
    intent: Intent = llm[0] if llm is not None else keyword_intent(text) or "pro"
    if concerns:
        intent = "pro"  # 提到身体不适或特殊人群，一律按专业问题处理
    weighted: dict[str, float] = {
        n: sum((weights[c] * s.get(n, 0.0) for c, s in channels.items()), 0.0) for n in NAMES
    }
    if intent != "pro":
        return Decision(intent, (), weighted, channels, weights, concerns)
    ranked = sorted(NAMES, key=lambda n: (-weighted[n], NAMES.index(n)))
    top = weighted[ranked[0]]
    if top <= 0:  # 哪一路都没打出分（比如几路都不可用）：不硬选，交给调用方兜底
        return Decision(intent, (), weighted, channels, weights, concerns)
    chosen = [ranked[0]] + [
        n for n in ranked[1:] if weighted[n] >= JOIN_MIN and top - weighted[n] <= JOIN_GAP
    ]
    if "discomfort" in concerns and Role.RECOVERY.value not in chosen:
        chosen.append(Role.RECOVERY.value)  # 身体正不舒服时一定请康复恢复师
    roles: list[Role] = [Role(n) for n in chosen]
    if Role.RECOVERY in roles and Role.TRAINER in roles:  # 康复恢复师排在训练教练之前（主责不动）
        rest: list[Role] = [r for r in roles[1:] if r is not Role.RECOVERY]
        if roles[0] is not Role.RECOVERY:
            at = rest.index(Role.TRAINER) if Role.TRAINER in rest else len(rest)
            rest.insert(at, Role.RECOVERY)
        roles = [roles[0], *rest]
    picked = llm.skills if isinstance(llm, LLMResult) else {}
    skills: dict[str, tuple[str, ...]] = {}  # 路由选了规程的角色（§21）
    for r in roles:
        if r.value in picked:
            skills[r.value] = picked[r.value]
    return Decision(intent, tuple(roles), weighted, channels, weights, concerns, skills)


@dataclass
class Router:
    """三路打分路由；关键字和向量两路的打分器只建一次。哪一路是 None，那一路就不参加。"""

    keyword: KeywordScorer | None = field(default_factory=KeywordScorer.build)
    vector: VectorScorer | None = field(default_factory=VectorScorer)

    def vector_scores(self, text: str) -> dict[str, float] | None:
        if self.vector is None:
            return None
        try:
            return self.vector.scores(text)
        except Exception as e:  # 本机模型不可用时这一路不参加
            _log.warning("vector channel unavailable: error_type=%s", type(e).__name__)
            return None

    def similar(self, text: str, candidates: Sequence[str]) -> list[float] | None:
        if self.vector is None:
            return None
        try:
            return self.vector.similar(text, candidates)
        except Exception as e:  # 本机模型不可用时不用这个兜底
            _log.warning("skill similarity unavailable: error_type=%s", type(e).__name__)
            return None

    def warm(self) -> None:
        """提前载入本机模型并算好例句的向量（启动时在后台调用），第一位用户不用等。"""
        self.vector_scores("热身")

    async def route(
        self, text: str, llm: LLM | None, history: Sequence[str] = (), persona: str = ""
    ) -> Decision:
        """模型这一路和本机的两路同时进行。"""
        asked = asyncio.create_task(llm_scores(text, llm, history, persona)) if llm else None
        keyword = self.keyword.scores(text) if self.keyword is not None else None
        vector = await asyncio.to_thread(self.vector_scores, text)
        found = await asked if asked is not None else None
        return combine(text, llm=found, keyword=keyword, vector=vector)


@cache
def default_router() -> Router:
    return Router()
