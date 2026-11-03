"""伤病和特殊情况的结构化字段（spec [2026-10-23] §148，记忆结构第 1 步）。

伤病、孕期这类特殊情况以前只有一句话，十几处读的地方各自用正则拆部位和情况。现在写入时就存成字段：
- 伤病：部位（关节编码，可多个）、左右、类型、哪些动作会疼、不能做什么、轻重；一句话里同时说了特殊情况
  （"怀孕 20 周，最近腰疼"）的，特殊情况的代码也带在这一条上，风险提醒照样读得到；
- 特殊情况：代码（孕期、心脏病、糖尿病、高血压、近期手术），一句话里说了几种就带几种。
管家交的字段要和原话对得上（防编）；没给字段的（后台提取、旧的写法）写入时按内容补一次，读到还没补的当场补。
读的地方只读字段；补不出的（只说了体态等）照旧按句子认。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

INJURY = "injury"
SPECIAL = "special"
STRUCTURED = (INJURY, SPECIAL)

# 键是身体部位编码表（body_codes.yaml）里的关节编码；和 protools.movement.JOINT_NAMES 一致
PARTS: dict[str, re.Pattern[str]] = {
    "joint.knee": re.compile(r"膝|半月板|髌"),
    "joint.lumbar": re.compile(r"腰|椎间盘|下背|脊柱"),
    "joint.shoulder": re.compile(r"肩"),
    "joint.wrist": re.compile(r"手腕|腕关节"),
    "joint.ankle": re.compile(r"脚踝|踝|跟腱"),
    "joint.cervical": re.compile(r"颈椎|脖子"),
    "joint.hip": re.compile(r"髋|胯|股骨头"),
    "joint.elbow": re.compile(r"手肘|肘"),
}
SIDES = ("左", "右", "两侧")
KINDS = ("旧伤", "急性", "慢性", "术后")
SEVERITIES = ("轻", "中", "重")
SPECIALS: dict[str, tuple[str, re.Pattern[str]]] = {
    "pregnancy": ("孕期", re.compile(r"怀孕|孕\s*\d+\s*周|孕期|孕妇|孕中|孕晚|孕早")),
    "cardiac": ("心脏病", re.compile(r"心脏病|冠心病|心梗|心肌梗|支架|搭桥|心衰|心律失常|房颤|心肌炎")),
    "diabetes": ("糖尿病", re.compile(r"糖尿病")),
    "hypertension": ("高血压", re.compile(r"高血压")),
    "surgery": ("近期手术", re.compile(r"手术")),
}  # fmt: skip
POSTURE = re.compile(
    r"圆肩|驼背|含胸|头前伸|探颈|富贵包|骨盆前倾|骨盆后倾|高低肩|翼状肩|X型腿|O型腿|扁平足"
)
PAIN = re.compile(r"疼|痛|伤|不舒服|酸|肿|弹响|咔咔响|响了一下|卡住|打软")
_POST_OP = re.compile(r"手术|术后|做了.{0,4}(?:修复|重建|置换)")
# "一个月左右""100 斤左右"是约数，不是左右两边（复核 11-03）；"左右膝都疼"后面跟着部位，照旧是两边
_PART_CHARS = "膝肩腕踝髋胯肘腰脚手腿臂颈脖背"
# 约数的"左右"：前面紧挨数字、时间词（"两周左右""100 斤左右"），或者后面不跟部位（复核 11-03）
_ABOUT = re.compile(
    rf"(?<=[\d一二两三四五六七八九十百千半几个天周月年岁次斤克钟时])左右|左右(?![{_PART_CHARS}])"
)
# 两边：明说"两边、两侧、双侧"，或者"双、两、左右"紧跟部位（"双膝""两个膝盖"不算：后面是"个"）
_BOTH = re.compile(rf"两边|两侧|双侧|[双两](?=[{_PART_CHARS}])|左右(?=[{_PART_CHARS}])")
MAX_LIST = 5  # 会疼的动作、不能做的各最多几条
MAX_WORDS = 20


def parts_in(text: str) -> list[str]:
    return [k for k, p in PARTS.items() if p.search(text)]


def side_in(text: str, parts: int = 1) -> str:
    """左右：约数的"左右"不算；说了"双、两边"是两侧；几个部位里有左有右（左膝、右肩）分不清是哪个，空着。"""
    t = _ABOUT.sub("", text)
    if _BOTH.search(t):
        return "两侧"
    left, right = "左" in t, "右" in t
    if left and right:
        return "两侧" if parts <= 1 else ""
    return "左" if left else "右" if right else ""


def said_side(side: str, quote: str) -> bool:
    """原话里说没说这个左右（说了才算他说的，没说是推测）。"""
    t = _ABOUT.sub("", quote)
    if side == "两侧":
        return bool(_BOTH.search(t)) or ("左" in t and "右" in t)
    return side in t


def specials_in(text: str) -> list[str]:
    return [k for k, (_, p) in SPECIALS.items() if p.search(text)]


def codes_of(data: Mapping[str, Any]) -> list[str]:
    """一条记忆带的特殊情况代码（§148 早期写成单个 code 的也认）。"""
    got = data.get("codes") or ([data["code"]] if data.get("code") else [])
    return [str(x) for x in got if str(x) in SPECIALS]


def derive(category: str, content: str) -> tuple[str, dict[str, Any]]:
    """按内容补字段（后台提取、旧的写法没给字段时；迁移也用它）。返回（类别, 字段）。
    只说了特殊情况、没说哪个部位：特殊情况类；说了部位：伤病，同一句里的特殊情况代码一起带上。"""
    if category not in STRUCTURED:
        return category, {}
    parts = parts_in(content)
    codes = specials_in(content)
    # 只说体态：去掉体态词后再没有部位（"左肩做过手术，有点圆肩"还有左肩，不算只说体态）
    posture = (bool(POSTURE.search(content)) and not PAIN.search(content)
               and not parts_in(POSTURE.sub("", content)))  # fmt: skip
    if category == SPECIAL or (codes and (not parts or posture)):
        return (SPECIAL, {"codes": codes}) if codes else (category, {})
    if posture:
        return category, {}  # 只说体态不是伤病（§108），不给部位
    data: dict[str, Any] = {"parts": parts}
    if parts:
        data["side"] = side_in(content, len(parts))
    if _POST_OP.search(content):
        data["kind"] = "术后"
        codes = [c for c in codes if c != "surgery"]  # 术后已经说明了手术，不重复带
    if codes:
        data["codes"] = codes
    return category, data


def _words(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = [str(x).strip()[:MAX_WORDS] for x in raw if str(x).strip()]
    return list(dict.fromkeys(out))[:MAX_LIST]


def _part_code(raw: Any) -> str | None:
    """关节编码或中文说法（"膝盖""腰"）都认。"""
    text = str(raw or "").strip()
    if text in PARTS:
        return text
    hit = parts_in(text)
    return hit[0] if len(hit) == 1 else None


def _given_codes(raw: Mapping[str, Any]) -> list[str]:
    got = raw.get("codes")
    if isinstance(got, list):
        return [str(x) for x in got if str(x).strip()]
    return [str(raw["code"])] if raw.get("code") else []


def structured(
    category: str, raw: Mapping[str, Any], content: str, quote: str
) -> tuple[str, dict[str, Any], str]:
    """管家交的字段：核对后返回（类别, 字段, 退回原因）；没给的按内容补。原因不为空就不记。"""
    if category not in STRUCTURED:
        return category, {}, ""
    said = f"{content}\n{quote}"
    given = _given_codes(raw)
    for code in given:
        if code not in SPECIALS:
            return category, {}, "特殊情况的代码不对（孕期、心脏病、糖尿病、高血压、近期手术）"
        if not SPECIALS[code][1].search(said):
            return category, {}, "特殊情况和原话对不上"
    if category == SPECIAL:
        codes = list(dict.fromkeys(given or specials_in(said)))
        return (SPECIAL, {"codes": codes}, "") if codes else (category, {}, "认不出是哪种特殊情况")
    cat, data = derive(category, content)
    if cat == SPECIAL:  # 说的是特殊情况、没说部位（"有高血压"）：照特殊情况记
        return cat, {"codes": list(dict.fromkeys(data["codes"] + given))}, ""
    got = raw.get("parts")
    if got not in (None, [], ""):  # 给了空的当作没给，用按内容认的（复核 11-03）
        picked = [_part_code(x) for x in (got if isinstance(got, list) else [got])]
        if any(c is None for c in picked):
            return category, {}, "部位要写关节：肩、手肘、手腕、颈椎、腰椎、髋、膝、踝"
        if [c for c in picked if c and not PARTS[c].search(said)]:
            return category, {}, "部位和原话对不上"
        data["parts"] = [c for c in dict.fromkeys(picked) if c]
    side = str(raw.get("side") or "")
    if side:
        if side not in SIDES:
            return category, {}, "左右写左、右或两侧"
        data["side"] = side
    for name, allowed in (("kind", KINDS), ("severity", SEVERITIES)):
        v = str(raw.get(name) or "")
        if v:
            if v not in allowed:
                return category, {}, f"{name} 只能写 {'、'.join(allowed)}"
            data[name] = v
    for name in ("triggers", "avoid"):
        if words := _words(raw.get(name)):
            data[name] = words
    if given:  # 伤病带了特殊情况（"左膝半月板手术后"）：部位留着，代码一起带上（复核 11-03）
        data["codes"] = list(dict.fromkeys([*codes_of(data), *given]))
        if "surgery" in given and data.get("parts"):
            data.setdefault("kind", "术后")
    if not data.get("parts"):
        data.pop("side", None)
    return category, data, ""


def key_of(category: str, data: Mapping[str, Any]) -> str:
    """同一件事的键：伤病是"部位+左右"，特殊情况是代码；部位认不出的伤病没有键（不自动合并）。"""
    if category == SPECIAL and codes_of(data):
        return "special:" + "+".join(sorted(codes_of(data)))
    if category == INJURY and data.get("parts"):
        return f"injury:{'+'.join(sorted(data['parts']))}:{data.get('side') or ''}"
    return ""


def describe(data: Mapping[str, Any]) -> str:
    """给人看的字段（训练记录器、档案里补在那句话后面）：左膝盖，旧伤，深蹲会疼，不做跳跃。"""
    from ironm_agent.protools.movement import JOINT_NAMES

    specials = "、".join(SPECIALS[c][0] for c in codes_of(data))
    names = "、".join(JOINT_NAMES.get(p, p) for p in data.get("parts") or [])
    bits = [f"{data.get('side') or ''}{names}" if names else ""]
    bits += [str(data.get("kind") or ""), str(data.get("severity") or "")]
    if data.get("triggers"):
        bits.append("、".join(data["triggers"]) + "会疼")
    if data.get("avoid"):
        bits.append("不做" + "、".join(data["avoid"]))
    bits.append(specials)
    return "，".join(b for b in bits if b)


def injured(items: Sequence[Any]) -> list[str]:
    """有效伤病的部位（读字段；没字段的旧记忆按句子认）。"""
    out: list[str] = []
    for x in items:
        if x.category != INJURY or x.status != "active":
            continue
        data = getattr(x, "data", None) or {}
        if data:
            out += list(data.get("parts") or [])
        elif not (POSTURE.search(x.content) and not PAIN.search(x.content)):
            out += parts_in(x.content)
    return list(dict.fromkeys(out))
