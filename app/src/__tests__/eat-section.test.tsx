// 首页·干饭整块（spec §164 第二期）：读今天的饮食、计划、复盘；照计划记、写一句记一餐、确认复盘建议都调对接口。
import { fireEvent, render, screen } from "@testing-library/react-native";

import { router } from "expo-router";

import { configureApi, setFetcher } from "@/api/client";
import { EatSection } from "@/features/eat/eat";

jest.mock("expo-router", () => ({ router: { push: jest.fn(), navigate: jest.fn() } }));

const M = (kcal: number, p = 0) => ({ kcal, protein_g: p, carbs_g: 0, fat_g: 0 });
const slot = (name: string, kcal: number) => ({ type: "recipe", id: name, missing: false, name, kcal, protein_g: 30, foods: [{ name: "鸡胸肉", grams: 150, kcal: 200 }], image: null });

const today = { day: "2026-11-05", meals: [] as unknown[], totals: M(0), target: M(2000, 120) };
const eaten = {
  ...today,
  meals: [{ id: "m1", day: "2026-11-05", kind: "午餐", name: "鸡胸饭", items: [], macros: M(650, 40), foods: [{ name: "鸡胸肉", grams: 150, macros: M(200, 30) }] }],
  totals: M(650, 40),
};
const plan = {
  slots: ["早餐", "午餐", "晚餐", "加餐"],
  sets: { weekday: { 早餐: null, 午餐: slot("鸡胸饭", 650), 晚餐: null, 加餐: null }, weekend: { 早餐: null, 午餐: null, 晚餐: null, 加餐: null } },
  totals: { weekday: { kcal: 650, protein_g: 40 }, weekend: { kcal: 0, protein_g: 0 } },
  target: { kcal: 2000, protein_g: 120 },
  today_set: "weekday",
};
const review = { observed: null, current: { kcal: -150, since: "2026-10-20", reason: "IronM 复盘：两周体重没降" } };

function reply(body: unknown, status = 200) {
  return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
}

const NO_MODEL_SAID = "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。";
let seen: { url: string; method: string; body: unknown }[] = [];
let day: typeof today = today;
let mealPostStatus = 200;

beforeEach(() => {
  seen = [];
  day = today;
  mealPostStatus = 200;
  (router.navigate as jest.Mock).mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body });
    if (path === "/iron/api/meals" && method === "GET") return reply(day);
    if (path === "/iron/api/meals" && method === "POST") {
      return mealPostStatus === 428 ? reply({ detail: NO_MODEL_SAID }, 428) : reply(eaten);
    }
    if (path === "/iron/api/metrics") return reply({ metrics: [] });
    if (path === "/iron/api/diet/plan") return reply(plan);
    if (path === "/iron/api/diet/review") return reply(review);
    if (path === "/iron/api/diet/plan/log") return reply(eaten);
    if (path === "/iron/api/diet/adjust/undo") return reply({ ...review, current: null });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("shows the budget, the plan rows and logs a planned meal", async () => {
  await render(<EatSection />);
  expect(await screen.findByText("今天还能吃")).toBeTruthy();
  expect(await screen.findByText("按工作日的计划，一共 650 千卡。")).toBeTruthy();
  expect(screen.getByText("热量目标调整过 −150 千卡")).toBeTruthy();
  expect(screen.queryByText("确认")).toBeNull();  // 规则的热量建议去掉了，没有"确认"（§163 需求 6）
  expect(screen.getAllByText("没排")).toHaveLength(3);
  await fireEvent.press(screen.getByText("照计划记"));
  expect(await screen.findByText("记下了午餐")).toBeTruthy();
  expect(seen.find((x) => x.url === "/iron/api/diet/plan/log")?.body).toBe('{"slot":"午餐"}');
  expect(screen.getByText("已吃")).toBeTruthy();
});

it("writes a meal in one sentence as a form", async () => {
  await render(<EatSection />);
  await fireEvent.press(await screen.findByText("写一句"));
  await fireEvent.press(await screen.findByText("记下，估算热量"));
  expect(await screen.findByText("写一句吃了什么")).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText("吃了什么"), "一碗牛肉面");
  await fireEvent.press(screen.getByRole("radio", { name: "晚餐" }));
  await fireEvent.press(screen.getByText("记下，估算热量"));
  const post = await waitPost();
  expect(post.body).toBeInstanceOf(FormData);
  const form = post.body as FormData;
  expect(form.get("said")).toBe("一碗牛肉面");
  expect(form.get("kind")).toBe("晚餐");
});

// §167：没填自己的模型时写一句估热量回 428：当场说清楚、给"去填模型"；点了先关弹出页再去「我」打开模型和 API
it("asks to fill a model when the meal estimate needs one", async () => {
  mealPostStatus = 428;
  await render(<EatSection />);
  await fireEvent.press(await screen.findByText("写一句"));
  await fireEvent.changeText(screen.getByLabelText("吃了什么"), "一碗牛肉面");
  await fireEvent.press(screen.getByText("记下，估算热量"));
  expect(await screen.findByText(NO_MODEL_SAID)).toBeTruthy();
  await fireEvent.press(screen.getByText("去填模型"));
  expect(router.navigate).toHaveBeenCalledWith({ pathname: "/me", params: { open: "model" } });
  expect(screen.queryByLabelText("吃了什么")).toBeNull();  // 弹出页关了，不盖在「我」上面
  // 不要模型的照常：照计划记
  await fireEvent.press(screen.getByText("照计划记"));
  expect(await screen.findByText("记下了午餐")).toBeTruthy();
});

it("undoes a kcal adjustment and reloads", async () => {
  await render(<EatSection />);
  await fireEvent.press(await screen.findByText("撤销"));
  expect(seen.some((x) => x.url === "/iron/api/diet/adjust/undo" && x.method === "POST")).toBe(true);
  expect(seen.some((x) => x.url === "/iron/api/diet/adjust")).toBe(false);
  expect(seen.filter((x) => x.url === "/iron/api/metrics").length).toBeGreaterThanOrEqual(2);
});

async function waitPost() {
  for (let i = 0; i < 20; i += 1) {
    const post = seen.find((x) => x.url === "/iron/api/meals" && x.method === "POST");
    if (post) return post;
    await new Promise((r) => setTimeout(r, 5));
  }
  throw new Error("没有发出记一餐的请求");
}
