"""管家的专业提示词（spec [2026-10-23] §15、§87、§88）：只写分工和工具，引用的资料都存在。"""

import re
from typing import Any

from ironm_agent.frameworks import framework, framework_refs
from ironm_agent.kb import default_kb
from ironm_agent.llm import Reply
from ironm_agent.roles import Role


def test_refs_exist_in_knowledge_base() -> None:
    kb = default_kb()
    text = framework(Role.GENERAL)
    assert all(kb.get(r) is not None for r in framework_refs(Role.GENERAL))
    # 每轮都带的提示词只写分工和工具，不写具体数字（数字在规程里，§88）
    assert not re.search(r"\d", text) and "check_plan" in text and "nutrition_calc" in text


def scripted(*replies: Reply) -> Any:
    it = iter(replies)
    return lambda *_: next(it)
