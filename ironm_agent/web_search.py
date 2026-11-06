"""联网搜索（spec [2026-10-23] §91）：知识库查不到、又需要一个具体的数或结论时，由管家自己决定按白名单联网查。

搜索服务用 Tavily（能限定域名），密钥在环境变量 TAVILY_API_KEY；没配密钥时不给管家这个工具。
只留白名单机构的结果；每条编成 K8001 这样的编号，和知识库条目一样引用、一样核对数字，
但标成"联网资料，未审"，不写进知识库。查询词和网址加密记下来，同类查询多了列进待审清单。
日志只记查了几次、几条、是否出错，不记查询词。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import date
from typing import Any, Protocol
from urllib.parse import urlparse

from ironm_agent.ddl import run_ddl
from ironm_agent.kb import Entry, Point

_log = logging.getLogger("ironm_agent.web_search")

KEY_ENV = "TAVILY_API_KEY"
URL = "https://api.tavily.com/search"
TIMEOUT_S = 10.0
MAX_CALLS = 2  # 每轮最多查几次
MAX_HITS = 5  # 每次最多几条
FIRST_ID = 8001  # 联网资料的编号从 K8001 起（知识库 K01–K116，动作库 K901 起）
REVIEW_TIMES = 2  # 同类查询查到几次进待审清单

# 白名单：域名 → 机构（子域名也算）
WHITELIST: dict[str, str] = {
    "acsm.org": "美国运动医学会（ACSM）",
    "who.int": "世界卫生组织（WHO）",
    "cdc.gov": "美国疾病控制与预防中心（CDC）",
    "nsca.com": "美国国家体能协会（NSCA）",
    "heart.org": "美国心脏协会",
    "nhs.uk": "英国国家医疗服务体系（NHS）",
    "medlineplus.gov": "MedlinePlus（美国国家医学图书馆）",
    "ods.od.nih.gov": "美国 NIH 膳食补充剂办公室",
    "cnsoc.org": "中国营养学会",
    "nhc.gov.cn": "国家卫生健康委员会",
    "chinacdc.cn": "中国疾病预防控制中心",
    "pubmed.ncbi.nlm.nih.gov": "PubMed",
    "pmc.ncbi.nlm.nih.gov": "PubMed Central",
    "europepmc.org": "Europe PMC",
    "cochranelibrary.com": "Cochrane 图书馆",
}

SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "联网查权威机构和论文库（ACSM、WHO、NSCA、中国营养学会、PubMed 等白名单）。只在知识库里查不到合适的条目、"
            "这个问题又需要一个具体的数或结论时用；问他自己的数据、闲聊、App 用法不要用。每轮最多 2 次。"
            "返回带编号（如 K8001）的条目，引用和知识库一样写编号，数字照原文片段写。"
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查的事，中英文都行（英文论文库更全）；不写他的名字、数据和病情细节",
                }
            },
            "required": ["query"],
        },
    },
}

type Search = Callable[[str], Awaitable[list[dict[str, Any]]]]


def org_of(url: str) -> str | None:
    """网址属于白名单里的哪个机构；不在白名单返回 None。"""
    host = (urlparse(url).hostname or "").lower()
    for domain, org in WHITELIST.items():
        if host == domain or host.endswith("." + domain):
            return org
    return None


class WebEntry(Entry):
    """一条联网查到的资料：和知识库条目一样引用、核对，但标明未审、带网址。"""

    def cite_label(self) -> str:
        year = f"，{self.year}" if self.year else ""
        return f"〔{self.id}〕{self.title}：{self.publisher}{year}，联网资料（未审），{self.url}"

    def as_evidence(self) -> str:
        points = "\n".join(f"- {p.text}" for p in self.points)
        return f"[{self.id}] {self.title}\n来源：{self.publisher}（联网资料，未审）{self.url}\n原文片段：\n{points}"


_SENT = re.compile(r"[^。！？.!?\n]+[。！？.!?]?")


def _year(hit: Mapping[str, Any]) -> int:
    found = re.search(r"(19|20)\d{2}", str(hit.get("published_date") or ""))
    return int(found.group(0)) if found else 0


def to_entries(hits: Sequence[Mapping[str, Any]], start: int) -> list[WebEntry]:
    """搜索结果 → 编好号的条目；不在白名单的、没有正文的丢掉。"""
    out: list[WebEntry] = []
    for hit in hits:
        url = str(hit.get("url") or "")
        org = org_of(url)
        text = " ".join(str(hit.get("content") or "").split())
        if org is None or not text:
            continue
        points = [s.strip() for s in _SENT.findall(text[:900]) if len(s.strip()) > 8][:4]
        if not points:
            continue
        out.append(WebEntry(
            id=f"K{start + len(out)}", domains=("training",), title=str(hit.get("title") or org)[:80],
            source=url, publisher=org, year=_year(hit), level="web", population="未注明",
            summary=points[0], points=tuple(Point(text=p, where=url) for p in points),
            url=url, review="web",
        ))  # fmt: skip
        if len(out) >= MAX_HITS:
            break
    return out


async def tavily(query: str, key: str) -> list[dict[str, Any]]:
    """Tavily 搜索，限定在白名单域名里。"""
    import httpx

    body = {"query": query, "search_depth": "basic", "max_results": MAX_HITS,
            "include_domains": list(WHITELIST), "include_answer": False}  # fmt: skip
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        data = r.json()
    hits = data.get("results") if isinstance(data, dict) else None
    return [x for x in hits or [] if isinstance(x, dict)]


# ---- 待审清单 -------------------------------------------------------------------------------


def norm(query: str) -> str:
    """同一类查询：去掉空白和标点、英文小写。"""
    return re.sub(r"[\W_]+", "", query.lower())


class WebLog(Protocol):
    async def add(self, query: str, urls: Sequence[str], day: date) -> None: ...
    async def rows(self) -> list[dict[str, Any]]: ...


class WebBook:
    """内存版（测试用）。"""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    async def add(self, query: str, urls: Sequence[str], day: date) -> None:
        self.items.append({"query": query, "urls": list(urls), "day": day.isoformat()})

    async def rows(self) -> list[dict[str, Any]]:
        return list(self.items)


DDL = """
CREATE TABLE IF NOT EXISTS ironm_web_search (
    id         text PRIMARY KEY,
    content    text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


class PgWebLog:
    """数据库版：查询词和网址加密后存；不记是谁查的。"""

    def __init__(self) -> None:
        self._ready = False

    async def _q(self, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        from mirobody.utils.db import execute_query

        if not self._ready:
            await run_ddl(DDL)
            self._ready = True
        rows = await execute_query(sql, params, log_sql=False)
        return rows if isinstance(rows, list) else []

    async def add(self, query: str, urls: Sequence[str], day: date) -> None:
        import json

        content = json.dumps({"query": query, "urls": list(urls), "day": day.isoformat()},
                             ensure_ascii=False)  # fmt: skip
        await self._q(
            "INSERT INTO ironm_web_search (id, content) VALUES (:id, encrypt_content(:c))",
            {"id": uuid.uuid4().hex[:16], "c": content},
        )

    async def rows(self) -> list[dict[str, Any]]:
        import json

        got = await self._q(
            "SELECT decrypt_content(content) AS content FROM ironm_web_search ORDER BY created_at",
            {},
        )
        return [json.loads(r["content"]) for r in got]


_default: WebLog | None = None


def default_log() -> WebLog:
    global _default
    if _default is None:
        _default = PgWebLog()
    return _default


async def pending(log: WebLog, times: int = REVIEW_TIMES) -> list[dict[str, Any]]:
    """待审清单：同一类查询查到 times 次以上的，带查过的网址（多的在前）。"""
    rows = await log.rows()
    count = Counter(norm(r["query"]) for r in rows)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = norm(r["query"])
        if count[k] < times:
            continue
        item = out.setdefault(k, {"query": r["query"], "times": count[k], "urls": []})
        item["urls"] += [u for u in r["urls"] if u not in item["urls"]]
    return sorted(out.values(), key=lambda x: -x["times"])


# ---- 给管家的工具 ----------------------------------------------------------------------------


def web_tool(search: Search, log: WebLog | None, today: date) -> Any:
    """这一轮的联网搜索工具（每轮新建：次数按轮算）。"""
    calls = 0

    async def run(box: Any, args: Mapping[str, Any]) -> str:
        nonlocal calls
        query = " ".join(str(args.get("query") or "").split())[:120]
        if not query:
            box._outcome = "error"
            return "没有写要查什么。"
        if calls >= MAX_CALLS:
            box._outcome = "refused"
            return f"这一轮已经联网查了 {MAX_CALLS} 次，用已经查到的回答；不够就如实说。"
        calls += 1
        box.evidence.knowledge_queries += 1
        try:
            hits = await search(query)
        except Exception as e:
            _log.warning("web search failed: error_type=%s", type(e).__name__)
            box._outcome = "error"
            return "这次联网没查成，用知识库和已有的资料回答，不确定的如实说。"
        start = FIRST_ID + sum(1 for k in box.evidence.entries if int(k[1:]) >= FIRST_ID)
        found = to_entries(hits, start)
        _log.info("web search: hits=%d kept=%d", len(hits), len(found))
        if log is not None:
            try:
                await log.add(query, [x.url or "" for x in found], today)
            except Exception as err:
                _log.warning("web search log failed: error_type=%s", type(err).__name__)
        if not found:
            box._outcome = "empty"
            return "白名单机构里没查到相关资料。不要编数字，如实说还没有可靠的资料。"
        for hit in found:
            box.evidence.entries[hit.id] = hit
        return "联网查到的资料（未审，引用时写编号；数字只用原文片段里的）：\n\n" + "\n\n".join(
            e.as_evidence() for e in found
        )

    return run


def configured(environ: Mapping[str, str]) -> Search | None:
    """配了密钥才有搜索；没配返回 None（不给管家这个工具）。"""
    key = environ.get(KEY_ENV, "").strip()
    if not key:
        return None

    async def search(query: str) -> list[dict[str, Any]]:
        return await tavily(query, key)

    return search
