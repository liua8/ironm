"""依据库：自建的资料条目与检索。只收公开可得的资料，摘要与要点用自己的话写。"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.yamlfile import load_yaml

KB_PATH = Path(__file__).with_name("kb.yaml")

type Level = Literal[
    "guideline",
    "position_stand",
    "systematic_review",
    "consensus",
    "review",
    "textbook",
    "health_info",
]

# 证据等级从高到低：指南与立场声明 > 系统综述 > 专家共识、综述、教材、权威机构的健康科普
LEVEL_NAMES: dict[str, str] = {
    "guideline": "指南",
    "position_stand": "立场声明",
    "systematic_review": "系统综述与荟萃分析",
    "consensus": "专家共识",
    "review": "综述",
    "textbook": "教材",
    "health_info": "权威机构健康科普",
}

DOMAINS = frozenset({"training", "exercise", "nutrition", "recovery", "safety", "data"})


class Point(ContractModel):
    text: Annotated[str, Field(min_length=1)]  # 一句可以核对的陈述
    where: Annotated[str, Field(min_length=1)]  # 在原文中的位置


class Entry(ContractModel):
    id: Annotated[str, Field(pattern=r"^K\d{2,3}$")]
    domains: tuple[str, ...] = Field(min_length=1)
    title: str
    source: str  # 资料名称
    publisher: str
    year: int
    level: Level
    population: str  # 适用人群
    summary: str  # 用自己的话写的摘要
    points: tuple[Point, ...] = Field(min_length=1)
    keywords: tuple[str, ...] = ()
    url: str | None = None
    review: Literal["approved", "claude_draft"]

    def cite_label(self) -> str:
        """回答末尾“依据”里的一行。"""
        return f"〔{self.id}〕{self.title}：{self.source}（{self.publisher}，{self.year}，{LEVEL_NAMES[self.level]}）"

    def as_evidence(self) -> str:
        """交给 Agent 看的样子。"""
        points = "\n".join(f"- {p.text}" for p in self.points)
        return f"[{self.id}] {self.title}\n来源：{self.cite_label()}；适用：{self.population}\n{self.summary}\n要点：\n{points}"

    def text(self) -> str:
        return " ".join([self.title, self.summary, *(p.text for p in self.points), *self.keywords])


class KbFile(ContractModel):
    version: str
    entries: tuple[Entry, ...] = Field(min_length=1)


_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]")


# 单字检索时不算的常用字（虚词、代词）
_STOP = frozenset("我你他她它的了吗呢吧啊么怎什是有在和与或也都就还要会能可这那个些么一不没很太最")


def _grams(text: str) -> list[str]:
    """中文按相邻两字、英文与数字按词切分。"""
    tokens = _TOKEN.findall(text.lower())
    out: list[str] = [t for t in tokens if not ("一" <= t <= "鿿")]
    han = [t for t in tokens if "一" <= t <= "鿿"]
    out.extend(a + b for a, b in pairwise(han))
    return out


def _chars(text: str) -> set[str]:
    """中文单字（去掉常用虚词），用于两字切分匹配不上时兜底。"""
    return {t for t in _TOKEN.findall(text.lower()) if "一" <= t <= "鿿" and t not in _STOP}


@dataclass(frozen=True)
class KnowledgeBase:
    entries: tuple[Entry, ...]

    @classmethod
    def load(cls, path: Path = KB_PATH) -> KnowledgeBase:
        data = KbFile.model_validate(load_yaml(path), strict=False)
        ids = [e.id for e in data.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("依据库编号重复")
        bad = {d for e in data.entries for d in e.domains} - DOMAINS
        if bad:
            raise ValueError(f"未知的领域：{sorted(bad)}")
        return cls(data.entries)

    def get(self, entry_id: str) -> Entry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    def search(self, query: str, domains: Iterable[str], k: int = 4) -> list[Entry]:
        """在给定领域里按词重叠打分（稀有的词分高），返回得分最高的几条。"""
        allowed = set(domains)
        pool = [e for e in self.entries if allowed.intersection(e.domains)]
        if not pool:
            return []
        docs = {e.id: Counter(_grams(e.text())) for e in pool}
        chars = {e.id: _chars(e.text()) for e in pool}
        df = Counter(g for c in docs.values() for g in c)
        cdf = Counter(ch for s in chars.values() for ch in s)
        q, qc = set(_grams(query)), _chars(query)
        n = len(pool)
        scored = []
        for e in pool:
            c = docs[e.id]
            score = sum(math.log(1 + n / df[g]) for g in q if c[g])
            # 单字权重低：只在两字切分没对上时起作用（"睡得不好"对上"睡眠"）
            score += 0.3 * sum(math.log(1 + n / cdf[ch]) for ch in qc if ch in chars[e.id])
            score += sum(2.0 for kw in e.keywords if kw.lower() in query.lower())
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda x: (-x[0], x[1].id))
        return [e for _, e in scored[:k]]


@cache
def default_kb() -> KnowledgeBase:
    return KnowledgeBase.load()
