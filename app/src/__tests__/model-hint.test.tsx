// 首页"先填模型"提示卡（spec §167 需求 2）：没填模型的人看到一次，"以后再说"记在这台设备上，填了模型不再出现；
// 读不到设置时不出现。"去填模型"到「我」打开模型和 API。
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { router } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import { HINT_KEY, HINT_TEXT, ModelHint, NeedModel } from "@/features/me/need-model";

jest.mock("expo-router", () => ({
  router: { navigate: jest.fn() },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
}));
jest.mock("expo-secure-store", () => {
  const mem = new Map<string, string>();
  return {
    __mem: mem,
    getItemAsync: jest.fn(async (k: string) => mem.get(k) ?? null),
    setItemAsync: jest.fn(async (k: string, v: string) => void mem.set(k, v)),
    deleteItemAsync: jest.fn(async (k: string) => void mem.delete(k)),
  };
});
const mem = jest.requireMock<{ __mem: Map<string, string> }>("expo-secure-store").__mem;

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = (el: React.ReactElement) => render(<SafeAreaProvider initialMetrics={METRICS}>{el}</SafeAreaProvider>);
const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);

let model: unknown = null;
let down = false;
let reads = 0;

beforeEach(() => {
  mem.clear();
  model = null;
  down = false;
  reads = 0;
  (router.navigate as jest.Mock).mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url) => {
    if (url.endsWith("/iron/api/my-model")) {
      reads += 1;
      return down ? Promise.reject(new Error("offline")) : reply({ model, presets: {} });
    }
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("shows once for a user without a model; 以后再说 is remembered on this device", async () => {
  const first = await page(<ModelHint />);
  expect(await screen.findByText(HINT_TEXT)).toBeTruthy();
  await fireEvent.press(screen.getByText("去填模型"));
  expect(router.navigate).toHaveBeenCalledWith({ pathname: "/me", params: { open: "model" } });
  await fireEvent.press(screen.getByText("以后再说"));
  expect(screen.queryByText(HINT_TEXT)).toBeNull();
  await waitFor(() => expect(mem.get(HINT_KEY)).toBe("1"));
  await first.unmount();

  // 再打开：记着关过，不再读也不再出现
  reads = 0;
  await page(<ModelHint />);
  await waitFor(() => expect(mem.get(HINT_KEY)).toBe("1"));
  expect(screen.queryByText(HINT_TEXT)).toBeNull();
  expect(reads).toBe(0);
});

it("never shows once a model is filled", async () => {
  model = { provider: "deepseek", chat_model: "deepseek-chat", key_tail: "abcd" };
  await page(<ModelHint />);
  await waitFor(() => expect(reads).toBe(1));
  expect(screen.queryByText(HINT_TEXT)).toBeNull();
});

it("stays hidden when the setting can't be read", async () => {
  down = true;
  await page(<ModelHint />);
  await waitFor(() => expect(reads).toBe(1));
  expect(screen.queryByText(HINT_TEXT)).toBeNull();
});

it("NeedModel: note plus 去填模型, closing the sheet first", async () => {
  const before = jest.fn();
  await page(<NeedModel text="先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。" before={before} />);
  expect(screen.getByText("先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。")).toBeTruthy();
  await fireEvent.press(screen.getByText("去填模型"));
  expect(before).toHaveBeenCalledTimes(1);
  expect(router.navigate).toHaveBeenCalledWith({ pathname: "/me", params: { open: "model" } });
  expect(before.mock.invocationCallOrder[0]).toBeLessThan((router.navigate as jest.Mock).mock.invocationCallOrder[0]);
});
