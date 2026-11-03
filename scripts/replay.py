"""重放清单（spec [2026-10-23] §62 需求 1 及 10-29 修改、§138）：在本机服务上用重放账号逐条跑真实模型，
打印每一轮的回答和是否符合期望；跑完删掉这次建的会话、取消留下的预览，并清空重放账号的 iron-m 数据。
清单里的后台用例（到期复查、练完定下次）在本进程里用内存存储跑，不登录、不碰账号和数据库。
每次跑完在 evals/replay/reports/ 留一份报告，并和以前的结果比（每轮取最近一次跑过它的）：
有变差的退出码为 1，对话用例中途出错为 2，没变差但有不符合的为 3。

用法：.venv/bin/python scripts/replay.py [--only 条目编号 ...] [--wait 秒] [--label 标签]
      [--against 报告文件] [--agent-only | --no-agent]
需要 .env 里的 DEEPSEEK_API_KEY；跑对话用例还要 REPLAY_EMAIL、REPLAY_CODE（重放账号的预设验证码）、PG_PASSWORD。
只碰重放账号：登录成了别的账号、或账号是演示账号时直接停下。花真实模型的钱，不进每次提交的标准检查。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.replay.report import Row, baseline, compare, exit_code, load, render, save  # noqa: E402

BASE = os.environ.get("REPLAY_BASE", "http://127.0.0.1:18090")  # 自测另起的端口可以用环境变量指定
CASES = ROOT / "evals" / "replay" / "cases.yaml"
NOT_REPLAY = {"you@mirobody.ai", "mom@mirobody.ai"}  # 演示账号：重放绝不用
KEEP_TABLES = {"ironm_turn_trace"}  # 运行轨迹保留，方便事后看
MIN_BALANCE = 1.0  # 元
WAIT = 20  # 每条结束后等后台写完（和 §51 的等待上限一致），再清空进入下一条


def load_env() -> None:
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def call(
    method: str, path: str, body: Any = None, token: str | None = None, timeout: int = 60
) -> Any:
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(3):
        req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise
            wait = min(int(e.headers.get("Retry-After") or 60), 90)  # 服务限流：照它说的等
            print(f"  （服务限流，等 {wait} 秒再试）")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def preflight(server: bool = True) -> str | None:
    """开头检查：服务起没起（只跑后台用例时不用）、模型余额够不够。返回停下的原因。"""
    if server:
        try:
            call("GET", "/iron/", timeout=5)
        except (urllib.error.URLError, OSError):
            return f"本机服务没起（{BASE}）：先运行 scripts/run_mirobody.sh"
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        return ".env 里没有 DEEPSEEK_API_KEY"
    req = urllib.request.Request("https://api.deepseek.com/user/balance",
                                 headers={"Authorization": f"Bearer {key}"})  # fmt: skip
    try:
        info = json.load(urllib.request.urlopen(req, timeout=15))
    except (urllib.error.URLError, OSError, ValueError):
        return "查不到模型余额（网络或密钥问题），先不跑"
    cny = sum(float(x.get("total_balance") or 0) for x in info.get("balance_infos", [])
              if x.get("currency") == "CNY")  # fmt: skip
    if not info.get("is_available") or cny < MIN_BALANCE:
        return f"模型余额不够（{cny:.2f} 元，至少要 {MIN_BALANCE:.0f} 元）"
    print(f"模型余额 {cny:.2f} 元")
    return None


def login() -> tuple[str, str]:
    email, code = os.environ.get("REPLAY_EMAIL", ""), os.environ.get("REPLAY_CODE", "")
    if not email or not code:
        sys.exit("停下：.env 里没有 REPLAY_EMAIL / REPLAY_CODE")
    if email in NOT_REPLAY:
        sys.exit("停下：REPLAY_EMAIL 是演示账号，重放只能用专门的重放账号")
    call("POST", "/email/login", {"email": email})
    data = json.load(call("POST", "/email/verify", {"email": email, "code": code}))
    token = str(data["data"]["access_token"])
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    user_id = str(claims.get("sub") or "")
    if not user_id or user_id == "1":
        sys.exit("停下：登录到的不是重放账号")
    return token, user_id


def db() -> Any:
    import psycopg
    import yaml

    # 预置记忆要用库里的 encrypt_content：和本机服务一样，密钥取环境变量，没有就取 mirobody 的 config.yaml
    key = os.environ.get("PG_ENCRYPTION_KEY") or str(
        (yaml.safe_load((ROOT / "vendor" / "mirobody" / "config.yaml").read_text()) or {}).get(
            "PG_ENCRYPTION_KEY", ""
        )
    )
    return psycopg.connect(
        f"postgresql://ironm:{os.environ['PG_PASSWORD']}@127.0.0.1:55432/mirobody",
        autocommit=True,
        options=f"-c app.encryption_key={key}" if key else "",
    )


def reset(user_id: str) -> int:
    """清空重放账号在 iron-m 各表里的数据（只按这个账号的编号删）。返回删了几行。"""
    with db() as c:
        tables = [r[0] for r in c.execute(
            "SELECT table_name FROM information_schema.columns WHERE column_name = 'user_id'"
            " AND table_schema = 'public' AND table_name LIKE 'ironm%%'"
        ).fetchall() if r[0] not in KEEP_TABLES]  # fmt: skip
        return sum(
            c.execute(f'DELETE FROM "{t}" WHERE user_id = %s', (user_id,)).rowcount for t in tables
        )


def illness_rows(user_id: str) -> int:
    with db() as c:
        return int(
            c.execute(
                "SELECT count(*) FROM ironm_illness WHERE user_id = %s", (user_id,)
            ).fetchone()[0]
        )


def ask(
    token: str, session_id: str, text: str
) -> tuple[str, list[dict[str, str]], list[str], float]:
    """问一句：返回回答正文、这一轮的预览卡片（种类、编号）、过程里显示的步骤、耗时。"""
    start = time.perf_counter()
    resp = call(
        "POST", "/api/chat", {"question": text, "session_id": session_id}, token, timeout=300
    )
    answer, cards, steps = "", [], []
    for raw in resp:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        b = json.loads(line[5:])
        if b.get("type") == "text":
            answer += b.get("text", "")
        elif b.get("type") == "tool_call" and str(b.get("id", "")).startswith("card-"):
            args = b.get("args") or {}
            cards.append({"kind": str(args.get("kind", "")), "draft": str(args.get("draft", ""))})
        elif b.get("type") == "tool_call" and b.get("name"):
            steps.append(str(b["name"]))
    return answer.strip(), cards, steps, time.perf_counter() - start


def active_events(user_id: str) -> int:
    """重放账号现在有效的近况条数（§73：同一件事说几遍只有一条），只数条数、不读内容。"""
    with db() as c:
        return int(c.execute(
            "SELECT count(*) FROM ironm_memory WHERE user_id = %s AND category = 'event'"
            " AND status = 'active'", (user_id,),
        ).fetchone()[0])  # fmt: skip


def memory_keys(user_id: str) -> set[str]:
    """重放账号有效记忆的键（伤病"部位+左右"、特殊情况代码，§148；键是明文，不读内容）。"""
    with db() as c:
        rows = c.execute(
            "SELECT key FROM ironm_memory WHERE user_id = %s AND status IN ('active', 'pending')"
            " AND key IS NOT NULL", (user_id,),
        ).fetchall()  # fmt: skip
    return {str(r[0]) for r in rows}


def seed_memories(user_id: str, rows: list[dict[str, Any]]) -> None:
    """预置记忆（§154）：推测的、很久没确认的、系统生成的该问的；days 是几天前说的（也是更新日期）；
    跟进没写 until 的今天到期。"""
    with db() as c:
        for r in rows:
            c.execute(
                "INSERT INTO ironm_memory (id, user_id, category, content, evidence, origin, status,"
                " supersedes, until, created_at, updated_at, data, key) VALUES (%s, %s, %s,"
                " encrypt_content(%s), encrypt_content(%s), %s, %s, NULL, %s,"
                " now() - make_interval(days => %s), now() - make_interval(days => %s),"
                " CASE WHEN %s::text IS NULL THEN NULL ELSE encrypt_content(%s) END, %s)",
                (r["id"], user_id, r["category"], r["content"], r.get("evidence", r["content"]),
                 r.get("origin", "said"), r.get("status", "active"),
                 r.get("until") or (date.today().isoformat() if r["category"] == "followup" else None),
                 int(r.get("days", 0)), int(r.get("days", 0)),
                 json.dumps(r["data"], ensure_ascii=False) if r.get("data") else None,
                 json.dumps(r["data"], ensure_ascii=False) if r.get("data") else None, r.get("key")),
            )  # fmt: skip


def old_memories(user_id: str) -> dict[str, int]:
    """有效记忆里 30 天以上没更新（没确认）的，按类别数条数（§154），不读内容。"""
    with db() as c:
        rows = c.execute(
            "SELECT category, count(*) FROM ironm_memory WHERE user_id = %s AND status = 'active'"
            " AND updated_at < now() - interval '30 days' GROUP BY category", (user_id,),
        ).fetchall()  # fmt: skip
    return {str(k): int(n) for k, n in rows}


def memories(user_id: str) -> dict[str, int]:
    """重放账号现在有效的记忆，按类别数条数（§145），只数条数、不读内容。"""
    with db() as c:
        rows = c.execute(
            "SELECT category, count(*) FROM ironm_memory WHERE user_id = %s AND status = 'active'"
            " GROUP BY category", (user_id,),
        ).fetchall()  # fmt: skip
    return {str(k): int(n) for k, n in rows}


def official_of(token: str) -> dict[str, Any]:
    """正式目标：档案里的目标类型、目标表的目标体重（§151）。"""
    prof = json.load(call("GET", "/iron/api/profile", token=token)).get("profile") or {}
    goal = json.load(call("GET", "/iron/api/goal", token=token)).get("goal") or {}
    return {"type": prof.get("goal"), "weight": goal.get("value")}


def judge(
    turn: dict[str, Any],
    answer: str,
    cards: list[dict[str, str]],
    ill: int | None,
    events: int | None = None,
    mem: dict[str, int] | None = None,
    keys: set[str] | None = None,
    gear: set[str] | None = None,
    official: dict[str, Any] | None = None,
    undone: dict[str, Any] | None = None,
    old: dict[str, int] | None = None,
) -> list[str]:
    """不符合的地方；空列表就是符合。"""
    bad = []
    for group in turn.get("must") or []:
        if not any(w in answer for w in group):
            bad.append("没说到「" + " / ".join(group) + "」")
    bad += [f"出现了「{w}」" for w in turn.get("must_not") or [] if w in answer]
    want = turn.get("card")
    kinds = [c["kind"] for c in cards]
    if want == "none" and kinds:
        bad.append(f"不该出卡片，出了 {kinds}")
    elif want in ("plan", "log", "goal") and want not in kinds:
        bad.append(f"该出{want}卡片，没出")
    if "illness" in turn and ill != turn["illness"]:
        bad.append(f"生病记录应有 {turn['illness']} 条，实际 {ill} 条")
    if "events" in turn and events != turn["events"]:
        bad.append(f"有效近况应有 {turn['events']} 条，实际 {events} 条")
    for cat, n in (turn.get("memory") or {}).items():
        got = (mem or {}).get(cat, 0)
        if got != n:
            bad.append(f"有效的 {cat} 记忆应有 {n} 条，实际 {got} 条")
    bad += [
        f"应有记忆键 {k}，没有" for k in turn.get("memory_keys") or [] if k not in (keys or set())
    ]
    for name, want_v in (
        turn.get("official") or {}
    ).items():  # 正式目标（§151）：档案的类型、目标表的体重
        got_v = (official or {}).get(name)
        if got_v != want_v:
            bad.append(f"正式目标的 {name} 应是 {want_v}，实际 {got_v}")
    for name, want_v in (turn.get("undone") or {}).items():
        got_v = (undone or {}).get(name)
        if got_v != want_v:
            bad.append(f"撤销后正式目标的 {name} 应是 {want_v}，实际 {got_v}")
    for cat, n in (turn.get("old") or {}).items():  # 很久没确认的（§154）
        got = (old or {}).get(cat, 0)
        if got != n:
            bad.append(f"30 天以上没确认的 {cat} 记忆应有 {n} 条，实际 {got} 条")
    lack = [g for g in turn.get("gear") or [] if g not in (gear or set())]
    if lack:
        bad.append("器械页少了 " + "、".join(lack))
    asks = answer.count("？") + answer.count("?")
    if "asks" in turn and asks > turn["asks"]:
        bad.append(f"问题最多 {turn['asks']} 个，实际 {asks} 个")
    return bad


def run_case(case: dict[str, Any], profile: dict[str, Any], token: str, user_id: str,
             made: dict[str, Any]) -> list[Row]:  # fmt: skip
    print(f"\n{'=' * 72}\n【{case['id']}】{case['from']}")
    print(f"  清空重放账号的 iron-m 数据：{reset(user_id)} 行")
    call("PUT", "/iron/api/profile", profile, token)
    setup = case.get("setup") or {}
    if "checkin" in setup:
        call("POST", "/iron/api/workouts", setup["checkin"], token)
        print("  准备：今天已打卡")
    if "memories" in setup:
        seed_memories(user_id, setup["memories"])
        print(f"  准备：预置 {len(setup['memories'])} 条记忆")
    session_id = str(json.load(call("POST", "/api/session", {}, token))["data"]["session_id"])
    made["sessions"].append(session_id)
    rows: list[Row] = made.setdefault("rows", [])  # 跑完一轮记一轮：中途出错时前面的轮照样进报告
    start = len(rows)
    for n, turn in enumerate(case["turns"], 1):
        if turn.get("new_session"):  # 换一个会话接着聊（§73 会话摘要）：先等后台写完摘要
            time.sleep(int(turn.get("pause", 20)))
            session_id = str(
                json.load(call("POST", "/api/session", {}, token))["data"]["session_id"]
            )
            made["sessions"].append(session_id)
            print(f"{'-' * 72}\n（换了一个新会话）")
        answer, cards, steps, secs = ask(token, session_id, turn["say"])
        made["drafts"] += [c["draft"] for c in cards if c["draft"]]
        if turn.get(
            "confirm"
        ):  # 确认这一轮的计划、改目标预览，后面几轮在它上面接着说（§120、§151）
            for c in cards:
                if c["kind"] in ("plan", "goal") and c["draft"]:
                    call("POST", f"/iron/api/drafts/{c['draft']}/confirm", {}, token)
        ill = illness_rows(user_id) if "illness" in turn else None
        if any(k in turn for k in ("events", "memory", "memory_keys", "gear", "old")):
            time.sleep(3)  # 当场写的记忆在回答之后
        events = active_events(user_id) if "events" in turn else None
        mem = memories(user_id) if "memory" in turn else None
        old = old_memories(user_id) if "old" in turn else None
        keys = memory_keys(user_id) if "memory_keys" in turn else None
        gear = None
        if "gear" in turn:  # 器械页看到的（§150：读字段，和他在页面上看到的一样）
            got = json.load(call("GET", "/iron/api/gear", token=token))
            gear = {*got.get("gear", []), *got.get("custom", [])}
        official = official_of(token) if "official" in turn else None
        undone = None
        if "undone" in turn:  # 撤销这一轮确认的改目标，看是否恢复成原来的（§151）
            for c in cards:
                if c["kind"] == "goal" and c["draft"]:
                    call("POST", f"/iron/api/drafts/{c['draft']}/undo", {}, token)
            undone = official_of(token)
        bad = judge(turn, answer, cards, ill, events, mem, keys, gear, official, undone, old)
        rows.append(Row(case=case["id"], turn=n, say=turn["say"], ok=not bad, bad=bad, secs=round(secs, 1),
                        answer=answer, cards=[c["kind"] for c in cards], tools=steps))  # fmt: skip
        print(f"{'-' * 72}\n问：{turn['say']}（{secs:.1f} 秒）")
        print("答：" + answer.replace("\n", "\n    "))
        if cards:
            print("卡片：" + "、".join(c["kind"] for c in cards))
        print("→ 符合" if not bad else "→ 不符合：" + "；".join(bad))
    made["cancelled"] += cancel(
        token, made["drafts"]
    )  # 下一条开始前会清空数据：这条的预览现在就取消
    made["drafts"] = []
    return rows[start:]


def cancel(token: str, drafts: list[str]) -> int:
    n = 0
    for draft in drafts:
        try:
            call("POST", f"/iron/api/drafts/{draft}/cancel", {}, token)
            n += 1
        except urllib.error.HTTPError:
            pass  # 已经确认、取消或过期的不管
    return n


def cleanup(token: str, user_id: str, made: dict[str, Any]) -> None:
    cancelled = made["cancelled"] + cancel(token, made["drafts"])
    deleted = []
    for session_id in made["sessions"]:  # 只删这次建的会话
        resp = json.load(call("POST", "/api/history/delete", {"session_id": session_id}, token))
        if resp.get("code", 0) == 0:
            deleted.append(session_id)
    rows = reset(user_id)
    print(f"\n清理：取消预览 {cancelled} 张；删掉会话 {len(deleted)} 个：{', '.join(deleted) or '无'}；"
          f"清空重放账号的 iron-m 数据 {rows} 行")  # fmt: skip


def models_used(config: Any) -> dict[str, str]:
    """报告里记的：每个环节用的模型（开没开思考），不含密钥（§142）。"""
    out = {}
    for stage in ("route", "expert", "compose", "memory", "coach"):
        r = config.route(stage)
        think = (r.extra_body.get("thinking") or {}).get("type", "")
        out[stage] = r.model + ("（思考）" if think == "enabled" else "")
    return out


def run_agent(cases: list[dict[str, Any]], profile: dict[str, Any], config: Any) -> list[Row]:
    """后台用例：本进程内存存储 + 真实模型（§138 需求 1）；config 是这次用的模型配置（§142）。"""
    import asyncio

    from evals.replay.agent import run_case as run_agent_case
    from ironm_agent.llm import TurnLLM
    from ironm_agent.metrics import Profile

    me = Profile(**{**profile, "birth": date.fromisoformat(str(profile["birth"]))})
    rows = []
    for case in cases:
        print(f"\n{'=' * 72}\n【{case['id']}】{case.get('from', '')}（后台）")
        res = asyncio.run(run_agent_case(case, me, TurnLLM(config, os.environ)))
        print(f"工具：{'、'.join(res.tools) or '没调'}（{res.secs:.1f} 秒）")
        print("结果：" + json.dumps(res.detail, ensure_ascii=False)[:400])
        print("说明：" + (res.answer or "（无）"))
        print("→ 符合" if not res.bad else "→ 不符合：" + "；".join(res.bad))
        rows.append(Row(case=res.id, turn=1, say=res.say, kind="agent", ok=not res.bad, bad=res.bad,
                        secs=round(res.secs, 1), answer=res.answer, tools=res.tools, detail=res.detail))  # fmt: skip
    return rows


def finish(
    rows: list[Row], label: str, against: str | None, meta: dict[str, Any] | None = None
) -> int:
    """存报告、和以前的结果比、打印汇总；返回退出码。"""
    path = save(rows, label, meta=meta)
    if against:
        old, names = load(Path(against)), [Path(against).name]
    else:
        old, names = baseline(before=path)
    print(f"\n{'=' * 72}\n汇总（报告：{path.relative_to(ROOT)}）")
    by_case: dict[str, list[Row]] = {}
    for r in rows:
        by_case.setdefault(r.case, []).append(r)
    for cid, rs in by_case.items():
        ok = sum(r.ok for r in rs)
        print(f"  {'✓' if ok == len(rs) else '✗'} {cid}：{ok}/{len(rs)} 轮符合")
    diff = None
    if not old:
        print("\n还没有以前的报告，这次作为以后对比的起点")
    else:
        diff = compare(old, rows)
        where = (
            names[0]
            if len(names) == 1
            else f"每轮最近一次，来自 {len(names)} 份报告，最新 {names[0]}"
        )
        print("\n" + render(diff, where))
    return exit_code(rows, diff)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", nargs="*", default=None, help="只跑这几条（条目编号）")
    p.add_argument("--wait", type=int, default=WAIT, help="每条之间等后台写完的秒数")
    p.add_argument("--label", default="", help="报告文件名里的标签")
    p.add_argument(
        "--models", default=None, help="后台用例换这份模型配置跑（默认 config/models.yaml，§142）"
    )
    p.add_argument("--against", default=None, help="只和这一份报告比（默认每轮取最近一次跑过它的）")
    side = p.add_mutually_exclusive_group()
    side.add_argument(
        "--agent-only", action="store_true", help="只跑后台用例（不用重放账号和本机服务）"
    )
    side.add_argument("--no-agent", action="store_true", help="不跑后台用例")
    args = p.parse_args()
    load_env()
    spec = yaml.safe_load(CASES.read_text())
    ids = [c["id"] for c in [*spec["cases"], *(spec.get("agent") or [])]]
    if len(ids) != len(set(ids)):
        sys.exit("停下：清单里有重复的条目编号（对话和后台用例也不能重名）")
    from ironm_agent.llm import MODELS_PATH, load_models

    if args.models and not args.agent_only:
        sys.exit(
            "停下：--models 只换后台用例的模型，要和 --agent-only 一起用（对话用例走本机服务的配置）"
        )
    config = load_models(Path(args.models) if args.models else MODELS_PATH)
    if args.against and not Path(args.against).exists():
        sys.exit(f"停下：找不到要对比的报告 {args.against}")

    def pick(c: dict[str, Any]) -> bool:
        return not args.only or c["id"] in args.only

    cases = [] if args.agent_only else [c for c in spec["cases"] if pick(c)]
    agent = [] if args.no_agent else [c for c in spec.get("agent") or [] if pick(c)]
    if not cases and not agent:
        sys.exit("停下：没有要跑的条目")
    why = preflight(server=bool(cases))
    if cases and not (os.environ.get("REPLAY_EMAIL") and os.environ.get("REPLAY_CODE")):
        why = why or ".env 里没有 REPLAY_EMAIL / REPLAY_CODE（对话用例要用重放账号）"
    if why:
        sys.exit("停下：" + why)
    login_as = login() if cases else None  # 先登录：登不上就停在花钱之前（复核 11-03）
    rows: list[Row] = run_agent(agent, spec["profile"], config) if agent else []
    crashed = False
    if login_as is not None:
        token, user_id = login_as
        made: dict[str, Any] = {"sessions": [], "drafts": [], "cancelled": 0, "rows": []}
        try:
            for i, case in enumerate(cases):
                if i:
                    time.sleep(args.wait)
                run_case(case, spec["profile"], token, user_id, made)
        except Exception as e:  # 中途出错：已经跑完的轮照样存报告
            print(f"\n对话用例中途出错：{type(e).__name__}，已跑完的轮照样存报告")
            crashed = True
        finally:
            time.sleep(min(args.wait, 10))
            cleanup(token, user_id, made)
        rows += made["rows"]
    code = finish(rows, args.label, args.against, {"models": models_used(config)})
    sys.exit(code if code == 1 or not crashed else 2)


if __name__ == "__main__":
    main()
