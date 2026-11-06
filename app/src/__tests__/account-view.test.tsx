// 账号与隐私（spec §180）：导出交给系统分享、注销要输邮箱、两页文字。
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { Share } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Legal from "@/app/legal";
import { DeleteBox, ExportBox } from "@/features/me/account";

let mockKind = "privacy";
jest.mock("expo-router", () => ({ router: { replace: jest.fn(), push: jest.fn(), back: jest.fn(), canGoBack: () => false }, useLocalSearchParams: () => ({ kind: mockKind }) }));
const mockSignOut = jest.fn(() => Promise.resolve());
jest.mock("@/auth/session", () => ({ useSession: () => ({ ready: true, token: "tok", signIn: jest.fn(), signOut: mockSignOut }) }));
const mockRouter = jest.requireMock<{ router: { replace: jest.Mock } }>("expo-router").router;
const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };

let seen: { url: string; method: string; body: unknown }[] = [];
let deleteStatus = 200;
beforeEach(() => {
  seen = [];
  deleteStatus = 200;
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    const reply = (b: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(b) } as Response);
    if (path === "/iron/api/export") return reply({ about: "x", data: { profile: [{ height_cm: 172 }] } });
    if (path === "/iron/api/account/delete") return deleteStatus === 200 ? reply({ ok: true }) : reply({ detail: "邮箱和这个账号的不一样，没有注销" }, deleteStatus);
    return reply({});
  });
});

it("export hands the JSON to the system share sheet", async () => {
  const share = jest.spyOn(Share, "share").mockResolvedValue({ action: "sharedAction", activityType: undefined });
  await render(<ExportBox />);
  await fireEvent.press(screen.getByText("导出 IronM 的数据"));
  await act(async () => {});
  expect(share).toHaveBeenCalledTimes(1);
  const arg = share.mock.calls[0][0] as { title: string; message: string };
  expect(arg.title).toMatch(/^ironm-\d{4}-\d{2}-\d{2}\.json$/);
  expect(JSON.parse(arg.message).data.profile[0].height_cm).toBe(172);
  expect(screen.getByText(/已导出：ironm-/)).toBeTruthy();
});

it("delete needs an email, says what goes wrong, and signs out when it worked", async () => {
  await render(<DeleteBox />);
  expect(screen.getByText(/马上删除，不能恢复/)).toBeTruthy();
  await fireEvent.press(screen.getByText("确认注销账号"));
  expect(seen.length).toBe(0);  // 没填邮箱点不了
  await fireEvent.changeText(screen.getByLabelText("输入你的邮箱确认"), "other@x.com");
  deleteStatus = 422;
  await fireEvent.press(screen.getByText("确认注销账号"));
  expect(await screen.findByText("邮箱和这个账号的不一样，没有注销")).toBeTruthy();
  expect(mockSignOut).not.toHaveBeenCalled();
  deleteStatus = 200;
  await fireEvent.changeText(screen.getByLabelText("输入你的邮箱确认"), " me@x.com ");
  await fireEvent.press(screen.getByText("确认注销账号"));
  await act(async () => {});
  expect(seen[seen.length - 1]).toEqual({ url: "/iron/api/account/delete", method: "POST", body: { confirm: "me@x.com" } });
  expect(mockSignOut).toHaveBeenCalledTimes(1);
  expect(mockRouter.replace).toHaveBeenCalledWith("/login");
});

it("privacy and terms pages show the draft note and their sections", async () => {
  mockKind = "privacy";
  await render(<SafeAreaProvider initialMetrics={METRICS}><Legal /></SafeAreaProvider>);
  expect(screen.getByText("隐私政策")).toBeTruthy();
  expect(screen.getByText(/草稿（.*），正式对外前请负责人审核。/)).toBeTruthy();
  expect(screen.getByText("发给谁")).toBeTruthy();
  mockKind = "terms";
  await render(<SafeAreaProvider initialMetrics={METRICS}><Legal /></SafeAreaProvider>);
  expect(screen.getByText("不是医疗建议")).toBeTruthy();
});
