// 首页·干饭的纯逻辑（照网页版 app.js 的 food / todayBudget / todayPlan / foodLines）：不碰界面，方便测。
import type { Day, DietPlan, DietReview, Food, Macros, Meal, Metric, Oil, PlanOption, PlanSlot, Usual } from "./types";

export const MEAL_KINDS = ["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"] as const;
/** 今天的饮食计划固定排这四顿；夜宵、练前、练后记了才出现（§125）。 */
export const MAIN_KINDS = ["早餐", "午餐", "晚餐", "加餐"] as const;
export const OILS: readonly Oil[] = ["少油", "正常", "多油"];
const OIL_K: Record<Oil, number> = { 少油: 0.5, 正常: 1, 多油: 1.5 };

/** 现在这个钟点记的大概是哪一餐。 */
export function mealKindNow(now: Date = new Date()): string {
  const hr = now.getHours();
  return hr < 5 ? "夜宵" : hr < 10 ? "早餐" : hr < 11 ? "加餐" : hr < 14 ? "午餐" : hr < 17 ? "加餐" : hr < 21 ? "晚餐" : "夜宵";
}

export function macroLine(m: Macros): string {
  return `${Math.round(m.kcal)} 千卡 · 蛋白质 ${Math.round(m.protein_g)} 克 · 碳水 ${Math.round(m.carbs_g)} 克 · 脂肪 ${Math.round(m.fat_g)} 克`;
}

/** 10-23 → 10月23日 */
export function md(iso: string): string {
  const [, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return m && d ? `${m}月${d}日` : "";
}

/** 页面上不出现依据库编号（〔K03〕、〔经验〕这类），只在内部留底。 */
export function stripRefs(text: string | undefined | null): string {
  return String(text ?? "").replace(/\s*〔[^〕]*〕/g, "").trim();
}

/** 没有配图时色块上写的那个字：去掉开头括号里的说明，取第一个字。 */
export function foodInitial(name: string): string {
  return String(name || "餐").replace(/^[（(].*?[)）]/, "").slice(0, 1) || "餐";
}

export type Budget =
  | { kind: "none"; eaten: Macros }
  | { kind: "ok"; left: number; over: boolean; pct: number; energy: number; eaten: Macros; target: number; proteinTarget: number };

/** 今日余额：还能吃多少、吃了百分之几、体力条剩多少；蛋白质目标用数据页那一段的下限（和网页一样）。 */
export function budgetOf(d: Day, metrics: Record<string, Metric>): Budget {
  const t = d.target;
  const tot = d.totals;
  if (!t || !t.kcal) return { kind: "none", eaten: tot };
  const protein = metrics.protein_target;
  const fromDisplay = protein?.display ? Number(String(protein.display).split("–")[0]) : NaN;
  const proteinTarget = Number.isFinite(fromDisplay) && fromDisplay > 0 ? fromDisplay : t.protein_g;
  const left = Math.round(t.kcal - tot.kcal);
  const pct = Math.min(100, Math.round((tot.kcal / t.kcal) * 100));
  return { kind: "ok", left: Math.abs(left), over: left < 0, pct, energy: Math.max(0, 100 - pct), eaten: tot, target: t.kcal, proteinTarget };
}

/** "目标怎么算的"：热量目标、蛋白质目标、基础代谢、每日总消耗四项，有值的才列。 */
export function targetFacts(metrics: Record<string, Metric>): { name: string; facts: [string, string][] }[] {
  return ["kcal_target", "protein_target", "bmr", "tdee"]
    .map((k) => metrics[k])
    .filter((x): x is Metric => !!x && x.value != null)
    .map((x) => ({
      name: x.name,
      facts: ([["结论", x.text], ["怎么算的", x.how], ["依据", x.source]] as [string, string | undefined][])
        .map(([k, v]) => [k, stripRefs(v)] as [string, string])
        .filter(([, v]) => !!v),
    }));
}

/** 按记的吃和体重变化估的实际消耗；条件不够时说还差什么。 */
export function observedFacts(r: DietReview): { facts: [string, string][] } | { lack: string } {
  const o = r.observed;
  if (!o) return { lack: `还算不出来：${r.observed_lack || "饮食和体重记录不够"}。` };
  return {
    facts: [
      ["结论", `每天约 ${o.tdee} 千卡${o.formula ? `（公式算的是 ${o.formula} 千卡）` : ""}`],
      ["用了哪些数据", `最近 ${o.days} 天平均每天吃 ${o.intake} 千卡；体重每周 ${o.kg_per_week > 0 ? "+" : ""}${o.kg_per_week} 公斤（称了 ${o.weighins} 次）`],
      ["怎么算的", o.how],
    ],
  };
}

/** 这段时间的事实（§163 需求 6）：平均每天吃多少、体重趋势；都没有时为空。 */
export function periodFacts(r: DietReview): [string, string][] {
  const out: [string, string][] = [];
  if (r.intake) out.push(["平均每天吃", `${r.intake.kcal} 千卡（最近 ${r.intake.of} 天里记了 2 餐以上的 ${r.intake.days} 天）`]);
  if (r.weight_trend) out.push(["体重趋势", r.weight_trend]);
  return out;
}

/** 计划标题下那一行：今天用哪一套、一共多少千卡。 */
export function planMeta(plan: DietPlan | null): string {
  if (!plan) return "";
  return `按${plan.today_set === "weekend" ? "周末" : "工作日"}的计划，一共 ${plan.totals[plan.today_set].kcal} 千卡。`;
}

/** 今天要列哪几顿：早午晚加餐固定有，其余记了才有。 */
export function shownKinds(meals: Meal[]): string[] {
  return MEAL_KINDS.filter((k) => (MAIN_KINDS as readonly string[]).includes(k) || meals.some((x) => x.kind === k));
}

export type SlotRow =
  | { kind: string; state: "done"; kcal: number; meals: Meal[]; image: Meal["image"] }
  | { kind: string; state: "planned"; kcal: number; slot: PlanSlot }
  | { kind: string; state: "unplanned" };

/** 一顿的状态：吃过的列实际记的；没吃、计划里有的列计划；都没有的"没排"。 */
export function slotRow(kind: string, meals: Meal[], plan: DietPlan | null): SlotRow {
  const xs = meals.filter((x) => x.kind === kind);
  if (xs.length) {
    return { kind, state: "done", kcal: xs.reduce((a, x) => a + x.macros.kcal, 0), meals: xs, image: xs.find((x) => x.image)?.image ?? null };
  }
  const set = plan?.sets?.[plan.today_set] ?? {};
  const planned = set[kind];
  if (planned && !planned.missing) return { kind, state: "planned", kcal: planned.kcal, slot: planned };
  return { kind, state: "unplanned" };
}

export function slotRows(d: Day, plan: DietPlan | null): SlotRow[] {
  return shownKinds(d.meals).map((k) => slotRow(k, d.meals, plan));
}

/** 热量调整那一行：调整过（IronM 复盘里调的、对话里让它调的）时"调整过"+撤销；规则建议去掉了（§163 需求 6）。 */
export function reviewLine(r: DietReview | null): { title: string; sub: string } | null {
  const c = r?.current;
  if (!c) return null;
  return { title: `热量目标调整过 ${c.kcal > 0 ? "+" : "−"}${Math.abs(c.kcal)} 千卡`, sub: `${stripRefs(c.reason)}（${md(c.since)}起）` };
}

/** 选到今天已经记过的那一餐时的提示：记下后会替换（每种餐每天只留一份）。 */
export function replaceHint(meals: Meal[], kind: string, writing = false): string {
  const had = meals.filter((x) => x.kind === kind).map((x) => x.name);
  if (!had.length) return "";
  return `今天已记过${kind}：${had.join("、")}，记下后会替换${writing ? "；要合在一起就把两样都写上" : ""}。`;
}

// ---- 逐样食物（§118）：改克数、油量、删一样、从库里加一样 -------------------------------------

/** 编辑中的一样食物：f 是食物库里的数（有了才能按库预估），kcal0 / grams0 是原来记的（库里没有的按比例算）。 */
export type LineRow = {
  key: string;
  name: string;
  grams: number;
  oil: Oil;
  food_id?: string | null;
  dish?: boolean;
  f?: Food;
  kcal0?: number;
  grams0?: number;
};

/** 和服务端同一个算法：菜品的油按少油 ×0.5、多油 ×1.5。 */
export function kcalOf(f: Food | undefined, grams: number, oil: Oil = "正常"): number | null {
  if (!f?.per100) return null;
  const extra = f.dish && f.unit_g ? ((OIL_K[oil] ?? 1) - 1) * f.oil_g * 8.84 * grams / f.unit_g : 0;
  return Math.round((f.per100.kcal * grams) / 100 + extra);
}

export function rowKcal(r: LineRow): number | null {
  if (r.f) return kcalOf(r.f, r.grams, r.oil);
  if (r.kcal0 != null && r.grams0) return Math.round((r.kcal0 * r.grams) / r.grams0);
  return null;
}

export function linesTotal(rows: LineRow[]): string {
  if (!rows.length) return "还没有食物";
  return `大约 ${rows.reduce((a, r) => a + (rowKcal(r) || 0), 0)} 千卡（保存后按食物库算准）`;
}

/** 交给接口的：克数大于 0 的，库里有的带上编号。 */
export function readLines(rows: LineRow[]): { name: string; grams: number; oil: Oil; food_id?: string }[] {
  return rows
    .filter((r) => r.grams > 0)
    .map((r) => ({ name: r.name, grams: r.grams, oil: r.oil || "正常", ...(r.food_id ? { food_id: r.food_id } : {}) }));
}

let seq = 0;
const nextKey = () => `l${++seq}`;

export function rowFromFood(f: Food): LineRow {
  return { key: nextKey(), name: f.name, food_id: f.id, grams: f.unit_g, oil: "正常", dish: f.dish, f };
}

export function rowsFromMeal(m: Meal): LineRow[] {
  return (m.foods ?? []).map((f) => ({
    key: nextKey(),
    name: f.name,
    food_id: f.food_id,
    grams: f.grams,
    oil: f.oil ?? "正常",
    dish: f.dish,
    kcal0: f.macros.kcal,
    grams0: f.grams,
  }));
}

/** 输入框里的克数：只认数字，最多 3000 克。 */
export function parseGrams(text: string): number {
  const n = Number(String(text).replace(/[^\d.]/g, ""));
  return Number.isFinite(n) ? Math.min(3000, Math.max(0, n)) : 0;
}

// ---- 改计划 ---------------------------------------------------------------------------------

export const PLAN_GROUPS = ["常吃的", "我的食谱", "推荐食谱", "减脂餐"] as const;

type RecipeLite = { id: string; name: string; per_serving: { kcal: number } };

/** 改计划时能选的：常吃的、我的食谱、推荐食谱、减脂餐。 */
export function planOptions(
  usual: Usual[],
  rec: { recommended: RecipeLite[]; mine: RecipeLite[] },
  presets: { id: string; name: string; kcal: number }[],
): PlanOption[] {
  return [
    ...usual.map((u) => ({ group: "常吃的", ref: { type: "meal" as const, id: u.id }, name: u.name, kcal: u.kcal })),
    ...rec.mine.map((r) => ({ group: "我的食谱", ref: { type: "mine" as const, id: r.id }, name: r.name, kcal: r.per_serving.kcal })),
    ...rec.recommended.map((r) => ({ group: "推荐食谱", ref: { type: "recipe" as const, id: r.id }, name: r.name, kcal: r.per_serving.kcal })),
    ...presets.map((x) => ({ group: "减脂餐", ref: { type: "preset" as const, id: x.id }, name: x.name, kcal: x.kcal })),
  ];
}

export function isPicked(slot: PlanSlot | null | undefined, o: PlanOption): boolean {
  return !!slot && slot.type === o.ref.type && slot.id === o.ref.id;
}
