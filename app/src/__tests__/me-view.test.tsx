// "我"和身体数据整页（spec §140、§141、§146、§153）：角色卡、目标、设置各行；记忆删前要再点一次；
// 身体数据三块、收起的两块、记一条；模型密钥用密码框；退出登录回登录页。
import { fireEvent, render, screen } from "@testing-library/react-native";

import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Me from "@/app/(tabs)/me";
import Body from "@/app/body";

let mockParams: Record<string, string | undefined> = {};
jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), navigate: jest.fn(), setParams: jest.fn(), canGoBack: () => false },
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
  Redirect: () => null,
}));
const mockSignOut = jest.fn(() => Promise.resolve());
// 凭证第二段：{"email":"wang@example.com"}
jest.mock("@/auth/session", () => ({
  useSession: () => ({ ready: true, token: "h.eyJlbWFpbCI6IndhbmdAZXhhbXBsZS5jb20ifQ.s", signIn: jest.fn(), signOut: mockSignOut }),
}));
const mockRouter = jest.requireMock<{ router: { push: jest.Mock; replace: jest.Mock; setParams: jest.Mock } }>("expo-router").router;

const metrics = {
  as_of: "2026-11-04",
  stale_days: 1,
  metrics: [
    { key: "weight", name: "体重", value: 72.4, unit: "公斤", text: "最近 7 天平均〔K03〕", brief: "", tone: "neutral", series: [["2026-11-01", 72.8], ["2026-11-04", 72.4]] },
    { key: "weight_trend", name: "每周变化", value: -0.3, unit: "公斤/周", brief: "稳步下降", series: [] },
    { key: "bmi", name: "BMI", value: 23.1, unit: "", brief: "正常", tone: "good", series: [] },
    { key: "bmr", name: "基础代谢", value: 1650, unit: "千卡", brief: "", series: [] },
  ],
};

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = (el: React.ReactElement) => render(<SafeAreaProvider initialMetrics={METRICS}>{el}</SafeAreaProvider>);

/** 关掉弹出页：点右上角的"关闭"。 */
async function closeSheet() {
  const all = screen.getAllByLabelText("关闭");
  await fireEvent.press(all[all.length - 1]);
}

let seen: { path: string; method: string; body: unknown }[] = [];
beforeEach(() => {
  seen = [];
  mockParams = {};
  mockRouter.setParams.mockClear();
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    seen.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
    if (path === "/iron/api/profile") return reply({ profile: { height_cm: 175, birth: null, sex: "male", goal: "gain", activity: null }, sources: {}, options: { goal: { gain: "增肌" }, activity: { light: "轻度活动" } } });
    if (path === "/iron/api/goal") return reply({ goal: { value: 68, by: "2026-12-31" }, progress: { status: "on_track", start: 74, current: 72.4, target: 68, changed: -1.6, percent: 27, message: "照现在的速度能按时到" } });
    if (path === "/iron/api/memory" && method === "GET") return reply({ categories: { injury: "伤病与身体状况" }, items: [{ id: "m1", category: "injury", content: "左膝旧伤", status: "active" }] });
    if (path === "/iron/api/memory/m1" && method === "DELETE") return reply({ ok: true });
    if (path === "/iron/api/my-model") return reply({ model: null, presets: { deepseek: { name: "DeepSeek", chat: ["deepseek-chat"], vision: [] } } });
    if (path === "/iron/api/metrics") return reply(metrics);
    if (path === "/iron/api/muscles") return reply({ muscles: [{ name: "股四头肌", tier: "high", recovery: 40, last: "2026-11-04" }], sessions: 2, untrained: [], note: "恢复度是估算" });
    if (path === "/iron/api/brief") return reply({ week: { planned: 3, done: 1, tips: ["睡眠少，降一点强度"] } });
    if (path.startsWith("/iron/api/readings?kind=")) return reply({ kind: "body_fat", title: "体脂率", unit: "%", low: 3, high: 60, rows: [] });
    if (path === "/iron/api/readings" && method === "POST") return reply({ ok: true, rows: [] });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("me: role card, goal, settings rows; memory delete needs a second tap; sign out goes to login", async () => {
  await page(<Me />);
  expect(await screen.findByText("wang@example.com")).toBeTruthy();
  expect(await screen.findByText("175 厘米 · 男 · 增肌")).toBeTruthy();
  expect(await screen.findByText("目标体重 68 公斤")).toBeTruthy();
  expect(screen.getByText("已减 1.6 公斤 · 完成 27%")).toBeTruthy();

  await fireEvent.press(screen.getByText("身体数据"));
  expect(mockRouter.push).toHaveBeenCalledWith("/body");
  // 第四期：设置里有"提醒"一行（训练日提醒，默认关）
  expect(screen.getByText("提醒")).toBeTruthy();
  expect(screen.getByText("训练日提醒，默认关")).toBeTruthy();

  await fireEvent.press(screen.getByText("IronM 记得的事"));
  expect(await screen.findByText("左膝旧伤")).toBeTruthy();
  await fireEvent.press(screen.getByText("删掉"));
  expect(seen.some((x) => x.method === "DELETE")).toBe(false);
  await fireEvent.press(screen.getByText("确定删掉"));
  expect(await screen.findByText("删掉了。")).toBeTruthy();
  expect(seen.some((x) => x.path === "/iron/api/memory/m1" && x.method === "DELETE")).toBe(true);
  await closeSheet();

  await fireEvent.press(screen.getByText("模型和 API"));
  const key = await screen.findByLabelText("API 密钥");
  expect(key.props.secureTextEntry).toBe(true);
  expect(screen.getAllByText("deepseek-chat").length).toBeGreaterThan(0);
  await closeSheet();

  await fireEvent.press(screen.getByText("退出登录"));
  expect(mockSignOut).toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/login");
});

it("body: weight with weekly change, BMI, body fat to record; folds closed until tapped", async () => {
  await page(<Body />);
  expect(await screen.findByText("每周 −0.30 公斤 · 稳步下降")).toBeTruthy();
  expect(screen.getByText("72.4")).toBeTruthy();
  expect(screen.getByText("23.1")).toBeTruthy();
  expect(screen.getByText("还没记录")).toBeTruthy();
  expect(screen.queryByText("基础代谢")).toBeNull();

  await fireEvent.press(screen.getByText("全部指标"));
  expect(screen.getByText("基础代谢")).toBeTruthy();
  await fireEvent.press(screen.getByText("这周训练"));
  expect(screen.getByText("睡眠少，降一点强度")).toBeTruthy();
  expect(screen.getByText("想改计划，咨询 IronM。")).toBeTruthy();
  expect(screen.getByText("股四头肌")).toBeTruthy();

  await fireEvent.press(screen.getByLabelText("体重，点开看怎么算的"));
  expect(await screen.findByText("最近 7 天平均")).toBeTruthy();
  expect(screen.queryByText(/K03/)).toBeNull();
  await closeSheet();

  await fireEvent.press(screen.getByLabelText("体脂率，点开看怎么算的"));
  const input = await screen.findByLabelText("体脂率（%）");
  await fireEvent.changeText(input, "18.5");
  await fireEvent.press(screen.getByText("记下"));
  expect(seen.find((x) => x.path === "/iron/api/readings" && x.method === "POST")?.body).toMatchObject({ kind: "body_fat", value: 18.5 });
  expect(await screen.findByText("已记下，指标会按新数据重新算。")).toBeTruthy();
});

// §167：别处点"去填模型"带着 open=model 进来，直接打开"模型和 API"，参数用完清掉
it("me: open=model from navigation opens the model sheet", async () => {
  mockParams = { open: "model" };
  await page(<Me />);
  expect(await screen.findByText(/还没填自己的模型/)).toBeTruthy();
  expect(screen.getByLabelText("API 密钥")).toBeTruthy();
  expect(mockRouter.setParams).toHaveBeenCalledWith({ open: undefined });
});

it("me: no param, no sheet", async () => {
  await page(<Me />);
  expect(await screen.findByText("wang@example.com")).toBeTruthy();
  expect(screen.queryByLabelText("API 密钥")).toBeNull();
  expect(mockRouter.setParams).not.toHaveBeenCalled();
});
