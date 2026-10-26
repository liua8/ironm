"""混合问题请全角色（spec [2026-10-23] §42 需求 2）：问题里明确点到另一个领域时，把那个领域的角色加上。

只看明确的说法，不靠猜；路由已经请到的不重复加。
"""

from __future__ import annotations

import re
from collections.abc import Collection

from ironm_agent.roles import Role

_DOMAINS: tuple[tuple[Role, re.Pattern[str]], ...] = (
    (
        Role.NUTRITION,
        re.compile(
            r"饮食|吃什么|怎么吃|吃多少|营养|蛋白质|热量|卡路里|补剂|蛋白粉|肌酸|早餐|午餐|晚餐|加餐"
        ),
    ),
    (
        Role.RECOVERY,
        re.compile(
            r"睡了|没睡|睡不好|睡得|失眠|熬夜|疲劳|好累|很累|酸痛|疼|痛|受伤|生病|感冒|发烧"
        ),
    ),
)


def missing_roles(text: str, roles: Collection[Role]) -> list[Role]:
    """问题点到、但这一轮没请到的领域角色。"""
    return [role for role, pattern in _DOMAINS if role not in roles and pattern.search(text)]
