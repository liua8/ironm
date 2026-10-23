"""导入苹果健康：认出压缩包里的数据文件（含中文系统的"导出.xml"），后台分批写入，出错能收尾。"""

import asyncio
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import imports
from ironm_agent.imports import (
    ImportFailed,
    ImportJob,
    _Done,
    extract_export,
    parse_batches,
    run_import,
)
from tests.apple_export import export_xml, write_zip

END = date(2026, 10, 21)


def test_finds_the_health_file_in_a_chinese_export(tmp_path: Path) -> None:
    write_zip(str(tmp_path / "导出.zip"), END)
    xml = extract_export(tmp_path / "导出.zip", tmp_path)
    assert b"<HealthData" in xml.read_bytes()[:4096]


def test_prefers_export_xml_and_skips_cda(tmp_path: Path) -> None:
    write_zip(str(tmp_path / "export.zip"), END, member="apple_health_export/export.xml")
    assert extract_export(tmp_path / "export.zip", tmp_path).name == "export.xml"


def test_rejects_files_that_are_not_health_exports(tmp_path: Path) -> None:
    other = tmp_path / "photos.zip"
    with zipfile.ZipFile(other, "w") as zf:
        zf.writestr("a.xml", "<note>hi</note>")
    with pytest.raises(ImportFailed, match="没有找到健康数据"):
        extract_export(other, tmp_path)
    text = tmp_path / "x.zip"
    text.write_text("not a zip")
    with pytest.raises(ImportFailed, match="不是健康 App 导出的文件"):
        extract_export(text, tmp_path)
    plain = tmp_path / "export.xml"
    plain.write_text(export_xml(END, 2))
    assert extract_export(plain, tmp_path) == plain  # 直接上传 XML 也行


def test_parses_sleep_hrv_and_steps_in_batches(tmp_path: Path) -> None:
    plain = tmp_path / "export.xml"
    plain.write_text(export_xml(END, 10))
    parts = list(parse_batches(plain, "Asia/Shanghai", batch=10))
    done = parts[-1]
    assert isinstance(done, _Done) and done.records == 30 and done.facts >= 30
    assert sum(len(p) for p in parts[:-1] if isinstance(p, list)) == done.facts
    assert all(len(p) <= 19 for p in parts[:-1] if isinstance(p, list))  # 按批写入
    assert done.span is not None and done.span[0] < done.span[1]


def run(upload: Path, **fakes: Any) -> ImportJob:
    job = ImportJob(id="t")
    asyncio.run(run_import("42", upload, "Asia/Shanghai", job, **fakes))
    return job


def fakes(stored: list[int], fail_at: int | None = None) -> dict[str, Any]:
    counter = {"n": 100}

    async def store(user: str, tz: str, records: list[Any]) -> None:
        if fail_at is not None and len(stored) == fail_at:
            raise ImportFailed("有一批数据没写进去，可以稍后重新导入（不会重复计数）")
        stored.append(len(records))
        counter["n"] += len(records)

    async def count(user: str) -> int:
        return counter["n"]

    async def aggregate(user: str, span: tuple[int, int]) -> None:
        return None

    return {"store": store, "count": count, "aggregate": aggregate}


def test_import_reports_counts_dates_and_cleans_up(tmp_path: Path) -> None:
    upload = tmp_path / "导出.zip"
    write_zip(str(upload), END, days=10)
    stored: list[int] = []
    job = run(upload, **fakes(stored))
    assert job.state == "done" and job.records == 30 and job.added == sum(stored) == job.written
    assert (job.first, job.last) == ("2026-10-11", "2026-10-21") and not upload.exists()


def test_store_failure_ends_cleanly_with_a_reason(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(imports, "BATCH", 5)
    upload = tmp_path / "导出.zip"
    write_zip(str(upload), END, days=40)  # 很多批：出错后解析线程要能停下来
    stored: list[int] = []
    job = run(upload, **fakes(stored, fail_at=1))
    assert job.state == "failed" and "重新导入" in job.error and len(stored) == 1


def test_bad_file_fails_with_a_message_the_user_understands(tmp_path: Path) -> None:
    upload = tmp_path / "x.zip"
    upload.write_text("not a zip")
    job = run(upload, **fakes([]))
    assert job.state == "failed" and "健康 App" in job.error and not upload.exists()


def client(monkeypatch: Any) -> tuple[TestClient, list[tuple[str, str]]]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    started: list[tuple[str, str]] = []

    def fake_start(user_id: str, upload: Path, tz: str) -> ImportJob:
        started.append((user_id, tz))
        upload.unlink()
        job = ImportJob(id="j1")
        imports._jobs[user_id] = job
        return job

    monkeypatch.setattr(imports, "start", fake_start)
    monkeypatch.setattr(imports, "_jobs", {})
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    return TestClient(app), started


def test_upload_endpoint_starts_one_import_at_a_time(tmp_path: Path, monkeypatch: Any) -> None:
    c, started = client(monkeypatch)
    write_zip(str(tmp_path / "导出.zip"), END, days=2)
    files = {"file": ("导出.zip", (tmp_path / "导出.zip").read_bytes(), "application/zip")}
    r = c.post("/iron/api/import/apple", files=files, data={"tz": "Asia/Shanghai"})
    assert r.status_code == 200 and r.json()["job"]["state"] == "running"
    assert started == [("42", "Asia/Shanghai")]
    assert c.post("/iron/api/import/apple", files=files).status_code == 409  # 上一次还在跑
    assert c.get("/iron/api/import/apple").json()["job"]["id"] == "j1"


def test_upload_endpoint_rejects_other_files_and_bad_zones(
    tmp_path: Path, monkeypatch: Any
) -> None:
    c, started = client(monkeypatch)
    pdf = {"file": ("report.pdf", b"%PDF-1.4", "application/pdf")}
    assert c.post("/iron/api/import/apple", files=pdf).status_code == 400
    empty = {"file": ("导出.zip", b"", "application/zip")}
    assert c.post("/iron/api/import/apple", files=empty).status_code == 400
    ok = {"file": ("export.xml", export_xml(END, 1).encode(), "text/xml")}
    c.post("/iron/api/import/apple", files=ok, data={"tz": "Mars/Base"})
    assert started == [("42", "UTC")]  # 不认识的时区按 UTC
