"""测试共用：管家评估、轨迹、网页里交给模型说的话，默认都不连数据库和真实模型。"""

from collections.abc import Iterator

import pytest

from ironm_agent import plugin


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
def next_targets_recorded(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, object]]]:
    """练完定下次（§132）：测试里默认只记下被触发了，不连数据库和真实模型；读管家定的下次目标当作没有。"""
    from ironm_agent import web_more

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(web_more, "targets_later", lambda uid, log: calls.append((uid, log)))

    async def none(_: str) -> dict[str, object]:
        return {}

    monkeypatch.setattr(web_more, "decided_targets", none)
    yield calls


@pytest.fixture(autouse=True)
def traces_in_memory(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """运行框架的轨迹（spec [2026-10-23] §31）：测试里默认存在内存里，不连数据库。"""
    from ironm_agent import harness

    book = harness.TraceBook()
    monkeypatch.setattr(harness, "_default", book)
    yield book


from ironm_agent import user_models as _user_models  # noqa: E402

_REAL_OWN_CONFIG = _user_models.own_config


class _Down:
    async def chat(self, *_: object, **__: object) -> object:
        raise RuntimeError("测试里不连真实模型")


def real_own_config() -> object:
    """真正的"读这个人填的模型"（测它本身时用；别的测试被下面的夹具换掉了）。"""
    return _REAL_OWN_CONFIG


def model_is(monkeypatch: pytest.MonkeyPatch, llm: object | None) -> None:
    """这个测试里"他自己填的模型"是什么（§167）；None 表示没填。"""
    from ironm_agent import user_models

    async def pick(*_: object, **__: object) -> object | None:
        return llm

    async def own_config(*_: object, **__: object) -> object | None:
        # 对话链路自己建模型（测试里 plugin.TurnLLM 被换成假的），这里只要"填没填"
        from ironm_agent.llm import load_models

        return None if llm is None else (load_models(), {"DEEPSEEK_API_KEY": "test"})

    monkeypatch.setattr(user_models, "pick", pick)
    monkeypatch.setattr(user_models, "own_config", own_config)


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """要调模型的网页接口和后台任务用本人填的模型（§167）：测试里默认"填了但调不通"，
    退回规则的那句；要测的自己用 model_is 换掉，测"没填"的传 None。"""
    model_is(monkeypatch, _Down())
    yield


@pytest.fixture(autouse=True)
def no_coach_review_in_web(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """首页"今天的版本"读管家今天的复盘（spec [2026-10-23] §97）：测试里默认没有，不连数据库；要测的自己换掉。"""
    from ironm_agent import web_more

    async def none(_: str) -> None:
        return None

    monkeypatch.setattr(web_more, "review_today", none)
    yield
