// 首页·干饭用到的接口数据（照 iron-m 的 /iron/api/meals、/iron/api/diet/*、/iron/api/foods、/iron/api/metrics）。
// 只写页面用到的字段；服务端多给的字段不管。

export type Macros = { kcal: number; protein_g: number; carbs_g: number; fat_g: number };

/** 配图：url 是服务端的相对地址（/iron/api/food-images/...），用的时候前面拼 API_BASE。 */
export type FoodImage = { url: string; author?: string; license?: string; page?: string } | null;

export type Oil = "少油" | "正常" | "多油";

/** 一餐里的一样食物（§118）。 */
export type FoodLine = {
  name: string;
  grams: number;
  oil?: Oil;
  food_id?: string | null;
  dish?: boolean;
  macros: Macros;
};

/** 记下的一餐。 */
export type Meal = {
  id: string;
  day: string;
  kind: string;
  name: string;
  items: string[];
  macros: Macros;
  foods?: FoodLine[];
  confidence?: string;
  note?: string;
  has_photo?: boolean;
  image?: FoodImage;
};

/** 今天的饮食：GET /iron/api/meals 和记一餐、删一餐之后都回这个。 */
export type Day = {
  day: string;
  meals: Meal[];
  totals: Macros;
  target: Macros | null;
  goal?: string;
  replaced?: string[];
};

/** 指标（/iron/api/metrics 里的一项）。 */
export type Metric = {
  key: string;
  name: string;
  value: number | null;
  text?: string;
  how?: string;
  source?: string;
  display?: string;
};

/** 饮食计划里的一个位置。 */
export type PlanSlot = {
  type: string;
  id: string;
  servings?: number;
  missing: boolean;
  name: string;
  kcal: number;
  protein_g: number;
  foods: { name: string; grams: number; kcal: number }[];
  image: FoodImage;
};

export type PlanSet = "weekday" | "weekend";

export type DietPlan = {
  slots: string[];
  sets: Record<PlanSet, Record<string, PlanSlot | null>>;
  totals: Record<PlanSet, { kcal: number; protein_g: number }>;
  target: { kcal: number; protein_g: number } | null;
  today_set: PlanSet;
};

/** 两周饮食复盘（GET /iron/api/diet/review）。 */
export type DietReview = {
  observed: { tdee: number; intake: number; kg_per_week: number; days: number; weighins: number; formula: number | null; how: string } | null;
  observed_lack?: string;
  current: { kcal: number; since: string; reason: string } | null;
  proposal: { delta: number; total: number; before: number; after: number; reason: string } | null;
};

/** 常吃的（GET /iron/api/meals/usual）。 */
export type Usual = { id: string; name: string; times: number; kind: string; kcal: number; protein_g: number; image: FoodImage };

/** 食物库的一样（GET /iron/api/foods）。 */
export type Food = {
  id: string;
  name: string;
  cat: string;
  dish: boolean;
  unit: string;
  unit_g: number;
  oil_g: number;
  image: FoodImage;
  per100: Macros;
};

/** 改计划时下拉里能选的：常吃的、我的食谱、推荐食谱、减脂餐。 */
export type PlanRef = { type: "meal" | "mine" | "recipe" | "preset"; id: string };
export type PlanOption = { group: string; ref: PlanRef; name: string; kcal: number };
