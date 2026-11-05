// 分享卡上写什么（同网页 workoutCard、weekImage，spec §147、§164 第四期）：只放训练的数，不放体重、体脂这类身体数据
// （周报那张网页也带体重变化和饮食达标，照网页一样带上）。〔K..〕这类编号一律去掉。
import { md, type WeekReport } from "@/features/record/logic";
import { stripRefs } from "@/features/me/logic";

/** GET /iron/api/share/workout/{id} 返回的（ironm_agent/share.py workout_card）。 */
export type WorkoutShare = {
  id: string;
  photo: boolean;
  day: string;
  session: string;
  minutes?: number | null;
  sets: number;
  volume_kg: number;
  moves: string[];
  records: { exercise: string; weight_kg: number; reps: number }[];
  streak_days: number;
  rpe?: number | null;
};

/** 卡下面一行：记号、字；red 的记号画成红色（破纪录）。 */
export type CardLine = { mark: string; text: string; red?: boolean };

export type CardData = {
  title: string;
  date: string;
  head: string;
  sub: string;
  stats: { name: string; value: string; unit: string }[];
  lines: CardLine[];
  foot: string;
};

/** 时长、组数、总重量三个大数：没有的写"—"，不写单位；一吨以上换成吨。 */
function stats(minutes: number | null | undefined, sets: number | null | undefined, kg: number | null | undefined): CardData["stats"] {
  const v = kg || 0;
  return [
    { name: "时长", value: minutes ? String(minutes) : "—", unit: minutes ? "分钟" : "" },
    { name: "组数", value: sets ? String(sets) : "—", unit: sets ? "组" : "" },
    { name: "总重量", value: v >= 1000 ? (v / 1000).toFixed(1) : Math.round(v) ? String(Math.round(v)) : "—", unit: v ? (v >= 1000 ? "吨" : "公斤") : "" },
  ];
}

const record = (x: { exercise: string; weight_kg: number; reps: number }): CardLine => ({
  mark: "★",
  text: `破纪录：${stripRefs(x.exercise)} ${x.weight_kg} 公斤 × ${x.reps}`,
  red: true,
});

/** 练完卡：委托完成、哪天、练的什么、三个大数、破纪录（最多 3 条）、连续打卡、做了哪些动作。 */
export function workoutCard(d: WorkoutShare): CardData {
  const lines: (CardLine | null)[] = [
    ...d.records.slice(0, 3).map(record),
    d.streak_days > 1 ? { mark: "▲", text: `连续打卡 ${d.streak_days} 天` } : null,
    d.moves.length ? { mark: "■", text: d.moves.map(stripRefs).join("、") } : null,
  ];
  return {
    title: "委托完成",
    date: md(d.day),
    head: stripRefs(d.session) || "训练",
    sub: d.rpe ? `感受 ${d.rpe} 分` : "",
    stats: stats(d.minutes, d.sets, d.volume_kg),
    lines: lines.filter((x): x is CardLine => x !== null),
    foot: "练完打卡，一起变强",
  };
}

/** 上周周报那张：练了几次、平均感受、三个大数、破纪录（最多 2 条）、体重、饮食、下周重点。 */
export function weekCard(r: WeekReport): CardData {
  const lines: (CardLine | null)[] = [
    ...r.records.slice(0, 2).map(record),
    r.weight ? { mark: "▲", text: `体重 ${r.weight.from} → ${r.weight.to} 公斤（${r.weight.change > 0 ? "+" : ""}${r.weight.change}）` } : null,
    r.diet ? { mark: "■", text: `饮食 ${r.diet.on_target} / ${r.diet.logged} 天在目标热量上下` } : null,
    { mark: "→", text: `下周重点：${stripRefs(r.focus)}` },
  ];
  return {
    title: "上周周报",
    date: `${md(r.from)}–${md(r.to)}`,
    head: `练了 ${r.done} 次${r.planned ? `，计划 ${r.planned} 次` : ""}`,
    sub: r.rpe != null ? `平均感受 ${r.rpe} 分` : "",
    stats: stats(r.minutes, r.sets, r.volume_kg),
    lines: lines.filter((x): x is CardLine => x !== null),
    foot: "每周一出上周的周报",
  };
}
