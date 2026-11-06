// 登录页发验证码（§155、§174）：发信要十几秒，按下就变灰、说"正在发送"，连点也只发一封（新码会让旧码作废）。
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

const mockSend = jest.fn();
jest.mock("@/api/auth", () => ({
  mailReady: jest.fn(async () => true),
  sendCode: (...a: unknown[]) => mockSend(...a),
  signInWith: jest.fn(),
}));
jest.mock("@/auth/session", () => ({ useSession: () => ({ ready: true, token: "", signIn: jest.fn(), signOut: jest.fn() }) }));
jest.mock("expo-router", () => ({ router: { replace: jest.fn() }, Redirect: () => null }));

import Login from "@/app/login";

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };

it("sends one code however many times the button is pressed while sending", async () => {
  let done: () => void = () => {};
  mockSend.mockImplementation(() => new Promise<void>((r) => (done = r)));
  await render(
    <SafeAreaProvider initialMetrics={METRICS}>
      <Login />
    </SafeAreaProvider>,
  );
  await fireEvent.press(screen.getByText("注册"));
  await fireEvent.changeText(screen.getByPlaceholderText("邮箱"), "a@b.com");
  void fireEvent.press(screen.getByText("获取验证码"));  // 发信挂着不回：不等它
  expect(await screen.findByText("发送中…")).toBeTruthy();
  expect(screen.getByText("正在发送验证码，一般十几秒内到。")).toBeTruthy();
  void fireEvent.press(screen.getByText("发送中…"));
  void fireEvent.press(screen.getByText("发送中…"));
  await act(async () => {});
  expect(mockSend).toHaveBeenCalledTimes(1);
  await act(async () => done());
  expect(screen.getByText(/以最新一封为准/)).toBeTruthy();
  expect(screen.getByText(/秒后重发/)).toBeTruthy();
});
