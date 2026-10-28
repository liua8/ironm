"""实时天气与空气质量，以及天气对训练的影响（spec [2026-10-23] §13）。

城市在个人中心设置（iron-m 自己的表）；天气由服务端按城市的经纬度去取（Open-Meteo，不需要密钥），
页面不直接访问外部网站。天气对训练的影响全用规则判断，不调用模型。取不到天气时如实说明，不影响其他功能。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal

_log = logging.getLogger("ironm_agent.weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEOUT_S = 6.0
CACHE_S = 600  # 同一个地方 10 分钟内不重复取

type Level = Literal["good", "caution", "indoor", "avoid"]
LEVEL_NAMES: dict[str, str] = {
    "good": "适合户外",
    "caution": "户外要注意",
    "indoor": "建议在室内练",
    "avoid": "避免户外运动",
}
_ORDER: tuple[Level, ...] = ("good", "caution", "indoor", "avoid")

# ---- 天气现象（WMO 天气代码）-------------------------------------------------------------------


def weather_text(code: int) -> str:
    if code == 0:
        return "晴"
    if code in (1, 2):
        return "多云"
    if code == 3:
        return "阴"
    if code in (45, 48):
        return "雾"
    if 51 <= code <= 57:
        return "毛毛雨"
    if 61 <= code <= 67:
        return "雨"
    if 71 <= code <= 77:
        return "雪"
    if 80 <= code <= 82:
        return "阵雨"
    if code in (85, 86):
        return "阵雪"
    if code >= 95:
        return "雷暴"
    return "未知"


def _wet(code: int) -> bool:
    return 51 <= code <= 86


# ---- 空气质量指数（HJ 633—2012）-----------------------------------------------------------------

# 分指数的分段：(浓度, 分指数)；PM2.5、PM10 用 24 小时平均的分段（这里用的是当前浓度，所以是估算）
_PM25 = ((0, 0), (35, 50), (75, 100), (115, 150), (150, 200), (250, 300), (350, 400), (500, 500))
_PM10 = ((0, 0), (50, 50), (150, 100), (250, 150), (350, 200), (420, 300), (500, 400), (600, 500))
AQI_LEVELS = (
    (50, "优", "可以正常户外活动"),
    (100, "良", "极少数异常敏感的人减少户外活动"),
    (150, "轻度污染", "儿童、老人和心脏病、呼吸系统疾病患者减少长时间、高强度的户外锻炼"),
    (200, "中度污染", "一般人群适量减少户外运动"),
    (300, "重度污染", "一般人群减少户外运动"),
    (10_000, "严重污染", "一般人群避免户外活动"),
)


def _iaqi(c: float, table: tuple[tuple[int, int], ...]) -> float:
    if c <= 0:
        return 0.0
    for (c0, i0), (c1, i1) in pairwise(table):
        if c <= c1:
            return i0 + (i1 - i0) * (c - c0) / (c1 - c0)
    return 500.0


def aqi(pm25: float | None, pm10: float | None) -> int | None:
    parts = [_iaqi(pm25, _PM25)] if pm25 is not None else []
    parts += [_iaqi(pm10, _PM10)] if pm10 is not None else []
    return round(max(parts)) if parts else None


def aqi_level(value: int) -> tuple[str, str]:
    for top, name, advice in AQI_LEVELS:
        if value <= top:
            return name, advice
    return AQI_LEVELS[-1][1], AQI_LEVELS[-1][2]


# ---- 天气与判断 -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Day:
    """一天的预报。"""

    day: str  # YYYY-MM-DD（当地日期）
    code: int
    tmax: float
    tmin: float
    feels_min: float
    rain: int | None  # 降水概率（%）
    wind_kmh: float | None

    @property
    def text(self) -> str:
        return weather_text(self.code)


@dataclass(frozen=True)
class Weather:
    place: str
    temperature: float
    feels_like: float
    humidity: float | None
    code: int
    wind_kmh: float | None
    pm25: float | None = None
    pm10: float | None = None
    observed: str = ""  # 观测时间（当地时间）
    days: tuple[Day, ...] = ()  # 今天起 7 天的预报（首页日历用，spec [2026-10-23] §33）

    @property
    def text(self) -> str:
        return weather_text(self.code)

    @property
    def aqi(self) -> int | None:
        return aqi(self.pm25, self.pm10)


@dataclass(frozen=True)
class Advice:
    level: Level
    reasons: tuple[str, ...]  # 每条都是一句完整的话
    sources: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return LEVEL_NAMES[self.level]

    def line(self) -> str:
        return f"{self.name}：" + "；".join(self.reasons) if self.reasons else self.name


HEAT = ((40, "avoid"), (37, "indoor"), (35, "caution"))  # 高温预警的温度分档（红 40、橙 37、黄 35）
COLD_INDOOR = -10  # 体感温度，经验规则
COLD_CAUTION = 0
WIND_INDOOR = 39  # 公里/小时，约 6 级风，经验规则


def assess(w: Weather) -> Advice:
    """天气对训练的影响：取各项里最严的那一档。"""
    level: Level = "good"
    reasons: list[str] = []
    sources: list[str] = []

    def raise_to(new: Level) -> None:
        nonlocal level
        if _ORDER.index(new) > _ORDER.index(level):
            level = new

    a = w.aqi
    if a is not None and a > 100:
        name, advice = aqi_level(a)
        raise_to("caution" if a <= 150 else "indoor" if a <= 300 else "avoid")
        reasons.append(f"空气质量{name}（指数约 {a}），{advice}")
        sources.append("HJ 633—2012（按当前 PM2.5、PM10 估算）")
    for top, lv in HEAT:
        if w.temperature >= top:
            raise_to(lv)  # type: ignore[arg-type]
            reasons.append(
                f"气温 {w.temperature:.0f}℃，达到高温预警的 {top}℃ 档，"
                + {
                    "avoid": "不要在户外运动",
                    "indoor": "户外只做轻量活动并避开中午，训练改在室内",
                    "caution": "降低强度、缩短时间、多补水，避开中午",
                }[lv]
            )
            sources.append("气象灾害预警信号（高温）；K13")
            break
    if w.feels_like <= COLD_INDOOR:
        raise_to("indoor")
        reasons.append(f"体感温度 {w.feels_like:.0f}℃，太冷，建议在室内练（经验）")
    elif w.feels_like <= COLD_CAUTION:
        raise_to("caution")
        reasons.append(f"体感温度 {w.feels_like:.0f}℃，户外要多穿、热身时间加长（经验）")
    if w.code >= 95:
        raise_to("avoid")
        reasons.append("有雷暴，不要在户外运动（经验）")
    elif _wet(w.code):
        raise_to("indoor")
        reasons.append(f"有{w.text}，户外有氧改成室内（经验）")
    if w.wind_kmh is not None and w.wind_kmh >= WIND_INDOOR:
        raise_to("indoor")
        reasons.append(f"风速约 {w.wind_kmh:.0f} 公里/小时，风大，建议在室内练（经验）")
    return Advice(level, tuple(reasons), tuple(dict.fromkeys(sources)))


RAIN_LIKELY = 50  # 降水概率不到这么多：预报里的雨、雷暴只提醒"可能有"，不改到室内（经验规则）


def assess_day(d: Day) -> Advice:
    """某一天的预报对训练的影响：和实时天气同一套规则；高温看最高气温，寒冷看最低体感温度；没有空气质量预报。
    预报有雨或雷暴但降水概率不高时，只提醒可能有，备好雨具或改室内。"""
    unlikely = (_wet(d.code) or d.code >= 95) and d.rain is not None and d.rain < RAIN_LIKELY
    a = assess(Weather("", d.tmax, d.feels_min, None, 3 if unlikely else d.code, d.wind_kmh))
    if not unlikely:
        return a
    level: Level = a.level if _ORDER.index(a.level) > _ORDER.index("caution") else "caution"
    reason = f"可能有{d.text}（降水概率 {d.rain}%），户外运动备好雨具，或者改在室内（经验）"
    return Advice(level, (*a.reasons, reason), a.sources)


def summary(w: Weather) -> str:
    parts = [f"{w.place} {w.text}", f"{w.temperature:.0f}℃（体感 {w.feels_like:.0f}℃）"]
    a = w.aqi
    if a is not None:
        parts.append(f"空气质量{aqi_level(a)[0]}（约 {a}）")
    return "，".join(parts)


def case_line(w: Weather | None) -> str:
    """写进共享档案的一行；取不到天气时为空。"""
    if w is None:
        return ""
    return f"现在的天气：{summary(w)}。对训练的影响：{assess(w).line()}"


# ---- 取天气（网络）----------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    name: str  # 给人看的名字，如"北京市"
    lat: float
    lon: float


_cache: dict[tuple[float, float], tuple[float, Weather]] = {}


async def _get(url: str, params: dict[str, Any]) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, dict) else {}


async def geocode(city: str) -> Place | None:
    """城市名 → 经纬度；同名的地方优先取中国的、人口最多的那个。"""
    name = city.strip()[:30]
    if not name:
        return None
    data = await _get(GEO_URL, {"name": name, "count": 10, "language": "zh", "format": "json"})
    found = [x for x in data.get("results") or [] if isinstance(x, dict)]
    if not found:
        return None
    cn = [x for x in found if x.get("country_code") == "CN"] or found
    best = max(
        cn,
        key=lambda x: (
            x.get("feature_code") in ("PPLC", "PPLA", "PPLA2"),
            x.get("population") or 0,
        ),
    )
    label = best.get("admin2") or best.get("name") or name
    return Place(str(label), float(best["latitude"]), float(best["longitude"]))


async def fetch(place: Place) -> Weather:
    key = (round(place.lat, 2), round(place.lon, 2))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    point = {"latitude": place.lat, "longitude": place.lon, "timezone": "auto"}
    got = await asyncio.gather(
        _get(
            FORECAST_URL,
            point
            | {
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_min,"
                "precipitation_probability_max,wind_speed_10m_max",
                "forecast_days": 7,
            },
        ),
        _get(AIR_URL, point | {"current": "pm2_5,pm10"}),
        return_exceptions=True,
    )
    now, air = got
    if isinstance(now, BaseException):
        raise now
    cur = now.get("current") or {}
    air_now = (air.get("current") or {}) if isinstance(air, dict) else {}
    w = Weather(
        place.name,
        float(cur["temperature_2m"]),
        float(cur.get("apparent_temperature", cur["temperature_2m"])),
        _float(cur.get("relative_humidity_2m")),
        int(cur.get("weather_code") or 0),
        _float(cur.get("wind_speed_10m")),
        _float(air_now.get("pm2_5")),
        _float(air_now.get("pm10")),
        str(cur.get("time") or ""),
        _days(now.get("daily") or {}),
    )
    _cache[key] = (time.monotonic(), w)
    return w


def _days(daily: dict[str, Any]) -> tuple[Day, ...]:
    """每日预报（按列给的数组）拼成一天一条；缺数的那天跳过。"""

    def col(name: str, i: int) -> Any:
        values = daily.get(name) or []
        return values[i] if i < len(values) else None

    out = []
    for i, day in enumerate(daily.get("time") or []):
        tmax, tmin = _float(col("temperature_2m_max", i)), _float(col("temperature_2m_min", i))
        if tmax is None or tmin is None:
            continue
        feels = _float(col("apparent_temperature_min", i))
        rain = _float(col("precipitation_probability_max", i))
        out.append(Day(str(day), int(col("weather_code", i) or 0), tmax, tmin, tmin if feels is None else feels,
                       None if rain is None else int(rain), _float(col("wind_speed_10m_max", i))))  # fmt: skip
    return tuple(out)


def _float(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


async def safe_fetch(place: Place | None) -> Weather | None:
    """取不到时返回 None（日志只记错误类型，不记位置）。"""
    if place is None:
        return None
    try:
        return await fetch(place)
    except Exception as e:
        _log.warning("weather unavailable: error_type=%s", type(e).__name__)
        return None


# ---- 城市（iron-m 自己的表）-------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS ironm_place (
    user_id    text PRIMARY KEY,
    city       text NOT NULL,
    label      text NOT NULL,
    lat        double precision NOT NULL,
    lon        double precision NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
"""
_ready = False


async def _q(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    from mirobody.utils.db import execute_query

    global _ready
    if not _ready:
        await execute_query(DDL, {}, log_sql=False)
        _ready = True
    rows = await execute_query(sql, params or {}, log_sql=False)
    return rows if isinstance(rows, list) else []


async def load_place(user_id: str) -> tuple[str, Place | None]:
    rows = await _q(
        "SELECT city, label, lat, lon FROM ironm_place WHERE user_id = :uid", {"uid": user_id}
    )
    if not rows:
        return "", None
    r = rows[0]
    return str(r["city"]), Place(str(r["label"]), float(r["lat"]), float(r["lon"]))


async def save_place(user_id: str, city: str, place: Place) -> None:
    await _q(
        "INSERT INTO ironm_place (user_id, city, label, lat, lon) VALUES (:uid, :city, :label, :lat, :lon) "
        "ON CONFLICT (user_id) DO UPDATE SET city = EXCLUDED.city, label = EXCLUDED.label, "
        "lat = EXCLUDED.lat, lon = EXCLUDED.lon, updated_at = now()",
        {
            "uid": user_id,
            "city": city.strip()[:30],
            "label": place.name,
            "lat": place.lat,
            "lon": place.lon,
        },
    )


async def for_user(user_id: str) -> Weather | None:
    """这个人所在城市的天气；没设置城市或取不到时为 None。"""
    try:
        _, place = await load_place(user_id)
    except Exception as e:
        _log.warning("place unavailable: error_type=%s", type(e).__name__)
        return None
    return await safe_fetch(place)
