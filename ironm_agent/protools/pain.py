"""疼痛判断：按疼痛分数（0–10）和有没有就医信号，给出"可以继续 / 减量改动作 / 停下并就医"。

只做运动场景的分流，不做诊断。
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from ironm_agent.protools.result import Finding, Result

type Sign = Literal[
    "snap", "deformity", "cannot_bear", "numbness", "swelling_worse", "worsening", "morning_worse"
]  # fmt: skip
SIGNS: dict[str, str] = {
    "snap": "受伤时听到断裂声",
    "deformity": "受伤部位变形",
    "cannot_bear": "不能活动或不能承重",
    "numbness": "麻木或刺痛",
    "swelling_worse": "肿胀越来越重",
    "worsening": "越来越疼，或自己处理几天不见好",
    "morning_worse": "早上起床时的疼和僵硬一周比一周重",
}
URGENT = frozenset({"snap", "deformity", "cannot_bear", "numbness"})  # 立即就医（K15）
SOON = frozenset(
    {"swelling_worse", "worsening", "morning_worse"}
)  # 停下这个动作，尽快看医生（K15、K33）
ALLOWED = 5  # 运动中和运动后疼痛允许到 5 分（K33）
SEVERE = 8  # 疼痛严重（K15）
WATCH = "出现断裂声、变形、不能承重、麻木刺痛时立即就医；肿胀加重、越来越疼或几天不见好时去看医生（K15）"


def pain_check(score: int | None, signs: Collection[str] = (), *, part: str = "") -> Result:
    where = f"{part}的" if part else ""
    named = [SIGNS[s] for s in signs if s in SIGNS]
    data = (
        f"{where}疼痛"
        + (f" {score} 分（0–10）" if score is not None else "，没有打分")
        + ("；就医信号：" + "、".join(named) if named else "；没有提到就医信号")
    )
    urgent = [s for s in signs if s in URGENT]
    soon = [s for s in signs if s in SOON]
    if urgent:
        verdict, why, source = (
            "停下，立即就医",
            "有需要立即就医的信号：" + "、".join(SIGNS[s] for s in urgent),
            "K15",
        )
    elif soon:
        verdict, why, source = (
            "停下引起疼痛的动作，尽快去看医生",
            "有要看医生的信号：" + "、".join(SIGNS[s] for s in soon),
            "K15、K33",
        )
    elif score is None:
        return Result.note(
            "先请他给疼痛打个分（0 不疼，10 最疼），并问有没有断裂声、变形、不能承重、麻木刺痛、肿胀加重。",
            WATCH,
        )
    elif not 0 <= score <= 10:
        return Result.note("疼痛分数要在 0 到 10 之间。")
    elif score >= SEVERE:
        verdict, why, source = "停下，去看医生", f"疼痛 {score} 分，属于严重的疼", "K15"
    elif score > ALLOWED:
        verdict = "这个部位今天减量：停掉引起疼痛的动作，换成不疼的动作或更小的幅度"
        why, source = f"疼痛 {score} 分，超过了运动中允许的 {ALLOWED} 分", "K33"
    else:
        verdict = "可以继续，但要盯着疼痛"
        why = f"疼痛 {score} 分，在运动中允许的 {ALLOWED} 分以内；要在第二天早上前消退，早上的疼和僵硬不能一周比一周重"
        source = "K33"
    return Result(
        (
            Finding(
                "疼痛判断",
                f"{verdict}（{why}）",
                "先看有没有就医信号，再按疼痛分数分档：5 分以内可以继续，6–7 分减量改动作，8 分及以上停下就医",
                data,
                source,
            ),
        ),
        notes=(WATCH, "这只是运动时怎么办的判断，不是诊断。"),
    )
