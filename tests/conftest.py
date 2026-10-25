"""测试共用：作答链路的路由只用模型这一路（假模型给分），不载入本机中文小模型，结果固定。

三路打分本身（关键字、语义向量、加权、阈值）在 test_routing.py 里单独测。
"""

from collections.abc import Iterator

import pytest

from ironm_agent import plugin
from ironm_agent.routing import Router


@pytest.fixture(autouse=True)
def model_only_router(monkeypatch: pytest.MonkeyPatch) -> Iterator[Router]:
    router = Router(keyword=None, vector=None)
    monkeypatch.setattr(plugin, "default_router", lambda: router)
    yield router


@pytest.fixture(autouse=True)
def coach_in_memory(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    """管家重新评估（spec [2026-10-23] §23）：测试里默认只记下被触发了，不连数据库；要测评估本身的测试自己换掉。"""
    from ironm_agent import web, web_more

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(web_more, "coach_later", lambda uid, reason: calls.append((uid, reason)))
    monkeypatch.setattr(web, "coach_later", lambda uid, reason: calls.append((uid, reason)))

    async def coach(uid: str, reason: str, force: bool) -> None:
        calls.append((uid, reason))

    monkeypatch.setattr(plugin, "default_coach_eval", coach)
    yield calls


@pytest.fixture(autouse=True)
def traces_in_memory(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """运行框架的轨迹（spec [2026-10-23] §31）：测试里默认存在内存里，不连数据库。"""
    from ironm_agent import harness

    book = harness.TraceBook()
    monkeypatch.setattr(harness, "_default", book)
    yield book
