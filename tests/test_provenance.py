"""追问来源的识别与回答；正文去掉出处标记。"""

import pytest

from ironm_agent.checks import plain
from ironm_agent.provenance import explain, is_provenance


@pytest.mark.parametrize(
    "text",
    [
        "这个数据从哪来的",
        "依据是什么",
        "2764 是怎么算的",
        "你刚才说的来源呢",
        "出处呢",
        "这些是根据什么",
    ],
)
def test_provenance_questions(text: str) -> None:
    assert is_provenance(text)


@pytest.mark.parametrize(
    "text", ["增肌训练有什么科学依据吗", "肌酸要怎么吃", "跑步前要不要吃东西", "我最近体重怎么样"]
)
def test_ordinary_questions_are_not_provenance(text: str) -> None:
    assert not is_provenance(text)


def test_explain_picks_the_lines_with_the_asked_number() -> None:
    sources = "计算：\n- 热量目标：2764 千卡\n- 蛋白质：111–138 克\n\n资料：\n- 指南"
    assert explain("2764 怎么算的", sources) == "2764 是这样来的：\n- 热量目标：2764 千卡"
    assert explain("依据是什么", "").startswith("上一条回答没有用到资料")
    assert explain("依据是什么", None).startswith("还没有可以追溯的回答")


def test_plain_text_drops_markers_but_keeps_words() -> None:
    text = "每天 3–5 克〔K10〕。<statement>按你 69.2 公斤算约 21 克〔K10〕<cite>[r1]</cite></statement>；先练动作〔经验〕。按 BMI 22.6〔C3〕看正常。"
    assert plain(text) == "每天 3–5 克。按你 69.2 公斤算约 21 克；先练动作。按 BMI 22.6看正常。"


def test_previous_explanation_is_skipped_when_finding_sources(monkeypatch: object) -> None:
    import asyncio

    import mirobody.agent.chat.message as message

    from ironm_agent.memory import last_sources

    async def history(owner: str, session: str) -> list[dict[str, object]]:
        return [
            {"role": "user", "content": "增肌每天该吃多少"},
            {
                "role": "assistant",
                "content": "每天约 2764 千卡。",
                "content_dict": [
                    {"type": "text", "text": "每天约 2764 千卡。"},
                    {"type": "tool_result", "tool_call_id": "sources", "content": "计算：\n- 2764"},
                ],
            },
            {"role": "user", "content": "2764 是怎么算的"},
            {"role": "assistant", "content": "2764 是这样来的：\n- 2764", "content_dict": []},
            {"role": "user", "content": "依据是什么"},
        ]

    monkeypatch.setattr(message, "get_chat_history", history)  # type: ignore[attr-defined]
    assert asyncio.run(last_sources("1:s", "sources")) == "计算：\n- 2764"
