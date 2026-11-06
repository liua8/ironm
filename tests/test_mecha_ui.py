"""界面改成机甲风、底部 首页 / 图鉴 / 战绩 / 我（spec [2026-10-23] §121）：页面脚本里的规则。"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
JS = (WEB / "app.js").read_text()
CSS = (WEB / "style.css").read_text()


def _code_lines() -> list[str]:
    """去掉整行注释和行尾注释，只看会显示出来的代码。"""
    out = []
    for ln in JS.splitlines():
        if ln.lstrip().startswith("//"):
            continue
        out.append(re.split(r"(?<=[;,)])\s*//", ln)[0])
    return out


def test_no_old_names_on_the_page() -> None:
    code = "\n".join(_code_lines())
    assert "管家" not in code and "搭子" not in code  # 先改叫搭子，11-03 又改叫 IronM
    for slang in ("班味", "脆皮", "上强度"):
        assert slang not in code
    assert "个人中心" not in code.replace(
        'x.includes("个人中心")', ""
    )  # 后端缺项说明里还叫个人中心，只用来判断


def test_segments() -> None:
    assert 'const HOME_SEGS = [["home", "练"], ["home/eat", "干饭"]];' in JS  # §175：IronM 在底栏单独一格
    assert (
        'const ATLAS_SEGS = [["moves", "动作"], ["machines", "器械"], ["food", "食物"], ["plans", "方案"]];'
        in JS  # §175 照参照图四段
    )
    assert "RECORD_SEGS" not in JS and "recordPage(view); }" in JS  # §137 战绩不分段
    chat = JS[JS.index("function chatPage(view)") : JS.index("function reviewExtra")]
    assert "homeSeg(" not in chat and "mech(40)" in chat  # §175：对话页顶上不再分段；页头是企鹅头像


def test_home_shows_only_what_it_has() -> None:
    vit = JS[JS.index("function vitalsRow") : JS.index("// 搭子的调整")]
    assert (
        "w?.sleep?.value != null ?" in vit
        and "w?.resting_hr?.value != null ?" in vit
        and "wx ?" in vit
    )
    assert "return cells.length ?" in vit  # 一格都没有就整排不显示
    card = JS[JS.index("function trainCard") : JS.index("function vitalsRow")]
    assert "先热身约" in card and '"开始训练"' in card and '"已经练完了，直接打卡"' in card  # §175 照参照图
    assert (
        "(planned[it.exercise] || 0) - (it.sets || 0)" in card and "`比计划少 ${cut} 组`" in card
    )  # 被减掉的组标出来
    assert "TODAY" not in card  # §175 照参照图标题用"今日委托 · 名字"，不用英文小标签


def test_pr_wall_rules() -> None:
    pr = JS[JS.index("function prWall") : JS.index("async function recordPage")]
    assert (
        "cur.broke = cur.times > 0 && better(b, cur.best);" in pr
    )  # 只有一次记录不标；比更早的都好才标
    assert "x.done !== false && !x.rest" in pr  # 没练的那条不算
    assert "x.weight_kg === a.weight_kg && x.reps > a.reps" in JS  # 一样重次数多的算更好


def test_mascot_is_our_own() -> None:
    """§175 需求 3：IronM 的头像是自己画的黄色胖企鹅，头顶一滴牛奶；顶栏标志也用它。"""
    pen = JS[JS.index("function mech(") : JS.index("async function api(")]
    assert "#ffd83d" in pen and "#ffefa6" in pen  # 纯黄身子、浅黄肚子
    assert '"#fff", stroke: "#cbd5dd"' in pen  # 头顶白色的一滴牛奶
    assert "image" not in pen and "href" not in pen  # 全是自己画的形状，不引图片
    assert '$("logo").append(mech(30))' in JS


def test_motion_and_no_external() -> None:
    assert (
        "@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; }"
        in CSS
    )
    for f in ("index.html", "app.js", "style.css"):
        assert "https://" not in (WEB / f).read_text(), f  # 字体、图片都不从外面加载
    assert "fonts.googleapis" not in CSS and "@import" not in CSS
