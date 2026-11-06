// 训练记录器的纯逻辑（同网页 livePage 的 checkKg、markDone、addSet、finish）。
import {
  addSet, bumpValue, checkKg, clampRest, clock, completeSet, curPos, doneWords, e1rm, emptyMsg, type Live, type LiveItem,
  minutesToSeconds, moveItem, progress, secondsToMinutes, summarize, toNum, typedNum,
} from "@/features/live/logic";

const set = (w: number | null, r: number | null, done = false) => ({ weight_kg: w, reps: r, seconds: null, done, at: null });
const item = (over: Partial<LiveItem> = {}): LiveItem => ({
  exercise: "卧推", timed: false, rest: 90, target: "3×8 40 公斤", best: null, plan_kg: 40, sets: [set(40, 8), set(40, 8), set(40, 8)], cardio: false, ...over,
});
const live = (items: LiveItem[], noHeavier = false): Live => ({ id: "x", started: "2026-11-05T10:00:00", updated: "", session: "上肢", items, no_heavier: noHeavier });

describe("clock and e1rm", () => {
  it("formats", () => {
    expect(clock(65)).toBe("1:05");
    expect(clock(3725)).toBe("1:02:05");
    expect(clock(-3)).toBe("0:00");
  });
  it("same formula as the server", () => {
    expect(e1rm(100, 1)).toBe(100);
    expect(e1rm(60, 10)).toBeCloseTo(80);
    expect(e1rm(60, 31)).toBeNull();
    expect(e1rm(null, 5)).toBeNull();
  });
});

describe("checkKg", () => {
  it("within one step of plan: no warning", () => {
    const L = live([item()]);
    L.items[0].sets[0].weight_kg = 42.5;
    expect(checkKg(L, 0, 0, 40, { 卧推: 2.5 }, {}, null)).toBeNull();
  });
  it("more than a step over plan asks to confirm", () => {
    const L = live([item()]);
    L.items[0].sets[0].weight_kg = 50;
    expect(checkKg(L, 0, 0, 40, { 卧推: 2.5 }, {}, null)).toEqual({ i: 0, text: "比计划重 25%，超过一档或一成，确定吗？", back: 40, w: 50 });
  });
  it("confirmed weight is not asked again", () => {
    const L = live([item()]);
    L.items[0].sets[0].weight_kg = 50;
    expect(checkKg(L, 0, 0, 40, undefined, { 0: 50 }, null)).toBeNull();
  });
  it("no heavier than plan for special cases: puts it back", () => {
    const L = live([item()], true);
    L.items[0].sets[0].weight_kg = 45;
    const w = checkKg(L, 0, 0, 40, undefined, {}, null);
    expect(w?.text).toMatch(/今天不比计划加重/);
    expect(L.items[0].sets[0].weight_kg).toBe(40);
  });
  it("way above past best warns about a typo", () => {
    const L = live([item({ plan_kg: null, best: 50 })]);
    L.items[0].sets[0].weight_kg = 60;
    expect(checkKg(L, 0, 0, 40, undefined, {}, null)?.text).toBe("比你以前最好的成绩重不少，确定没有多按？");
  });
  it("lighter clears this item's warning", () => {
    const L = live([item()]);
    L.items[0].sets[0].weight_kg = 35;
    expect(checkKg(L, 0, 0, 40, undefined, {}, { i: 0, text: "x" })).toBeNull();
    expect(checkKg(L, 0, 0, 40, undefined, {}, { i: 1, text: "y" })).toEqual({ i: 1, text: "y" });
  });
});

describe("marking sets", () => {
  it("empty set cannot be ticked", () => {
    expect(emptyMsg(item(), set(40, null), false)).toBe("先填这一组做了几次（和重量），再打勾。");
    expect(emptyMsg(item({ timed: true }), set(null, null), false)).toBe("先填秒数，或点计时。");
    expect(emptyMsg(item({ timed: true, cardio: true }), set(null, null), false)).toBe("先填做了多少分钟，或点计时。");
    expect(emptyMsg(item({ timed: true }), set(null, null), true)).toBe("");
    expect(emptyMsg(item(), set(40, 8), false)).toBe("");
  });
  it("short set lowers the next one by a step; rest starts", () => {
    const it = item();
    it.sets[0].reps = 6;
    const r = completeSet([it], 0, 0, 1000, null, { 卧推: 2.5 });
    expect(it.sets[0].done).toBe(true);
    expect(r.restEnd).toBe(1000 + 90 * 1000);
    expect(it.sets[1].weight_kg).toBe(37.5);
    expect(r.next).toBe("这组少了 2 次，下一组先用 37.5 公斤");
  });
  it("records a PR only above past best and this session's sets", () => {
    const it = item({ best: 50, sets: [set(45, 8), set(40, 8)] });
    expect(completeSet([it], 0, 0, 0, null, undefined).pr).toBe("卧推 45×8，估算最大重量 57 公斤（以前 50）");
    expect(completeSet([it], 0, 1, 0, null, undefined).pr).toBe("");
  });
  it("timing records seconds", () => {
    const it = item({ timed: true, sets: [{ weight_kg: null, reps: null, seconds: null, done: false, at: null }] });
    completeSet([it], 0, 0, 31_000, 1_000, undefined);
    expect(it.sets[0].seconds).toBe(30);
  });
  it("current set, progress and summary", () => {
    const a = item({ sets: [set(40, 8, true), set(40, 8)] });
    const b = item({ exercise: "平板支撑", timed: true, sets: [{ weight_kg: null, reps: null, seconds: 60, done: true, at: null }] });
    expect(curPos([a, b])).toEqual({ i: 0, j: 1 });
    expect(progress([a, b])).toMatchObject({ all: 3, done: 2, text: "第 3 / 共 3 组", pct: 67 });
    expect(summarize([a, b])).toEqual({ sets: 2, exercises: 2, volume: 320 });
  });
});

describe("editing", () => {
  it("add set copies the last one, max 20", () => {
    const it = item();
    addSet(it);
    expect(it.sets[3]).toEqual(set(40, 8));
    it.sets = Array.from({ length: 20 }, () => set(1, 1));
    expect(addSet(it)).toBe(false);
  });
  it("bump never goes below zero", () => {
    const s = set(1, 8);
    expect(bumpValue(s, "weight_kg", -2.5)).toBe(1);
    expect(s.weight_kg).toBe(0);
  });
  it("move and rest limits", () => {
    const xs = [item({ exercise: "A" }), item({ exercise: "B" })];
    expect(moveItem(xs, 0, -1)).toBe(false);
    expect(moveItem(xs, 0, 1)).toBe(true);
    expect(xs.map((x) => x.exercise)).toEqual(["B", "A"]);
    expect(clampRest(20, -15)).toBe(15);
    expect(clampRest(595, 15)).toBe(600);
  });
  it("cardio minutes are stored as seconds", () => {
    expect(minutesToSeconds(20)).toBe(1200);
    expect(minutesToSeconds(null)).toBeNull();
    expect(secondsToMinutes(1250)).toBe("21");
    expect(toNum("")).toBeNull();
    expect(toNum("abc")).toBeNull();
    expect(toNum("37.5")).toBe(37.5);
  });
});

describe("doneWords", () => {
  const base = { summary: { minutes: 40, exercises: 3, sets: 9, volume: 2000 } };
  it("week goal reached now", () => {
    expect(doneWords({ ...base, workout: { id: "w", celebrate: { week: { before: 2, done: 3, planned: 3, reached_now: true } } } })).toEqual({ title: "本周目标达成", week: "这一练让本周目标刚好达成！" });
  });
  it("PR and still behind", () => {
    const prs = [{ exercise: "卧推", weight_kg: 50, reps: 5, e1rm: 58, before: 55 }];
    expect(doneWords({ ...base, workout: { id: "w", celebrate: { prs, week: { done: 1, planned: 3 } } } })).toEqual({ title: "破纪录了", week: "本周第 1 练，还差 2 练。" });
  });
  it("extra after goal", () => {
    expect(doneWords({ ...base, workout: { id: "w", celebrate: { week: { done: 4, planned: 3 } } } }).week).toBe("本周目标已经达成，这一练是额外加分。");
  });
});

describe("typedNum (§178)", () => {
  const kg = { max: 500, dec: true };
  const reps = { max: 100 };
  it("parses weight with one decimal and whole reps", () => {
    expect(["62.5", " 70 ", "70，5", "７５", "62.55", "0"].map((t) => typedNum(t, kg))).toEqual([62.5, 70, 70.5, 75, 62.6, 0]);
    expect(["8", "8.6"].map((t) => typedNum(t, reps))).toEqual([8, 9]);
  });
  it("bad input keeps the old value", () => {
    expect(["", "abc", "-5", "600", "1e3"].map((t) => typedNum(t, kg))).toEqual([null, null, null, null, null]);
    expect(typedNum("101", reps)).toBeNull();
  });
});
