// 根布局的登录闸（spec §164）：凭证读出来之前不画页面；直接打开 /chat 这类标签外的页面，
// 第一次渲染就带着凭证；没登录打开它们落到登录页。
import { Text } from "react-native";
import { renderRouter, screen, waitFor } from "expo-router/testing-library";

import { useSession } from "@/auth/session";
import RootLayout from "@/app/_layout";

let mockSaved = "";
jest.mock("expo-secure-store", () => ({
  // 故意慢一拍：模拟从系统存储里读凭证要时间
  getItemAsync: jest.fn(() => new Promise((r) => setTimeout(() => r(mockSaved || null), 20))),
  setItemAsync: jest.fn(async () => {}),
  deleteItemAsync: jest.fn(async () => {}),
}));

const firstToken: string[] = [];
function Chat() {
  const { token } = useSession();
  if (!firstToken.length) firstToken.push(token);
  return <Text>对话页</Text>;
}
const stub = (name: string) => () => <Text>{name}</Text>;

const routes = {
  _layout: RootLayout,
  "(tabs)/_layout": stub("标签"),
  "(tabs)/index": stub("首页"),
  "(tabs)/atlas": stub("图鉴"),
  "(tabs)/record": stub("战绩"),
  "(tabs)/me": stub("我"),
  login: stub("登录页"),
  chat: Chat,
  plan: stub("计划"),
  live: stub("训练"),
  timeline: stub("时间线"),
  body: stub("身体数据"),
  "rank/index": stub("排行榜"),
  "rank/[board]/index": stub("榜单"),
  "rank/[board]/[item]": stub("条目"),
};

beforeEach(() => {
  firstToken.length = 0;
});

it("opens /chat directly with the stored token already loaded", async () => {
  mockSaved = "tok";
  await renderRouter(routes, { initialUrl: "/chat" });
  await waitFor(() => expect(screen.getByText("对话页")).toBeTruthy());
  expect(firstToken).toEqual(["tok"]);
});

it("sends a signed-out visitor of /chat to the login page", async () => {
  mockSaved = "";
  const r = await renderRouter(routes, { initialUrl: "/chat" });
  await waitFor(() => expect(r.getPathname()).toBe("/login"));
  expect(screen.getByText("登录页")).toBeTruthy();
  expect(screen.queryByText("对话页")).toBeNull();
});
