// 对话页的消息（spec §164 第二期）：回答不带内部编号；预览卡片按服务端状态给按钮，确认后能撤销；管家消息能"暂不"。
import { fireEvent, render, screen } from "@testing-library/react-native";

const mockApi = jest.fn();
jest.mock("@/api/client", () => ({ api: (...a: unknown[]) => mockApi(...a) }));
jest.mock("expo/fetch", () => ({ fetch: jest.fn() }));
jest.mock("expo-localization", () => ({ getCalendars: () => [{ timeZone: "Asia/Shanghai" }] }));
jest.mock("expo-router", () => ({ router: { push: jest.fn(), navigate: jest.fn() }, useFocusEffect: jest.fn() }));

import { InboxMsg } from "@/features/chat/inbox";
import { Message } from "@/features/chat/message";
import { applyBlock, coachMsg } from "@/features/chat/model";

beforeEach(() => mockApi.mockReset());

it("shows the answer without reference codes, and a plan card that can be confirmed and undone", async () => {
  mockApi.mockImplementation(async (path: string) => {
    if (path.endsWith("/confirm")) return { draft: { state: "confirmed" } };
    return { draft: { state: "pending" } };
  });
  let m = coachMsg("k");
  for (const b of [
    { type: "start", id: "r1" },
    { type: "text", text: "加重 2–10%〔K03〕。\n- 深蹲 3×8" },
    { type: "tool_call", id: "card-d1", args: { kind: "plan", draft: "d1" } },
    { type: "tool_result", tool_call_id: "card-d1", content: JSON.stringify({ title: "计划预览", headline: "每周 3 练", sessions: [{ day: "周一", name: "腿", minutes: 50, items: ["深蹲 3×8"] }] }) },
    { type: "end" },
  ])
    m = applyBlock(m, b);
  await render(<Message msg={m} onRate={jest.fn()} />);
  expect(screen.getByText("加重 2–10%。")).toBeTruthy();
  expect(screen.queryByText(/K03/)).toBeNull();
  expect(await screen.findByText("确认，保存计划")).toBeTruthy();
  await fireEvent.press(screen.getByText("确认，保存计划"));
  expect(mockApi).toHaveBeenCalledWith("/iron/api/drafts/d1/confirm", { method: "POST", json: {} });
  expect(await screen.findByText("计划已保存")).toBeTruthy();
  expect(screen.getByText("撤销")).toBeTruthy();
  expect(screen.getByText("👍 有用")).toBeTruthy();
});

it("lets the user put off a coach suggestion", async () => {
  mockApi.mockResolvedValue({});
  await render(<InboxMsg inbox={{ version: 1, changes: [], pending: [{ key: "proposal:diet", kind: "proposal", title: "热量往下调一点" }] }} />);
  await fireEvent.press(screen.getByText("暂不"));
  expect(mockApi).toHaveBeenCalledWith("/iron/api/coach/decide", { method: "POST", json: { key: "proposal:diet", decision: "later" } });
  expect(await screen.findByText("好的，「热量往下调一点」今天不再提。")).toBeTruthy();
});

it("puts a 去填模型 button under the no-model reply (§167)", async () => {
  const { router } = jest.requireMock<{ router: { navigate: jest.Mock } }>("expo-router");
  let m = coachMsg("k");
  for (const b of [
    { type: "start", id: "r2" },
    { type: "text", text: "先在「我 → 模型和 API」填你自己的模型，IronM 才能回答。记训练、看计划不用填也能用。" },
    { type: "end" },
  ])
    m = applyBlock(m, b);
  await render(<Message msg={m} onRate={jest.fn()} />);
  await fireEvent.press(screen.getByText("去填模型"));
  expect(router.navigate).toHaveBeenCalledWith({ pathname: "/me", params: { open: "model" } });
});

it("does not show 去填模型 under ordinary answers", async () => {
  let m = coachMsg("k");
  for (const b of [{ type: "start", id: "r3" }, { type: "text", text: "今天练腿。" }, { type: "end" }]) m = applyBlock(m, b);
  await render(<Message msg={m} onRate={jest.fn()} />);
  expect(screen.queryByText("去填模型")).toBeNull();
});
