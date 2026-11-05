// 战绩页的纯计算（同网页 app.js 的 recordPage、prWall、monthGrid、weekReport、timelinePage）：不碰界面，方便测试。

export type Feeling = "good" | "ok" | "poor";
export type RestWhy = "rest" | "sick" | "travel" | "busy";
export type DoneSet = { reps: number; weight_kg?: number | null };
export type LogItem = { exercise: string; sets?: number | null; reps?: string; weight_kg?: number | null; done_sets?: DoneSet[] };
export type Workout = {
  id: string | number;
  day: string;
  session?: string;
  items?: LogItem[];
  done?: boolean;
  rpe?: number | null;
  minutes?: number | null;
  note?: string;
  energy?: Feeling | null;
  slept?: Feeling | null;
  sore?: string[];
  rest?: RestWhy | null;
  photo?: boolean;
};

export type CalEntry = { id: string | number; done: boolean; session?: string; rpe?: number | null; line: string; rest?: RestWhy | null };
export type Calendar = {
  month: string; // 2026-11
  today: string; // 2026-11-05
  days: Record<string, CalEntry[]>;
  done_days: string[];
  rest_days?: string[];
  sets?: Record<string, number>;
  month_minutes?: number;
  streak_days?: number;
  week?: { rpe?: number | null };
};

export type WeekRecord = { exercise: string; weight_kg: number; reps: number };
export type WeekReport = {
  from: string;
  to: string;
  done: number;
  planned?: number | null;
  minutes?: number;
  sets?: number;
  volume_kg?: number;
  records: WeekRecord[];
  weight?: { from: number; to: number; change: number } | null;
  diet?: { on_target: number; logged: number } | null;
  rpe?: number | null;
  focus: string;
  seen?: boolean;
};

export const FEELING_WORDS: Record<Feeling, string> = { good: "好", ok: "一般", poor: "差" };
export const REST_WORDS: Record<RestWhy, string> = { rest: "休息", sick: "生病", travel: "出差", busy: "太忙" };
export const WEEK = ["一", "二", "三", "四", "五", "六", "日"] as const;

/** 本地日期写成 2026-11-05。 */
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** 2026-11-05 → 11月5日。 */
export function md(iso: string | null | undefined): string {
  const [, m, d] = String(iso ?? "").slice(0, 10).split("-").map(Number);
  return m && d ? `${m}月${d}日` : "";
}

/** 这一天所在那周的周一。 */
export function mondayOf(d: Date): string {
  return isoDay(new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7)));
}

function addDays(iso: string, n: number): string {
  const [y, m, d] = iso.split("-").map(Number);
  return isoDay(new Date(y, m - 1, d + n));
}

const trainedOnly = (logs: Workout[]) => logs.filter((x) => x.done !== false && !x.rest);

/** 这周练了几天、上周几天（同网页：按天数算，一天练两次算一次）。 */
export function weekCount(logs: Workout[], today: Date): { monday: string; days: number; before: number; diff: number } {
  const monday = mondayOf(today);
  const lastMonday = addDays(monday, -7);
  const trained = trainedOnly(logs);
  const days = new Set(trained.filter((x) => x.day >= monday).map((x) => x.day)).size;
  const before = new Set(trained.filter((x) => x.day >= lastMonday && x.day < monday).map((x) => x.day)).size;
  return { monday, days, before, diff: days - before };
}

/** "比上周多 2 次。" 这一句。 */
export function compareLine(diff: number, before: number): string {
  if (diff > 0) return `比上周多 ${diff} 次。`;
  if (diff < 0) return `比上周少 ${-diff} 次。`;
  return before ? "和上周一样。" : "上周没有记录。";
}

type BriefWeek = { planned?: number; due?: number; weight?: { brief?: string } | null; sleep?: { value?: number | null } | null };

/** 这周第二行：连续打卡、平均感受、体重、睡眠，有数据才写。 */
export function weekMoreLine(cal: Calendar | null, w: BriefWeek | null | undefined): string {
  const rpe = cal?.week?.rpe;
  const parts = [
    cal ? `连续打卡 ${cal.streak_days ?? 0} 天` : "",
    rpe != null ? `平均感受 ${rpe.toFixed(1)} 分` : "",
    w?.weight?.brief ? `体重${w.weight.brief}` : "",
    w?.sleep?.value != null ? `睡眠平均 ${w.sleep.value} 小时` : "",
  ].filter(Boolean);
  return parts.length ? `${parts.join("，")}。` : "";
}

/** 这个动作这次最好的一组：重的优先，一样重次数多的优先。 */
export function bestSet(it: LogItem): DoneSet | null {
  const sets: DoneSet[] = it.done_sets?.length ? it.done_sets : it.weight_kg ? [{ weight_kg: it.weight_kg, reps: parseInt(it.reps ?? "", 10) || 0 }] : [];
  let best: DoneSet | null = null;
  for (const x of sets) {
    if (!x.weight_kg) continue;
    if (!best || better(x, best)) best = x;
  }
  return best;
}

const better = (a: DoneSet, b: DoneSet) => (a.weight_kg ?? 0) > (b.weight_kg ?? 0) || (a.weight_kg === b.weight_kg && a.reps > b.reps);

export type PrRow = { name: string; best: DoneSet; day: string; times: number; broke: boolean };

/** 成就：最近 30 天每个动作最好的一组；比这 30 天里更早的都好的标"破 PR"（只有一次记录的不标）。 */
export function prWall(workouts: Workout[]): PrRow[] {
  const by = new Map<string, { best: DoneSet | null; day: string; times: number; broke: boolean }>();
  for (const w of trainedOnly(workouts).sort((a, b) => a.day.localeCompare(b.day))) {
    for (const it of w.items ?? []) {
      const b = bestSet(it);
      if (!b) continue;
      const cur = by.get(it.exercise) ?? { best: null, day: "", times: 0, broke: false };
      cur.broke = cur.times > 0 && cur.best !== null && better(b, cur.best);
      if (!cur.best || better(b, cur.best)) {
        cur.best = b;
        cur.day = w.day;
      }
      cur.times += 1;
      by.set(it.exercise, cur);
    }
  }
  return [...by.entries()]
    .map(([name, x]) => ({ name, best: x.best as DoneSet, day: x.day, times: x.times, broke: x.broke }))
    .sort((a, b) => Number(b.broke) - Number(a.broke) || b.day.localeCompare(a.day));
}

export type CalCell = { iso: string; day: number; lit: boolean; level: 1 | 2 | 3; rest: boolean; today: boolean; entries: CalEntry[]; sets: number } | null;

/** 月历的格子：前面空出周一之前的天数（null），之后每天一格；组数 ≥16 最深、≥8 中等。 */
export function monthCells(cal: Calendar): CalCell[] {
  const [y, m] = cal.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate();
  const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  const lit = new Set(cal.done_days);
  const rested = new Set(cal.rest_days ?? []);
  const cells: CalCell[] = Array.from({ length: lead }, () => null);
  for (let d = 1; d <= days; d++) {
    const iso = `${cal.month}-${String(d).padStart(2, "0")}`;
    const n = cal.sets?.[iso] ?? 0;
    cells.push({ iso, day: d, lit: lit.has(iso), level: n >= 16 ? 3 : n >= 8 ? 2 : 1, rest: rested.has(iso), today: iso === cal.today, entries: cal.days[iso] ?? [], sets: n });
  }
  while (cells.length % 7) cells.push(null);
  return cells;
}

/** 翻月：2026-01 往前一个月是 2025-12。 */
export function shiftMonth(month: string, n: number): string {
  const [y, m] = month.split("-").map(Number);
  return isoDay(new Date(y, m - 1 + n, 1)).slice(0, 7);
}

/** 月历下面那一句。 */
export function monthLine(cal: Calendar): string {
  const now = cal.month === cal.today.slice(0, 7);
  return `${now ? "本月" : `${Number(cal.month.slice(5))}月`}练了 ${cal.done_days.length} 天，共 ${cal.month_minutes ?? 0} 分钟。`;
}

export const kgText = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)} 吨` : `${Math.round(v)} 公斤`);

/** 上周周报的几行字（同网页 weekReport）。 */
export function weekReportText(r: WeekReport): { date: string; head: string; facts: string; more: string[] } {
  const facts = [
    r.minutes ? `${r.minutes} 分钟` : "",
    r.sets ? `${r.sets} 组` : "",
    r.volume_kg ? `总重量 ${kgText(r.volume_kg)}` : "",
    r.rpe != null ? `平均感受 ${r.rpe} 分` : "",
  ].filter(Boolean).join("，");
  const more = [
    r.records.length ? `破纪录：${r.records.slice(0, 3).map((x) => `${x.exercise} ${x.weight_kg}×${x.reps}`).join("、")}` : "",
    r.weight ? `体重 ${r.weight.from} → ${r.weight.to} 公斤` : "",
    r.diet ? `饮食 ${r.diet.on_target} / ${r.diet.logged} 天在目标热量上下` : "",
  ].filter(Boolean);
  return {
    date: `${md(r.from)}–${md(r.to)}`,
    head: r.done ? `练了 ${r.done} 次${r.planned ? `，计划 ${r.planned} 次` : ""}` : "上周没有训练记录",
    facts: facts ? `${facts}。` : "",
    more,
  };
}

export const setsOf = (it: LogItem) => it.done_sets?.length || it.sets || 0;

export function stateText(x: Workout): string {
  return [
    x.energy ? `精力${FEELING_WORDS[x.energy]}` : "",
    x.slept ? `睡得${FEELING_WORDS[x.slept]}` : "",
    x.sore?.length ? `${x.sore.join("、")}酸` : "",
  ].filter(Boolean).join("，");
}

/** 时间线卡片上的一行：多长时间、几组、感受、状态。 */
export function timelineFacts(x: Workout): string {
  const sets = (x.items ?? []).reduce((a, it) => a + setsOf(it), 0);
  return [x.minutes ? `${x.minutes} 分钟` : "", sets ? `${sets} 组` : "", x.rpe ? `感受 ${x.rpe} 分` : "", stateText(x)].filter(Boolean).join("，");
}

export type Exercise = { name: string; part?: string };

/** 这次练得最多的部位（按组数），配图用。 */
export function mainPart(lib: Exercise[] | null, x: Workout): string {
  const n: Record<string, number> = {};
  for (const it of x.items ?? []) {
    const p = lib?.find((e) => e.name === it.exercise)?.part ?? "";
    if (p) n[p] = (n[p] ?? 0) + Math.max(1, setsOf(it));
  }
  return Object.entries(n).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
}

/** 时间线：练了的和记了没练的，从新到旧（接口已经按新到旧排）。 */
export function timelineRows(logs: Workout[]): Workout[] {
  return logs.filter((x) => x.done !== false || x.rest);
}

/** 战绩页时间线入口那一句。 */
export function lastLine(logs: Workout[]): string {
  const last = logs.find((x) => x.done !== false && !x.rest);
  return last ? `最近一次：${md(last.day)}，${last.session || "训练"}` : "还没有训练记录";
}
