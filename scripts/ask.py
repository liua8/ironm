"""用演示账号向本机 mirobody 提问，打印每一轮的过程与回答（看问答效果用）。

用法：.venv/bin/python scripts/ask.py "问题一" "问题二" ...
同一次运行里的问题在同一个会话中，可以测试指代（"那它的替代动作呢"）。
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from typing import Any

BASE = "http://127.0.0.1:18090"


def _post(path: str, body: dict[str, Any], token: str | None = None) -> Any:
    headers = {"content-type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST", headers=headers)
    return urllib.request.urlopen(req, timeout=300)


def login() -> str:
    _post("/email/login", {"email": "you@mirobody.ai"})
    data = json.load(_post("/email/verify", {"email": "you@mirobody.ai", "code": "111111"}))
    return str(data["data"]["access_token"])


def new_session(token: str) -> str:
    """和网页一样，先建会话（点开引用时要用到会话记录）。"""
    data = json.load(_post("/api/session", {}, token))
    return str(data["data"]["session_id"])


def ask(token: str, question: str, session_id: str) -> None:
    start = time.perf_counter()
    resp = _post("/api/chat", {"question": question, "session_id": session_id}, token)
    print(f"\n{'=' * 70}\n问：{question}\n{'-' * 70}")
    text = ""
    for raw in resp:
        line = raw.decode().strip()
        if not line.startswith("data:"):
            continue
        b = json.loads(line[5:])
        kind = b.get("type")
        if kind == "tool_call":
            task = (b.get("args") or {}).get("任务", "")
            print(f"[{b.get('name')}] 开始" + (f"：{task}" if task else ""))
        elif kind == "tool_result":
            body = str(b.get("content", "")).replace("\n", " | ")
            print(f"   └ {body[:300]}")
        elif kind == "notice":
            print(f"（提示）{b.get('text')}")
        elif kind == "error":
            print(f"（出错）{b.get('message')}")
        elif kind == "text":
            text += b.get("text", "")
    print(f"{'-' * 70}\n{text}\n（用时 {time.perf_counter() - start:.1f} 秒）")


def main() -> None:
    token = login()
    session = new_session(token)
    for q in sys.argv[1:]:
        ask(token, q, session)


if __name__ == "__main__":
    main()
