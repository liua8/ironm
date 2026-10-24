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
