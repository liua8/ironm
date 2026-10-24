"""Token usage for one agent turn, and the ``usage`` block it becomes.

LangChain normalises every provider's usage into ``AIMessage.usage_metadata``:
``input_tokens`` (which ALREADY includes cache reads and writes: unlike raw
Anthropic events), ``output_tokens``, ``input_token_details.cache_read`` /
``cache_creation`` and ``output_token_details.reasoning``. Summing those across
every chunk (or every ``on_llm_end``) of a turn is correct for every provider
this repository has run: OpenAI-compatible backends emit one usage chunk per
call when ``stream_usage=True``; Anthropic splits input and output across the
first and last chunk; summing is right either way.

The block deliberately reports TOKENS ONLY. It used to also compute a
dollar figure, which was the operator's provider cost, not the user's bill.
Pricing (if a deployment meters) is that deployment's table.

Cache accounting is ONE field, ``input_token_details.cache_read``. Cache
*creation* is counted here (a meter may want it) but never shown: only
Anthropic reports it separately, it is already inside ``input_tokens``, and a
second cache field that appears for one provider family is a client
special-case for a number nobody acts on. Reads are what a cache saves.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)


class UsageAccumulator:
    """Sums ``usage_metadata`` dicts across a turn."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read = 0
        self.cache_creation = 0
        self.reasoning = 0

    def add(self, usage: Mapping | None) -> None:
        if not isinstance(usage, Mapping):
            return
        self.input_tokens += int(usage.get("input_tokens") or 0)
        self.output_tokens += int(usage.get("output_tokens") or 0)
        input_details = usage.get("input_token_details") or {}
        self.cache_read += int(input_details.get("cache_read") or 0)
        self.cache_creation += int(input_details.get("cache_creation") or 0)
        output_details = usage.get("output_token_details") or {}
        self.reasoning += int(output_details.get("reasoning") or 0)

    @property
    def empty(self) -> bool:
        return self.input_tokens == 0 and self.output_tokens == 0


def usage_block(usage: UsageAccumulator | None, model_name: str) -> dict | None:
    """The ``usage`` block a turn ends with, or ``None`` when nothing was used.

    Field names and nesting are LangChain's ``usage_metadata``, and the counts
    are integers: they used to be strings in a chunk called ``costStatistics``,
    which is the same numbers under names only this repository used. The detail
    dicts appear only when non-zero.
    """
    if usage is None or usage.empty:
        return None
    block = {
        "type": "usage",
        "model": model_name or "unknown",
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.input_tokens + usage.output_tokens,
    }
    if usage.cache_read > 0:
        block["input_token_details"] = {"cache_read": usage.cache_read}
    if usage.reasoning > 0:
        block["output_token_details"] = {"reasoning": usage.reasoning}
    return block
