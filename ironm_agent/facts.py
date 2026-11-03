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
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ironm_agent.exercises import Equipment

INJURY = "injury"
SPECIAL = "special"
STRUCTURED = (INJURY, SPECIAL, "equipment", "schedule")  # §148 伤病、特殊情况，§150 器械、可练时间

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
    if category == EQUIPMENT:
        return category, derive_equipment(content)
    if category == SCHEDULE:
        return category, derive_schedule(content)
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
    if category in (EQUIPMENT, SCHEDULE):
        data, why = structured_more(category, raw, content, quote)
        return category, (data if not why else {}), why
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
    # 说了在哪练、每周几次的是完整情况；只补一句的不带键（§150）
    if category == EQUIPMENT and data.get("place"):
        return "equipment"
    if category == SCHEDULE and (data.get("per_week") or data.get("days")):
        return "schedule"
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


# ---- 器械与场地、可练时间（§150，记忆结构第 2 步）------------------------------------------------

EQUIPMENT = "equipment"
SCHEDULE = "schedule"
PLACES = ("gym", "home", "both")
_GYM = re.compile(r"健身房|健身中心|器械都有")  # 认器械时去掉这些（"健身房"不是一样器械）
_HOME = re.compile(r"家里|在家|家中|宿舍|小区")
# "在哪练"：和 latest._PLACE 一致，说了在哪练才算完整的说法（"家里还有个壶铃"只是补一样器械，复核 11-03）
_AT_GYM = re.compile(
    r"(?<![不没别])(?:在|去)[^，。；不没]{0,4}(?:健身房|健身中心)|办了?.{0,3}健身房|健身房的?卡|器械都有"
)  # "去公司健身房"也算
_AT_HOME = re.compile(
    r"在(?:家里?|宿舍)(?:练|锻炼|健身|训练|用|做|[，,；;。]|$)|居家(?:练|锻炼|健身|训练)"
)
_BOTH_PLACES = re.compile(
    r"(?:健身房|健身中心).{0,8}家.{0,4}都练|家.{0,8}健身房.{0,4}都练|两边都练"
)
# 和 protools.movement.equipment_of 认器械的说法一致
GEAR_WORDS: dict[str, re.Pattern[str]] = {
    "哑铃": re.compile(r"哑铃"), "壶铃": re.compile(r"壶铃"),
    "弹力带": re.compile(r"弹力带|拉力带|阻力带"), "杠铃": re.compile(r"杠铃"),
    "单杠": re.compile(r"单杠|引体|门框杆"),
    "器械": re.compile(r"器械|动感单车|单车|跑步机|划船机|椭圆机|龙门架|史密斯"),
}  # fmt: skip
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}
_N = "1-7一二两三四五六七"
# 每周几次："3-4 次""三到四次"按少的算；"每周三练"是周三，不是 3 次（复核 11-03）
_PER_WEEK = re.compile(
    rf"(?:每周|一周|每星期|一星期|一个礼拜|每个礼拜)[^，。；\d{_N}]{{0,4}}([{_N}])"
    rf"(?:\s*[-–~～到至]?\s*[{_N}])?\s*(?:次|天|回)"  # "两三次"按少的算
)
_DAILY = re.compile(r"每天|天天")
_WORKDAYS = re.compile(r"工作日")
_DAY_RANGE = re.compile(
    r"(?:周|星期|礼拜)([一二三四五六日])\s*(?:到|至|-|–|~)\s*(?:周|星期|礼拜)?([一二三四五六日])"
)
# 哪几天："周一三五"认全；"每周三次""两周一次"不是周三、周一
_WEEKDAY = re.compile(
    r"(?<![一二两三四五六七八九十\d])(?:周|星期|礼拜)([一二三四五六日天](?:[、和及,，]?[一二三四五六日])*)(?![次天回])"
)
_WEEKDAY_NO = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
_MINUTES = re.compile(r"(\d{1,3})\s*分钟")
_CN_MINUTES = re.compile(r"([二三四五六九]?十|十五|四十五)\s*分钟")  # 三十分钟、四十五分钟
_HOURS = re.compile(
    r"(?<![\d.])(\d(?:\.\d)?|半|一|两)\s*个?\s*(半)?\s*(?:小时|钟头)(半)?"
)  # 一个半小时、1.5 小时；"24 小时健身房"不算


def _num(raw: str) -> int:
    return int(raw) if raw.isdigit() else _CN_NUM.get(raw, 0)


def place_of(content: str) -> str:
    """说了在哪练：gym / home / both；只补一句器械（"家里还有个壶铃"）返回空。"""
    if _BOTH_PLACES.search(content):
        return "both"
    gym, home = bool(_AT_GYM.search(content)), bool(_AT_HOME.search(content))
    return "both" if gym and home else "gym" if gym else "home" if home else ""


def derive_equipment(content: str) -> dict[str, Any]:
    place = place_of(content)
    gear = [g for g, p in GEAR_WORDS.items() if p.search(_GYM.sub("", content))]
    data: dict[str, Any] = {}
    if place:
        data["place"] = place
    if gear:
        data["gear"] = gear
    return data


def derive_schedule(content: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if m := _PER_WEEK.search(content):
        data["per_week"] = _num(m.group(1))
    elif _DAILY.search(content):
        data["per_week"] = 5 if _WORKDAYS.search(content) else 7  # 工作日每天：5 次
    days = {_WEEKDAY_NO[c] for g in _WEEKDAY.findall(content) for c in g if c in _WEEKDAY_NO}
    for a, b in _DAY_RANGE.findall(content):  # 周一到周五
        lo, hi = _WEEKDAY_NO[a], _WEEKDAY_NO[b]
        if lo <= hi:
            days |= set(range(lo, hi + 1))
    if days:
        data["days"] = sorted(days)
    if m := _MINUTES.search(content):
        data["minutes"] = int(m.group(1))
    elif m := _CN_MINUTES.search(content):
        word = m.group(1)
        data["minutes"] = {"十五": 15, "四十五": 45}.get(word) or (
            _num(word[0]) * 10 if len(word) == 2 else 10
        )
    elif m := _HOURS.search(content):
        raw = m.group(1)
        hours = 0.5 if raw == "半" else float(raw) if raw[0].isdigit() else float(_num(raw) or 1)
        data["minutes"] = int(hours * 60 + (30 if m.group(2) or m.group(3) else 0))
    return data


def structured_more(
    category: str, raw: Mapping[str, Any], content: str, quote: str
) -> tuple[dict[str, Any], str]:
    """器械、可练时间：管家交的字段核对后返回（字段, 退回原因）；没给的按内容补。"""
    said = f"{content}\n{quote}"
    if category == EQUIPMENT:
        data = derive_equipment(content)
        place = str(raw.get("place") or "")
        if place:
            ok = place == place_of(said)  # 说了在哪练才算（"家里还有个壶铃"不是，复核 11-03）
            if place not in PLACES or not ok:
                return {}, "场所写 gym（健身房）、home（家里）或 both，要是他说到的"
            data["place"] = place
        got = raw.get("gear")
        if got not in (None, [], ""):
            gear = [str(x) for x in (got if isinstance(got, list) else [got])]
            if any(g not in GEAR_WORDS for g in gear):
                return {}, "器械写哑铃、壶铃、弹力带、杠铃、单杠或器械；别的写进 custom"
            if any(not GEAR_WORDS[g].search(said) for g in gear):
                return {}, "器械和原话对不上"
            data["gear"] = list(dict.fromkeys(gear))
        custom = [str(x).strip()[:12] for x in raw.get("custom") or [] if str(x).strip()]
        if any(c not in said for c in custom):
            return {}, "自己加的器材要是他说到的"
        from ironm_agent.gear import clean_custom

        custom = [c for c in clean_custom(custom) if len(c) >= 2]  # 和勾选项重名的、一个字的不要
        if custom:
            data["custom"] = custom
        return data, ""
    data = derive_schedule(content)
    heard = derive_schedule(said)
    per_week, minutes = raw.get("per_week"), raw.get("minutes")
    if per_week not in (None, ""):
        if (
            isinstance(per_week, bool)
            or not isinstance(per_week, int)
            or per_week != heard.get("per_week")
        ):
            return {}, '每周几次写 1–7，要是他说的（"每周 3 次"）'
        data["per_week"] = per_week
    got = raw.get("days")
    if got not in (None, [], ""):
        days = got if isinstance(got, list) else [got]
        named = set(heard.get("days") or [])
        if any(isinstance(d, bool) or not isinstance(d, int) or d not in named for d in days):
            return {}, "哪几天写 1–7（1 是周一），要是他说到的"
        data["days"] = sorted(set(days))
    if minutes not in (None, ""):
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 300:
            return {}, "每次多少分钟写 5–300"
        if minutes != heard.get("minutes"):
            return {}, "每次多少分钟要是他说到的"
        data["minutes"] = minutes
    return data, ""


def equipment(items: Sequence[Any]) -> frozenset[Equipment] | None:
    """他有哪些器械（排计划工具、换动作、复盘改计划、器械页、MCP 共用，§150）：读字段，没字段的旧记忆按句子认。
    说了健身房（或都有）就是器械都有；什么都没说过返回 None（不知道）。"""
    from ironm_agent.exercises import EQUIPMENT as ALL
    from ironm_agent.latest import current
    from ironm_agent.protools.movement import equipment_of

    active = [x for x in items if x.category == EQUIPMENT and x.status == "active"]
    rows = current(active)  # 生效的里面最近的为准（推测的不会把生效的挤掉，复核 11-03）
    if not rows:
        return None
    found: set[Equipment] = {"自重"}
    for x in rows:
        data = getattr(x, "data", None) or {}
        if not data:
            got = equipment_of([x.content]) or frozenset()
            if got == frozenset(ALL):
                return frozenset(ALL)
            found |= got
            continue
        if data.get("place") in ("gym", "both"):
            return frozenset(ALL)
        found |= {cast("Equipment", g) for g in data.get("gear") or [] if g in GEAR_WORDS}
        found |= set(equipment_of(data.get("custom") or []) or ())  # 划船机算健身器械，同原来
    return frozenset(found)
