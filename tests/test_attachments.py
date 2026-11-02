"""对话里的图片和报告（spec [2026-10-23] §11）：只读本人的附件，图片交给管家，报告说明正在识别。"""

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

from ironm_agent.attachments import MAX_FILE_BYTES, read
from ironm_agent.llm import Reply, Stage
from tests.fakes import jsonr, system_of
from tests.test_plugin import agent, text_of
from tests.test_turn_flow import snapshot_of

PHOTO = {"file_key": "u/42/a.jpg", "file_name": "午饭.jpg", "file_type": "image/jpeg"}
REPORT = {"file_key": "u/42/r.pdf", "file_name": "体检报告.pdf", "file_type": "application/pdf"}
FOREIGN = {"file_key": "u/7/b.jpg", "file_name": "别人的.jpg", "file_type": "image/jpeg"}


def fakes(big: bool = False, report: str = "") -> dict[str, Any]:
    async def owned(user_id: str, keys: Sequence[str]) -> set[str]:
        return {k for k in keys if k.startswith(f"u/{user_id}/")}

    async def fetch(key: str) -> bytes:
        return b"x" * (MAX_FILE_BYTES + 1 if big else 10)

    async def pdf(_: bytes) -> str:
        return report

    return {"owned": owned, "fetch": fetch, "pdf": pdf}


def test_only_the_users_own_files_are_read() -> None:
    files = asyncio.run(read("42", [PHOTO, REPORT, FOREIGN, {"file_name": "无 key"}], **fakes()))
    assert [x.name for x in files.images] == ["午饭.jpg"] and [x.name for x in files.reports] == [
        "体检报告.pdf"
    ]
    assert files.skipped == ("别人的.jpg",)
    assert "已收到" in files.note_for_user() and "没能读取" in files.note_for_user()
    assert "正在识别" in files.note_for_experts()  # 读不出文字时不让角色猜
    assert files.images[0].part()["image_url"]["url"].startswith("data:image/jpeg;base64,")
    big = asyncio.run(read("42", [PHOTO], **fakes(big=True)))
    assert big.images == () and big.skipped == ("午饭.jpg",)


def test_meal_photo_goes_to_the_agent_with_the_image(monkeypatch: Any) -> None:
    seen: dict[str, Any] = {}

    def script(stage: Stage, messages: Sequence[Mapping[str, Any]], tools: bool) -> Reply:
        if stage == "route":  # 选规程的模型说是闲聊，也要按附了图片处理
            return jsonr({"skills": [], "domains": [], "intent": "闲聊", "fit": "chat"})
        if stage == "expert":
            seen["system"] = system_of(messages)
            seen["content"] = messages[1]["content"]
            return jsonr({"answer": "这一餐大约 600–800 千卡〔经验〕。"})
        return jsonr({"ops": []})

    a = agent(script, monkeypatch=monkeypatch, snapshot=snapshot_of())
    a._files, a._remember_on = fakes(), False

    async def go() -> list[dict[str, Any]]:
        msgs = [{"role": "user", "content": "这顿多少热量"}]
        return [
            b
            async for b in a.generate_response(
                "42", msgs, session_id="42:s1", file_list=[PHOTO, REPORT]
            )
        ]

    blocks = asyncio.run(go())
    assert "看照片估算一餐" in seen["system"]  # 附了图片：装上看照片估算的规程
    content = seen["content"]
    assert isinstance(content, list) and content[1]["type"] == "image_url"
    assert "不要猜报告里写了什么" in content[0]["text"]
    assert "《体检报告.pdf》" in text_of(blocks) and "600–800 千卡" in text_of(blocks)


def test_report_text_is_given_to_the_experts_and_heic_is_skipped() -> None:
    heic = {"file_key": "u/42/c.heic", "file_name": "IMG_1.HEIC", "file_type": "image/heic"}
    files = asyncio.run(read("42", [REPORT, heic], **fakes(report="血红蛋白 145 g/L")))
    assert files.reports[0].text == "血红蛋白 145 g/L" and files.skipped == ("IMG_1.HEIC",)
    assert "血红蛋白 145 g/L" in files.note_for_experts() and "HEIC" in files.note_for_user()
