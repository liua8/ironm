// 对话状态（spec §164 第二期）：发问时先开会话、回答一块块填进去；停止留"已停止。"；换了登录的人清空。
import type { StreamArgs } from "@/features/chat/api";

const mockApiData = jest.fn();
const mockStreamChat = jest.fn();
const mockApi = jest.fn();
const mockUpload = jest.fn();

jest.mock("@/features/chat/api", () => ({
  apiData: (...a: unknown[]) => mockApiData(...a),
  streamChat: (...a: unknown[]) => mockStreamChat(...a),
  uploadPhoto: (...a: unknown[]) => mockUpload(...a),
  errorText: (err: unknown, fallback = "没有成功") => (err instanceof Error && err.message ? err.message : fallback),
}));
jest.mock("@/api/client", () => ({ api: (...a: unknown[]) => mockApi(...a) }));

import { ask, attachPhoto, chatState, dropFile, ensureOwner, newChat, openChat, stop, uploading } from "@/features/chat/store";

const auth = { token: "tok", signOut: jest.fn() };

beforeEach(() => {
  mockApiData.mockReset();
  mockStreamChat.mockReset();
  mockApi.mockReset();
  mockUpload.mockReset();
  ensureOwner(`owner-${Math.random()}`);
});

it("opens a session, streams the answer in and marks it done", async () => {
  mockApiData.mockResolvedValueOnce({ session_id: "s1" });
  mockStreamChat.mockImplementation(async ({ onBlock, session }: StreamArgs) => {
    expect(session).toBe("s1");
    onBlock({ type: "start", id: "r1" });
    onBlock({ type: "text", text: "今天练腿" });
    onBlock({ type: "end" });
  });
  await ask("  练什么  ", auth);
  const st = chatState();
  expect(mockApiData).toHaveBeenCalledWith("/api/session", { method: "POST", json: {} });
  expect(st.session).toBe("s1");
  expect(st.busy).toBe(false);
  expect(st.messages.map((m) => m.role)).toEqual(["user", "coach"]);
  expect(st.messages[0]).toMatchObject({ text: "练什么" });
  expect(st.messages[1]).toMatchObject({ id: "r1", text: "今天练腿", done: true });
});

it("says it stopped when the user stops", async () => {
  mockApiData.mockResolvedValueOnce({ session_id: "s2" });
  mockStreamChat.mockImplementation(
    ({ signal, onBlock }: StreamArgs) =>
      new Promise((_, reject) => {
        onBlock({ type: "text", text: "先热" });
        signal.addEventListener("abort", () => reject(new Error("aborted")));
      }),
  );
  const p = ask("练什么", auth);
  await new Promise((r) => setTimeout(r, 0));
  expect(chatState().busy).toBe(true);
  stop();
  await p;
  expect(chatState().messages[1]).toMatchObject({ text: "先热", notices: ["已停止。"], done: true });
  expect(chatState().busy).toBe(false);
});

it("explains failures and empty answers", async () => {
  mockApiData.mockResolvedValueOnce({ session_id: "s3" });
  mockStreamChat.mockRejectedValueOnce(new Error("连不上服务，请检查网络后再试。"));
  await ask("a", auth);
  expect(chatState().messages[1]).toMatchObject({ error: "连不上服务，请检查网络后再试。", done: true });
  mockStreamChat.mockResolvedValueOnce(undefined);
  await ask("b", auth);
  expect(chatState().messages[3]).toMatchObject({ error: "这次没有收到回答，请稍后再试。" });
});

it("loads the latest session, the coach inbox and the weekly message on open", async () => {
  mockApi.mockImplementation(async (path: string) => {
    if (path === "/iron/api/coach/inbox") return { version: 7, changes: [{ key: "c1", kind: "review", change: "added", after: "少练一组" }], pending: [] };
    if (path === "/iron/api/report/week") return { seen: false, from: "2026-10-27", to: "2026-11-02", done: 2, records: [], focus: "照计划来" };
    return {};
  });
  mockApiData.mockImplementation(async (path: string) => {
    if (path === "/api/history") return { summaries: [{ session_id: "old" }] };
    return { history: [{ role: "user", content: "上次问的" }, { role: "assistant", id: "r", content: "上次答的" }] };
  });
  await openChat();
  const st = chatState();
  expect(st.session).toBe("old");
  expect(st.messages.map((m) => m.role === "user" ? m.text : m.text)).toEqual(["上次问的", "上次答的"]);
  expect(st.inbox?.changes).toHaveLength(1);
  expect(st.week?.done).toBe(2);
  expect(mockApi).toHaveBeenCalledWith("/iron/api/coach/seen", { method: "POST", json: { version: 7 } });
  newChat();
  expect(chatState()).toMatchObject({ session: null, messages: [], loaded: true });
});

it("clears the conversation when another person signs in", async () => {
  mockApiData.mockResolvedValueOnce({ session_id: "s4" });
  mockStreamChat.mockResolvedValueOnce(undefined);
  ensureOwner("a");
  await ask("x", auth);
  expect(chatState().messages).toHaveLength(2);
  ensureOwner("a");
  expect(chatState().messages).toHaveLength(2);
  ensureOwner("b");
  expect(chatState()).toMatchObject({ owner: "b", messages: [], session: null });
});

// 拍一张（§152）：照片先传到存储；传的时候不能发；传好的跟下一问一起发，发完清掉；传不上的留着能去掉
const PHOTO = { uri: "file:///s.jpg", type: "image/jpeg", width: 1600, height: 1200, blob: null };
const REF = { file_key: "k1", file_name: "photo.jpg", file_type: "image/jpeg", file_url: "https://x/k1", file_size: 1234 };

it("传照片的时候不能发，传好的跟下一问一起发", async () => {
  let finish: (v: unknown) => void = () => {};
  mockUpload.mockReturnValueOnce(new Promise((r) => { finish = r; }));
  const pending = attachPhoto(PHOTO);
  expect(uploading()).toBe(true);
  expect(chatState().files).toEqual([expect.objectContaining({ uri: "file:///s.jpg", data: null, error: "" })]);
  await ask("这是什么", auth);
  expect(mockStreamChat).not.toHaveBeenCalled(); // 还在传

  finish(REF);
  expect(await pending).toBe(true);
  expect(uploading()).toBe(false);
  mockApiData.mockResolvedValueOnce({ session_id: "s9" });
  mockStreamChat.mockImplementation(async ({ onBlock }: StreamArgs) => onBlock({ type: "text", text: "是坐姿推胸机" }));
  await ask("这是什么", auth);
  expect(mockStreamChat.mock.calls[0][0].files).toEqual([REF]);
  expect(chatState().files).toEqual([]);
  expect(chatState().messages[0]).toMatchObject({ role: "user", text: "这是什么", photos: ["file:///s.jpg"] });
});

it("照片传不上：留一句中文说明，不挡发问，能去掉", async () => {
  mockUpload.mockRejectedValueOnce(new Error("连不上服务，请检查网络后再试。"));
  expect(await attachPhoto(PHOTO)).toBe(false);
  const f = chatState().files[0];
  expect(f.error).toBe("连不上服务，请检查网络后再试。");
  expect(uploading()).toBe(false);
  mockApiData.mockResolvedValueOnce({ session_id: "s10" });
  mockStreamChat.mockResolvedValueOnce(undefined);
  await ask("练什么", auth);
  expect(mockStreamChat.mock.calls[0][0].files).toEqual([]);
  expect(chatState().files).toHaveLength(1); // 传不上的留着
  dropFile(f.key);
  expect(chatState().files).toEqual([]);
});

it("新对话、换了人都清掉附图", async () => {
  mockUpload.mockResolvedValue(REF);
  await attachPhoto(PHOTO);
  newChat();
  expect(chatState().files).toEqual([]);
  await attachPhoto(PHOTO);
  ensureOwner("someone-else");
  expect(chatState().files).toEqual([]);
});
