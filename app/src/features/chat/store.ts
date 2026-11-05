// 对话的状态放在页面外面（同网页版的 chat 对象）：离开对话页回首页时回答照样在收，回来接着看；
// 换了登录的人就清空。页面用 useChat() 订阅。
// 拍一张（§152）：照片先传到存储，传好的跟下一问一起发；传的时候不能发。
import { useSyncExternalStore } from "react";

import { api } from "@/api/client";
import type { Photo } from "@/lib/photo";

import { apiData, errorText, type FileRef, streamChat, uploadPhoto } from "./api";
import { applyBlock, type ChatMsg, type CoachMsg, coachMsg, fromHistory, type HistoryRow, type Inbox, inboxEmpty, type WeekReport } from "./model";

/** 输入框上方的一张附图：传的时候 data 为空，传好了有 data，传不上有 error。 */
export type Attach = { key: string; uri: string; data: FileRef | null; error: string };

export type ChatState = {
  owner: string; // 这份对话属于哪个登录凭证
  session: string | null;
  messages: ChatMsg[];
  busy: boolean;
  loaded: boolean; // 已经读过最近一段对话（或点了新对话）
  loading: boolean;
  inbox: Inbox | null;
  inboxKey: number; // 每次重新读管家消息就换一个，消息卡片重新开始
  week: WeekReport | null;
  files: Attach[];
};

const initial = (owner = ""): ChatState => ({
  owner, session: null, messages: [], busy: false, loaded: false, loading: false, inbox: null, inboxKey: 0, week: null, files: [],
});

let state: ChatState = initial();
const listeners = new Set<() => void>();
let ctrl: AbortController | null = null;
let run = 0; // 第几次发问：旧的那次结束时不去动新的
let seq = 0;
const nextKey = () => `m${++seq}`;

function set(patch: Partial<ChatState>): void {
  state = { ...state, ...patch };
  for (const f of listeners) f();
}

function subscribe(f: () => void): () => void {
  listeners.add(f);
  return () => listeners.delete(f);
}

export function useChat(): ChatState {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

export function chatState(): ChatState {
  return state;
}

function updateCoach(key: string, fn: (m: CoachMsg) => CoachMsg): void {
  set({ messages: state.messages.map((m) => (m.key === key && m.role === "coach" ? fn(m) : m)) });
}

export type Auth = { token: string; signOut: () => void };

/** 换了登录的人：清掉上一个人的对话。页面渲染时、读状态之前调用，所以这里不通知订阅者。 */
export function ensureOwner(token: string): void {
  if (state.owner === token) return;
  ctrl?.abort();
  ctrl = null;
  run += 1;
  state = initial(token);
}

/** 新对话：清空当前这段，下次发问开一个新会话。 */
export function newChat(): void {
  ctrl?.abort();
  ctrl = null;
  run += 1;
  set({ session: null, messages: [], busy: false, loaded: true, loading: false, files: [] });
}

/** 还有照片在传。 */
export const uploading = (s: ChatState = state): boolean => s.files.some((f) => !f.data && !f.error);

/** 有传好的照片可以发。 */
export const photoReady = (s: ChatState = state): boolean => s.files.some((f) => f.data);

function updateFile(key: string, patch: Partial<Attach>): void {
  if (!state.files.some((f) => f.key === key)) return; // 已经去掉了、换了人或开了新对话
  set({ files: state.files.map((f) => (f.key === key ? { ...f, ...patch } : f)) });
}

/** 附一张照片：先放上小图，传好或传不上再改。传好了返回 true。 */
export async function attachPhoto(photo: Photo): Promise<boolean> {
  const key = nextKey();
  set({ files: [...state.files, { key, uri: photo.uri, data: null, error: "" }] });
  try {
    const data = await uploadPhoto(photo, `photo-${Date.now()}.jpg`);
    updateFile(key, { data });
    return state.files.some((f) => f.key === key);
  } catch (err) {
    updateFile(key, { error: errorText(err, "照片没传上，请再试一次。") });
    return false;
  }
}

/** 去掉一张附图。 */
export function dropFile(key: string): void {
  set({ files: state.files.filter((f) => f.key !== key) });
}

export function stop(): void {
  ctrl?.abort();
}

async function loadInbox(): Promise<void> {
  try {
    const r = await api<Inbox>("/iron/api/coach/inbox");
    const inbox = inboxEmpty(r) ? null : { version: r.version, changes: r.changes ?? [], pending: r.pending ?? [] };
    set({ inbox, inboxKey: state.inboxKey + 1 });
    // 看过了：下次打开不再列这些调整
    if (r.changes?.length) api("/iron/api/coach/seen", { method: "POST", json: { version: r.version } }).catch(() => {});
  } catch {
    set({ inbox: null });
  }
}

async function loadWeek(): Promise<void> {
  try {
    const r = await api<WeekReport>("/iron/api/report/week");
    set({ week: r.seen ? null : r });
  } catch {
    set({ week: null });
  }
}

/** 周报消息点掉：这周不再出（记在服务端）。 */
export function closeWeek(): void {
  set({ week: null });
  api("/iron/api/report/week/seen", { method: "POST" }).catch(() => {});
}

/** 打开某一段以前的对话（§36）：读出消息，接着在这个会话里问。 */
export async function loadSession(id: string): Promise<void> {
  if (state.busy) return;
  try {
    const rows = (await apiData<{ history?: HistoryRow[] }>(`/api/history?session_id=${encodeURIComponent(id)}`)).history ?? [];
    set({ session: id, messages: fromHistory(rows, nextKey), loaded: true });
  } catch {
    set({ session: id, messages: [], loaded: true });
  }
}

async function loadLatest(): Promise<void> {
  set({ loaded: true, loading: true });
  try {
    const list = (await apiData<{ summaries?: { session_id: string }[] }>("/api/history")).summaries ?? [];
    // 读的时候已经问了新问题：不再盖掉
    if (list.length && !state.messages.length) await loadSession(list[0].session_id);
  } catch {
    // 读不到以前的对话就从空白开始
  } finally {
    set({ loading: false });
  }
}

/** 打开对话页：第一次读最近一段对话；每次都重新读管家消息和周报消息。 */
export async function openChat(): Promise<void> {
  const extras = Promise.all([loadInbox(), loadWeek()]);
  if (!state.loaded) await loadLatest();
  await extras;
}

/** 发问：先放上提问和一条空回答，回答一块一块填进去。 */
export async function ask(question: string, auth: Auth): Promise<void> {
  const q = question.trim();
  if (!q || state.busy || uploading()) return;
  // 传好的照片跟这一问一起发；传不上的留着，让用户自己去掉或重拍
  const sent = state.files.filter((f) => f.data);
  const files = sent.map((f) => f.data as FileRef);
  const photos = sent.map((f) => f.uri);
  const at = new Date().toISOString();
  const key = nextKey();
  const mine = ++run;
  ctrl = new AbortController();
  const signal = ctrl.signal;
  set({
    busy: true,
    loaded: true,
    files: state.files.filter((f) => !f.data),
    messages: [...state.messages, { role: "user", key: nextKey(), text: q, at, ...(photos.length ? { photos } : {}) }, coachMsg(key, at)],
  });
  try {
    if (!state.session) {
      const s = await apiData<{ session_id: string }>("/api/session", { method: "POST", json: {} });
      if (mine !== run) return;
      set({ session: s.session_id });
    }
    await streamChat({
      token: auth.token,
      question: q,
      session: state.session ?? "",
      files,
      signal,
      onBlock: (b) => {
        if (mine === run) updateCoach(key, (m) => applyBlock(m, b));
      },
      onUnauthorized: auth.signOut,
    });
    updateCoach(key, (m) => (!m.text && !m.error ? { ...m, error: "这次没有收到回答，请稍后再试。" } : m));
  } catch (err) {
    if (signal.aborted) updateCoach(key, (m) => ({ ...m, notices: [...m.notices, "已停止。"] }));
    else updateCoach(key, (m) => ({ ...m, error: errorText(err, "这次没能回答，请稍后再试。") }));
  } finally {
    updateCoach(key, (m) => ({ ...m, done: true }));
    if (mine === run) {
      ctrl = null;
      set({ busy: false });
    }
  }
}

/** 评价一条回答：有用 / 没用（§31）。 */
export async function rate(key: string, value: 1 | -1): Promise<void> {
  const msg = state.messages.find((m): m is CoachMsg => m.key === key && m.role === "coach");
  if (!msg || msg.rating === value) return;
  try {
    await apiData("/api/rating", { method: "POST", json: { rating: value, responseId: msg.id } });
    updateCoach(key, (m) => ({ ...m, rating: value }));
    if (msg.turn) api(`/iron/api/turns/${encodeURIComponent(msg.turn)}/rating`, { method: "POST", json: { rating: value } }).catch(() => {});
  } catch {
    updateCoach(key, (m) => ({ ...m, notices: [...m.notices, "评价没有保存成功，请稍后再试。"] }));
  }
}
