// 今天的版本由管家定（§163，同网页 todayVersion）：正在看时隔几秒再问；点了重试、"有点累""只有 30 分钟"之后，
// 后台重看还没完时服务端一时还给旧结果（还是"出错了"、还是原来的版本），这段时间先当作"正在看"。
import type { TodayVersion as TV } from "./types";

export const TODAY_POLL_MS = 5000;
export const TODAY_POLL_MAX = 24; // 最多问 2 分钟，之后给"刷新"
export const TODAY_WAIT_MAX = 9; // 点了之后最多把 45 秒内的旧结果当作正在看

export type Wait = { error?: boolean; before?: string; left: number } | null;

/** 今天的版本长什么样：比较"变了没有"用。 */
export function todaySig(v: TV): string {
  return v.status === "ok" && "today" in v ? JSON.stringify([v.changed, v.today.items]) : v.status;
}

/** 收到一次结果后：显示什么、还等不等、要不要再问。 */
export function settle(v: TV, wait: Wait, last: TV | null): { shown: TV; wait: Wait; poll: boolean } {
  if (wait) {
    const stale = (wait.error && v.status === "coach_error") || (wait.before !== undefined && (v.status === "reviewing" || todaySig(v) === wait.before));
    if (stale && wait.left > 0) {
      const original = v.original ?? last?.original;
      return { shown: { status: "reviewing", ...(original ? { original } : {}) }, wait: { ...wait, left: wait.left - 1 }, poll: true };
    }
  }
  return { shown: v, wait: null, poll: v.status === "reviewing" };
}

/** 首页大卡片上那一行（同网页 heroCoach）：正在看、出错了、调整了今天、今天休息；没什么要说的返回 null。 */
export function heroLine(v: TV | null): { tone: "busy" | "error" | "adjusted" | "rest"; text: string } | null {
  if (!v) return null;
  if (v.status === "reviewing") return { tone: "busy", text: "IronM 正在看今天的情况，下面先列原计划" };
  if (v.status === "coach_error") return { tone: "error", text: "IronM 出错了，还没看今天的情况，下面是原计划" };
  if (v.status === "rest_today") return { tone: "rest", text: ("message" in v && v.message) || "今天休息" };
  if (v.status === "ok" && "changed" in v && v.changed) return { tone: "adjusted", text: `IronM 调整了今天：${v.changes.join("；")}` };
  return null;
}

/** 首页动作表跟着管家定的今天走（§163）：调整过就把这周里今天那天换成调整后的版本，没调整原样返回。 */
export function withCoach<W extends { days?: { today?: boolean; version?: unknown }[] }>(week: W | null, v: TV | null): W | null {
  if (!week || !v || v.status !== "ok" || !("changed" in v) || !v.changed) return week;
  return { ...week, days: week.days?.map((d) => (d.today ? { ...d, version: v.today } : d)) };
}
