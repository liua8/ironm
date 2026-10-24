"""LangGraph's stream → what a client renders.

    blocks.py         the vocabulary, named the way LangChain names it: `text`,
                      `reasoning`, `tool_call`, `tool_result`, `usage`, plus
                      the four the stream itself reports. Stdlib only, so
                      reading a stored transcript needs no framework
    events_bridge.py  one reading of the stream into `kernel.events`, the
                      wire-neutral vocabulary: usage, reasoning, text, tool
                      call started/arguments/completed, tool result with its
                      artifact status, interrupt with every pending action
    stream.py         the blocks a client renders, over those events

Two layers because the second is a product decision and the first is not: a
consumer whose client speaks its own frames binds `events_bridge` and writes
its own renderer, and both then agree about what happened in the turn.

Which seam is for whom:

* a REPLACEMENT AGENT (`registry.AbstractAgent`) yields `blocks`. Stdlib only,
  so a plugin depends on the vocabulary without depending on LangChain;
* a consumer rendering its OWN wire binds `events_bridge` and `kernel.events`;
* `stream` is this repository's renderer over the second for the first, and is
  nobody's seam.
"""
