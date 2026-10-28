"""身体部位编码表（spec [2026-10-23] §57 需求 1）：部位 → 肌群 → 细分肌肉，关节挂在部位下。

读入 body_codes.yaml 并校验：编码不重复、上级存在且层级对、同一个说法只指一个编码。查说法时先抹掉
全角半角、大小写和空格，只认表里写了的说法，查不到返回 None，不猜。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import Field

from ironm_agent.common import ContractModel
from ironm_agent.yamlfile import load_yaml

CODES_PATH = Path(__file__).with_name("body_codes.yaml")

type Level = Literal["part", "group", "muscle", "joint"]
# 每层的上级只能是哪一层
PARENT_LEVEL: dict[str, str | None] = {
    "part": None,
    "group": "part",
    "muscle": "group",
    "joint": "part",
}


class Node(ContractModel):
    code: str = Field(pattern=r"^(part|group|muscle|joint)\.[a-z_]+$")
    level: Level
    name: str
    parent: str | None = None
    formal: str = ""
    fedb: str = ""
    uberon: str = Field(default="", pattern=r"^(UBERON:\d{7})?$")
    says: tuple[str, ...] = ()
    model: tuple[str, ...] = ()  # 3D 人体图模型里对应的分区（只有细分肌肉写）


class CodeFile(ContractModel):
    version: str
    review: str
    nodes: tuple[Node, ...]


def fold(text: str) -> str:
    """查说法前的统一写法：全角转半角、不分大小写、去掉空格。"""
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


class BodyTable:
    def __init__(self, nodes: tuple[Node, ...]) -> None:
        self.nodes: dict[str, Node] = {}
        for n in nodes:
            if n.code in self.nodes:
                raise ValueError(f"编码重复：{n.code}")
            if not n.code.startswith(n.level + "."):
                raise ValueError(f"编码和层级对不上：{n.code}")
            self.nodes[n.code] = n
        regions = [r for n in nodes for r in n.model]
        if len(regions) != len(set(regions)):
            raise ValueError("模型分区重复对应")
        if any(n.model for n in nodes if n.level != "muscle"):
            raise ValueError("只有细分肌肉对应模型分区")
        self.kids: dict[str, list[str]] = {}
        for n in nodes:
            want = PARENT_LEVEL[n.level]
            if want is None:
                if n.parent is not None:
                    raise ValueError(f"部位不能有上级：{n.code}")
                continue
            up = self.nodes.get(n.parent or "")
            if up is None or up.level != want:
                raise ValueError(f"上级不对：{n.code} → {n.parent}")
            self.kids.setdefault(up.code, []).append(n.code)
        self.index: dict[str, str] = {}
        for n in nodes:
            for word in (n.name, n.formal, *n.says):
                if word:
                    self._add(fold(word), n.code)

    def _add(self, key: str, code: str) -> None:
        old = self.index.get(key)
        if old is None or old == code:
            self.index[key] = code
            return
        # 肌群和它唯一的同名细分肌肉可以同名，落到细分肌肉
        for group, muscle in ((old, code), (code, old)):
            if self.kids.get(group) == [muscle]:
                self.index[key] = muscle
                return
        raise ValueError(f"说法「{key}」同时指 {old} 和 {code}")

    def node(self, code: str) -> Node:
        return self.nodes[code]

    def lookup(self, word: str) -> Node | None:
        """一个说法对应的编码（落在最细的那层）；表里没有就是 None。"""
        code = self.index.get(fold(word))
        return self.nodes[code] if code else None

    def of_level(self, level: Level) -> list[Node]:
        return [n for n in self.nodes.values() if n.level == level]

    def ancestors(self, code: str) -> Iterator[Node]:
        """从上级一直到部位。"""
        up = self.nodes[code].parent
        while up:
            yield self.nodes[up]
            up = self.nodes[up].parent

    def children(self, code: str) -> list[Node]:
        return [self.nodes[c] for c in self.kids.get(code, [])]

    def muscles_under(self, code: str) -> list[Node]:
        """这个编码下面所有的细分肌肉（本身是细分肌肉就是它自己）；往上汇总、按部位筛选都用它。"""
        n = self.nodes[code]
        if n.level == "muscle":
            return [n]
        return [m for c in self.kids.get(code, []) for m in self.muscles_under(c)]

    def within(self, code: str, ancestor: str) -> bool:
        """code 是不是 ancestor 本身或在它下面。"""
        return code == ancestor or any(a.code == ancestor for a in self.ancestors(code))


@cache
def table(path: Path = CODES_PATH) -> BodyTable:
    data = CodeFile.model_validate(load_yaml(path), strict=False)
    return BodyTable(data.nodes)


def name(code: str) -> str:
    """页面和回答里用的常用名。"""
    return table().node(code).name


# §57 之前存下的名字（肌肉感受、说疼的部位）：读的时候按规则换成编码，原记录不改。
# 被拆开的三块旧名对拆出来的每一块都算；其余旧名按编码表的名字查。
LEGACY_MUSCLES: dict[str, tuple[str, ...]] = {
    "斜方肌": ("muscle.upper_traps", "muscle.mid_lower_traps"),
    "胸大肌": ("muscle.pec_major_upper", "muscle.pec_major_lower"),
    "小腿": ("muscle.gastrocnemius", "muscle.soleus", "muscle.tibialis_anterior"),
}
LEGACY_JOINTS: dict[str, str] = {
    "knee": "joint.knee", "back": "joint.lumbar", "shoulder": "joint.shoulder",
    "wrist": "joint.wrist", "ankle": "joint.ankle", "neck": "joint.cervical",
}  # fmt: skip


def muscle_codes(stored: str) -> tuple[str, ...]:
    """存下的肌肉（编码或 §57 之前的名字）对应的细分肌肉编码；认不出是空的。"""
    t = table()
    if stored in t.nodes:
        return (stored,) if t.node(stored).level == "muscle" else ()
    if stored in LEGACY_MUSCLES:
        return LEGACY_MUSCLES[stored]
    n = t.lookup(stored)
    return (n.code,) if n is not None and n.level == "muscle" else ()


def joint_code(stored: str) -> str | None:
    """存下的关节（编码或 §57 之前的 knee / back 这类）对应的编码；认不出是 None。"""
    t = table()
    if stored in t.nodes:
        return stored if t.node(stored).level == "joint" else None
    return LEGACY_JOINTS.get(stored)
