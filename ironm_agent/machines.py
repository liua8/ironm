"""认器械（spec [2026-11-03] §149）：常见器械的资料（machines.yaml），和拍照识别的一层。

看照片的是可替换的一层（Looker）：现在用能看图的大模型（模型配置的"看图"环节，默认 deepseek-flash），
模型直接写器械资料，不限于清单；和清单里同一种时带上编号，页面再接图鉴里的详情。
照片只在识别时发给模型，不保存，日志不记图片和模型回的内容。
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.exercises import library
from ironm_agent.llm import LLM, ModelUnavailable, parse_json
from ironm_agent.yamlfile import load_yaml

MACHINES_PATH = Path(__file__).with_name("machines.yaml")
SURE = 0.6  # 最像的那个把握低于这个，说认不准


class Machine(ContractModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    aka: tuple[str, ...] = ()
    group: Literal["gym", "free", "cardio"]
    trains: str
    setup: tuple[str, ...] = Field(min_length=1)
    careful: tuple[str, ...] = Field(min_length=1)
    moves: tuple[str, ...] = Field(min_length=1)  # 动作库里的编号，第一个是主要动作


class MachineFile(ContractModel):
    version: str
    review: str
    machines: tuple[Machine, ...]


@cache
def machines(path: Path = MACHINES_PATH) -> tuple[Machine, ...]:
    got = MachineFile.model_validate(load_yaml(path), strict=False).machines
    ids = [x.id for x in got]
    if len(ids) != len(set(ids)):
        raise ValueError("器械编号重复")
    known = {x.id for x in library().exercises}
    if bad := sorted({m for x in got for m in x.moves} - known):
        raise ValueError(f"器械列的动作不在动作库里：{bad}")
    return got


class Looker(Protocol):
    """看一张照片，写出这是什么器械；照片里没有器械时返回 None，看不了时抛 ModelUnavailable。"""

    async def look(self, image: bytes, mime: str) -> Described | None: ...


@dataclass(frozen=True)
class Described:
    """模型看照片写的器械资料（不限于清单）；match 是和清单里同一种时的编号。"""

    name: str
    aka: tuple[str, ...] = ()
    trains: str = ""
    setup: tuple[str, ...] = ()
    careful: tuple[str, ...] = ()
    moves: tuple[str, ...] = ()
    score: float = 0.0
    match: str | None = None


_ASK = (
    "你在帮健身的人认照片里的器械。看照片里最主要的那台健身器械或器材，用大白话中文写："
    "name 叫什么（常见叫法）、aka 也叫什么（0–2 个）、trains 练哪里（一句）、"
    "setup 怎么调和怎么用（2–3 条，座椅、靠垫、把手、配重）、careful 要注意（1–2 条）、"
    "moves 能用它练的动作（3–5 个；动作库里有的照抄动作库的名字，没有的写常见中文叫法）、"
    "score 你有多大把握（0 到 1）。"
    "如果和下面清单里的某一种是同一种器械，match 写它的编号，不是就写空字符串。"
    "照片里没有健身器械时 name 写空字符串。"
    '只输出 JSON：{"name": "", "aka": [], "trains": "", "setup": [], "careful": [], "moves": [], '
    '"score": 0.0, "match": ""}\n'
)


def _texts(raw: Any, n: int, size: int = 40) -> tuple[str, ...]:
    items = raw if isinstance(raw, list) else []
    return tuple(str(x).strip()[:size] for x in items if str(x).strip())[:n]


def described(raw: dict[str, Any] | None) -> Described | None:
    """模型的输出 → 器械资料；没写名字（照片里没有器械）或不是 JSON 时为 None。"""
    name = str((raw or {}).get("name") or "").strip()[:20]
    if raw is None or not name:
        return None
    try:
        score = max(0.0, min(1.0, float(raw.get("score") or 0)))
    except (TypeError, ValueError):
        score = 0.0
    match = str(raw.get("match") or "").strip()
    return Described(
        name=name,
        aka=_texts(raw.get("aka"), 2, 20),
        trains=str(raw.get("trains") or "").strip()[:40],
        setup=_texts(raw.get("setup"), 3, 60),
        careful=_texts(raw.get("careful"), 2, 60),
        moves=_texts(raw.get("moves"), 5, 20),
        score=score,
        match=match if match in {x.id for x in machines()} else None,
    )


@dataclass(frozen=True)
class ModelLooker:
    """用能看图的大模型看（模型配置的"看图"环节）。"""

    llm: LLM

    async def look(self, image: bytes, mime: str) -> Described | None:
        menu = "清单（编号：名字）：\n" + "\n".join(f"{m.id}：{m.name}" for m in machines())
        menu += "\n动作库：" + "、".join(x.name for x in library().exercises)
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        content = [
            {"type": "text", "text": _ASK + menu},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        reply = await self.llm.chat(
            "vision", [{"role": "user", "content": content}], json_mode=True
        )
        return described(parse_json(reply.content))


def looker(llm: LLM | None = None) -> Looker | None:
    """看照片用这个人自己的模型（§167）；没有模型就不看（recognize 回 no_model）。"""
    return ModelLooker(llm) if llm is not None else None


@dataclass(frozen=True)
class Recognition:
    status: Literal["no_model", "ok", "unsure", "none", "failed"]
    found: Described | None = None

    def json(self) -> dict[str, Any]:
        if self.found is None:
            return {"status": self.status}
        known = {x.name: x.id for x in library().exercises}
        f = self.found
        return {
            "status": self.status,
            "name": f.name, "aka": list(f.aka), "trains": f.trains, "setup": list(f.setup),
            "careful": list(f.careful), "score": round(f.score, 2), "match": f.match,
            "moves": [{"name": n, "id": known.get(n)} for n in f.moves],  # 动作库有的带编号，能点开
        }  # fmt: skip


async def recognize(image: bytes, mime: str, model: Looker | None = None) -> Recognition:
    """看照片写出是什么器械；把握低时为 unsure，照片里没有器械为 none，没有模型为 no_model，
    模型这次不可用（没配密钥、超时、出错）为 failed。"""
    if model is None:
        return Recognition("no_model")
    try:
        found = await model.look(image, mime)
    except ModelUnavailable:
        return Recognition("failed")
    if found is None:
        return Recognition("none")
    return Recognition("ok" if found.score >= SURE else "unsure", found)
