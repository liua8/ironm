"""工具的结果：带数字的结论各领一个编号；不带数字的说明原样给角色看。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    """一条带数字的结论：写明怎么算的、用了哪些数据、依据哪份资料（与指标计算同一种写法）。"""

    name: str
    text: str
    how: str = ""
    data: str = ""
    source: str = ""

    def detail(self) -> str:
        parts = [f"{self.name}：{self.text}"]
        if self.how:
            parts.append(f"计算：{self.how}")
        if self.data:
            parts.append(f"数据：{self.data}")
        if self.source:
            parts.append(f"依据：{self.source}")
        return "。".join(parts)


@dataclass(frozen=True)
class Result:
    findings: tuple[Finding, ...] = ()
    notes: tuple[str, ...] = ()  # 不领编号的说明：缺什么、怎么用、动作清单等
    entries: tuple[str, ...] = ()  # 用到的动作库条目编号（K9..），记为这一轮可以引用的依据
    problems: tuple[str, ...] = ()  # 必须改的问题（计划检查用；系统据此退回重写）
    plans: tuple[tuple[str, object], ...] = ()  # 方案库做好的草稿：方案编号 → 计划（交新计划时可以直接用，§165）

    @classmethod
    def note(cls, *lines: str) -> Result:
        return cls(notes=lines)
