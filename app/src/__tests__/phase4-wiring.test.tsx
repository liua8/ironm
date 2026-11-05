// 第四期接线（spec §164）：设置里拍照上传报告、"我"里有提醒入口、退出登录清掉这台手机上的提醒。
import { fireEvent, render, screen } from "@testing-library/react-native";
import { act } from "react";
import { Text } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { setFetcher } from "@/api/client";
import { SessionProvider, useSession } from "@/auth/session";
import { clearReminders } from "@/lib/notify";
import { getPhoto } from "@/lib/photo";
import { ImportBox } from "@/features/me/settings";

jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: () => false },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
}));
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async () => "tok"),
  setItemAsync: jest.fn(async () => {}),
  deleteItemAsync: jest.fn(async () => {}),
}));
jest.mock("@/lib/notify", () => ({ ...jest.requireActual("@/lib/notify"), clearReminders: jest.fn(async () => {}) }));
jest.mock("@/lib/photo", () => ({ ...jest.requireActual("@/lib/photo"), getPhoto: jest.fn() }));

const METRICS = { frame: { x: 0, y: 0, width: 390, height: 844 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const photo = { uri: "file:///r.jpg", type: "image/jpeg", width: 1200, height: 1600, blob: null };
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

beforeEach(() => jest.clearAllMocks());

it("uploads a photographed report to the file upload endpoint", async () => {
  (getPhoto as jest.Mock).mockResolvedValue(photo);
  const calls: { url: string; body: unknown }[] = [];
  setFetcher((url, init) => {
    calls.push({ url, body: init?.body });
    return url.includes("/files/upload") ? reply({ code: 0, data: [{ file_key: "k1" }] }) : reply({ journal: { days: [] } });
  });
  await render(<SafeAreaProvider initialMetrics={METRICS}><ImportBox /></SafeAreaProvider>);
  await fireEvent.press(screen.getByText("拍一页或从相册选"));
  expect(await screen.findByText(/传好了，正在识别/)).toBeTruthy();
  const up = calls.find((c) => c.url.endsWith("/files/upload?file=true"));
  expect(up?.body).toBeInstanceOf(FormData);
  expect((up?.body as FormData).get("files")).toBeTruthy();
  expect(screen.queryByText("第四期")).toBeNull();
});

it("says why when the photo could not be picked, and uploads nothing", async () => {
  (getPhoto as jest.Mock).mockRejectedValue(new Error("没有相机权限"));
  const calls: string[] = [];
  setFetcher((url) => {
    calls.push(url);
    return reply({ journal: { days: [] } });
  });
  await render(<SafeAreaProvider initialMetrics={METRICS}><ImportBox /></SafeAreaProvider>);
  await fireEvent.press(screen.getByText("拍一页或从相册选"));
  expect(await screen.findByText("没有相机权限")).toBeTruthy();
  expect(calls.some((u) => u.includes("/files/upload"))).toBe(false);
});

function SignOutProbe() {
  const { ready, signOut } = useSession();
  return ready ? <Text onPress={() => void signOut()}>退出</Text> : null;
}

it("clears this phone's reminders on sign out", async () => {
  await render(<SessionProvider><SignOutProbe /></SessionProvider>);
  const btn = await screen.findByText("退出");
  await act(async () => {
    fireEvent.press(btn);
  });
  expect(clearReminders).toHaveBeenCalledTimes(1);
});
