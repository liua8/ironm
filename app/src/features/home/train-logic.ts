// 首页·练和训练计划的纯逻辑（照网页版 app.js 的 trainCard、weekDots、setsText、itemLine、parseReps）。
import { API_BASE } from "@/config";

import type { Brief, ImageRef, Library, PlanItem, Session, Training, Warmup, Week } from "./types";

/** 去掉内部依据编号（〔K03〕〔经验〕这类），用户不该看到。 */
export function clean(text: string | null | undefined): string {
  return String(text ?? "").replace(/〔[^〕]*〕/g, "").replace(/[ \t]{2,}/g, " ").trim();
}

/** 服务端给的图片地址是相对的（/iron/api/...），补上服务地址。 */
export function absUrl(url: string | undefined | null): string {
  if (!url) return "";
  return /^https?:\/\//.test(url) ? url : `${API_BASE}${url}`;
}

export const partOf = (lib: Library | null | undefined, name: string): string => lib?.exercises?.find((x) => x.name === name)?.part || "";

/** 动作配图：有动图先用动图（§144）。 */
export function exImg(lib: Library | null | undefined, name: string): string {
  const x = lib?.exercises?.find((e) => e.name === name);
  return absUrl((x?.gif || x?.images?.[0])?.url);
}

/** 组次写法：有氧写时长（§130），其余写 组×次。 */
export const setsText = (it: PlanItem, lib: Library | null | undefined): string =>
  partOf(lib, it.exercise) === "有氧" || /分钟/.test(it.reps) ? it.reps : `${it.sets}×${it.reps}`;

export const itemLine = (it: PlanItem, lib: Library | null | undefined): string =>
  `${it.exercise} ${setsText(it, lib)}${it.load || it.note ? `（${[it.load, it.note].filter(Boolean).join("，")}）` : ""}`;

/** 本周的点：计划几次、练了几次；没计划时不显示。 */
export function weekDots(brief: Brief | null | undefined): { planned: number; done: number; dots: boolean[]; label: string } | null {
  const planned = brief?.week?.planned || brief?.week?.due || 0;
  const done = brief?.week?.done || 0;
  if (!planned) return null;
  return {
    planned,
    done,
    dots: Array.from({ length: Math.max(planned, done) }, (_, i) => i < done),
    label: `这周练了 ${done} 次，计划 ${planned} 次`,
  };
}

export type MoveRow = { exercise: string; note: string; cut: boolean; sets: string; pic: string };

export type TodayCard =
  | { kind: "failed" }
  | { kind: "noPlan" }
  | { kind: "plain"; title: string; sub: string }
  | {
      kind: "session";
      weekday: string;
      title: string;
      sub: string;
      minutes: number;
      moves: number;
      burn: string;
      photo: ImageRef | null;
      rows: MoveRow[];
      warmup: Warmup | null;
      session: Session;
      parts: string[];  // 部位标签（§176 照参照图）
      version: Session | null;  // 管家调整过的今天版本（直接打卡时带上）
    };

/** 今日委托这张卡显示什么（同网页 trainCard）。 */
export function todayCard(
  brief: Brief | null,
  tr: Training | null,
  week: Week | null,
  lib: Library | null,
  photos: Record<string, ImageRef> = {},
): TodayCard {
  if (!tr || !week) return { kind: "failed" };
  const t = brief?.today?.training;
  const today = week.days?.find((d) => d.today);
  if (!tr.plan) return { kind: "noPlan" };
  if (!today?.session) return { kind: "plain", title: "今天休息", sub: "散散步、拉拉伸，让身体恢复。" };
  if (week.sick?.mode === "rest" && !(t?.done || today.done)) return { kind: "plain", title: "今天先休息", sub: clean(week.sick.why) };
  const v = today.version || today.session;
  if (t?.done || today.done) return { kind: "plain", title: `${v.name}，练完了`, sub: "好好恢复。" };
  const parts = [...new Set(v.items.map((it) => partOf(lib, it.exercise)).filter(Boolean))].slice(0, 3);
  const adjusted = Boolean(today.version || today.changes.length);
  const main = v.items.map((it) => partOf(lib, it.exercise)).find((x) => photos[x]) || "";
  const photo = main ? photos[main] : null;
  // 被减掉的组：和计划本身比，少了几组就标出来（§121 需求 4）
  const planned = Object.fromEntries(today.session.items.map((it) => [it.exercise, it.sets]));
  const rows = v.items.map((it) => {
    const cut = (planned[it.exercise] || 0) - (it.sets || 0);
    return {
      exercise: it.exercise,
      note: [it.load, cut > 0 ? `比计划少 ${cut} 组` : ""].filter(Boolean).join("，"),
      cut: cut > 0,
      sets: setsLine(it, lib),
      pic: exImg(lib, it.exercise),
    };
  });
  return {
    kind: "session",
    weekday: today.weekday,
    title: v.name,
    sub: `${today.weekday}，练${parts.length ? parts.join("和") : "全身"}${adjusted ? "。IronM 按你今天的状态调整过" : ""}。`,
    minutes: v.minutes,
    moves: v.items.length,
    burn: today.burn ? `${today.burn.low}–${today.burn.high}` : "",
    photo: photo?.url ? { ...photo, url: absUrl(photo.url) } : null,
    rows,
    warmup: today.warmup,
    session: today.session,
    parts,
    version: today.version || null,
  };
}

/** 一行组数（§176 照参照图）：力量写"4 组 × 10 次"，有氧写时长。 */
export function setsLine(it: PlanItem, lib: Library | null | undefined): string {
  if (partOf(lib, it.exercise) === "有氧" || /分钟/.test(it.reps)) return it.reps;
  return `${it.sets} 组 × ${it.reps}${/[\d–-]$/.test(it.reps) ? " 次" : ""}`;
}

/** 进行中的训练开始了几分钟。 */
export const liveMinutes = (started: string, now: number = Date.now()): number =>
  Math.max(0, Math.round((now - new Date(started).getTime()) / 60000));

// 次数：一个数或一个范围才能加减（"每侧 8 次""30 秒"这类让 IronM 改）
export function parseReps(s: string): number[] | null {
  const m = String(s).trim().match(/^(\d+)(?:\s*[–~-]\s*(\d+))?$/);
  return m ? [Number(m[1]), ...(m[2] ? [Number(m[2])] : [])] : null;
}
export const repsText = (r: number[]): string => (r.length === 2 ? `${r[0]}–${r[1]}` : String(r[0]));

export const WEEK = "一二三四五六日";
export const weekdayName = (d: number): string => `周${WEEK[d - 1]}`;

/** 改完计划的一句话（同网页 planEdited）：改了什么、说明、提醒。 */
export function editedLine(r: { lines: string[]; notes: string[]; warnings: string[] }): string {
  return [...r.lines, ...r.notes, ...r.warnings.map((w) => `提醒：${w.split("：")[0]}`)].map(clean).join("；");
}
