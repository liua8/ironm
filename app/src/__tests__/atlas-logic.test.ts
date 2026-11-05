// 图鉴的纯逻辑（spec §136、§144、§161）：动作筛选和按部位收纳、常见动作在前、配图地址和署名、器械三组、
// 食谱筛选、吃几份、方案库的标签、不给用户看出处编号。
import {
  ALL_EQUIP,
  ALL_PARTS,
  coverOf,
  creditLine,
  filterMoves,
  foodMark,
  groupMoves,
  imgUrl,
  isGrouped,
  machineGroups,
  mealKindNow,
  plain,
  planFor,
  planItemLine,
  planTags,
  recipesFor,
  recipeTagLabel,
  recipeTags,
  replaceHint,
  servingsText,
  stepServings,
} from "@/features/atlas/logic";
import type { Exercise, Machine, PlanLib, Recipe, RecipeBook } from "@/features/atlas/types";
import { API_BASE } from "@/config";

const ex = (over: Partial<Exercise>): Exercise => ({
  id: "x", name: "动作", part: "胸", muscles: "胸大肌", equipment: ["哑铃"], level: "入门",
  steps: [], cues: [], mistakes: [], easier: "", harder: "", avoid: "", images: [], gif: null, ...over,
});

const pic = { url: "/iron/api/exercise-images/a.jpg", author: "A", license: "CC BY-SA 4.0", site: "wger" };

describe("动作库", () => {
  const lib = [
    ex({ id: "a", name: "哑铃卧推", part: "胸", equipment: ["哑铃"] }),
    ex({ id: "b", name: "俯卧撑", part: "胸", equipment: ["徒手"], images: [pic] }),
    ex({ id: "c", name: "毛巾划船", part: "背", equipment: ["徒手"], common: false, images: [pic] }),
    ex({ id: "d", name: "杠铃划船", part: "背", muscles: "背阔肌", equipment: ["杠铃"] }),
  ];

  it("按部位、器械、搜索词筛", () => {
    expect(filterMoves(lib, { part: "背", equip: ALL_EQUIP, q: "" }).map((x) => x.id)).toEqual(["c", "d"]);
    expect(filterMoves(lib, { part: ALL_PARTS, equip: "徒手", q: "" }).map((x) => x.id)).toEqual(["b", "c"]);
    expect(filterMoves(lib, { part: ALL_PARTS, equip: ALL_EQUIP, q: " 背阔 " }).map((x) => x.id)).toEqual(["d"]);
    expect(filterMoves(lib, { part: ALL_PARTS, equip: ALL_EQUIP, q: "肩" })).toEqual([]);
  });

  it("没选部位、没搜时才按部位收纳", () => {
    expect(isGrouped({ part: ALL_PARTS, equip: "哑铃", q: "" })).toBe(true);
    expect(isGrouped({ part: "胸", equip: ALL_EQUIP, q: "" })).toBe(false);
    expect(isGrouped({ part: ALL_PARTS, equip: ALL_EQUIP, q: "蹲" })).toBe(false);
  });

  it("常见动作在前，同样常见的有图的在前；空的部位不出", () => {
    const g = groupMoves(["胸", "背", "肩"], lib);
    expect(g.map((x) => x.part)).toEqual(["胸", "背"]);
    expect(g[0].items.map((x) => x.id)).toEqual(["b", "a"]);
    expect(g[1].items.map((x) => x.id)).toEqual(["d", "c"]); // 冷门的有图也排在常见的后面
  });

  it("封面先用动图，地址补上服务地址", () => {
    const gif = { ...pic, url: "/iron/api/exercise-images/a-0.gif", made: "由两张图合成" };
    expect(coverOf(ex({ images: [pic], gif }))).toBe(`${API_BASE}/iron/api/exercise-images/a-0.gif`);
    expect(coverOf(ex({ images: [pic] }))).toBe(`${API_BASE}${pic.url}`);
    expect(coverOf(ex({}))).toBe("");
    expect(imgUrl("https://x.org/a.png")).toBe("https://x.org/a.png");
  });

  it("署名一行：动图注明合成", () => {
    expect(creditLine({ ...pic, made: "由两张图合成" })).toBe("动图：A · 由两张图合成 · 来自 wger · CC BY-SA 4.0");
    expect(creditLine(pic)).toBe("图：A · 来自 wger · CC BY-SA 4.0");
  });
});

describe("器械", () => {
  it("按健身房、自由重量、有氧三组，空组不出", () => {
    const m = (id: string, group: Machine["group"]): Machine => ({ id, name: id, aka: [], group, trains: "", setup: [], careful: [], moves: [], picture: null });
    const g = machineGroups([m("a", "cardio"), m("b", "gym"), m("c", "gym")]);
    expect(g.map((x) => [x.name, x.items.length])).toEqual([["健身房器械", 2], ["有氧器械", 1]]);
  });
});

describe("饮食", () => {
  const r = (id: string, tags: string[]): Recipe => ({
    id, name: id, tags, servings: 2, parts: [], oil: 0, steps: [], mine: false, image: null,
    per_serving: { kcal: 412.4, protein_g: 31.6, carbs_g: 40, fat_g: 12 },
  });
  const book: RecipeBook = { tags: ["减脂", "增肌", "早餐", "带饭"], recommended: [r("a", ["减脂"]), r("b", ["早餐", "增肌"])], mine: [r("m", [])], note: "" };

  it("食谱标签：推荐、各标签、我的（带个数）", () => {
    expect(recipeTags(book)).toEqual(["推荐", "减脂", "增肌", "早餐", "带饭", "我的"]);
    expect(recipeTagLabel("我的", book)).toBe("我的 1");
    expect(recipeTagLabel("我的", { ...book, mine: [] })).toBe("我的");
    expect(recipesFor(book, "推荐").map((x) => x.id)).toEqual(["a", "b"]);
    expect(recipesFor(book, "增肌").map((x) => x.id)).toEqual(["b"]);
    expect(recipesFor(book, "我的").map((x) => x.id)).toEqual(["m"]);
  });

  it("吃几份：每次半份，0.5 到 3 份", () => {
    expect(stepServings(1, -0.5)).toBe(0.5);
    expect(stepServings(0.5, -0.5)).toBe(0.5);
    expect(stepServings(3, 0.5)).toBe(3);
    expect(servingsText(r("a", []), 1.5)).toBe("吃 1.5 份：约 619 千卡、蛋白质 47 克");
  });

  it("这一餐今天记过时提示会替换", () => {
    expect(replaceHint([{ kind: "午餐", name: "牛肉饭" }], "午餐")).toBe("今天已记过午餐：牛肉饭，记下后会替换。");
    expect(replaceHint([{ kind: "午餐", name: "牛肉饭" }], "晚餐")).toBe("");
  });

  it("按钟点猜哪一餐", () => {
    const at = (h: number) => mealKindNow(new Date(2026, 10, 5, h));
    expect([at(7), at(12), at(15), at(19), at(23)]).toEqual(["早餐", "午餐", "加餐", "晚餐", "夜宵"]);
  });

  it("没图时写名字第一个字（去掉括号说明）", () => {
    expect(foodMark("（外卖）牛肉饭")).toBe("牛");
    expect(foodMark("")).toBe("餐");
  });
});

describe("方案库", () => {
  const x: PlanLib = {
    id: "p", name: "全身三分", blurb: "", levels: ["新手", "有基础"], goals: ["增肌"], people: ["成年人"], place: "健身房",
    minutes: [45, 60], days: [3, 4], why: "", intensity: "", progress: "", sessions: [], blogger: "",
  };

  it("标签和适合谁", () => {
    expect(planTags(x)).toEqual(["增肌", "健身房", "每周 3或4 天", "每次 45–60 分钟"]);
    expect(planFor(x)).toBe("适合：新手、有基础");
    expect(planFor({ ...x, people: ["孕期"] })).toBe("适合：孕期");
    expect(planItemLine({ move: "深蹲", sets: 3, reps: "8–10", note: "" })).toBe("深蹲 3 组 × 8–10");
    expect(planItemLine({ move: "深蹲", sets: 3, reps: "8", note: "慢放" })).toBe("深蹲 3 组 × 8（慢放）");
  });

  it("不给用户看出处编号", () => {
    expect(plain("每周加一点重量〔K03〕〔经验〕")).toBe("每周加一点重量");
  });
});
