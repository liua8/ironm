"""问 App 怎么用（spec [2026-10-23] §36）：照使用说明给具体操作；说明里的数字可以照说，编出来的数字仍退回固定介绍。"""


from ironm_agent.coach import app_guide


def test_guide_covers_the_main_pages() -> None:
    guide = app_guide()
    for words in (
        "首页",
        "今日任务",
        "练完打卡",
        "记一条",
        "设置城市",
        "历史",
        "撤销",
        "目前还做不到",
    ):
        assert words in guide, words






