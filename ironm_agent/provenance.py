"""用户追问来源（“这个数从哪来的”“依据是什么”“怎么算的”）：从上一条回答的“依据与来源”里讲给他听。"""

from __future__ import annotations

import re

# 追问回复的开头：找“上一条回答”时跳过这些，往前找真正的回答
REPLY_PREFIXES = ("上一条回答的依据", "还没有可以追溯的回答", "上一条回答没有用到")
_EXPLAINED = re.compile(r"^[\d.、]+ 是这样来的")

_ASK = re.compile(
    r"来源|出处|依据|从哪|哪来|哪里来|哪儿来|怎么算|如何算|算出来|根据什么|凭什么|参考了|引用"
)
_POINT = re.compile(r"这|那|上面|刚才|刚刚|你说|它|这些|那些|上一")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def is_provenance(text: str) -> bool:
    """问的是上一条回答的来源：有“来源/依据/怎么算”这类词，并且指着上一条回答（指代、具体数字，或就是一句短问）。"""
    t = text.strip()
    if not _ASK.search(t):
        return False
    return bool(_POINT.search(t) or _NUMBER.search(t) or len(t) <= 8)


def explain(question: str, sources: str | None) -> str:
    """把来源讲给用户；问到具体数字时，先讲包含这个数字的那几条。"""
    if sources is None:
        return "还没有可以追溯的回答。你先问一个问题，我回答后，可以接着问依据和来源。"
    if not sources.strip():
        return "上一条回答没有用到资料、计算或你的数据，主要是教练的专业经验。"
    numbers = _NUMBER.findall(question)
    if numbers:
        lines = [
            ln
            for ln in sources.splitlines()
            if ln.startswith("- ") and any(n in ln for n in numbers)
        ]
        if lines:
            return f"{'、'.join(numbers)} 是这样来的：\n" + "\n".join(lines)
    return "上一条回答的依据：\n\n" + sources


def is_explanation(answer: str) -> bool:
    """这条助手回复是不是追问来源的回复（不是真正的回答）。"""
    a = answer.strip()
    return a.startswith(REPLY_PREFIXES) or bool(_EXPLAINED.match(a))
