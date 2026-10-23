"""导入苹果健康：用户上传 iPhone"健康"App 导出的压缩包，在后台写进本人的记录。

与 `mirobody import apple export.zip --into <用户>` 走同一条路：来源记为 apple_health_export，
同一个文件再导入不会重复计数（读数按内容去重），导入后重算这些天的每日值。
- 中文系统导出的压缩包里，数据文件可能叫"导出.xml"：先认出真正的数据文件，再交给 mirobody 解析；
- 解析在线程里做（几百 MB 的文件要解析好几分钟，不能卡住服务），写库在事件循环里分批做；
- 每个人同一时间只跑一个导入；进度与结果留在内存里，页面轮询查看。日志只记条数，不记内容。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

_log = logging.getLogger("ironm_agent.imports")

SOURCE = "apple_health_export"
BATCH = 2_000  # 每批写多少条读数（一批一个事务）
_HEAD = 256 * 1024  # 判断是不是健康数据文件时读开头多少字节（文件头里有很长的 DTD）

type State = Literal["running", "done", "failed"]


class ImportFailed(Exception):
    """用户能看懂的导入失败原因。"""


@dataclass
class ImportJob:
    id: str
    state: State = "running"
    stage: str = "准备中"
    records: int = 0  # 读到的记录
    facts: int = 0  # 认出的读数
    written: int = 0  # 已经写入的读数（进度）
    added: int = 0  # 新增的读数（再导入同一个文件时为 0）
    first: str = ""  # 数据覆盖的第一天
    last: str = ""
    error: str = ""
    started: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished: str = ""

    def json(self) -> dict[str, Any]:
        return asdict(self)


_jobs: dict[str, ImportJob] = {}  # 每个人最近一次导入
_tasks: set[asyncio.Task[None]] = set()


def latest(user_id: str) -> ImportJob | None:
    return _jobs.get(user_id)


def running(user_id: str) -> bool:
    job = _jobs.get(user_id)
    return job is not None and job.state == "running"


def _is_health_xml(head: bytes) -> bool:
    return b"<HealthData" in head


def extract_export(upload: Path, workdir: Path) -> Path:
    """从上传的文件里取出健康数据 XML（压缩包里的 export.xml / 导出.xml，或直接上传的 XML）。"""
    if not zipfile.is_zipfile(upload):
        with upload.open("rb") as f:
            if _is_health_xml(f.read(_HEAD)):
                return upload
        raise ImportFailed("这不是健康 App 导出的文件：请上传导出得到的 .zip 压缩包")
    with zipfile.ZipFile(upload) as zf:
        names = [
            n
            for n in zf.namelist()
            if n.lower().endswith(".xml")
            and not n.startswith("__MACOSX/")
            and "_cda" not in n.lower()
            and "/workout-routes/" not in n
        ]
        names.sort(key=lambda n: (not n.endswith("export.xml"), n.count("/"), len(n)))
        for name in names:
            with zf.open(name) as f:
                if not _is_health_xml(f.read(_HEAD)):
                    continue
            target = workdir / "export.xml"
            with zf.open(name) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
            return target
    raise ImportFailed("压缩包里没有找到健康数据（export.xml）：请上传健康 App 导出的原始压缩包")


@dataclass
class _Done:
    records: int
    facts: int
    span: tuple[int, int] | None


def parse_batches(xml: Path, tz: str, batch: int = BATCH) -> Iterator[list[Any] | _Done]:
    """解析健康数据，按批产出 mirobody 的标准记录；最后产出一个 _Done（条数与时间范围）。"""
    from mirobody.collect import records_from_facts
    from mirobody.kernel import decoders
    from mirobody.kernel.decoders import apple_export

    counts = apple_export.Counts()
    out: list[Any] = []
    facts, lo, hi = 0, None, None
    for kind, item in apple_export.iter_items(xml, counts):
        found = decoders.decode("apple", kind, item, tz)
        if not found:
            continue
        facts += len(found)
        for f in found:
            ms = f.effective_start_ms
            lo = ms if lo is None or ms < lo else lo
            hi = ms if hi is None or ms > hi else hi
        out.extend(records_from_facts(found, slug="apple_health", tz=tz,
                                      source_id=item.get("sourceName") or "export", source=SOURCE))  # fmt: skip
        if len(out) >= batch:
            yield out
            out = []
    if out:
        yield out
    yield _Done(counts.records, facts, (lo, hi) if lo is not None and hi is not None else None)


async def _count(user_id: str) -> int:
    from mirobody.utils.db import execute_query

    rows = await execute_query(
        "SELECT count(*) AS n FROM th_observation WHERE user_id = :u", {"u": user_id}, log_sql=False
    )
    return int(rows[0]["n"]) if rows else 0


async def _store(user_id: str, tz: str, records: list[Any]) -> None:
    from mirobody.collect import StandardPulseData, StandardPulseMetaInfo
    from mirobody.collect.ingest import StandardHealthService

    data = StandardPulseData(
        metaInfo=StandardPulseMetaInfo(userId=user_id, source=SOURCE, timezone=tz),
        healthData=list(records),
    )
    if not await StandardHealthService().process_standard_data(data, user_id):
        raise ImportFailed("有一批数据没写进去，可以稍后重新导入（不会重复计数）")


async def _aggregate(user_id: str, span: tuple[int, int]) -> None:
    from mirobody.translate import AggregateIndicatorService

    first, last = (datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=None) for ms in span)
    result = await AggregateIndicatorService().recalculate_date_range(first, last, user_id=user_id)
    if result.get("status") != "success":
        raise ImportFailed("读数已经导入，但每日汇总没有算完，稍后会自动补上")


async def run_import(
    user_id: str,
    upload: Path,
    tz: str,
    job: ImportJob,
    *,
    store: Callable[[str, str, list[Any]], Awaitable[None]] = _store,
    count: Callable[[str], Awaitable[int]] = _count,
    aggregate: Callable[[str, tuple[int, int]], Awaitable[None]] = _aggregate,
) -> None:
    """导入一个上传的文件；结果写进 job。

    解析在线程里，写库在这里；队列有上限，线程不会跑在写库前面太多。线程总以一个结束标记收尾
    （_Done 或异常）；写库出错时通知线程停下，并继续取完队列，两边都能正常结束。
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[list[Any] | _Done | BaseException] = asyncio.Queue(maxsize=3)
    stop = threading.Event()
    workdir = Path(tempfile.mkdtemp(prefix="ironm-apple-"))

    def put(item: list[Any] | _Done | BaseException) -> None:
        asyncio.run_coroutine_threadsafe(queue.put(item), loop).result()

    def produce() -> None:
        try:
            xml = extract_export(upload, workdir)
            for part in parse_batches(xml, tz, BATCH):
                if stop.is_set():
                    put(_Done(0, 0, None))
                    return
                put(part)
        except BaseException as e:  # 交给事件循环那边处理
            put(e)

    try:
        before = await count(user_id)
        job.stage = "正在读取文件"
        worker = loop.run_in_executor(None, produce)
        failure: BaseException | None = None
        while True:
            part = await queue.get()
            if isinstance(part, BaseException):
                failure = failure or part
                break
            if isinstance(part, _Done):
                done = part
                break
            if failure is not None:
                continue  # 已经出错：只取不写，等线程收尾
            job.stage = "正在写入数据"
            try:
                await store(user_id, tz, part)
            except Exception as e:
                failure = e
                stop.set()
                continue
            job.written += len(part)
        await worker
        if failure is not None:
            raise failure
        job.records, job.facts = done.records, done.facts
        if done.span:
            job.stage = "正在汇总每日数据"
            await aggregate(user_id, done.span)
            job.first, job.last = (
                datetime.fromtimestamp(ms / 1000, UTC).date().isoformat() for ms in done.span
            )
        job.added = await count(user_id) - before
        job.state, job.stage = "done", "已完成"
        if not done.facts:
            job.error = "文件里没有能识别的健康数据"
    except ImportFailed as e:
        job.state, job.error = "failed", str(e)
    except Exception as e:
        _log.error("apple import failed: error_type=%s", type(e).__name__)
        job.state, job.error = "failed", "导入没有成功，请稍后再试"
    finally:
        stop.set()
        job.finished = datetime.now(UTC).isoformat()
        shutil.rmtree(workdir, ignore_errors=True)
        upload.unlink(missing_ok=True)
        _log.info("apple import %s: records=%d facts=%d added=%d", job.state, job.records,
                  job.facts, job.added)  # fmt: skip


def start(user_id: str, upload: Path, tz: str) -> ImportJob:
    """开始后台导入；同一个人已经有导入在跑时由调用方先拒绝。"""
    job = ImportJob(id=uuid.uuid4().hex[:12])
    _jobs[user_id] = job
    task = asyncio.create_task(run_import(user_id, upload, tz, job))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job
