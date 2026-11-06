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
  await render(<InboxMsg inbox={{ version: 1, changes: [], pending: [{ key: "proposal:review", kind: "proposal", title: "这周的安排要调一下" }] }} />);
  await fireEvent.press(screen.getByText("暂不"));
  expect(mockApi).toHaveBeenCalledWith("/iron/api/coach/decide", { method: "POST", json: { key: "proposal:review", decision: "later" } });
  expect(await screen.findByText("好的，「这周的安排要调一下」今天不再提。")).toBeTruthy();
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

const tempDraft = (state: string, expired = false) => ({
  draft: { id: "t1", kind: "temp", state, expired, items: ["杠铃卧推 换成 哑铃卧推"], temp: { start: "2026-11-07", end: "2026-11-09", why: "出差只有哑铃", lines: ["杠铃卧推 换成 哑铃卧推", "周五 腿 先停"] } },
});

it("§163: 好 on a preview really confirms it, then can be undone", async () => {
  mockApi.mockImplementation(async (path: string) => {
    if (path === "/iron/api/drafts/t1") return tempDraft("pending");
    if (path.endsWith("/confirm")) return tempDraft("confirmed");
    if (path.endsWith("/undo")) return tempDraft("undone");
    return {};
  });
  await render(<InboxMsg inbox={{ version: 1, changes: [], pending: [{ key: "review:temp", kind: "proposal", title: "这几天临时这样练", value: { draft: "t1", temp: true } }] }} />);
  expect(await screen.findByText("11月7日到11月9日这样练，到期回到原计划")).toBeTruthy();
  expect(screen.getByText("• 周五 腿 先停")).toBeTruthy();
  expect(screen.getByText("为什么：出差只有哑铃")).toBeTruthy();
  await fireEvent.press(screen.getByText("好"));
  const calls = mockApi.mock.calls.map((c) => c[0]);
  expect(calls.indexOf("/iron/api/drafts/t1/confirm")).toBeLessThan(calls.indexOf("/iron/api/coach/decide"));
  expect(mockApi).toHaveBeenCalledWith("/iron/api/coach/decide", { method: "POST", json: { key: "review:temp", decision: "accept" } });
  expect(await screen.findByText("已生效，到期回到原计划。")).toBeTruthy();
  await fireEvent.press(screen.getByText("撤销"));
  expect(await screen.findByText("已撤销，回到原计划。")).toBeTruthy();
});

it("§163: an expired preview says so and offers no button", async () => {
  mockApi.mockImplementation(async () => tempDraft("pending", true));
  await render(<InboxMsg inbox={{ version: 1, changes: [], pending: [{ key: "review:temp", kind: "proposal", title: "这几天临时这样练", value: { draft: "t1", temp: true } }] }} />);
  expect(await screen.findByText("没确认，已经作废了；想调可以再跟 IronM 说。")).toBeTruthy();
  expect(screen.queryByText("好")).toBeNull();
});

it("§163: a 'today' change that is not automatic (e.g. coach error) is not listed", async () => {
  mockApi.mockResolvedValue({});
  await render(<InboxMsg inbox={{ version: 1, pending: [], changes: [
    { key: "today", kind: "today", change: "changed", after: "IronM 出错了，还没看今天的情况", status: "info" },
    { key: "today2", kind: "today", change: "changed", after: "今天按七成练", status: "auto" },
  ] }} />);
  expect(screen.queryByText(/出错了/)).toBeNull();
  expect(screen.getByText("今天按七成练")).toBeTruthy();
});

it("§163: a temp card in an answer reads as 'these days, then back to the plan'", async () => {
  mockApi.mockImplementation(async (path: string) => (path.endsWith("/confirm") ? { draft: { state: "confirmed" } } : { draft: { state: "pending" } }));
  let m = coachMsg("k2");
  for (const b of [
    { type: "start", id: "r3" },
    { type: "text", text: "出差这几天先这样练。" },
    { type: "tool_call", id: "card-t2", args: { kind: "temp", draft: "t2" } },
    { type: "tool_result", tool_call_id: "card-t2", content: JSON.stringify({ title: "临时调整", headline: "11月7日到11月9日这样练", items: ["杠铃卧推 换成 哑铃卧推"], expires: "2099-01-01T00:00:00+08:00" }) },
    { type: "end" },
  ])
    m = applyBlock(m, b);
  await render(<Message msg={m} onRate={jest.fn()} />);
  expect(await screen.findByText("确认，这几天这样练")).toBeTruthy();
  expect(screen.getByText(/到期自动回到原计划；点确认才生效/)).toBeTruthy();
  await fireEvent.press(screen.getByText("确认，这几天这样练"));
  expect(await screen.findByText("已生效，到期回到原计划")).toBeTruthy();
});
