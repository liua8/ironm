// App 跟上网页（§163、§173、§118）：推荐这一餐、没填模型时给去填；用当前位置只交两位小数、不同意时如实说。
import { act, fireEvent, render, screen } from "@testing-library/react-native";

import { configureApi, setFetcher } from "@/api/client";
import { RecommendMeal } from "@/features/eat/recommend";
import { spotOf } from "@/features/me/logic";
import { CityBox } from "@/features/me/settings";

jest.mock("expo-router", () => ({ router: { push: jest.fn(), replace: jest.fn(), navigate: jest.fn() } }));
const mockPerm = jest.fn();
jest.mock("expo-location", () => ({
  Accuracy: { Low: 2 },
  requestForegroundPermissionsAsync: () => mockPerm(),
  getCurrentPositionAsync: async () => ({ coords: { latitude: 30.27413, longitude: 120.15514 } }),
}));

let seen: { url: string; method: string; body: unknown }[] = [];
let recStatus = 200;
beforeEach(() => {
  seen = [];
  recStatus = 200;
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (b: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(b) } as Response);
    if (path === "/iron/api/meals/recommend") {
      if (recStatus === 428) return reply({ detail: "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。" }, 428);
      return reply({ recommendation: { title: "鸡胸肉饭", why: "今天还差 40 克蛋白质", dishes: [{ name: "鸡胸肉", amount: "150 克", kcal: 250, protein_g: 45 }] }, total: { kcal: 520, protein_g: 50, carbs_g: 60, fat_g: 8 }, remaining: { kcal: 900, protein_g: 40 }, considered: ["目标增肌"] });
    }
    if (path === "/iron/api/meals/record") return reply({ meals: [] });
    if (path === "/iron/api/place") return reply({ city: "", label: "" });
    if (path === "/iron/api/place/locate") return reply({ city: "杭州", label: "浙江省上城区" });
    return reply({});
  });
});

it("recommends a meal and records it", async () => {
  const done = jest.fn();
  await render(<RecommendMeal done={done} />);
  await fireEvent.press(screen.getByText("很饿"));
  await fireEvent.press(screen.getByText("推荐这一餐"));
  expect(await screen.findByText("鸡胸肉饭")).toBeTruthy();
  expect((seen.find((x) => x.url === "/iron/api/meals/recommend")?.body as { appetite: string }).appetite).toBe("很饿");
  expect(screen.getByText("合计 520 千卡 · 蛋白质 50 克 · 碳水 60 克 · 脂肪 8 克")).toBeTruthy();
  await fireEvent.press(screen.getByText("就吃这个，记下来"));
  await act(async () => {});
  expect(seen.find((x) => x.url === "/iron/api/meals/record")?.body).toMatchObject({ name: "鸡胸肉饭", items: ["鸡胸肉 150 克"], macros: { kcal: 520 } });
  expect(done).toHaveBeenCalled();
});

it("no model: says so with 去填模型", async () => {
  recStatus = 428;
  await render(<RecommendMeal done={jest.fn()} />);
  await fireEvent.press(screen.getByText("推荐这一餐"));
  expect(await screen.findByText("去填模型")).toBeTruthy();
});

it("用当前位置 sends two decimals; refusal is said plainly", async () => {
  expect(spotOf({ latitude: 30.27413, longitude: 120.15514 })).toEqual({ lat: 30.27, lon: 120.16 });
  mockPerm.mockResolvedValueOnce({ status: "denied" });
  await render(<CityBox />);
  await fireEvent.press(await screen.findByText("用当前位置"));
  expect(await screen.findByText("没有同意定位，可以手填城市")).toBeTruthy();
  mockPerm.mockResolvedValueOnce({ status: "granted" });
  await fireEvent.press(screen.getByText("用当前位置"));
  expect(await screen.findByText("浙江省上城区")).toBeTruthy();
  expect(seen.find((x) => x.url === "/iron/api/place/locate")?.body).toEqual({ lat: 30.27, lon: 120.16 });
});
