// 首页·干饭的纯逻辑（spec §164 第二期，照网页版 §125）：今日余额、按顿的状态、复盘那一行、替换提示、逐样食物的预估。
import {
  budgetOf,
  kcalOf,
  linesTotal,
  mealKindNow,
  observedFacts,
  parseGrams,
  planMeta,
  planOptions,
  readLines,
  replaceHint,
  reviewLine,
  rowKcal,
  shownKinds,
  slotRows,
  stripRefs,
  targetFacts,
} from "@/features/eat/logic";
import type { Day, DietPlan, Food, Meal } from "@/features/eat/types";

const M = (kcal: number, p = 0, c = 0, f = 0) => ({ kcal, protein_g: p, carbs_g: c, fat_g: f });

function meal(kind: string, name: string, kcal: number, extra: Partial<Meal> = {}): Meal {
  return { id: `${kind}-${name}`, day: "2026-11-05", kind, name, items: [], macros: M(kcal, 20, 50, 10), ...extra };
}

function day(meals: Meal[], target: Day["target"] = M(2000, 120)): Day {
  const tot = meals.reduce((a, x) => M(a.kcal + x.macros.kcal, a.protein_g + x.macros.protein_g, a.carbs_g + x.macros.carbs_g, a.fat_g + x.macros.fat_g), M(0));
  return { day: "2026-11-05", meals, totals: tot, target };
}

const slot = (name: string, kcal: number, missing = false) => ({
  type: "recipe", id: name, missing, name, kcal, protein_g: 30, foods: [{ name: "米饭", grams: 150, kcal: 174 }], image: null,
});

function plan(set: "weekday" | "weekend" = "weekday"): DietPlan {
  const one = { 早餐: slot("燕麦碗", 420), 午餐: slot("鸡胸饭", 650), 晚餐: slot("旧食谱", 0, true), 加餐: null };
  return {
    slots: ["早餐", "午餐", "晚餐", "加餐"],
    sets: { weekday: one, weekend: one },
    totals: { weekday: { kcal: 1070, protein_g: 60 }, weekend: { kcal: 900, protein_g: 50 } },
    target: { kcal: 2000, protein_g: 120 },
    today_set: set,
  };
}

const food: Food = { id: "f1", name: "番茄炒蛋", cat: "家常菜", dish: true, unit: "份", unit_g: 200, oil_g: 10, image: null, per100: M(100) };

describe("mealKindNow", () => {
  it("picks the meal by hour like the web", () => {
    const at = (h: number) => mealKindNow(new Date(2026, 10, 5, h, 0));
    expect([at(3), at(8), at(10), at(12), at(15), at(19), at(22)]).toEqual(["夜宵", "早餐", "加餐", "午餐", "加餐", "晚餐", "夜宵"]);
  });
});

describe("budgetOf", () => {
  it("says how much is left, the energy bar and protein target from the metric range", () => {
    const b = budgetOf(day([meal("早餐", "粥", 500)]), { protein_target: { key: "protein_target", name: "蛋白质目标", value: 130, display: "111–138" } });
    expect(b).toMatchObject({ kind: "ok", left: 1500, over: false, pct: 25, energy: 75, target: 2000, proteinTarget: 111 });
  });

  it("flips to 多吃了 and caps the bar when over target", () => {
    const b = budgetOf(day([meal("午餐", "火锅", 2600)]), {});
    expect(b).toMatchObject({ kind: "ok", left: 600, over: true, pct: 100, energy: 0, proteinTarget: 120 });
  });

  it("has no budget without a target", () => {
    expect(budgetOf(day([], null), {}).kind).toBe("none");
  });
});

describe("today plan rows", () => {
  it("lists the four main meals and extra kinds only when logged", () => {
    expect(shownKinds([])).toEqual(["早餐", "午餐", "晚餐", "加餐"]);
    expect(shownKinds([meal("练后", "蛋白粉", 120)])).toEqual(["早餐", "午餐", "晚餐", "加餐", "练后"]);
  });

  it("marks eaten, planned, and unplanned (a missing recipe counts as unplanned)", () => {
    const rows = slotRows(day([meal("早餐", "包子", 300), meal("早餐", "豆浆", 100)]), plan());
    expect(rows.map((r) => r.state)).toEqual(["done", "planned", "unplanned", "unplanned"]);
    expect(rows[0]).toMatchObject({ kcal: 400 });
    expect(rows[1]).toMatchObject({ kcal: 650 });
  });

  it("works before the plan has loaded", () => {
    expect(slotRows(day([]), null).every((r) => r.state === "unplanned")).toBe(true);
  });

  it("says which set and total", () => {
    expect(planMeta(plan())).toBe("按工作日的计划，一共 1070 千卡。");
    expect(planMeta(plan("weekend"))).toBe("按周末的计划，一共 900 千卡。");
    expect(planMeta(null)).toBe("");
  });
});

describe("reviewLine", () => {
  it("shows a proposal with confirm", () => {
    const r = reviewLine({ observed: null, current: null, proposal: { delta: -150, total: -150, before: 2200, after: 2050, reason: "两周体重没降〔K12〕" } });
    expect(r).toEqual({ title: "建议每天少吃 150 千卡", sub: "两周体重没降，目标从 2200 调到 2050", action: "confirm" });
  });

  it("shows a past adjustment with undo when there is no new proposal", () => {
    const r = reviewLine({ observed: null, proposal: null, current: { kcal: -150, since: "2026-10-20", reason: "两周体重没降" } });
    expect(r).toEqual({ title: "热量目标调整过 −150 千卡", sub: "两周体重没降（10月20日起）", action: "undo" });
  });

  it("shows nothing otherwise", () => {
    expect(reviewLine({ observed: null, current: null, proposal: null })).toBeNull();
    expect(reviewLine(null)).toBeNull();
  });
});

describe("target explanations", () => {
  it("lists metrics that have values and hides reference codes", () => {
    const items = targetFacts({
      kcal_target: { key: "kcal_target", name: "热量目标", value: 2000, text: "每天约 2000 千卡", how: "总消耗 − 300", source: "减脂常用缺口〔K03〕" },
      bmr: { key: "bmr", name: "基础代谢", value: null, text: "缺身高" },
    });
    expect(items).toEqual([{ name: "热量目标", facts: [["结论", "每天约 2000 千卡"], ["怎么算的", "总消耗 − 300"], ["依据", "减脂常用缺口"]] }]);
  });

  it("explains observed burn or what is missing", () => {
    expect(observedFacts({ observed: null, observed_lack: "体重只称了 1 次", current: null, proposal: null })).toEqual({ lack: "还算不出来：体重只称了 1 次。" });
    const o = observedFacts({ observed: { tdee: 2300, intake: 2100, kg_per_week: -0.2, days: 14, weighins: 6, formula: 2400, how: "粗算" }, current: null, proposal: null });
    expect("facts" in o && o.facts[0][1]).toBe("每天约 2300 千卡（公式算的是 2400 千卡）");
  });

  it("strips internal codes", () => {
    expect(stripRefs("多喝水〔经验〕")).toBe("多喝水");
  });
});

describe("replaceHint", () => {
  it("warns that logging the same meal replaces it", () => {
    const ms = [meal("午餐", "牛肉面", 600)];
    expect(replaceHint(ms, "午餐")).toBe("今天已记过午餐：牛肉面，记下后会替换。");
    expect(replaceHint(ms, "午餐", true)).toBe("今天已记过午餐：牛肉面，记下后会替换；要合在一起就把两样都写上。");
    expect(replaceHint(ms, "晚餐")).toBe("");
  });
});

describe("food lines", () => {
  it("estimates kcal like the server, with oil for dishes", () => {
    expect(kcalOf(food, 200)).toBe(200);
    expect(kcalOf(food, 200, "多油")).toBe(244); // 200 + 0.5 × 10 克油 × 8.84
    expect(kcalOf(food, 200, "少油")).toBe(156);
    expect(kcalOf(undefined, 100)).toBeNull();
  });

  it("scales the old estimate when the food is not in the library", () => {
    expect(rowKcal({ key: "a", name: "自制酱", grams: 50, oil: "正常", kcal0: 200, grams0: 100 })).toBe(100);
  });

  it("totals and reads only rows with grams", () => {
    const rows = [
      { key: "a", name: "番茄炒蛋", grams: 200, oil: "正常" as const, food_id: "f1", dish: true, f: food },
      { key: "b", name: "米饭", grams: 0, oil: "正常" as const, food_id: "f2" },
      { key: "c", name: "自制酱", grams: 30, oil: "正常" as const, kcal0: 90, grams0: 30 },
    ];
    expect(linesTotal(rows)).toBe("大约 290 千卡（保存后按食物库算准）");
    expect(linesTotal([])).toBe("还没有食物");
    expect(readLines(rows)).toEqual([
      { name: "番茄炒蛋", grams: 200, oil: "正常", food_id: "f1" },
      { name: "自制酱", grams: 30, oil: "正常" },
    ]);
  });

  it("parses grams input", () => {
    expect(parseGrams("150")).toBe(150);
    expect(parseGrams("12.5克")).toBe(12.5);
    expect(parseGrams("")).toBe(0);
    expect(parseGrams("99999")).toBe(3000);
  });
});

describe("planOptions", () => {
  it("groups usual meals, my recipes, recommended recipes and presets", () => {
    const os = planOptions(
      [{ id: "u1", name: "牛肉面", times: 3, kind: "午餐", kcal: 600, protein_g: 30, image: null }],
      { mine: [{ id: "m1", name: "我的早餐", per_serving: { kcal: 400 } }], recommended: [{ id: "r1", name: "鸡胸饭", per_serving: { kcal: 650 } }] },
      [{ id: "p1", name: "便利店套餐", kcal: 500 }],
    );
    expect(os.map((o) => [o.group, o.ref.type, o.name])).toEqual([
      ["常吃的", "meal", "牛肉面"],
      ["我的食谱", "mine", "我的早餐"],
      ["推荐食谱", "recipe", "鸡胸饭"],
      ["减脂餐", "preset", "便利店套餐"],
    ]);
  });
});
