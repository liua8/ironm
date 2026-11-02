"""重放清单（spec [2026-10-23] §62 需求 1 及 10-29 修改）：在本机服务上用重放账号逐条跑真实模型，
打印每一轮的回答和是否符合期望；跑完删掉这次建的会话、取消留下的预览，并清空重放账号的 iron-m 数据。

用法：.venv/bin/python scripts/replay.py [--only 条目编号 ...] [--wait 秒]
需要 .env 里的 REPLAY_EMAIL、REPLAY_CODE（重放账号的预设验证码）、DEEPSEEK_API_KEY、PG_PASSWORD。
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
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:18090"
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


def preflight() -> str | None:
    """开头检查：服务起没起、模型余额够不够。返回停下的原因。"""
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

    return psycopg.connect(
        f"postgresql://ironm:{os.environ['PG_PASSWORD']}@127.0.0.1:55432/mirobody", autocommit=True
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


def ask(token: str, session_id: str, text: str) -> tuple[str, list[dict[str, str]], float]:
    """问一句：返回回答正文、这一轮的预览卡片（种类、编号）、耗时。"""
    start = time.perf_counter()
    resp = call(
        "POST", "/api/chat", {"question": text, "session_id": session_id}, token, timeout=300
    )
    answer, cards = "", []
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
    return answer.strip(), cards, time.perf_counter() - start


def active_events(user_id: str) -> int:
    """重放账号现在有效的近况条数（§73：同一件事说几遍只有一条），只数条数、不读内容。"""
    with db() as c:
        return int(c.execute(
            "SELECT count(*) FROM ironm_memory WHERE user_id = %s AND category = 'event'"
            " AND status = 'active'", (user_id,),
        ).fetchone()[0])  # fmt: skip


def judge(
    turn: dict[str, Any],
    answer: str,
    cards: list[dict[str, str]],
    ill: int | None,
    events: int | None = None,
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
    elif want in ("plan", "log") and want not in kinds:
        bad.append(f"该出{want}卡片，没出")
    if "illness" in turn and ill != turn["illness"]:
        bad.append(f"生病记录应有 {turn['illness']} 条，实际 {ill} 条")
    if "events" in turn and events != turn["events"]:
        bad.append(f"有效近况应有 {turn['events']} 条，实际 {events} 条")
    asks = answer.count("？") + answer.count("?")
    if "asks" in turn and asks > turn["asks"]:
        bad.append(f"问题最多 {turn['asks']} 个，实际 {asks} 个")
    return bad


def run_case(case: dict[str, Any], profile: dict[str, Any], token: str, user_id: str,
             made: dict[str, Any]) -> tuple[int, int]:  # fmt: skip
    print(f"\n{'=' * 72}\n【{case['id']}】{case['from']}")
    print(f"  清空重放账号的 iron-m 数据：{reset(user_id)} 行")
    call("PUT", "/iron/api/profile", profile, token)
    setup = case.get("setup") or {}
    if "checkin" in setup:
        call("POST", "/iron/api/workouts", setup["checkin"], token)
        print("  准备：今天已打卡")
    session_id = str(json.load(call("POST", "/api/session", {}, token))["data"]["session_id"])
    made["sessions"].append(session_id)
    ok = 0
    for turn in case["turns"]:
        if turn.get("new_session"):  # 换一个会话接着聊（§73 会话摘要）：先等后台写完摘要
            time.sleep(int(turn.get("pause", 20)))
            session_id = str(
                json.load(call("POST", "/api/session", {}, token))["data"]["session_id"]
            )
            made["sessions"].append(session_id)
            print(f"{'-' * 72}\n（换了一个新会话）")
        answer, cards, secs = ask(token, session_id, turn["say"])
        made["drafts"] += [c["draft"] for c in cards if c["draft"]]
        ill = illness_rows(user_id) if "illness" in turn else None
        if "events" in turn:
            time.sleep(3)  # 当场写的记忆在回答之后
        events = active_events(user_id) if "events" in turn else None
        bad = judge(turn, answer, cards, ill, events)
        ok += not bad
        print(f"{'-' * 72}\n问：{turn['say']}（{secs:.1f} 秒）")
        print("答：" + answer.replace("\n", "\n    "))
        if cards:
            print("卡片：" + "、".join(c["kind"] for c in cards))
        print("→ 符合" if not bad else "→ 不符合：" + "；".join(bad))
    made["cancelled"] += cancel(
        token, made["drafts"]
    )  # 下一条开始前会清空数据：这条的预览现在就取消
    made["drafts"] = []
    return ok, len(case["turns"])


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


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", nargs="*", default=None, help="只跑这几条（条目编号）")
    p.add_argument("--wait", type=int, default=WAIT, help="每条之间等后台写完的秒数")
    args = p.parse_args()
    load_env()
    spec = yaml.safe_load(CASES.read_text())
    cases = [c for c in spec["cases"] if not args.only or c["id"] in args.only]
    if not cases:
        sys.exit("停下：没有要跑的条目")
    why = preflight()
    if why:
        sys.exit("停下：" + why)
    token, user_id = login()
    made: dict[str, Any] = {"sessions": [], "drafts": [], "cancelled": 0}
    totals = []
    try:
        for i, case in enumerate(cases):
            if i:
                time.sleep(args.wait)
            totals.append((case["id"], *run_case(case, spec["profile"], token, user_id, made)))
    finally:
        time.sleep(min(args.wait, 10))
        cleanup(token, user_id, made)
    print(f"\n{'=' * 72}\n汇总")
    for cid, ok, n in totals:
        print(f"  {'✓' if ok == n else '✗'} {cid}：{ok}/{n} 轮符合")
    sys.exit(0 if all(ok == n for _, ok, n in totals) else 1)


if __name__ == "__main__":
    main()
