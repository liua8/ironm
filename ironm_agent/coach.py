"""管家直接回答：打招呼、闲聊、App 怎么用、超出范围。不给具体的训练量、热量、剂量数字。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

GUIDE_PATH = Path(__file__).with_name("app_guide.md")


@cache
def app_guide() -> str:
    """App 使用说明（spec [2026-10-23] §36）：问 App 怎么用时照着答。"""
    return GUIDE_PATH.read_text(encoding="utf-8")
