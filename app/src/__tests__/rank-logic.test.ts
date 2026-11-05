// 排行榜的纯逻辑（spec §161）：没人评时不写"没人评""0 人参与""待评 N 个"；三种排法；条目的状态一行；评论排序。
import {
  boardCaption,
  emptyText,
  itemStatus,
  lineMeta,
  md,
  pendingTitle,
  peopleLine,
  planDaysText,
  rowNo,
  rowTag,
  scoreText,
  shortOf,
  sortComments,
  sortOptions,
  sortRows,
  tierBars,
  tierNames,
  trendKind,
  waitingOf,
  weekdayName,
} from "@/features/rank/logic";
import type { Comment, RankRow } from "@/features/rank/types";

const TIERS = [
  { key: "hang", name: "夯" },
  { key: "top", name: "顶级" },
  { key: "elite", name: "人上人" },
  { key: "npc", name: "NPC" },
  { key: "la", name: "拉" },
];
const names = tierNames(TIERS);

const row = (over: Partial<RankRow>): RankRow => ({
  key: "k", name: "深蹲", part: "", custom: false, added: "", desc: "", tag: "", votes: 0, mean: null, score: null, tier: "",
  counts: { hang: 0, top: 0, elite: 0, npc: 0, la: 0 }, mine: "", rank: null, trend: "", image: null, credit: null, ...over,
});

describe("没人评时不写空话（§161）", () => {
  it("名次、档位牌", () => {
    expect(rowNo(0, null)).toBe("");
    expect(rowNo(3, null)).toBe("–");
    expect(rowNo(3, 2)).toBe("2");
    expect(rowTag(0, row({}), names)).toBeNull();
    expect(rowTag(4, row({}), names)).toEqual({ text: "待评", tier: "wait" });
    expect(rowTag(4, row({ rank: 1, tier: "hang" }), names)).toEqual({ text: "夯", tier: "hang" });
  });

  it("人数、最上面一行、待评标题、空列表", () => {
    expect(peopleLine(0)).toBe("");
    expect(peopleLine(5)).toBe("本周 · 5 人参与");
    const none = boardCaption({ people: 0, disclaimer: "用户评分，不代表平台观点。" }, "");
    expect(none).toBe("还没人评过，点进去打第一个分。用户评分，不代表平台观点。");
    expect(none).not.toMatch(/0 人参与|没人评$|待评/);
    expect(boardCaption({ people: 7, disclaimer: "说明。" }, "胸")).toBe("7 人参与 · 说明。 按部位看时名次是这个部位里的，不显示名次变化。");
    expect(pendingTitle(0, 12)).toBe("");
    expect(pendingTitle(2, 12)).toBe("待评 12 个 · 3 个人评过才上榜");
    expect(emptyText(0, "综合")).toBe("");
    expect(emptyText(2, "综合")).toMatch(/还没有上榜的/);
    expect(emptyText(2, "新上榜")).toBe("还没有用户添加的条目。");
  });
});

describe("榜单", () => {
  const items = [
    row({ key: "a", rank: 1, score: 4.5, votes: 5, comments: 1 }),
    row({ key: "b", rank: 2, score: 4.1, votes: 3, comments: 6, added: "2026-11-01" }),
    row({ key: "c", votes: 2, added: "2026-11-04" }),
    row({ key: "d", votes: 0 }),
    row({ key: "e", votes: 1 }),
  ];

  it("三种排法；训练计划榜没有新上榜", () => {
    expect(sortRows(items, "综合").map((x) => x.key)).toEqual(["a", "b"]);
    expect(sortRows(items, "评论多").map((x) => x.key)).toEqual(["b", "a"]);
    expect(sortRows(items, "新上榜").map((x) => x.key)).toEqual(["c", "b"]);
    expect(sortOptions({ can_add: true })).toEqual(["综合", "评论多", "新上榜"]);
    expect(sortOptions({ can_add: false })).toEqual(["综合", "评论多"]);
  });

  it("待评按票数，写还差几票", () => {
    expect(waitingOf(items).map((x) => x.key)).toEqual(["c", "e", "d"]);
    expect(shortOf(items[2], 3)).toBe("还差 1 票");
    expect(shortOf(items[3], 3)).toBe("");
  });

  it("分数、趋势、下面一行小字", () => {
    expect(scoreText({ mean: 4 })).toBe("4.0");
    expect(scoreText({ mean: null })).toBe("—");
    expect([trendKind("↑2"), trendKind("↓1"), trendKind("新"), trendKind("")]).toEqual(["up", "down", "new", ""]);
    const c: Comment = { id: "1", nick: "铁人", text: "很稳", likes: 2, liked: false, mine: false, at: "2026-11-05T10:00:00" };
    expect(lineMeta(row({ votes: 4, comments: 1, top_comment: c }))).toBe("4 人评过 · 1 条评论 · “很稳”");
  });
});

describe("条目", () => {
  it("状态一行", () => {
    expect(itemStatus(row({ votes: 4, rank: 2, trend: "↑1" }), 3)).toBe("第 2 名 · 4 人评过 · 本周 ↑1");
    expect(itemStatus(row({ votes: 1 }), 3)).toBe("1 人评过，还差 2 票上榜");
    expect(itemStatus(row({}), 3)).toBe("还没人评过，来投第一票");
  });

  it("五档条长按最多的那档", () => {
    const bars = tierBars(row({ counts: { hang: 4, top: 2, elite: 0, npc: 0, la: 1 } }), TIERS);
    expect(bars.map((b) => [b.name, b.n, b.frac])).toEqual([["夯", 4, 1], ["顶级", 2, 0.5], ["人上人", 0, 0], ["NPC", 0, 0], ["拉", 1, 0.25]]);
  });

  it("评论：热门照服务端的顺序，最新按时间", () => {
    const c = (id: string, at: string): Comment => ({ id, nick: "", text: "", likes: 0, liked: false, mine: false, at });
    const list = [c("a", "2026-11-01T00:00:00"), c("b", "2026-11-05T00:00:00"), c("c", "2026-11-03T00:00:00")];
    expect(sortComments(list, "热门").map((x) => x.id)).toEqual(["a", "b", "c"]);
    expect(sortComments(list, "最新").map((x) => x.id)).toEqual(["b", "c", "a"]);
    expect(md("2026-11-05T10:00:00")).toBe("11月5日");
  });

  it("训练计划的周几和版本说明", () => {
    expect(weekdayName(1)).toBe("周一");
    expect(weekdayName(7)).toBe("周日");
    expect(planDaysText({ days: [3, 4], sessions: [1, 2, 3] })).toBe("有每周 3、4 天几个版本，这里是每周 3 天的健身房版。");
    expect(planDaysText({ days: [3], sessions: [1, 2, 3] })).toBe("这里是健身房版。");
  });
});
