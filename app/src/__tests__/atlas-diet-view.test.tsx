// 图鉴·饮食方案库（spec §184）：方案段的 训练 / 饮食 小标签；饮食方案列表、详情（按热量目标缩放的一天）、
// "用这份当我的饮食计划"先确认再调接口，换好后能撤销一次。
import { fireEvent, render, screen } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Atlas from "@/app/(tabs)/atlas";
import { servingsLine, slotName } from "@/features/atlas/diet-plans";

jest.mock("expo-router", () => ({ router: { push: jest.fn(), navigate: jest.fn() }, useLocalSearchParams: () => ({ seg: "plans", chip: "diet" }) }));

const slot = (name: string, kcal: number, servings = 1) => ({
  type: "recipe", id: name, servings, name: servings === 1 ? name : `${name}（${servings} 份）`, kcal, protein_g: 30, carbs_g: 40, fat_g: 10,
  foods: [{ name: "鸡蛋", grams: 100, kcal: 143 }],
});
const day = (lunch: number) => ({
  slots: { 早餐: slot("燕麦碗", 400), 午餐: slot("鸡胸饭", lunch, lunch > 500 ? 1.5 : 1), 晚餐: slot("蒸鱼饭", 430), 加餐: slot("酸奶", 260) },
  total: { kcal: 1090 + lunch, protein_g: 120, carbs_g: 160, fat_g: 40 },
});
const BRIEF = {
  id: "cut-home", name: "减脂·高蛋白（家常）", goals: ["减脂"], suits: ["想减脂的成年人"], summary: "蛋白质吃到高的一端",
  per_day: { weekday: { kcal: 1550, protein_g: 132 }, weekend: { kcal: 1480, protein_g: 122 } },
};
const PLAN = {
  ...BRIEF, not_for: ["有肾病的：先问医生"], energy: "按你的每日热量目标吃，不再另减。", macros: { protein: "每天 1.4–2.0 克/公斤", carbs: "主食不断", fat: "少油" },
  points: ["每餐一份优质蛋白"], refs: ["运动人群的蛋白质需要量与分配（国际运动营养学会，2017）"],
  days: { weekday: day(480), weekend: day(450) },
  scaled: { target: { kcal: 2000, protein_g: 120 }, days: { weekday: day(720), weekend: day(460) } },
  note: "每顿 0.5–3 份、取半份的倍数。",
};

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = () => render(<SafeAreaProvider initialMetrics={METRICS}><Atlas /></SafeAreaProvider>);
const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);

let seen: { path: string; method: string }[] = [];
let undoStatus = 200;

beforeEach(() => {
  seen = [];
  undoStatus = 200;
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ path, method });
    if (path === "/iron/api/diet/library") return reply({ plans: [BRIEF], note: "按推荐份数算" });
    if (path === "/iron/api/diet/library/cut-home" && method === "GET") return reply(PLAN);
    if (path === "/iron/api/diet/library/cut-home/apply" && method === "POST") return reply({ sets: {}, applied: { id: "cut-home" } });
    if (path === "/iron/api/diet/library/undo" && method === "POST") {
      return undoStatus === 200 ? reply({ sets: {}, undone: true }) : reply({ detail: "没有可以撤销的饮食计划" }, undoStatus);
    }
    if (path === "/iron/api/plan-library") return reply({ plans: [] });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("小工具：一顿的名字去掉份数，份数写在热量后面", () => {
  expect(slotName("鸡胸饭（1.5 份）")).toBe("鸡胸饭");
  expect(servingsLine(719.6, 1.5)).toBe("720 千卡 · 1.5 份");
  expect(servingsLine(400, 1)).toBe("400 千卡");
});

it("饮食方案：列表、详情按热量目标缩放，确认后套用，再撤销", async () => {
  await page();
  expect(await screen.findByText("减脂·高蛋白（家常）")).toBeTruthy();
  expect(screen.getByText("每天约 1550 千卡 · 蛋白质 132 克")).toBeTruthy();
  expect(screen.getByText("适合：想减脂的成年人")).toBeTruthy();
  await fireEvent.press(screen.getByLabelText("减脂·高蛋白（家常），点开看一天吃什么"));
  expect(await screen.findByText("有肾病的：先问医生")).toBeTruthy();
  expect(screen.getByText("午餐 · 鸡胸饭")).toBeTruthy();
  expect(screen.getByText("720 千卡 · 1.5 份")).toBeTruthy(); // 用的是按目标缩放后的
  expect(screen.getByText("一天合计 1810 千卡 · 蛋白质 120 克 · 碳水 160 克 · 脂肪 40 克")).toBeTruthy();
  expect(screen.getByText(/按你每天 2000 千卡的目标/)).toBeTruthy();
  await fireEvent.press(screen.getByText("周末"));
  expect(screen.getByText("一天合计 1550 千卡 · 蛋白质 120 克 · 碳水 160 克 · 脂肪 40 克")).toBeTruthy();

  await fireEvent.press(screen.getByText("用这份当我的饮食计划"));
  expect(seen.some((x) => x.method === "POST")).toBe(false); // 先确认，不直接换
  await fireEvent.press(screen.getByText("先不换"));
  await fireEvent.press(screen.getByText("用这份当我的饮食计划"));
  await fireEvent.press(screen.getByText("确认换"));
  expect(await screen.findByText("饮食计划换成了「减脂·高蛋白（家常）」")).toBeTruthy();
  expect(seen.filter((x) => x.method === "POST").map((x) => x.path)).toEqual(["/iron/api/diet/library/cut-home/apply"]);

  await fireEvent.press(screen.getByText("撤销"));
  expect(await screen.findByText("撤销了，饮食计划回到换之前")).toBeTruthy();
  expect(seen.filter((x) => x.method === "POST").map((x) => x.path)).toEqual([
    "/iron/api/diet/library/cut-home/apply", "/iron/api/diet/library/undo",
  ]);
  expect(screen.queryByText("撤销")).toBeNull(); // 只能撤销一次
});

it("撤销失败时如实说，按钮还在", async () => {
  undoStatus = 404;
  await page();
  await fireEvent.press(await screen.findByLabelText("减脂·高蛋白（家常），点开看一天吃什么"));
  await fireEvent.press(await screen.findByText("用这份当我的饮食计划"));
  await fireEvent.press(screen.getByText("确认换"));
  await fireEvent.press(await screen.findByText("撤销"));
  expect(await screen.findByText("没有可以撤销的饮食计划")).toBeTruthy();
  expect(screen.getByText("撤销")).toBeTruthy();
});

it("训练小标签还是训练方案库", async () => {
  await page();
  await fireEvent.press(await screen.findByText("训练"));
  expect(await screen.findByText(/方案库由 IronM 整理/)).toBeTruthy();
  expect(seen.some((x) => x.path === "/iron/api/plan-library")).toBe(true);
});
