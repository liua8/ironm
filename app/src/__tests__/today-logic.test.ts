// 今天的版本由管家定（§163）：正在看要再问；点了之后的旧结果先当作正在看；首页那一行怎么说。
import { heroLine, settle, todaySig, withCoach } from "@/features/home/today-logic";
import type { TodayVersion } from "@/features/home/types";

const S = { day: 4, name: "上肢", minutes: 45, items: [{ exercise: "卧推", sets: 3, reps: "8" }] };
const ok = (changed = false): TodayVersion => ({ status: "ok", original: S, today: changed ? { ...S, items: [{ ...S.items[0], sets: 2 }] } : S, changed, changes: changed ? ["每个动作少 1 组〔K31〕"] : [], reasons: [] });

it("reviewing keeps polling; ok stops", () => {
  expect(settle({ status: "reviewing", original: S }, null, null)).toMatchObject({ poll: true, wait: null });
  expect(settle(ok(), null, null)).toMatchObject({ poll: false });
});

it("after 重试, a still-old coach_error is shown as reviewing until the wait runs out", () => {
  const r = settle({ status: "coach_error", original: S }, { error: true, left: 2 }, null);
  expect(r.shown.status).toBe("reviewing");
  expect(r.shown.original).toEqual(S);
  expect(r.wait).toEqual({ error: true, left: 1 });
  expect(settle({ status: "coach_error" }, { error: true, left: 0 }, null).shown.status).toBe("coach_error");
  expect(settle(ok(true), { error: true, left: 5 }, null)).toMatchObject({ wait: null, poll: false });
});

it("after 有点累, the unchanged old version counts as reviewing; a new version ends the wait", () => {
  const before = todaySig(ok());
  expect(settle(ok(), { before, left: 3 }, ok()).shown.status).toBe("reviewing");
  expect(settle(ok(true), { before, left: 3 }, ok()).shown).toEqual(ok(true));
});

it("hero line", () => {
  expect(heroLine({ status: "reviewing" })?.text).toBe("IronM 正在看今天的情况，下面先列原计划");
  expect(heroLine({ status: "coach_error" })?.tone).toBe("error");
  expect(heroLine({ status: "rest_today", message: "今天休息：连着练了 4 天" })?.text).toBe("今天休息：连着练了 4 天");
  expect(heroLine(ok(true))?.text).toBe("IronM 调整了今天：每个动作少 1 组〔K31〕");
  expect(heroLine(ok())).toBeNull();
});

it("withCoach swaps today's version only when the coach changed it", () => {
  const week = { days: [{ today: false, version: null }, { today: true, version: null }] };
  expect(withCoach(week, ok())).toBe(week);
  expect(withCoach(week, { status: "reviewing" })).toBe(week);
  const w = withCoach(week, ok(true));
  expect(w?.days?.[1].version).toEqual({ ...S, items: [{ ...S.items[0], sets: 2 }] });
  expect(w?.days?.[0].version).toBeNull();
});
