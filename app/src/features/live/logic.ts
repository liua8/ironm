// 训练记录器的纯逻辑（同网页 livePage 里的 checkKg、markDone、addSet、finish 这些）。
// 训练整份放在一个对象里、就地改（和网页一样），页面改完再整份存回服务端（PUT /iron/api/live）。

export type LiveSet = { weight_kg: number | null; reps: number | null; seconds: number | null; done: boolean; at: string | null };
export type LiveItem = {
  exercise: string;
  timed: boolean;
  rest: number;
  target: string;
  best: number | null;
  plan_kg: number | null;
  sets: LiveSet[];
  cardio: boolean;
};
export type Live = { id: string; started: string; updated: string; session: string; items: LiveItem[]; no_heavier: boolean };
export type LiveResp = {
  live: Live | null;
  now?: string;
  steps?: Record<string, number>;
  expired?: { line?: string } | null;
};
export type FinishResp = {
  summary: { minutes: number; exercises: number; sets: number; volume: number };
  workout: {
    id: string;
    line?: string;
    celebrate?: {
      prs?: { exercise: string; weight_kg: number; reps: number; e1rm: number; before: number }[];
      week?: { before?: number; done: number; planned: number; reached_now?: boolean };
    };
  } | null;
};

/** 页面内提示：超上限可以确定或改回，空的一组提醒先填。 */
export type Warn = { i: number; text: string; back?: number; w?: number };

/** 估算最大重量：和服务端同一个公式。 */
export const e1rm = (w: number | null | undefined, r: number | null | undefined): number | null =>
  w && r && r <= 30 ? (r === 1 ? w : w * (1 + r / 30)) : null;

const pad2 = (n: number) => String(n).padStart(2, "0");
/** 秒数写成 分:秒（超过一小时写 时:分:秒）。 */
export function clock(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const hh = Math.floor(s / 3600);
  const mm = Math.floor((s % 3600) / 60);
  return hh ? `${hh}:${pad2(mm)}:${pad2(s % 60)}` : `${mm}:${pad2(s % 60)}`;
}

const round2 = (x: number) => Math.round(x * 100) / 100;

/** 一档多重：服务端按动作给（哑铃 1、下肢 5、其余 2.5）。 */
export const stepOf = (steps: Record<string, number> | undefined, it: LiveItem): number => steps?.[it.exercise] || 2.5;

/** 现在该做的那一组：第一个没完成的。 */
export function curPos(items: LiveItem[]): { i: number; j: number } | null {
  for (let i = 0; i < items.length; i++) {
    const j = items[i].sets.findIndex((s) => !s.done);
    if (j >= 0) return { i, j };
  }
  return null;
}

/**
 * 改了重量以后查上下限，返回新的提示（null 是没有提示）：
 * 比计划重一档以内、10% 以内不提示；超出要确认；特殊人群和这次说过疼的不能比计划重（直接改回）；
 * 比以前最好成绩重 10% 以上提醒防手误。
 */
export function checkKg(
  L: Live,
  i: number,
  j: number,
  prev: number | null,
  steps: Record<string, number> | undefined,
  okKg: Record<number, number>,
  warn: Warn | null,
): Warn | null {
  const it = L.items[i];
  const s = it.sets[j];
  const w = s.weight_kg;
  const plan = it.plan_kg;
  if (w == null || prev == null || w <= prev) return warn && warn.i === i ? null : warn;
  if (L.no_heavier && plan != null && w > plan) {
    s.weight_kg = prev <= plan ? prev : plan;
    return { i, text: "今天不比计划加重（身体情况或刚说过疼），按原来的重量练。" };
  }
  if (okKg[i] != null && w <= okKg[i]) return warn;
  const top = plan != null ? plan : prev;
  const over = w - top;
  if (plan != null && (over > stepOf(steps, it) + 1e-9 || over > plan * 0.1 + 1e-9)) {
    return { i, text: `比计划重 ${Math.round((over / plan) * 100)}%，超过一档或一成，确定吗？`, back: plan, w };
  }
  if (it.best && (e1rm(w, s.reps) || 0) > it.best * 1.1) {
    return { i, text: "比你以前最好的成绩重不少，确定没有多按？", back: prev, w };
  }
  return warn;
}

/** 空的一组不能打勾（§104 需求 1）：返回要提醒的话，能打勾时返回空。 */
export function emptyMsg(it: LiveItem, s: LiveSet, timingThis: boolean): string {
  const empty = it.timed ? !((s.seconds ?? 0) > 0) && !timingThis : !((s.reps ?? 0) > 0);
  if (!empty) return "";
  return it.cardio ? "先填做了多少分钟，或点计时。" : it.timed ? "先填秒数，或点计时。" : "先填这一组做了几次（和重量），再打勾。";
}

/**
 * 完成一组：记下时间（正在计时的这一组记下用时）、组间休息什么时候结束；
 * 破纪录时给一句（同一次只提示新高的那一下，§92）；这组次数没做够，下一组降一档（还是原来的重量时才改）。
 */
export function completeSet(
  items: LiveItem[],
  i: number,
  j: number,
  nowMs: number,
  timingFrom: number | null,
  steps: Record<string, number> | undefined,
): { restEnd: number; pr: string; next: string } {
  const it = items[i];
  const s = it.sets[j];
  if (timingFrom != null) s.seconds = Math.max(1, Math.round((nowMs - timingFrom) / 1000));
  s.done = true;
  s.at = new Date(nowMs).toISOString();
  let pr = "";
  const e = e1rm(s.weight_kg, s.reps);
  const bar = Math.max(it.best || 0, ...it.sets.filter((x, k) => x.done && k !== j).map((x) => e1rm(x.weight_kg, x.reps) || 0));
  if (it.best && e && e > bar + 0.05) {
    pr = `${it.exercise} ${s.weight_kg}×${s.reps}，估算最大重量 ${Math.round(e)} 公斤（以前 ${Math.round(it.best)}）`;
  }
  let next = "";
  const n = it.sets[j + 1];
  if (!it.timed && n && !n.done && s.weight_kg && n.weight_kg === s.weight_kg && n.reps && (s.reps ?? 0) < n.reps) {
    n.weight_kg = Math.max(0, round2(s.weight_kg - stepOf(steps, it)));
    next = `这组少了 ${n.reps - (s.reps ?? 0)} 次，下一组先用 ${n.weight_kg} 公斤`;
  }
  return { restEnd: nowMs + it.rest * 1000, pr, next };
}

/** 取消完成。 */
export function undoSet(s: LiveSet): void {
  s.done = false;
  s.at = null;
}

/** − / + 一档：不低于 0。 */
export function bumpValue(s: LiveSet, key: "weight_kg" | "reps", d: number): number | null {
  const prev = s[key];
  s[key] = Math.max(0, round2((prev || 0) + d));
  return prev;
}

/** 加一组：照上一组预填，最多 20 组。 */
export function addSet(it: LiveItem): boolean {
  if (it.sets.length >= 20) return false;
  const last: Partial<LiveSet> = it.sets[it.sets.length - 1] || {};
  it.sets.push({
    weight_kg: last.weight_kg ?? null,
    reps: it.timed ? null : last.reps ?? null,
    seconds: it.timed ? last.seconds ?? null : null,
    done: false,
    at: null,
  });
  return true;
}

/** 动作上移、下移。 */
export function moveItem(items: LiveItem[], i: number, d: number): boolean {
  const k = i + d;
  if (k < 0 || k >= items.length) return false;
  [items[i], items[k]] = [items[k], items[i]];
  return true;
}

/** 组间休息加减：15 秒到 10 分钟。 */
export const clampRest = (rest: number, d: number): number => Math.min(600, Math.max(15, rest + d));

/** 进度：第几组 / 共几组。 */
export function progress(items: LiveItem[]): { all: number; done: number; text: string; pct: number } {
  const all = items.reduce((a, it) => a + it.sets.length, 0);
  const done = items.reduce((a, it) => a + it.sets.filter((s) => s.done).length, 0);
  return { all, done, text: `第 ${Math.min(done + 1, all)} / 共 ${all} 组`, pct: all ? Math.round((done / all) * 100) : 0 };
}

/** 次数旁的小标签（§176，同网页）：服务端给"目标 …""上次 …"原样放；"计划 N 组 × 次数"只取次数写成"目标 N 次"。 */
export function targetPill(target: string | null | undefined): string {
  const t = String(target || "");
  if (!/^计划/.test(t)) return t;
  const reps = t.match(/×\s*([^，,、）)]+)/)?.[1]?.trim();
  return reps ? `目标 ${reps}${/\d$/.test(reps) ? " 次" : ""}` : "";
}

/** 结束时的小结：完成了几组、几个动作、总训练量（计时的不算重量）。 */
export function summarize(items: LiveItem[]): { sets: number; exercises: number; volume: number } {
  const done = items.flatMap((it) => it.sets.filter((s) => s.done).map((s) => [it, s] as const));
  const volume = done.reduce((n, [it, s]) => n + (it.timed ? 0 : (s.weight_kg || 0) * (s.reps || 0)), 0);
  return { sets: done.length, exercises: new Set(done.map(([it]) => it.exercise)).size, volume: Math.round(volume) };
}

/** 有氧（§130）：页面填分钟，存秒。 */
export const minutesToSeconds = (m: number | null): number | null => (m ? Math.round(m * 60) : null);
export const secondsToMinutes = (s: number | null): string => (s ? String(Math.round(s / 60)) : "");

/** 输入框的字转成数：空的是 null，不是数也当空。 */
export function toNum(v: string): number | null {
  const t = v.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** 练完的卡怎么说（同网页 finish 里的标题和本周一句）。 */
export function doneWords(r: FinishResp): { title: string; week: string } {
  const c = r.workout?.celebrate || {};
  const wk = c.week;
  const prs = c.prs || [];
  const won = Boolean(wk?.reached_now);
  const title = won ? "本周目标达成" : prs.length ? "破纪录了" : "练完了";
  let week = "";
  if (wk?.planned) {
    week = won ? "这一练让本周目标刚好达成！" : wk.done >= wk.planned ? "本周目标已经达成，这一练是额外加分。" : `本周第 ${wk.done} 练，还差 ${wk.planned - wk.done} 练。`;
  }
  return { title, week };
}
