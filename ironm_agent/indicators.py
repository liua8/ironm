"""问题里点到的健康指标（spec [2026-10-23] §37）：认出来后作答前由规则先查这个人的这几项数据。

只认常见的化验、体检、体征和穿戴设备指标（中文名、英文名、常见缩写）；查询时交给 mirobody 的健康记录查询，
它按关键词和自带的中英文同义词去找这个人记录里的指标，所以这里只需要认出"问到了哪个指标"，不需要标准编码。
"""

from __future__ import annotations

import re

# 长的写在前面：先认"空腹血糖"，再认"血糖"
TERMS: tuple[str, ...] = (
    # 肾功能、尿酸
    "血肌酐", "肌酐", "尿素氮", "尿素", "尿酸", "肾小球滤过率", "尿蛋白", "尿微量白蛋白",
    # 血糖
    "空腹血糖", "餐后血糖", "糖化血红蛋白", "血糖", "胰岛素",
    # 血脂
    "低密度脂蛋白", "高密度脂蛋白", "总胆固醇", "胆固醇", "甘油三酯", "血脂",
    # 肝功能
    "谷丙转氨酶", "谷草转氨酶", "转氨酶", "胆红素", "白蛋白",
    # 血常规
    "血红蛋白", "红细胞", "白细胞", "血小板",
    # 其他化验
    "维生素D", "维生素B12", "铁蛋白", "血清铁", "睾酮", "雌二醇", "皮质醇", "促甲状腺激素", "甲状腺素",
    "肌酸激酶", "C反应蛋白", "乳酸", "同型半胱氨酸",
    # 体征、穿戴设备（METRICS 里列的是这一类，其余算化验、体检）
    "静息心率", "心率变异性", "心率", "收缩压", "舒张压", "血压", "血氧", "体温", "呼吸频率",
    "体脂率", "体脂", "体重", "腰围", "睡眠", "步数", "最大摄氧量",
)  # fmt: skip
ABBREVIATIONS: tuple[str, ...] = (
    "HbA1c", "LDL", "HDL", "TG", "TC", "ALT", "AST", "TSH", "CK", "CRP", "eGFR", "BUN", "HRV", "VO2max",
    "SpO2",
)  # fmt: skip
_ABBR = re.compile(r"(?<![A-Za-z])(" + "|".join(ABBREVIATIONS) + r")(?![A-Za-z])", re.IGNORECASE)
MAX_NAMES = 6


def named_indicators(text: str) -> list[str]:
    """问题里点到的指标名（按出现顺序去重；已经被更长的名字包含的不重复算，如"空腹血糖"里的"血糖"）。"""
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for term in TERMS:
        for m in re.finditer(re.escape(term), text):
            span = (m.start(), m.end())
            if any(a <= span[0] and span[1] <= b for a, b in taken):
                continue
            taken.append(span)
            found.append((m.start(), term))
    for m in _ABBR.finditer(text):
        canonical = next(a for a in ABBREVIATIONS if a.lower() == m.group(1).lower())
        found.append((m.start(), canonical))
    out: list[str] = []
    for _, name in sorted(found):
        if name not in out:
            out.append(name)
    return out[:MAX_NAMES]


# 每天测的体征和穿戴设备指标；其余（肌酐、血糖、血脂……）算化验和体检指标
METRICS: frozenset[str] = frozenset({
    "静息心率", "心率变异性", "心率", "收缩压", "舒张压", "血压", "血氧", "体温", "呼吸频率", "体脂率", "体脂",
    "体重", "腰围", "睡眠", "步数", "最大摄氧量", "HRV", "VO2max", "SpO2",
})  # fmt: skip


def kinds_of(names: list[str]) -> set[str]:
    """问到的指标属于哪类：lab（化验、体检）、metric（每天测的体征和设备数据）。"""
    return {"metric" if n in METRICS else "lab" for n in names}
