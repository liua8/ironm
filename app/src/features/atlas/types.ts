// 图鉴用到的接口返回（照网页版和 ironm_agent/web*.py）：动作库、器械、食物库、食谱、方案库。

/** 配图署名：作者、许可、来源；动图多一个 made（"由两张图合成"）。 */
export type Img = {
  url: string;
  author?: string;
  author_url?: string;
  license?: string;
  license_url?: string;
  page?: string;
  site?: string;
  made?: string;
};

export type Exercise = {
  id: string;
  name: string;
  part: string;
  muscles: string;
  equipment: string[];
  level: string;
  steps: string[];
  cues: string[];
  mistakes: string[];
  easier: string;
  harder: string;
  avoid: string;
  timed?: boolean;
  common?: boolean;
  images: Img[];
  gif: Img | null;
};

export type ExerciseLib = { parts: string[]; equipment: string[]; note: string; exercises: Exercise[] };

export type MachineGroup = "gym" | "free" | "cardio";

export type Machine = {
  id: string;
  name: string;
  aka: string[];
  group: MachineGroup;
  trains: string;
  setup: string[];
  careful: string[];
  moves: { id: string; name: string }[];
  picture: Img | null;
};

/** 拍照认器械（§149，服务端 machines.Recognition）：模型看照片写的；match 是清单里同一种的编号。 */
export type MachineFound = {
  status: "ok" | "unsure" | "none" | "failed" | "no_model";
  name?: string;
  aka?: string[];
  trains?: string;
  setup?: string[];
  careful?: string[];
  moves?: { name: string; id: string | null }[];
  score?: number;
  match?: string | null;
  message?: string;
};

export type Macros = { kcal: number; protein_g: number; carbs_g: number; fat_g: number };

export type Food = {
  id: string;
  name: string;
  cat: string;
  dish: boolean;
  unit: string;
  unit_g: number;
  oil_g?: number;
  image: Img | null;
  per100: Macros;
};

export type Recipe = {
  id: string;
  name: string;
  tags: string[];
  servings: number;
  parts: { food_id: string; name: string; grams: number }[];
  oil: number;
  steps: string[];
  mine: boolean;
  per_serving: Macros;
  image: Img | null;
};

export type RecipeBook = { tags: string[]; recommended: Recipe[]; mine: Recipe[]; note: string };

export type PlanLib = {
  id: string;
  name: string;
  blurb: string;
  levels: string[];
  goals: string[];
  people: string[];
  place: string;
  minutes: number[];
  days: number[];
  why: string;
  intensity: string;
  progress: string;
  sessions: { name: string; items: { move: string; sets: number; reps: string; note: string }[] }[];
  blogger: string;
};

/** 今天的饮食（只用到这一天记过哪几餐，提示"记下后会替换"）。 */
export type MealDay = { meals: { kind: string; name: string }[] };
