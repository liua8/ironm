"""指标计算：纯函数，不连数据库。页面和问答共用这一份计算，同一个数两处一样。

每个指标都说明：值、怎么算的、用了哪些数据、依据哪份资料；数据不够时说清还缺什么，不给数字。
时间窗口以最后一条记录的日期为准（"最近 7 天"指最后一条记录往前 7 天），并标出数据截至哪天。
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

type Goal = Literal["muscle", "strength", "fat_loss", "endurance", "health"]
type Activity = Literal["sedentary", "light", "moderate", "active", "very_active"]
type Sex = Literal["male", "female"]
type Tone = Literal["good", "neutral", "attention"]
type Point = tuple[date, float]

GOALS: dict[str, str] = {
    "muscle": "增肌",
    "strength": "提升力量",
    "fat_loss": "减脂",
    "endurance": "提升耐力",
    "health": "综合健康",
}
# 常用的活动系数（每日总消耗 = 基础代谢 × 系数），用于估算
ACTIVITY: dict[str, tuple[str, float]] = {
    "sedentary": ("久坐，几乎不运动", 1.2),
    "light": ("轻度活动，每周运动 1–3 天", 1.375),
    "moderate": ("中度活动，每周运动 3–5 天", 1.55),
    "active": ("高度活动，每周运动 6–7 天", 1.725),
    "very_active": ("非常高，体力劳动或每天两练", 1.9),
}


@dataclass(frozen=True)
class Profile:
    height_cm: float | None = None
    birth: date | None = None
    sex: Sex | None = None
    goal: Goal | None = None
    activity: Activity | None = None

    def age(self, on: date) -> int | None:
        if self.birth is None:
            return None
        return on.year - self.birth.year - ((on.month, on.day) < (self.birth.month, self.birth.day))


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    value: float | None
    unit: str
    text: str  # 一句话结论
    how: str = ""  # 怎么算的（代入具体数）
    data: str = ""  # 用了哪些数据
    source: str = ""  # 依据
    missing: tuple[str, ...] = ()  # 还缺什么（有值时为空）
    tone: Tone = "neutral"
    series: tuple[Point, ...] = ()  # 画小趋势图用
    ref: str = ""  # 依据库编号（K..），没有时为空
    brief: str = ""  # 卡片上的短结论（如"正常""基本持平"），没有结论时为空
    display: str = ""  # 数值的写法（如血压 112/71、蛋白质 111–138），为空时按 value 显示

    @property
    def ok(self) -> bool:
        return self.value is not None and not self.missing


def missing(key: str, name: str, unit: str, *what: str, text: str = "") -> Metric:
    return Metric(key, name, None, unit, text or f"还缺：{'、'.join(what)}", missing=tuple(what))


def _fmt(x: float, places: int = 1) -> str:
    text = f"{x:.{places}f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _window(points: Sequence[Point], days: int, end: date) -> list[Point]:
    return [(d, v) for d, v in points if 0 <= (end - d).days < days]


def _span(points: Sequence[Point]) -> str:
    if not points:
        return ""
    first, last = min(d for d, _ in points), max(d for d, _ in points)
    return f"{first.isoformat()} 至 {last.isoformat()}，{len(points)} 天有记录"


# ---- 体重、BMI ---------------------------------------------------------------------------

BMI_SOURCE = "成人体重判定（WS/T 428-2013，国家卫生行业标准）"


def bmi(weight: Point | None, height_cm: float | None) -> Metric:
    if weight is None or not height_cm:
        what = [
            w for w, ok in (("体重记录", weight), ("身高（在“我的”里填写）", height_cm)) if not ok
        ]
        return missing("bmi", "BMI", "", *what)
    m = height_cm / 100
    value = round(weight[1] / (m * m), 1)
    if value < 18.5:
        label, tone, brief = "体重过低（< 18.5）", "attention", "偏低"
    elif value < 24:
        label, tone, brief = "正常（18.5–23.9）", "good", "正常"
    elif value < 28:
        label, tone, brief = "超重（24.0–27.9）", "attention", "超重"
    else:
        label, tone, brief = "肥胖（≥ 28.0）", "attention", "肥胖"
    return Metric(
        "bmi",
        "BMI",
        value,
        "",
        f"{_fmt(value)}，{label}",
        how=f"体重 {_fmt(weight[1])} 公斤 ÷ 身高 {_fmt(m, 2)} 米的平方 = {_fmt(value)}",
        data=f"体重 {_fmt(weight[1])} 公斤（{weight[0].isoformat()}）；身高 {_fmt(height_cm)} 厘米",
        source=f"{BMI_SOURCE}：中国成年人 18.5–23.9 为正常。BMI 不区分肌肉和脂肪，肌肉量大的人会偏高",
        tone=tone,  # type: ignore[arg-type]
        brief=brief,
    )


def weight_now(points: Sequence[Point]) -> Metric:
    if not points:
        return missing("weight", "体重", "公斤", "体重记录")
    end = max(d for d, _ in points)
    last = max(points)
    week = _window(points, 7, end)
    avg = statistics.fmean(v for _, v in week)
    return Metric(
        "weight",
        "体重",
        round(last[1], 1),
        "公斤",
        f"最近一次 {_fmt(last[1])} 公斤，最近 7 天平均 {_fmt(avg)} 公斤",
        how="最近 7 天（以最后一条记录为准）每天的体重取平均",
        data=_span(week),
        series=tuple(sorted(points))[-60:],
    )


# t 分布 0.975 分位数（自由度 1–30），超过 30 用 2.0 近似（偏保守）
_T975 = [12.71, 4.30, 3.18, 2.78, 2.57, 2.45, 2.36, 2.31, 2.26, 2.23, 2.20, 2.18, 2.16, 2.14, 2.13,
         2.12, 2.11, 2.10, 2.09, 2.09, 2.08, 2.07, 2.07, 2.06, 2.06, 2.06, 2.05, 2.05, 2.05, 2.04]  # fmt: skip

TREND_WEEKS = (4, 8, 12)  # 称重不够频繁时依次放宽
TREND_MIN_POINTS = 6
TREND_MIN_SPAN = 14


def weight_trend(points: Sequence[Point]) -> Metric:
    """每周体重变化：对每天的体重做直线回归，斜率 × 7，给出 95% 可信范围。

    先看最近 4 周；称重不够频繁（如一周一次）时依次放宽到 8 周、12 周，并写明用的是多长时间。
    """
    key, name, unit = "weight_trend", "体重每周变化", "公斤/周"
    if not points:
        return missing(key, name, unit, "体重记录")
    end = max(d for d, _ in points)
    pts: list[Point] = []
    span = 0
    for weeks in TREND_WEEKS:
        pts = sorted(_window(points, weeks * 7, end))
        span = (pts[-1][0] - pts[0][0]).days if pts else 0
        if len(pts) >= TREND_MIN_POINTS and span >= TREND_MIN_SPAN:
            break
    else:
        need = f"最近 {TREND_WEEKS[-1]} 周至少 {TREND_MIN_POINTS} 次称重、跨度 {TREND_MIN_SPAN} 天以上（现在 {len(pts)} 次、跨 {span} 天）"
        return missing(key, name, unit, need)
    xs = [(d - pts[0][0]).days for d, _ in pts]
    ys = [v for _, v in pts]
    n = len(pts)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys, strict=True)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx) if n > 2 else 0.0
    t = _T975[n - 3] if n - 2 <= len(_T975) else 2.0
    week, low, high = slope * 7, (slope - t * se) * 7, (slope + t * se) * 7
    if high < 0:
        word, brief = "在下降", "在下降"
    elif low > 0:
        word, brief = "在上升", "在上升"
    else:
        word, brief = "变化不明显（可信范围跨过 0）", "基本持平"
    weeks_used = weeks  # 用的是哪个时间窗口（4、8 或 12 周）
    return Metric(
        key,
        name,
        round(week, 2),
        unit,
        f"最近 {weeks_used} 周每周 {week:+.2f} 公斤（95% 可信范围 {low:+.2f} 至 {high:+.2f}），{word}",
        how=f"对最近 {weeks_used} 周的称重做直线回归，斜率乘以 7；可信范围按 t 分布计算",
        data=_span(pts),
        source="每周减重 0.5–1 公斤左右更容易长期保持（美国疾控中心）",
        ref="K16",
        series=tuple(pts),
        brief=brief,
    )


# ---- 能量与蛋白质 -----------------------------------------------------------------------

BMR_SOURCE = "Mifflin-St Jeor 公式（Am J Clin Nutr 1990;51:241–247）"


def bmr(weight: Point | None, p: Profile, today: date) -> Metric:
    key, name, unit = "bmr", "基础代谢", "千卡/天"
    age = p.age(today)
    what = [
        w
        for w, ok in (
            ("体重记录", weight),
            ("身高", p.height_cm),
            ("出生日期", age),
            ("性别", p.sex),
        )
        if not ok
    ]
    if what or weight is None or p.height_cm is None or age is None or p.sex is None:
        return missing(key, name, unit, *what)
    s = 5 if p.sex == "male" else -161
    value = 10 * weight[1] + 6.25 * p.height_cm - 5 * age + s
    sex_term = "+ 5（男）" if p.sex == "male" else "− 161（女）"
    return Metric(
        key,
        name,
        round(value),
        unit,
        f"约 {round(value)} 千卡/天（安静躺着一整天消耗的能量）",
        how=f"10 × {_fmt(weight[1])} 公斤 + 6.25 × {_fmt(p.height_cm)} 厘米 − 5 × {age} 岁 {sex_term} = {round(value)}",
        data=f"体重 {_fmt(weight[1])} 公斤（{weight[0].isoformat()}）；身高、年龄、性别来自档案",
        source=BMR_SOURCE,
    )


def tdee(base: Metric, p: Profile) -> Metric:
    key, name, unit = "tdee", "每日总消耗", "千卡/天"
    if not base.ok or base.value is None:
        return missing(key, name, unit, *(base.missing or ("基础代谢",)))
    if p.activity is None:
        return missing(key, name, unit, "日常活动水平（在“我的”里选择）")
    label, factor = ACTIVITY[p.activity]
    value = round(base.value * factor)
    return Metric(
        key,
        name,
        value,
        unit,
        f"约 {value} 千卡/天（估算）",
        how=f"基础代谢 {round(base.value)} × 活动系数 {factor}（{label}）= {value}",
        data="基础代谢；活动水平来自档案",
        source="常用活动系数估算，个人差异可达 ±10% 以上，需结合体重变化校正",
    )


def calorie_target(total: Metric, base: Metric, p: Profile) -> Metric:
    key, name, unit = "kcal_target", "每日热量目标", "千卡/天"
    if not total.ok or total.value is None or base.value is None:
        return missing(key, name, unit, *(total.missing or ("每日总消耗",)))
    if p.goal is None:
        return missing(key, name, unit, "目标（在“我的”里选择）")
    t, b = total.value, base.value
    if p.goal == "fat_loss":
        floor = max(b, 1500 if p.sex == "male" else 1200)
        value = max(t - 500, floor)
        how = f"每日总消耗 {round(t)} − 500 = {round(t - 500)}"
        if value > t - 500:
            how += f"，不低于基础代谢与安全下限，取 {round(value)}"
        why = "每天少吃约 500 千卡，约每周减 0.5 公斤（按每公斤脂肪约 7700 千卡估算）"
        ref = "K16"
    elif p.goal == "muscle":
        value = t * 1.1
        how = f"每日总消耗 {round(t)} × 1.1 = {round(value)}"
        why = "增肌期小幅盈余（约 10%），配合力量训练，减少多余脂肪增长"
        ref = ""
    else:
        value = t
        how = f"等于每日总消耗 {round(t)}"
        why = "保持体重，按训练量和体重变化微调"
        ref = ""
    return Metric(
        key,
        name,
        round(value),
        unit,
        f"约 {round(value)} 千卡/天（目标：{GOALS[p.goal]}）",
        how=how,
        data="每日总消耗、基础代谢；目标来自档案",
        source=why,
        ref=ref,
        brief=GOALS[p.goal],
    )


PROTEIN = {"fat_loss": (1.6, 2.0), "muscle": (1.6, 2.0), "strength": (1.6, 2.0)}


def protein_target(weight: Point | None, p: Profile) -> Metric:
    key, name, unit = "protein_target", "每日蛋白质", "克/天"
    if weight is None:
        return missing(key, name, unit, "体重记录")
    lo, hi = PROTEIN.get(p.goal or "", (1.4, 1.6))
    a, b = round(weight[1] * lo), round(weight[1] * hi)
    goal = GOALS.get(p.goal or "", "未设置目标，按一般运动人群")
    return Metric(
        key,
        name,
        float(a),
        unit,
        f"每天 {a}–{b} 克（{goal}），分到 3–4 餐，每餐 20–40 克",
        how=f"体重 {_fmt(weight[1])} 公斤 × {lo}–{hi} 克/公斤 = {a}–{b} 克",
        data=f"体重 {_fmt(weight[1])} 公斤（{weight[0].isoformat()}）",
        source="运动人群每天 1.4–2.0 克/公斤体重（国际运动营养学会立场声明，2017）",
        ref="K09",
        brief=GOALS.get(p.goal or "", ""),
        display=f"{a}–{b}",
    )


# ---- 恢复：静息心率、心率变异性、睡眠 ----------------------------------------------------

BASELINE_DAYS = 60
BASELINE_MIN = 14


def against_baseline(
    key: str,
    name: str,
    unit: str,
    points: Sequence[Point],
    *,
    higher_is_worse: bool,
    ref: str,
    source: str,
) -> Metric:
    """最近 7 天平均与本人基线（之前最多 60 天）比较；基线不足 14 天只给平均，不下结论。"""
    if not points:
        return missing(key, name, unit, f"{name}记录")
    end = max(d for d, _ in points)
    week = _window(points, 7, end)
    base = [(d, v) for d, v in _window(points, BASELINE_DAYS + 7, end) if (end - d).days >= 7]
    avg = statistics.fmean(v for _, v in week)
    series = tuple(sorted(points))[-60:]
    if len(base) < BASELINE_MIN:
        return Metric(
            key, name, round(avg, 1), unit,
            f"最近 7 天平均 {_fmt(avg)} {unit}；本人基线的数据还不够（需要 {BASELINE_MIN} 天，现在 {len(base)} 天），暂不比较",
            how="最近 7 天（以最后一条记录为准）取平均", data=_span(week), source=source, ref=ref, series=series,
            brief="基线积累中",
        )  # fmt: skip
    mean = statistics.fmean(v for _, v in base)
    sd = statistics.pstdev([v for _, v in base]) or 0.0
    diff = avg - mean
    worse = diff > 0 if higher_is_worse else diff < 0
    if sd and abs(diff) >= sd and worse:
        word, tone = (
            ("明显高于" if diff > 0 else "明显低于") + "你自己的基线，可能疲劳、睡眠不足或生病",
            "attention",
        )
        brief = "明显偏高" if diff > 0 else "明显偏低"
    elif sd and abs(diff) >= sd:
        word, tone = ("高于" if diff > 0 else "低于") + "你自己的基线（方向是好的）", "good"
        brief = "好于基线"
    else:
        word, tone, brief = "在你自己的正常波动范围内", "good", "正常波动"
    return Metric(
        key,
        name,
        round(avg, 1),
        unit,
        f"最近 7 天平均 {_fmt(avg)} {unit}，基线 {_fmt(mean)} {unit}（±{_fmt(sd)}），{word}",
        how=f"最近 7 天平均减去之前 {len(base)} 天的平均，差 {diff:+.1f} {unit}；超过一个标准差算明显",
        data=f"最近 7 天：{_span(week)}；基线：{_span(base)}",
        source=source,
        ref=ref,
        tone=tone,  # type: ignore[arg-type]
        series=series,
        brief=brief,
    )


def resting_hr(points: Sequence[Point]) -> Metric:
    return against_baseline(
        "resting_hr", "静息心率", "次/分", points, higher_is_worse=True, ref="K18",
        source="和自己的基线比、看一周平均（Plews 等，2013）；成年人一般 60–100 次/分，常训练的人可以更低（美国心脏协会）",
    )  # fmt: skip


def hrv(points: Sequence[Point], algorithm: str) -> Metric:
    return against_baseline(
        f"hrv_{algorithm.lower()}", f"心率变异性（{algorithm}）", "毫秒", points, higher_is_worse=False, ref="K19",
        source="和自己的基线比；SDNN（苹果手表）与 RMSSD（其他设备）是不同指标，不放在一起比较",
    )  # fmt: skip


def sleep(points: Sequence[Point]) -> Metric:
    key, name, unit = "sleep", "睡眠时长", "小时"
    if not points:
        return missing(key, name, unit, "睡眠记录（连接手表或上传苹果健康数据）")
    end = max(d for d, _ in points)
    week = _window(points, 7, end)
    avg = statistics.fmean(v for _, v in week)
    short = sum(1 for _, v in week if v < 7)
    tone: Tone = "good" if avg >= 7 else "attention"
    return Metric(
        key, name, round(avg, 1), unit,
        f"最近 7 天平均 {_fmt(avg)} 小时，其中 {short} 天不足 7 小时",
        how="最近 7 天（以最后一条记录为准）每晚的睡眠时长取平均", data=_span(week),
        source="成年人每晚应规律地睡 7 小时及以上（美国睡眠医学会与睡眠研究会共识，2015）", ref="K07",
        tone=tone, series=tuple(sorted(points))[-60:], brief="充足" if avg >= 7 else "偏少",
    )  # fmt: skip


def steps(points: Sequence[Point], age: int | None) -> Metric:
    key, name, unit = "steps", "步数", "步/天"
    if not points:
        return missing(key, name, unit, "步数记录")
    end = max(d for d, _ in points)
    week = _window(points, 7, end)
    avg = statistics.fmean(v for _, v in week)
    lo, hi = (6000, 8000) if age is not None and age >= 60 else (8000, 10000)
    tone: Tone = "good" if avg >= lo else "attention"
    return Metric(
        key, name, round(avg), unit,
        f"最近 7 天平均 {round(avg)} 步；参考：{lo}–{hi} 步/天以后收益趋于平稳",
        how="最近 7 天（以最后一条记录为准）每天的步数取平均", data=_span(week),
        source=f"每天步数与全因死亡风险的荟萃分析（Lancet Public Health，2022）：{'60 岁及以上' if lo == 6000 else '60 岁以下'}约 {lo}–{hi} 步趋于平稳",
        ref="K21", tone=tone, series=tuple(sorted(points))[-60:], brief="达标" if avg >= lo else "偏少",
    )  # fmt: skip


def blood_pressure(sys_pt: Point | None, dia_pt: Point | None) -> Metric:
    key, name, unit = "blood_pressure", "血压", "mmHg"
    if sys_pt is None or dia_pt is None:
        return missing(key, name, unit, "血压记录")
    s, d = sys_pt[1], dia_pt[1]
    if s >= 140 or d >= 90:
        label, tone, brief = "达到高血压的数值范围（≥ 140/90）", "attention", "偏高"
    elif s >= 120 or d >= 80:
        label, tone, brief = "正常高值（120–139/80–89）", "neutral", "正常高值"
    else:
        label, tone, brief = "正常（< 120/80）", "good", "正常"
    return Metric(
        key, name, s, unit,
        f"最近一次 {round(s)}/{round(d)} mmHg，{label}。只作参考，不作诊断，确诊需要医生在不同日子多次测量",
        how="取最近一次收缩压和舒张压，按分级标准对照",
        data=f"收缩压 {round(s)}（{sys_pt[0].isoformat()}）；舒张压 {round(d)}（{dia_pt[0].isoformat()}）",
        source="中国高血压防治指南（2018 年修订版）的血压分级", tone=tone,  # type: ignore[arg-type]
        brief=brief, display=f"{round(s)}/{round(d)}",
    )  # fmt: skip


# ---- 汇总 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Readings:
    """计算用到的全部数据，由调用方从 mirobody 读好传入。"""

    weight: tuple[Point, ...] = ()
    height_cm: float | None = None  # mirobody 里的身高读数（档案没填时用）
    resting_hr: tuple[Point, ...] = ()
    hrv_sdnn: tuple[Point, ...] = ()
    hrv_rmssd: tuple[Point, ...] = ()
    sleep_hours: tuple[Point, ...] = ()
    steps: tuple[Point, ...] = ()
    systolic: tuple[Point, ...] = ()
    diastolic: tuple[Point, ...] = ()
    errors: tuple[str, ...] = field(default=())  # 哪些数据没读到


def compute_all(r: Readings, p: Profile, today: date) -> list[Metric]:
    profile = (
        p
        if p.height_cm or r.height_cm is None
        else Profile(r.height_cm, p.birth, p.sex, p.goal, p.activity)
    )
    latest_w = max(r.weight) if r.weight else None
    base = bmr(latest_w, profile, today)
    total = tdee(base, profile)
    out = [
        weight_now(r.weight),
        weight_trend(r.weight),
        bmi(latest_w, profile.height_cm),
        base,
        total,
        calorie_target(total, base, profile),
        protein_target(latest_w, profile),
        resting_hr(r.resting_hr),
        sleep(r.sleep_hours),
        steps(r.steps, profile.age(today)),
        blood_pressure(
            max(r.systolic) if r.systolic else None, max(r.diastolic) if r.diastolic else None
        ),
    ]
    if r.hrv_sdnn:
        out.append(hrv(r.hrv_sdnn, "SDNN"))
    if r.hrv_rmssd:
        out.append(hrv(r.hrv_rmssd, "RMSSD"))
    if not r.hrv_sdnn and not r.hrv_rmssd:
        out.append(
            missing("hrv", "心率变异性", "毫秒", "心率变异性记录（连接手表或上传苹果健康数据）")
        )
    return out
