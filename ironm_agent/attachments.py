"""对话里的图片和报告（spec [2026-10-23] §11）。

- 只读本人上传的附件：附件在 mirobody 的文件表里属于这个人（上传时 mirobody 已经把这一轮的附件登记好）；
- 图片：交给能看图的模型读（饭菜照片由营养估算热量和蛋白质）；大图先缩小再交给模型；HEIC 读不了，如实说明；
- 报告文件：mirobody 照常放进"我的文件"并自动识别；PDF 有文字层的，把读出的文字交给专业角色据此回答，
  读不出文字的（扫描件）说明正在识别，不编造报告内容。
日志只记附件的个数和类型，不记文件名和内容。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger("ironm_agent.attachments")

MAX_FILE_BYTES = 20 * 1024 * 1024  # 对话附件的上限（和网页一致）
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 交给模型的单张图片上限：更大的先缩小，缩不下来就不读
MAX_IMAGES = 3
MAX_REPORT_CHARS = 4000  # 报告文字交给专业角色的上限
_HEIC = (".heic", ".heif")
_IMAGE = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif")


@dataclass(frozen=True)
class Image:
    name: str
    mime: str
    data: bytes

    def part(self) -> dict[str, Any]:
        b64 = base64.b64encode(self.data).decode()
        return {"type": "image_url", "image_url": {"url": f"data:{self.mime};base64,{b64}"}}


@dataclass(frozen=True)
class Report:
    name: str
    text: str = ""  # PDF 文字层读出的文字（读不出时为空）


@dataclass(frozen=True)
class Attachments:
    images: tuple[Image, ...] = ()
    reports: tuple[Report, ...] = ()
    skipped: tuple[str, ...] = ()  # 读不了的（不是本人的、太大、取不到、HEIC）

    def note_for_user(self) -> str:
        """回答开头给用户的一句话（只说收到了什么、读不了什么）。"""
        parts = []
        if self.reports:
            names = "、".join(f"《{x.name}》" for x in self.reports)
            parts.append(f"已收到你上传的{names}，识别出的指标会出现在「数据」页的「我的文件」里。")
        if self.skipped:
            parts.append(
                f"有 {len(self.skipped)} 个附件这次没能读取（太大、HEIC 格式或不是你的文件），"
                "可以换成 JPG 再发。"
            )
        return "".join(parts)

    def note_for_experts(self) -> str:
        lines = []
        if self.images:
            lines.append(
                f"用户这次附了 {len(self.images)} 张图片（见下面的图片），回答时按图片内容说。"
            )
        for x in self.reports:
            if x.text:
                lines.append(
                    f"用户上传的报告《{x.name}》里读到的文字（系统从 PDF 读出，可能不完整；"
                    f"只按读到的说，不诊断）：\n{x.text}"
                )
            else:
                lines.append(
                    f"用户上传了报告《{x.name}》，系统正在识别，内容现在还读不到：不要猜报告里写了什么。"
                )
        return "\n\n".join(lines)


type Fetch = Callable[[str], Awaitable[bytes | None]]
type Owned = Callable[[str, Sequence[str]], Awaitable[set[str]]]


async def _owned(user_id: str, keys: Sequence[str]) -> set[str]:
    from mirobody.utils.db import execute_query

    rows = await execute_query(
        "SELECT file_key FROM th_files WHERE file_key = ANY(:keys)"
        " AND COALESCE(NULLIF(query_user_id, ''), user_id) = :uid",
        {"keys": list(keys), "uid": str(user_id)},
        log_sql=False,
    )
    return {str(r["file_key"]) for r in rows or []}


def _shrink(data: bytes, mime: str) -> tuple[bytes, str]:
    from mirobody.documents.extract import downscale_image

    out, kind = downscale_image(data, mime, max_bytes=MAX_IMAGE_BYTES)
    return out, str(kind)


async def _pdf(data: bytes) -> str:
    """PDF 的文字层（不做 OCR：扫描件交给 mirobody 的识别，这里读不出就是空）。"""
    from mirobody.documents.extract import pdf_text

    try:
        return str(await pdf_text(data))[:MAX_REPORT_CHARS]
    except Exception as e:
        _log.warning("report text unavailable: error_type=%s", type(e).__name__)
        return ""


async def _fetch(key: str) -> bytes | None:
    from mirobody.utils.config.storage.factory import get_storage_client

    content, _ = await get_storage_client().get(key)
    return content if isinstance(content, bytes) else None


async def _get(fetch: Fetch, key: str) -> bytes | None:
    try:
        return await fetch(key)
    except Exception as e:
        _log.warning("attachment fetch failed: error_type=%s", type(e).__name__)
        return None


def _is_image(name: str, mime: str) -> bool:
    return mime.startswith("image/") or name.lower().endswith(_IMAGE)


async def read(
    user_id: str,
    file_list: Sequence[Mapping[str, Any]] | None,
    *,
    owned: Owned = _owned,
    fetch: Fetch = _fetch,
    pdf: Callable[[bytes], Awaitable[str]] = _pdf,
) -> Attachments:
    files = [f for f in (file_list or []) if isinstance(f, Mapping) and f.get("file_key")]
    if not files:
        return Attachments()
    keys = [str(f["file_key"]) for f in files]
    try:
        mine = await owned(user_id, keys)
    except Exception as e:
        _log.warning("attachments unavailable: error_type=%s", type(e).__name__)
        mine = set()
    images: list[Image] = []
    reports: list[Report] = []
    skipped: list[str] = []
    for f in files:
        key, name = str(f["file_key"]), str(f.get("file_name") or "附件")
        mime = str(f.get("file_type") or mimetypes.guess_type(name)[0] or "")
        if key not in mine:
            skipped.append(name)
            continue
        image = _is_image(name, mime)
        if image and (name.lower().endswith(_HEIC) or "heic" in mime or "heif" in mime):
            skipped.append(name)  # 多数看图接口不认 HEIC
            continue
        if image and len(images) >= MAX_IMAGES:
            skipped.append(name)
            continue
        is_pdf = name.lower().endswith(".pdf") or mime == "application/pdf"
        data = await _get(fetch, key) if image or is_pdf else None
        if not image:
            text = await pdf(data) if data and is_pdf and len(data) <= MAX_FILE_BYTES else ""
            reports.append(Report(name, text.strip()))
            continue
        if data is None or not data or len(data) > MAX_FILE_BYTES:
            skipped.append(name)
            continue
        body: bytes = data
        kind = mime if mime.startswith("image/") else "image/jpeg"
        if len(body) > MAX_IMAGE_BYTES:  # 大图先缩小（在线程里做，不卡住服务）
            body, kind = await asyncio.to_thread(_shrink, body, kind)
        if len(body) > MAX_IMAGE_BYTES:
            skipped.append(name)
            continue
        images.append(Image(name, kind, body))
    _log.info("attachments: images=%d reports=%d report_text=%d skipped=%d", len(images),
              len(reports), sum(1 for x in reports if x.text), len(skipped))  # fmt: skip
    return Attachments(tuple(images), tuple(reports), tuple(skipped))
