"""iron-m 在使用中补充的急症判定用例（IronM 的 43 条红旗测试集原样保留在 red_flags.yaml）。"""

import pytest

from ironm_agent.safety.emergency import assess

CASES = [
    # 2026-10-22 网页实测：用户抱怨助手"答非所问"，被当成意识不清的急症
    ("感觉你答非所问", "none"),
    ("你总是答非所问", "none"),
    ("你的回答答非所问", "none"),
    ("你这个回答有点答非所问", "none"),
    # 说的是人本身时照样是急症
    ("我爸突然答非所问", "emergency"),
    ("他跑完步后答非所问，脸色发白", "emergency"),
    ("跑完步头很晕，有点意识模糊", "emergency"),
]


@pytest.mark.parametrize(("text", "expect"), CASES)
def test_case(text: str, expect: str) -> None:
    assert assess(text).level == expect
