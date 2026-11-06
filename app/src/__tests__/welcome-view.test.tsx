// 注册后完善资料（spec §174 需求 4）：必填三项不齐不存；存档案和体重，再提示填模型，以后再说就进首页。
import { fireEvent, render, screen } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Welcome from "@/app/welcome";

jest.mock("expo-router", () => ({ router: { replace: jest.fn(), push: jest.fn() }, Redirect: () => null }));
const mockRouter = jest.requireMock<{ router: { replace: jest.Mock } }>("expo-router").router;

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const profile = { profile: { height_cm: null, birth: null, sex: null, goal: null, activity: null }, options: { goal: { muscle: "增肌", fat_loss: "减脂" }, activity: { light: "轻度" } } };
let seen: { url: string; method: string; body: unknown }[] = [];

beforeEach(() => {
  seen = [];
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (b: unknown) => Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(b) } as Response);
    if (path === "/iron/api/profile") return reply(profile);
    if (path === "/iron/api/readings") return reply({ ok: true });
    return reply({});
  });
});

it("needs height, birth and weight, saves profile and weight, then offers the model or home", async () => {
  await render(<SafeAreaProvider initialMetrics={METRICS}><Welcome /></SafeAreaProvider>);
  expect(await screen.findByText("增肌")).toBeTruthy();
  await fireEvent.press(screen.getByText("保存"));
  expect(screen.getByText("身高填 100–250 厘米之间")).toBeTruthy();
  expect(seen.some((x) => x.method === "PUT")).toBe(false);
  await fireEvent.changeText(screen.getByLabelText("身高（厘米）"), "172");
  await fireEvent.changeText(screen.getByLabelText("出生日期"), "1995-06-18");
  await fireEvent.changeText(screen.getByLabelText("体重（公斤）"), "65");
  await fireEvent.press(screen.getByText("增肌"));
  await fireEvent.press(screen.getByText("保存"));
  expect(await screen.findByText("资料存好了。")).toBeTruthy();
  expect(seen.find((x) => x.method === "PUT")?.body).toEqual({ height_cm: 172, birth: "1995-06-18", goal: "muscle" });
  expect(seen.find((x) => x.url === "/iron/api/readings")?.body).toEqual({ kind: "weight", value: 65 });
  expect(screen.getByText("去填模型")).toBeTruthy();
  await fireEvent.press(screen.getByText("以后再说，先进首页"));
  expect(mockRouter.replace).toHaveBeenCalledWith("/");
});
