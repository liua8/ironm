"""回放报告和对比（spec [2026-10-23] §138 需求 2、3）：每跑一次留一份，和以前的结果比哪些轮变差、变好
（每轮取最近一次跑过它的结果，见 baseline）。

报告是 JSON：{"at": 时间, "label": 标签, "rows": [每一轮]}。每一轮用（用例编号, 第几轮）对上；
对话用例和后台用例都是一样的行，只是 kind 不同。只用规则判断的结果比，不打分。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPORTS = Path(__file__).resolve().parent / "reports"


@dataclass
class Row:
    case: str
    turn: int  # 第几轮（从 1 起）；后台用例只有 1 轮
    say: str
    kind: str = "chat"  # chat：对话用例；agent：后台用例
    ok: bool = True
    bad: list[str] = field(default_factory=list)
    secs: float = 0.0
    answer: str = ""
    cards: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, int]:
        return (self.case, self.turn)


def save(
    rows: Sequence[Row], label: str = "", where: Path = REPORTS, now: datetime | None = None
) -> Path:
    """存一份报告，文件名带时间和标签。"""
    now = now or datetime.now()
    where.mkdir(parents=True, exist_ok=True)
    tag = "".join(c for c in label if c.isalnum() or c in "-_")[:40]
    path = where / (now.strftime("%Y-%m-%d-%H%M%S") + (f"-{tag}" if tag else "") + ".json")
    body = {
        "at": now.isoformat(timespec="seconds"),
        "label": label,
        "rows": [asdict(r) for r in rows],
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1))
    return path


def load(path: Path) -> list[Row]:
    return [Row(**r) for r in json.loads(path.read_text())["rows"]]


def baseline(where: Path = REPORTS, before: Path | None = None) -> tuple[list[Row], list[str]]:
    """对比的基准：每一轮取最近一次跑过它的结果（只跑过一部分的那次不挡住更早的完整那次）；
    返回这些轮和用到的报告名。before 是这次刚存的那份，不算；坏掉的报告跳过。"""
    found = sorted(p for p in where.glob("*.json") if p != before) if where.exists() else []
    if before is not None:
        found = [p for p in found if p.name < before.name]
    got: dict[tuple[str, int], Row] = {}
    used: list[str] = []
    for p in reversed(found):
        try:
            rows = load(p)
        except (ValueError, KeyError, TypeError):
            continue
        fresh = [r for r in rows if r.key not in got]
        if fresh:
            used.append(p.name)
            got.update({r.key: r for r in fresh})
    return list(got.values()), used


@dataclass
class Diff:
    worse: list[tuple[Row, Row]] = field(default_factory=list)  # 上次符合、这次不符合
    better: list[tuple[Row, Row]] = field(default_factory=list)
    still_bad: list[Row] = field(default_factory=list)
    added: list[Row] = field(default_factory=list)  # 这次才有的轮
    removed: list[Row] = field(default_factory=list)
    secs: tuple[float, float] = (0.0, 0.0)  # 两边都有的轮：上次、这次的总耗时

    @property
    def regressed(self) -> bool:
        return bool(self.worse)


def compare(old: Sequence[Row], new: Sequence[Row]) -> Diff:
    """只比两边都跑了的轮的符不符合；耗时也只算两边都有的轮（只跑了一部分时不失真）。"""
    before = {r.key: r for r in old}
    after = {r.key: r for r in new}
    d = Diff()
    t_old = t_new = 0.0
    for key, r in after.items():
        o = before.get(key)
        if o is None:
            d.added.append(r)
            continue
        t_old, t_new = t_old + o.secs, t_new + r.secs
        if o.ok and not r.ok:
            d.worse.append((o, r))
        elif not o.ok and r.ok:
            d.better.append((o, r))
        elif not r.ok:
            d.still_bad.append(r)
    d.removed = [o for k, o in before.items() if k not in after]
    d.secs = (round(t_old, 1), round(t_new, 1))
    return d


def render(d: Diff, old_name: str) -> str:
    def name(r: Row) -> str:
        return f"{r.case} 第 {r.turn} 轮（{r.say[:30]}）"

    out = [f"和以前的结果比（{old_name}）"]
    out += [f"  ✗ 变差：{name(n)}：" + "；".join(n.bad) for _, n in d.worse]
    out += [f"  ✓ 变好：{name(n)}" for _, n in d.better]
    out += [f"  · 还是不符合：{name(r)}" for r in d.still_bad]
    if d.added:
        out.append("  + 新加：" + "、".join(sorted({r.case for r in d.added})))
    gone = sorted({r.case for r in d.removed})
    if gone:  # 只跑一部分时会很多：多了只说条数
        out.append("  - 这次没跑：" + ("、".join(gone) if len(gone) <= 5 else f"{len(gone)} 条"))
    a, b = d.secs
    if a:
        out.append(f"  耗时（两边都跑的轮）：{a:.0f} 秒 → {b:.0f} 秒（{(b - a) / a:+.0%}）")
    if not (d.worse or d.better or d.still_bad):
        out.append("  符不符合都和上次一样")
    return "\n".join(out)


def exit_code(rows: Sequence[Row], diff: Diff | None) -> int:
    """有变差 1；没变差但有不符合 3；都符合 0。"""
    if diff is not None and diff.regressed:
        return 1
    return 0 if all(r.ok for r in rows) else 3
