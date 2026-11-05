// 图鉴的纯逻辑（照网页版 app.js）：动作筛选和按部位收纳、配图地址、食谱筛选、方案库的标签、吃几份。
import { API_BASE } from "@/config";

import type { Exercise, Img, Machine, MachineGroup, PlanLib, Recipe, RecipeBook } from "./types";

/** 服务端给的图是相对地址（/iron/api/exercise-images/…），前面补上服务地址。 */
export function imgUrl(url: string | null | undefined): string {
  if (!url) return "";
  return /^https?:\/\//.test(url) ? url : `${API_BASE}${url}`;
}

/** 动作卡的封面：有动图先用动图，没有用第一张配图（§144）。 */
export function coverOf(x: Pick<Exercise, "gif" | "images">): string {
  return imgUrl((x.gif ?? x.images?.[0])?.url);
}

// 没图时封面上写一个字
export const PART_MARK: Record<string, string> = { 腿臀: "腿", 胸: "胸", 背: "背", 肩: "肩", 手臂: "臂", 核心: "核", 全身: "全", 有氧: "氧", 拉伸放松: "拉" };
export const partMark = (part: string) => PART_MARK[part] ?? part.slice(0, 1);

export const ALL_PARTS = "全部";
export const ALL_EQUIP = "全部器械";
export const GROUP_SHOW = 4; // 按部位收纳时每组先显示几个

export type MoveFilter = { part: string; equip: string; q: string };

export function filterMoves(list: Exercise[], f: MoveFilter): Exercise[] {
  const q = f.q.trim();
  return list.filter(
    (x) =>
      (f.part === ALL_PARTS || x.part === f.part) &&
      (f.equip === ALL_EQUIP || x.equipment.includes(f.equip)) &&
      (!q || `${x.name}${x.muscles}${x.part}`.includes(q)),
  );
}

/** 没选部位、没搜时按部位收纳（搜索或选了部位时平铺）。 */
export function isGrouped(f: MoveFilter): boolean {
  return f.part === ALL_PARTS && !f.q.trim();
}

// 常见动作排前面（§144），同样常见的有动图或配图的在前
const moveRank = (x: Exercise) => (x.common === false ? 0 : 2) + (x.gif || x.images?.length ? 1 : 0);

export function groupMoves(parts: string[], items: Exercise[]): { part: string; items: Exercise[] }[] {
  return parts
    .map((part) => ({
      part,
      items: items
        .map((x, i) => [x, i] as const)
        .filter(([x]) => x.part === part)
        .sort((a, b) => moveRank(b[0]) - moveRank(a[0]) || a[1] - b[1])
        .map(([x]) => x),
    }))
    .filter((g) => g.items.length > 0);
}

/** 动图的署名一行：动图：作者 · 由两张图合成 · 来自 wger · CC BY-SA。 */
export function creditLine(im: Img | null | undefined): string {
  if (!im) return "";
  const head = im.made ? "动图：" : "图：";
  return [`${head}${im.author || "佚名"}`, im.made, `来自 ${im.site || "wger"}`, im.license].filter(Boolean).join(" · ");
}

/** 食物、食谱配图的署名：图：作者 · 许可。 */
export function foodCredit(im: Img | null | undefined): string {
  if (!im?.url) return "";
  return `图：${im.author || "Wikimedia Commons"}${im.license ? ` · ${im.license}` : ""}`;
}

export const MACHINE_GROUPS: readonly (readonly [MachineGroup, string])[] = [
  ["gym", "健身房器械"],
  ["free", "自由重量和小器材"],
  ["cardio", "有氧器械"],
];

export function machineGroups(list: Machine[]): { key: MachineGroup; name: string; items: Machine[] }[] {
  return MACHINE_GROUPS.map(([key, name]) => ({ key, name, items: list.filter((m) => m.group === key) })).filter((g) => g.items.length > 0);
}

/** 食物、食谱没图时的那个字：去掉开头括号里的说明。 */
export function foodMark(name: string): string {
  return (String(name || "餐").replace(/^[（(].*?[)）]/, "") || "餐").slice(0, 1);
}

export const FOOD_STARTERS = ["鸡蛋", "米饭", "鸡胸", "牛奶", "燕麦", "香蕉", "豆腐", "牛肉", "西兰花", "面条"];

export const RECIPE_ALL = "推荐";
export const RECIPE_MINE = "我的";

/** 食谱一排筛选：推荐、各标签、我的。 */
export function recipeTags(r: RecipeBook): string[] {
  return [RECIPE_ALL, ...r.tags, RECIPE_MINE];
}

export function recipeTagLabel(tag: string, r: RecipeBook): string {
  return tag === RECIPE_MINE && r.mine.length ? `${RECIPE_MINE} ${r.mine.length}` : tag;
}

export function recipesFor(r: RecipeBook, tag: string): Recipe[] {
  if (tag === RECIPE_MINE) return r.mine;
  return r.recommended.filter((x) => tag === RECIPE_ALL || x.tags.includes(tag));
}

export const MEAL_KINDS = ["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"];
export const OILS = ["少油", "正常", "多油"];

/** 按现在几点猜这是哪一餐（同网页 mealKindNow）。 */
export function mealKindNow(d: Date = new Date()): string {
  const hr = d.getHours();
  return hr < 5 ? "夜宵" : hr < 10 ? "早餐" : hr < 11 ? "加餐" : hr < 14 ? "午餐" : hr < 17 ? "加餐" : hr < 21 ? "晚餐" : "夜宵";
}

/** 今天已经记过这一餐时提示会替换。 */
export function replaceHint(meals: { kind: string; name: string }[] | undefined, kind: string): string {
  const had = (meals ?? []).filter((x) => x.kind === kind).map((x) => x.name);
  return had.length ? `今天已记过${kind}：${had.join("、")}，记下后会替换。` : "";
}

/** 吃几份：每次半份，0.5 到 3 份。 */
export function stepServings(now: number, delta: number): number {
  return Math.min(3, Math.max(0.5, now + delta));
}

export function servingsText(x: Recipe, servings: number): string {
  return `吃 ${servings} 份：约 ${Math.round(x.per_serving.kcal * servings)} 千卡、蛋白质 ${Math.round(x.per_serving.protein_g * servings)} 克`;
}

/** 方案库卡片、详情的标签：目标、在哪练、每周几天、每次几分钟。 */
export function planTags(x: PlanLib): string[] {
  const [lo, hi] = x.minutes;
  return [...x.goals, x.place, `每周 ${x.days.join("或")} 天`, lo != null && hi != null ? `每次 ${lo}–${hi} 分钟` : ""].filter(Boolean);
}

export function planFor(x: PlanLib): string {
  return `适合：${x.people[0] === "成年人" ? x.levels.join("、") : x.people.join("、")}`;
}

export function planItemLine(it: { move: string; sets: number; reps: string; note: string }): string {
  return `${it.move} ${it.sets} 组 × ${it.reps}${it.note ? `（${it.note}）` : ""}`;
}

/** 出处编号只在内部留底，万一漏出来也不给用户看（〔K03〕、〔经验〕）。 */
export function plain(text: string | null | undefined): string {
  return String(text ?? "").replace(/〔[^〕]*〕/g, "").trim();
}
