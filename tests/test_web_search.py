"""联网搜索（spec [2026-10-23] §91）：知识库查不到时由管家决定联网查白名单机构，结果未审、可核对、留底。"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from ironm_agent.tools import Evidence
from ironm_agent.web_search import (
    MAX_CALLS,
    WebBook,
    configured,
    org_of,
    pending,
    to_entries,
    web_tool,
)
from tests.fakes import call, jsonr
from tests.test_plugin import text_of
from tests.test_single_agent import single
from tests.test_turn_flow import run

CREATINE = {
    "title": "Creatine supplementation position stand",
    "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5469049/",
    "content": "Creatine monohydrate is safe for long-term use. A loading phase is not required. "
    "Cycling creatine is not necessary; 3-5 g per day maintains stores.",
    "published_date": "2017-06-13",
}
BLOG = {
    "title": "My gym blog",
    "url": "https://evilacsm.org/x",
    "content": "Cycle creatine every 8 weeks.",
}


def test_only_whitelisted_organisations_count() -> None:
    assert org_of("https://www.acsm.org/a") == "美国运动医学会（ACSM）"
    assert org_of("https://pmc.ncbi.nlm.nih.gov/x") == "PubMed Central"
    assert org_of("https://evilacsm.org/x") is None and org_of("https://example.com") is None
    [e] = to_entries([BLOG, CREATINE, {"url": "https://www.who.int/x", "content": ""}], 8001)
    assert e.id == "K8001" and e.year == 2017 and e.review == "web" and len(e.points) == 3
    assert "联网资料（未审）" in e.cite_label() and CREATINE["url"] in e.cite_label()
    assert "3-5 g per day" in e.as_evidence()


class Box:
    def __init__(self) -> None:
        self.evidence = Evidence()
        self._outcome = "ok"


def test_tool_caps_calls_reports_failures_and_logs_queries() -> None:
    asked: list[str] = []

    async def search(q: str) -> list[dict[str, Any]]:
        asked.append(q)
        return [CREATINE, BLOG]

    log = WebBook()
    tool = web_tool(search, log, date(2026, 10, 30))
    box = Box()
    got = asyncio.run(tool(box, {"query": "creatine cycling"}))
    assert "[K8001]" in got and "evilacsm" not in got and "K8001" in box.evidence.entries
    got = asyncio.run(tool(box, {"query": "creatine loading"}))
    assert "[K8002]" in got  # 同一轮第二次接着编号
    got = asyncio.run(tool(box, {"query": "third"}))
    assert f"已经联网查了 {MAX_CALLS} 次" in got and box._outcome == "refused" and len(asked) == 2
    assert [r["query"] for r in log.items] == ["creatine cycling", "creatine loading"]

    async def broken(q: str) -> list[dict[str, Any]]:
        raise TimeoutError

    async def nothing(q: str) -> list[dict[str, Any]]:
        return [BLOG]

    box = Box()
    assert "没查成" in asyncio.run(web_tool(broken, None, date.today())(box, {"query": "x"}))
    assert box._outcome == "error"
    assert "没查到" in asyncio.run(web_tool(nothing, None, date.today())(box, {"query": "x"}))
    assert box._outcome == "empty" and not box.evidence.entries


def test_repeated_queries_go_on_the_review_list() -> None:
    log = WebBook()
    for q, urls in (
        ("肌酸 要不要 循环", ["a"]),
        ("肌酸要不要循环？", ["b"]),
        ("孕期平板支撑", ["c"]),
    ):
        asyncio.run(log.add(q, urls, date.today()))
    [item] = asyncio.run(pending(log))
    assert item["times"] == 2 and item["urls"] == ["a", "b"]


def test_no_key_means_no_tool(monkeypatch: Any) -> None:
    assert configured({}) is None and configured({"TAVILY_API_KEY": "x"}) is not None
    a, _ = single(lambda *_: jsonr({"answer": "好"}), monkeypatch)
    assert a._web_tools(date.today()) == {}


def test_agent_searches_cites_and_explains_the_source(monkeypatch: Any) -> None:
    async def search(q: str) -> list[dict[str, Any]]:
        return [CREATINE]

    said = "不用循环吃，每天 3-5 g 一直吃就行〔K8001〕。"

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call("search_web", query="creatine cycling necessary")
        assert "联网查到的资料" in results[0]
        return jsonr({"answer": said})

    a, _ = single(answer, monkeypatch, old=True)
    a._web_search, a._web_log = search, WebBook()
    blocks, seen = run(a, "肌酸要不要循环吃")
    text = text_of(blocks)
    assert (
        "search_web" in seen["tools"] and "3-5 g" in text and "K8001" not in text
    )  # 回答里不出编号
    assert not seen.get("constraints")  # 数字在原文片段里：核对通过
    sources = [
        b for b in blocks if b.get("type") == "tool_result" and "pmc.ncbi" in str(b.get("content"))
    ]
    assert sources and "联网资料（未审）" in str(
        sources[0]["content"]
    )  # 追问依据时讲得出机构和网址


def test_number_not_in_the_snippet_fails_the_check(monkeypatch: Any) -> None:
    async def search(q: str) -> list[dict[str, Any]]:
        return [CREATINE]

    def answer(system: str, user: str, results: list[str]) -> Any:
        if not results:
            return call("search_web", query="creatine dose")
        return jsonr({"answer": "每天吃 10 g〔K8001〕。"})  # 原文片段里没有 10 g

    a, _ = single(answer, monkeypatch, old=True)
    a._web_search, a._web_log = search, WebBook()
    blocks, seen = run(a, "肌酸一天吃多少")
    trace = seen["_experts"][0]
    assert trace.get("checks") and trace.get("repaired")  # 核对不过：先让它改，仍不过就修掉
    # 修掉的是"出处"：不再算在这条联网资料头上（和知识库一样改记成经验），依据里不列它
    assert not any(
        "pmc.ncbi" in str(b.get("content")) for b in blocks if b.get("type") == "tool_result"
    )
