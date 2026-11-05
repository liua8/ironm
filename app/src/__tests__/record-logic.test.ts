// 战绩页（spec §137、§139、§147）：成就墙、月历格子、这周的对比、周报的字、时间线的一行。
import {
  bestSet,
  compareLine,
  type Calendar,
  lastLine,
  mainPart,
  md,
  monthCells,
  monthLine,
  prWall,
  shiftMonth,
  timelineFacts,
  timelineRows,
  weekCount,
  weekMoreLine,
  weekReportText,
  type Workout,
} from "@/features/record/logic";

const w = (day: string, items: Workout["items"], extra: Partial<Workout> = {}): Workout => ({ id: day, day, items, ...extra });

describe("prWall", () => {
  it("picks the best set per move and marks a broken PR", () => {
    const rows = prWall([
      w("2026-11-01", [{ exercise: "深蹲", done_sets: [{ weight_kg: 60, reps: 8 }, { weight_kg: 60, reps: 10 }] }]),
      w("2026-11-04", [{ exercise: "深蹲", done_sets: [{ weight_kg: 65, reps: 5 }] }]),
      w("2026-11-03", [{ exercise: "卧推", weight_kg: 40, reps: "8" }]),
    ]);
    expect(rows[0]).toMatchObject({ name: "深蹲", best: { weight_kg: 65, reps: 5 }, day: "2026-11-04", broke: true });
    expect(rows[1]).toMatchObject({ name: "卧推", best: { weight_kg: 40, reps: 8 }, broke: false });
  });

  it("does not mark a single record, skips rest days and moves without weight", () => {
    const rows = prWall([
      w("2026-11-01", [{ exercise: "俯卧撑", sets: 3, reps: "15" }]),
      w("2026-11-02", [], { done: false, rest: "busy" }),
      w("2026-11-03", [{ exercise: "硬拉", done_sets: [{ weight_kg: 80, reps: 5 }] }]),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].broke).toBe(false);
  });

  it("same weight, more reps is better", () => {
    expect(bestSet({ exercise: "x", done_sets: [{ weight_kg: 50, reps: 5 }, { weight_kg: 50, reps: 7 }, { weight_kg: 0, reps: 20 }] })).toEqual({ weight_kg: 50, reps: 7 });
  });
});

describe("calendar", () => {
  const cal: Calendar = {
    month: "2026-11",
    today: "2026-11-05",
    days: { "2026-11-03": [{ id: 1, done: true, line: "下肢 40 分钟" }], "2026-11-04": [{ id: 2, done: false, rest: "busy", line: "没练（太忙）" }] },
    done_days: ["2026-11-03"],
    rest_days: ["2026-11-04"],
    sets: { "2026-11-03": 18 },
    month_minutes: 40,
  };

  it("leads with blanks up to Monday and pads to whole weeks", () => {
    const cells = monthCells(cal);
    // 2026-11-01 是星期日：前面空 6 格
    expect(cells.slice(0, 6).every((c) => c === null)).toBe(true);
    expect(cells[6]).toMatchObject({ day: 1, iso: "2026-11-01" });
    expect(cells.length % 7).toBe(0);
    const d3 = cells.find((c) => c?.day === 3);
    expect(d3).toMatchObject({ lit: true, level: 3, entries: [{ id: 1 }] });
    expect(cells.find((c) => c?.day === 4)).toMatchObject({ lit: false, rest: true });
    expect(cells.find((c) => c?.day === 5)).toMatchObject({ today: true, entries: [] });
  });

  it("shifts across years and writes the month line", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(monthLine(cal)).toBe("本月练了 1 天，共 40 分钟。");
    expect(monthLine({ ...cal, month: "2026-10", done_days: [], month_minutes: 0 })).toBe("10月练了 0 天，共 0 分钟。");
  });
});

describe("this week", () => {
  it("counts days this week vs last week", () => {
    const today = new Date(2026, 10, 5); // 星期四
    const logs = [
      w("2026-11-05", []),
      w("2026-11-03", []),
      w("2026-11-03", []), // 一天两次只算一次
      w("2026-11-02", [], { done: false, rest: "rest" }),
      w("2026-10-28", []),
    ];
    expect(weekCount(logs, today)).toEqual({ monday: "2026-11-02", days: 2, before: 1, diff: 1 });
    expect(compareLine(1, 1)).toBe("比上周多 1 次。");
    expect(compareLine(-2, 3)).toBe("比上周少 2 次。");
    expect(compareLine(0, 2)).toBe("和上周一样。");
    expect(compareLine(0, 0)).toBe("上周没有记录。");
  });

  it("writes the second line only with data", () => {
    expect(weekMoreLine(null, null)).toBe("");
    expect(weekMoreLine({ month: "2026-11", today: "2026-11-05", days: {}, done_days: [], streak_days: 4, week: { rpe: 7 } }, { weight: { brief: "下降 0.4 公斤" }, sleep: { value: 7.2 } })).toBe(
      "连续打卡 4 天，平均感受 7.0 分，体重下降 0.4 公斤，睡眠平均 7.2 小时。",
    );
  });
});

describe("week report", () => {
  it("writes facts, records, weight and diet", () => {
    const t = weekReportText({
      from: "2026-10-26",
      to: "2026-11-01",
      done: 3,
      planned: 4,
      minutes: 150,
      sets: 42,
      volume_kg: 5230,
      records: [{ exercise: "深蹲", weight_kg: 80, reps: 5 }],
      weight: { from: 72.4, to: 71.9, change: -0.5 },
      diet: { on_target: 4, logged: 6 },
      rpe: 7.3,
      focus: "照计划来，保持节奏。",
    });
    expect(t.date).toBe("10月26日–11月1日");
    expect(t.head).toBe("练了 3 次，计划 4 次");
    expect(t.facts).toBe("150 分钟，42 组，总重量 5.2 吨，平均感受 7.3 分。");
    expect(t.more).toEqual(["破纪录：深蹲 80×5", "体重 72.4 → 71.9 公斤", "饮食 4 / 6 天在目标热量上下"]);
  });

  it("says so when there was no training", () => {
    const t = weekReportText({ from: "2026-10-26", to: "2026-11-01", done: 0, records: [], focus: "照计划来" });
    expect(t.head).toBe("上周没有训练记录");
    expect(t.facts).toBe("");
    expect(t.more).toEqual([]);
  });
});

describe("timeline", () => {
  it("writes facts and picks the most trained part for the photo", () => {
    const x = w("2026-11-03", [{ exercise: "深蹲", done_sets: [{ reps: 5, weight_kg: 60 }, { reps: 5, weight_kg: 60 }] }, { exercise: "卧推", sets: 3 }], {
      minutes: 45,
      rpe: 7,
      energy: "good",
      sore: ["大腿前"],
    });
    expect(timelineFacts(x)).toBe("45 分钟，5 组，感受 7 分，精力好，大腿前酸");
    expect(mainPart([{ name: "深蹲", part: "腿臀" }, { name: "卧推", part: "胸" }], x)).toBe("胸");
    expect(mainPart(null, x)).toBe("");
  });

  it("keeps workouts and rest days, and finds the last one", () => {
    const logs = [w("2026-11-04", [], { done: false, rest: "sick" }), w("2026-11-03", [], { session: "下肢" }), w("2026-11-02", [], { done: false })];
    expect(timelineRows(logs).map((x) => x.day)).toEqual(["2026-11-04", "2026-11-03"]);
    expect(lastLine(logs)).toBe("最近一次：11月3日，下肢");
    expect(lastLine([])).toBe("还没有训练记录");
    expect(md("2026-01-09")).toBe("1月9日");
  });
});
