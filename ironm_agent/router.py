"""调度用的公共部分（Route、身体不适与特殊人群的判断、按关键词调度）。

作答链路已改用 routing.py 的三路打分路由（spec [2026-10-23] §16）；这里的 route() 只留给路由测评做对照（原来的主教练调度）。
"""

from __future__ import annotations

from typing import Literal

type Intent = Literal["chat", "app", "pro", "out_of_scope"]
type Concern = Literal["discomfort", "special"]


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


def concerns_of(text: str) -> tuple[Concern, ...]:
    out: list[Concern] = []
    if any(w in text for w in _DISCOMFORT):
        out.append("discomfort")
    if any(w in text for w in _SPECIAL):
        out.append("special")
    return tuple(out)
