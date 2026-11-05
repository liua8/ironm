"""把两周快进模拟的结果（scripts/simulate.py 的 JSON）排成一页逐日报告（spec [2026-10-23] §162）。

    uv run python scripts/sim_report.py evals/sim/reports/sim-xxx.json [--notes notes.md]

每天：他做了什么、管家怎么回答、首页今天的版本和提醒、下次目标和计划跟前一天比怎么变了。
--notes 是一段人写的观察（Markdown 的段落和列表），放在最前面。输出同名 .html（不进仓库）。
"""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

WEEK = "一二三四五六日"


def esc(x: Any) -> str:
    return html.escape(str(x or ""))


def para(text: str) -> str:
    """回答原文：换行保留，编号行成列表。"""
    lines = [x for x in str(text or "").splitlines() if x.strip()]
    out, items = [], []
    for x in lines:
        if re.match(r"^\s*\d+[\.、]", x):
            items.append(f"<li>{esc(re.sub(r'^\\s*\\d+[\\.、]\\s*', '', x))}</li>")
            continue
        if items:
            out.append("<ol>" + "".join(items) + "</ol>")
            items = []
        out.append(f"<p>{esc(x)}</p>")
    if items:
        out.append("<ol>" + "".join(items) + "</ol>")
    return "".join(out)


def notes_html(md: str) -> str:
    out, items = [], []
    for x in md.splitlines():
        if x.startswith(("- ", "* ")):
            items.append(f"<li>{inline(x[2:])}</li>")
            continue
        if items:
            out.append("<ul>" + "".join(items) + "</ul>")
            items = []
        if x.startswith("### "):
            out.append(f"<h3>{inline(x[4:])}</h3>")
        elif x.startswith("## "):
            out.append(f"<h2>{inline(x[3:])}</h2>")
        elif x.strip():
            out.append(f"<p>{inline(x)}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "".join(out)


def inline(x: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(x))


def targets(day: dict[str, Any]) -> dict[str, str]:
    return {c["key"].split(":", 1)[1]: c["title"] for c in day.get("coach") or []
            if str(c.get("key", "")).startswith("target:")}  # fmt: skip


def coach_line(day: dict[str, Any], key: str) -> str:
    return next((c["title"] for c in day.get("coach") or [] if c.get("key") == key), "")


def step_html(s: dict[str, Any]) -> str:
    k = s.get("kind")
    if k == "chat":
        cards = "".join(f'<span class="tag">出了{esc(c.get("kind"))}预览卡片</span>' for c in s.get("cards") or [])
        return (f'<div class="chat"><div class="me">{esc(s["say"])}</div>'
                f'<div class="coach">{para(s["answer"])}<div class="meta">{s.get("secs")} 秒 {cards}</div></div></div>')  # fmt: skip
    if k == "confirm":
        return f'<div class="act">他点了确认：{esc(s.get("what"))}</div>'
    if k == "workout":
        if s.get("skipped"):
            return f'<div class="act">{esc(s["skipped"])}</div>'
        note = f'，备注"{esc(s["note"])}"' if s.get("note") else ""
        sets = "".join(f"<li>{esc(x)}</li>" for x in s.get("items") or [])
        return (f'<div class="act"><b>打卡：{esc(s.get("session"))}</b>（感受 {s.get("rpe")}/10{note}）'
                f"<ul class=sets>{sets}</ul></div>")  # fmt: skip
    if k == "rest":
        return f'<div class="act">打卡：今天没练（{esc(s.get("why"))}）</div>'
    if k == "proposal":
        ops = "；".join(f'{o.get("kind")} 周{WEEK[int(o.get("day", 1)) - 1]}（{o.get("why", "")}）'
                       for o in s.get("ops") or [] if isinstance(o, dict))  # fmt: skip
        tips = "".join(f"<li>{esc(t)}</li>" for t in s.get("tips") or [])
        return (f'<div class="act"><b>{esc(s.get("trigger"))}的调整方案</b>：{esc(s.get("answer"))}'
                f'{f"<div class=meta>改法：{esc(ops)}</div>" if ops else ""}{f"<ul>{tips}</ul>" if tips else ""}</div>')  # fmt: skip
    return f'<div class="act">{esc(json.dumps(s, ensure_ascii=False))}</div>'


def render(data: dict[str, Any], notes: str) -> str:
    days = data["days"]
    rows, prev_t, prev_plan = [], {}, []
    for d in days:
        n = d["n"]
        wd = WEEK[(n - 1) % 7]
        t = targets(d)
        changed_t = [f"{v}" for k, v in t.items() if prev_t.get(k) != v]
        today = coach_line(d, "today")
        alerts = [c["title"] for c in d.get("coach") or [] if str(c.get("key", "")).startswith("alert:")]
        pending = [c["title"] for c in d.get("coach") or [] if c.get("action") == "confirm"]
        side = []
        if today:
            side.append(f'<div class="kv"><span>首页·今天</span>{esc(today)}</div>')
        for a in alerts:
            side.append(f'<div class="kv warn"><span>提醒</span>{esc(a)}</div>')
        for p in pending:
            side.append(f'<div class="kv"><span>待确认</span>{esc(p)}</div>')
        steps = "".join(step_html(s) for s in d.get("steps") or [])
        # 这一天之后：下次目标、计划的变化（打卡后管家定的下次，第二天的首页能看到）
        after_t = next((s.get("targets_after") for s in reversed(d.get("steps") or [])
                        if s.get("kind") == "workout" and s.get("targets_after")), None)  # fmt: skip
        tline = "".join(f"<li>{esc(x)}</li>" for x in after_t or [])
        plan = d.get("plan_after") or []
        pchange = ""
        if d.get("plan_changed"):
            old = set(prev_plan)
            pchange = "<div class='change'><b>计划变了</b><ul>" + "".join(
                f"<li class='{'new' if x not in old else ''}'>{esc(x)}</li>" for x in plan) + "</ul></div>"  # fmt: skip
        rows.append(f"""
<section class="day"><header><span class="n">第 {n} 天</span><span class="d">{esc(d['date'])} 周{wd}</span></header>
<div class="grid"><div class="main">{steps or '<div class="act quiet">这天没做什么，只打开了首页</div>'}{pchange}
{f"<div class='change'><b>练完后管家定的下次</b><ul>{tline}</ul></div>" if tline else ""}
{f"<div class='err'>出错：{esc(d['error'])}</div>" if d.get('error') else ""}</div>
<aside>{''.join(side)}{"".join(f"<div class='kv'><span>下次目标变了</span>{esc(x)}</div>" for x in changed_t[:6])}</aside></div></section>""")
        prev_t, prev_plan = t, plan
    first_plan = next((d["plan_after"] for d in days if d.get("plan_after")), [])
    last_plan = days[-1].get("plan_after") or []
    plans = (f"<div class='plans'><div><h3>第 1 天确认的计划</h3><ul>{''.join(f'<li>{esc(x)}</li>' for x in first_plan)}</ul></div>"
             f"<div><h3>两周后的计划</h3><ul>{''.join(f'<li>{esc(x)}</li>' for x in last_plan)}</ul></div></div>")  # fmt: skip
    prof = data.get("profile") or {}
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>两周模拟报告</title><style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;--accent:#2f7d4f;--warn:#b5651d;--me:#eef4ff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;--mute:#a09f98;--line:#33332f;--accent:#6cc28f;--warn:#e3a062;--me:#1f2a3a}}}}
body{{background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans SC",sans-serif;margin:0;padding:24px 16px}}
.wrap{{max-width:1080px;margin:0 auto}} h1{{font-size:24px;margin:0 0 4px}} .sub{{color:var(--mute);margin-bottom:20px}}
.notes,.plans,.day{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}}
.plans{{display:grid;grid-template-columns:1fr 1fr;gap:16px}} .plans h3{{margin:0 0 6px;font-size:15px}} .plans ul{{margin:0;padding-left:18px}}
.day header{{display:flex;gap:10px;align-items:baseline;margin-bottom:10px}} .n{{font-weight:700;font-size:17px}} .d{{color:var(--mute)}}
.grid{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px}}
.chat .me{{background:var(--me);border-radius:10px;padding:8px 12px;margin:6px 0 6px 15%}}
.chat .coach{{border-left:3px solid var(--accent);padding:2px 12px;margin:6px 15% 10px 0}} .coach p{{margin:4px 0}} .coach ol{{margin:4px 0;padding-left:20px}}
.meta{{color:var(--mute);font-size:13px}} .tag{{background:var(--accent);color:#fff;border-radius:6px;padding:0 6px;margin-left:6px}}
.act{{margin:8px 0;padding:8px 12px;border:1px dashed var(--line);border-radius:8px}} .act.quiet{{color:var(--mute)}} .sets{{margin:4px 0;padding-left:20px}}
.change{{margin:8px 0;padding:8px 12px;background:color-mix(in srgb,var(--accent) 10%,transparent);border-radius:8px}} .change ul{{margin:4px 0;padding-left:20px}} .change li.new{{font-weight:600}}
aside .kv{{font-size:13.5px;border-bottom:1px solid var(--line);padding:6px 0}} aside .kv span{{display:block;color:var(--mute);font-size:12px}} aside .warn{{color:var(--warn)}}
.err{{color:var(--warn)}} .notes h2{{font-size:18px;margin:6px 0}} .notes h3{{font-size:15px;margin:12px 0 4px}}
@media (max-width:760px){{.grid,.plans{{grid-template-columns:1fr}} .chat .me{{margin-left:8%}} .chat .coach{{margin-right:0}}}}
</style></head><body><div class="wrap">
<h1>两周快进模拟：管家怎么调整方案</h1>
<div class="sub">假数据、内存存储、真实模型；模拟用户：男，{esc(prof.get('birth'))} 出生，{esc(prof.get('height_cm'))} 厘米，目标增肌，健身房一周三练，左膝旧伤。从 {esc(data.get('start'))}（周一）起 14 天。</div>
{f"<div class='notes'>{notes_html(notes)}</div>" if notes else ""}
{plans}
{''.join(rows)}
</div></body></html>"""


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="两周快进模拟的逐日报告")
    p.add_argument("report")
    p.add_argument("--notes", default="")
    a = p.parse_args()
    src = Path(a.report)
    notes = Path(a.notes).read_text() if a.notes else ""
    out = src.with_suffix(".html")
    out.write_text(render(json.loads(src.read_text()), notes))
    print(out)
