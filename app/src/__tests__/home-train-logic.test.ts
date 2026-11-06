// 首页·练、训练计划的纯逻辑（同网页 trainCard、weekDots、setsText、parseReps、planEdited）。
import { clean, editedLine, itemLine, parseReps, repsText, setsText, todayCard, weekDots } from "@/features/home/train-logic";
import type { Brief, Library, Training, Week, WeekDay } from "@/features/home/types";

const lib: Library = {
  exercises: [
    { id: "squat", name: "深蹲", part: "腿臀", muscles: "股四头肌", equipment: ["杠铃"], images: [{ url: "/iron/api/exercise-images/squat-0.jpg" }] },
    { id: "bench", name: "卧推", part: "胸", muscles: "胸大肌", equipment: ["杠铃"], gif: { url: "/iron/api/exercise-images/bench-0.gif" } },
    { id: "bike", name: "动感单车", part: "有氧", muscles: "心肺", equipment: ["器械"] },
  ],
};

const session = { day: 3, name: "下肢", minutes: 50, items: [{ exercise: "深蹲", sets: 4, reps: "8–10", load: "60 公斤" }, { exercise: "动感单车", sets: 1, reps: "20 分钟" }] };
const day = (over: Partial<WeekDay> = {}): WeekDay => ({
  date: "2026-11-04", weekday: "周三", today: true, done: false, session, version: null, changes: [], edited: [], warmup: null, burn: { low: 300, high: 400, how: "按体重估" }, ...over,
});
const tr: Training = { plan: { title: "三分化", days_per_week: 3, sessions: [session] }, targets: {}, workouts: [] };

describe("todayCard", () => {
  it("says it could not read rather than no plan", () => {
    expect(todayCard(null, null, null, lib).kind).toBe("failed");
  });
  it("no plan", () => {
    expect(todayCard(null, { ...tr, plan: null }, { days: [day()] }, lib).kind).toBe("noPlan");
  });
  it("rest day", () => {
    expect(todayCard(null, tr, { days: [day({ session: null })] }, lib)).toEqual({ kind: "plain", title: "今天休息", sub: "散散步、拉拉伸，让身体恢复。" });
  });
  it("done today", () => {
    const b: Brief = { today: { training: { kind: "session", done: true } } };
    expect(todayCard(b, tr, { days: [day()] }, lib)).toMatchObject({ kind: "plain", title: "下肢，练完了" });
  });
  it("session: parts, figures, cut sets, cardio by time, photo by main part", () => {
    const version = { ...session, items: [{ ...session.items[0], sets: 2 }, session.items[1]] };
    const c = todayCard(null, tr, { days: [day({ version })] }, lib, { 腿臀: { url: "/iron/api/food-images/legs.jpg", author: "A", license: "CC0" } });
    if (c.kind !== "session") throw new Error(c.kind);
    expect(c.sub).toBe("周三，练腿臀和有氧。IronM 按你今天的状态调整过。");
    expect(c.burn).toBe("300–400");
    expect(c.rows[0]).toMatchObject({ exercise: "深蹲", note: "60 公斤，比计划少 2 组", cut: true, sets: "2 组 × 8–10 次" });  // §176 照参照图
    expect(c.rows[1].sets).toBe("20 分钟");
    expect(c.rows[0].pic).toMatch(/^https?:\/\/.+\/iron\/api\/exercise-images\/squat-0\.jpg$/);
    expect(c.photo?.url).toMatch(/\/iron\/api\/food-images\/legs\.jpg$/);
  });
});

describe("weekDots", () => {
  it("hidden without a plan", () => expect(weekDots({ week: { planned: 0, done: 2 } })).toBeNull());
  it("lights done days", () => {
    const w = weekDots({ week: { planned: 3, done: 1 } });
    expect(w?.dots).toEqual([true, false, false]);
    expect(w?.label).toBe("这周练了 1 次，计划 3 次");
  });
  it("more done than planned shows all", () => expect(weekDots({ week: { due: 2, done: 3 } })?.dots).toHaveLength(3));
});

describe("text helpers", () => {
  it("setsText and itemLine", () => {
    expect(setsText({ exercise: "卧推", sets: 3, reps: "8" }, lib)).toBe("3×8");
    expect(setsText({ exercise: "动感单车", sets: 1, reps: "30" }, lib)).toBe("30");
    expect(itemLine({ exercise: "卧推", sets: 3, reps: "8", load: "40 公斤", note: "慢放" }, lib)).toBe("卧推 3×8（40 公斤，慢放）");
  });
  it("parseReps only takes a number or a range", () => {
    expect(parseReps("8–12")).toEqual([8, 12]);
    expect(parseReps(" 10 ")).toEqual([10]);
    expect(parseReps("每侧 8 次")).toBeNull();
    expect(repsText([8, 12])).toBe("8–12");
  });
  it("strips internal reference codes", () => {
    expect(clean("先别加重〔K03〕，睡够再说〔经验〕")).toBe("先别加重，睡够再说");
  });
  it("editedLine joins lines, notes and warning heads", () => {
    expect(editedLine({ lines: ["深蹲改成 3 组"], notes: ["今天只改这一次"], warnings: ["膝盖：注意别内扣"] })).toBe("深蹲改成 3 组；今天只改这一次；提醒：膝盖");
  });
});
