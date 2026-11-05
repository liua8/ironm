// 对话页的纯逻辑（spec §164 第二期）：读流式回答、一块块拼回答、去掉内部编号、切段落。
import { applyBlock, cardExpired, coachMsg, fromHistory, inboxShown, progressHead, weekSaid } from "@/features/chat/model";
import { type ChatBlock, parseSseLine, parseSseText, readSse, SseParser, Utf8Stream } from "@/features/chat/sse";
import { cleanText, monthDay, paragraphs, sessionTime, spans } from "@/features/chat/text";

const utf8 = (s: string) => new TextEncoder().encode(s);

describe("Utf8Stream", () => {
  it("decodes Chinese split across chunks", () => {
    const bytes = utf8("深蹲😀好");
    const d = new Utf8Stream();
    let out = "";
    for (let i = 0; i < bytes.length; i += 1) out += d.decode(bytes.slice(i, i + 1));
    expect(out).toBe("深蹲😀好");
  });

  it("replaces bad bytes and a dangling half character at the end", () => {
    const d = new Utf8Stream();
    expect(d.decode(new Uint8Array([0x61, 0x80, 0x62]))).toBe("a�b");
    expect(d.decode(new Uint8Array([0xe6, 0xb7]), true)).toBe("�");
  });
});

describe("SSE", () => {
  it("parses data lines and skips heartbeats, junk and other lines", () => {
    expect(parseSseLine('data: {"type":"text","text":"你好"}')).toEqual({ type: "text", text: "你好" });
    expect(parseSseLine('data: {"type":"heartbeat"}')).toBeNull();
    expect(parseSseLine("data: {oops")).toBeNull();
    expect(parseSseLine("event: x")).toBeNull();
    expect(parseSseLine("data: [1]")).toBeNull();
  });

  it("joins lines split across pushes and handles CRLF", () => {
    const p = new SseParser();
    expect(p.push('data: {"type":"te')).toEqual([]);
    expect(p.push('xt","text":"a"}\r\n\r\ndata: {"type":"end"}')).toEqual([{ type: "text", text: "a" }]);
    expect(p.end()).toEqual([{ type: "end" }]);
    expect(parseSseText('data: {"type":"start","id":"x"}\n\ndata: {"type":"end"}\n')).toHaveLength(2);
  });

  it("reads a byte stream to the end", async () => {
    const all = utf8('data: {"type":"text","text":"练腿"}\n\ndata: {"type":"heartbeat"}\n\ndata: {"type":"end"}');
    const chunks = [all.slice(0, 25), all.slice(25, 26), all.slice(26)];
    let i = 0;
    const body = { getReader: () => ({ read: async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true }) }) };
    const got: ChatBlock[] = [];
    await readSse(body, (b) => got.push(b));
    expect(got).toEqual([{ type: "text", text: "练腿" }, { type: "end" }]);
  });
});

describe("cleanText", () => {
  it("removes internal reference codes and tags", () => {
    expect(cleanText("连续两次多做 1–2 次，加重 2–10%〔K03〕。没完成就保持〔经验〕。")).toBe("连续两次多做 1–2 次，加重 2–10%。没完成就保持。");
    expect(cleanText("你说过膝盖疼〔m20〕，先别跳。")).toBe("你说过膝盖疼，先别跳。");
    expect(cleanText("<statement>血糖 5.1<cite>[r3]</cite></statement>，正常")).toBe("血糖 5.1，正常");
    expect(cleanText("提醒一句：〔K01〕，先别练")).toBe("提醒一句：先别练");
    expect(cleanText("见上（〔K02〕）。")).toBe("见上。");
  });

  it("hides a half reference while still streaming", () => {
    expect(cleanText("加重 2–10%〔K0", true)).toBe("加重 2–10%");
    expect(cleanText("血糖 5.1<cite>[r", true)).toBe("血糖 5.1");
    expect(cleanText("血糖 5.1<ci", true)).toBe("血糖 5.1");
    expect(cleanText("加重〔K0", false)).toBe("加重〔K0");
  });
});

describe("paragraphs", () => {
  it("splits paragraphs, lists, headings and bold", () => {
    const ps = paragraphs("**今天练腿**\n- 深蹲 3×8\n2. 硬拉 3×5\n\n### 注意\n别憋气");
    expect(ps).toHaveLength(2);
    expect(ps[0][0]).toEqual({ kind: "text", mark: "", spans: [{ text: "今天练腿", bold: true }] });
    expect(ps[0][1]).toMatchObject({ kind: "bullet", mark: "•", spans: [{ text: "深蹲 3×8", bold: false }] });
    expect(ps[0][2]).toMatchObject({ kind: "num", mark: "2." });
    expect(ps[1][0]).toMatchObject({ kind: "head", spans: [{ text: "注意", bold: true }] });
    expect(spans("先**热身**再练")).toEqual([
      { text: "先", bold: false },
      { text: "热身", bold: true },
      { text: "再练", bold: false },
    ]);
  });
});

describe("time", () => {
  it("writes today and other days", () => {
    const now = new Date(2026, 10, 5, 20, 0);
    expect(sessionTime(new Date(2026, 10, 5, 8, 3).toISOString(), now)).toBe("今天 08:03");
    expect(sessionTime(new Date(2026, 10, 3, 21, 30).toISOString(), now)).toBe("11月3日 21:30");
    expect(sessionTime("bad", now)).toBe("");
    expect(monthDay("2026-11-03")).toBe("11月3日");
  });
});

describe("applyBlock", () => {
  it("builds an answer from blocks without changing the old message", () => {
    const blocks: ChatBlock[] = [
      { type: "start", id: "r1" },
      { type: "tool_call", id: "turn", args: { turn: "t9" } },
      { type: "tool_call", id: "agent", name: "IronM", args: { 任务: "查训练记录" } },
      { type: "text", text: "今天" },
      { type: "tool_result", tool_call_id: "agent", content: "查到 3 次" },
      { type: "text", text: "练腿。" },
      { type: "tool_call", id: "card-d1", name: "计划预览", args: { kind: "plan", draft: "d1" } },
      { type: "tool_result", tool_call_id: "card-d1", content: '{"title":"计划预览","sessions":[]}' },
      { type: "tool_call", id: "sources", name: "依据与来源" },
      { type: "tool_result", tool_call_id: "sources", content: "资料：\n- 指南" },
      { type: "notice", text: "记下了" },
      { type: "end" },
    ];
    const first = coachMsg("k1");
    let m = first;
    for (const b of blocks) {
      m = applyBlock(m, b);
      if (b.type === "tool_call" && b.id === "agent") expect(progressHead(m)).toBe("IronM 正在查资料和数据…");
    }
    expect(first.text).toBe("");
    expect(m).toMatchObject({ id: "r1", turn: "t9", text: "今天练腿。", sources: "资料：\n- 指南", notices: ["记下了"], done: true });
    expect(m.steps).toEqual([{ id: "agent", name: "IronM", task: "查训练记录", result: "查到 3 次", done: true }]);
    expect(m.cards).toEqual([{ id: "card-d1", kind: "plan", draft: "d1", data: { title: "计划预览", sessions: [] } }]);
    expect(progressHead(m)).toBe("IronM 是怎么答的");
  });

  it("keeps the first card, tolerates bad card JSON and reports errors", () => {
    let m = applyBlock(coachMsg("k"), { type: "tool_call", id: "card-x", args: { kind: "log", draft: "x" } });
    m = applyBlock(m, { type: "tool_call", id: "card-x", args: { kind: "log", draft: "x" } });
    m = applyBlock(m, { type: "tool_result", tool_call_id: "card-x", content: "{bad" });
    expect(m.cards).toEqual([{ id: "card-x", kind: "log", draft: "x", data: null }]);
    expect(applyBlock(m, { type: "error" }).error).toBe("这次没能回答，请稍后再试。");
    expect(applyBlock(m, { type: "whatever" })).toBe(m);
  });

  it("replays history rows", () => {
    let n = 0;
    const msgs = fromHistory(
      [
        { role: "user", content: "练什么", timestamp: "2026-11-05T01:00:00Z" },
        { role: "assistant", id: "r2", content: "备用正文", content_dict: [{ type: "text", text: "练背" }] },
        { role: "assistant", id: "r3", content: "只有正文" },
      ],
      () => `h${++n}`,
    );
    expect(msgs.map((m) => m.role)).toEqual(["user", "coach", "coach"]);
    expect(msgs[1]).toMatchObject({ key: "h2", id: "r2", text: "练背", done: true });
    expect(msgs[2]).toMatchObject({ text: "只有正文", done: true });
  });
});

describe("inbox, week report and cards", () => {
  it("lists at most three non-target changes", () => {
    const c = (key: string, kind = "review") => ({ key, kind, change: "added", after: key });
    expect(inboxShown({ version: 1, changes: [c("a", "target"), c("b"), c("c"), c("d"), c("e")], pending: [] }).map((x) => x.key)).toEqual(["b", "c", "d"]);
  });

  it("says the week in two or three sentences", () => {
    expect(weekSaid({ from: "", to: "", done: 3, planned: 4, minutes: 150, records: [{ exercise: "深蹲", weight_kg: 80, reps: 5 }], focus: "照计划来" })).toBe(
      "上周练了 3 次（计划 4 次），一共 150 分钟。破了 1 个纪录，深蹲 做到了 80 公斤 × 5。下周重点：照计划来",
    );
    expect(weekSaid({ from: "", to: "", done: 0, records: [], focus: "照计划来" })).toBe("上周没有训练记录。下周重点：照计划来");
  });

  it("marks pending cards past their time as expired", () => {
    const now = Date.parse("2026-11-05T12:00:00Z");
    expect(cardExpired({ expires: "2026-11-05T11:00:00Z" }, "pending", now)).toBe(true);
    expect(cardExpired({ expires: "2026-11-05T11:00:00Z" }, "confirmed", now)).toBe(false);
    expect(cardExpired({ expires: "2026-11-06T11:00:00Z" }, "pending", now)).toBe(false);
  });
});
