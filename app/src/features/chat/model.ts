// 对话里的消息（同网页版 coachMsg / applyBlock / loadSession）：回答一块一块到，每块改出一条新的消息（不原地改，方便 React 重画）。
import type { ChatBlock } from "./sse";

export type Step = { id: string; name: string; task: string; result: string; done: boolean };

/** 预览卡片的内容（服务端 render._card）：计划、训练记录、改目标、临时调整。 */
export type CardData = {
  kind?: string;
  draft?: string;
  title?: string;
  headline?: string;
  expires?: string;
  changes?: string;
  // 计划：按操作改的只列变化的行（§45）
  rows?: { what: string; before?: string; after: string }[];
  impact?: string[];
  skipped?: string[];
  hint?: string;
  // 计划：整份
  sessions?: { day: string; name: string; minutes: number; items: string[]; changed?: boolean }[];
  removed?: string[];
  replaces?: boolean;
  // 训练记录、改目标、临时调整
  items?: string[];
  rpe?: number | null;
  note?: string;
};

export type CardRef = { id: string; kind: string; draft: string; data: CardData | null };

export type UserMsg = { role: "user"; key: string; text: string; at: string; photos?: string[] }; // photos：随这一问带的照片（本机地址，只在这次显示）

export type CoachMsg = {
  role: "coach";
  key: string;
  id: string; // 回答的编号：评价时带回
  turn: string; // 这一轮的编号（§31）
  steps: Step[];
  text: string;
  notices: string[];
  sources: string;
  cards: CardRef[];
  error: string;
  done: boolean;
  rating: 0 | 1 | -1;
  at: string;
};

export type ChatMsg = UserMsg | CoachMsg;

export function coachMsg(key: string, at = ""): CoachMsg {
  return { role: "coach", key, id: "", turn: "", steps: [], text: "", notices: [], sources: "", cards: [], error: "", done: false, rating: 0, at };
}

const str = (v: unknown) => (v == null ? "" : String(v));
const argsOf = (b: ChatBlock): Record<string, unknown> =>
  b.args && typeof b.args === "object" ? (b.args as Record<string, unknown>) : {};

/** 收到一块，得到新的一条消息。 */
export function applyBlock(msg: CoachMsg, b: ChatBlock): CoachMsg {
  switch (b.type) {
    case "start":
      return b.id ? { ...msg, id: str(b.id) } : msg;
    case "tool_call": {
      const id = str(b.id);
      const args = argsOf(b);
      if (id === "turn") return { ...msg, turn: str(args.turn) };
      if (id === "sources") return msg;
      if (id.startsWith("card-")) {
        if (msg.cards.some((c) => c.id === id)) return msg;
        return { ...msg, cards: [...msg.cards, { id, kind: str(args.kind), draft: str(args.draft), data: null }] };
      }
      if (msg.steps.some((x) => x.id === id)) return msg;
      return { ...msg, steps: [...msg.steps, { id, name: str(b.name), task: str(args["任务"]), result: "", done: false }] };
    }
    case "tool_result": {
      const id = str(b.tool_call_id);
      if (id === "sources") return { ...msg, sources: str(b.content) };
      if (id.startsWith("card-")) {
        let data: CardData | null = null;
        try {
          const parsed: unknown = JSON.parse(str(b.content) || "{}");
          data = parsed && typeof parsed === "object" ? (parsed as CardData) : null;
        } catch {
          data = null;
        }
        return { ...msg, cards: msg.cards.map((c) => (c.id === id ? { ...c, data } : c)) };
      }
      if (!msg.steps.some((x) => x.id === id)) return msg;
      return { ...msg, steps: msg.steps.map((x) => (x.id === id ? { ...x, done: true, result: str(b.content) } : x)) };
    }
    case "text":
      return b.text ? { ...msg, text: msg.text + str(b.text) } : msg;
    case "notice":
      return b.text ? { ...msg, notices: [...msg.notices, str(b.text)] } : msg;
    case "error":
      return { ...msg, error: str(b.message) || "这次没能回答，请稍后再试。" };
    case "end":
      return { ...msg, done: true };
    default:
      return msg;
  }
}

export type HistoryRow = { role?: string; content?: unknown; content_dict?: unknown; id?: unknown; timestamp?: string };

/** 以前的对话读出来（§36）：只取最近 30 条；回答按当时的块重放，没有块的用正文。 */
export function fromHistory(rows: HistoryRow[], keyOf: () => string): ChatMsg[] {
  return rows.slice(-30).map((row): ChatMsg => {
    if (row.role === "user") return { role: "user", key: keyOf(), text: str(row.content), at: row.timestamp || "" };
    let msg = { ...coachMsg(keyOf(), row.timestamp || ""), id: str(row.id), done: true };
    if (Array.isArray(row.content_dict)) {
      for (const b of row.content_dict) if (b && typeof b === "object" && typeof (b as ChatBlock).type === "string") msg = applyBlock(msg, b as ChatBlock);
    }
    if (!msg.text) msg = { ...msg, text: str(row.content) };
    return { ...msg, done: true };
  });
}

/** 正在答的时候，过程那一行写什么（只有一个 IronM，§121）。 */
export function progressHead(msg: CoachMsg): string {
  if (!msg.done) return msg.text ? "正在整理回答…" : msg.steps.length ? "IronM 正在查资料和数据…" : "正在理解你的问题…";
  return msg.steps.length ? "IronM 是怎么答的" : "";
}

// ---- 管家消息（§26）和周报消息（§147）--------------------------------------------------------

export type InboxChange = { key: string; kind: string; change: string; before?: string; after?: string; why?: string; status?: string };
export type InboxPending = { key: string; kind: string; title: string; why?: string; value?: { trigger?: string } | null };
export type Inbox = { version: number | string; changes: InboxChange[]; pending: InboxPending[] };

export const INBOX_WORD: Record<string, string> = { added: "新", changed: "调整", removed: "解除" };

/** 管家消息里列出来的调整：训练目标那类不列，最多三条。 */
export function inboxShown(r: Inbox): InboxChange[] {
  return r.changes.filter((c) => c.kind !== "target").slice(0, 3);
}

export function inboxEmpty(r: Inbox | null | undefined): boolean {
  return !r || (!r.changes?.length && !r.pending?.length);
}

export type WeekRecord = { exercise: string; weight_kg: number; reps: number };
export type WeekReport = { seen?: boolean; from: string; to: string; done: number; planned?: number; minutes?: number; records: WeekRecord[]; focus: string };

/** IronM 发的周报消息：两三句话（§147 需求 3）。 */
export function weekSaid(r: WeekReport): string {
  const rec = r.records?.[0];
  return [
    r.done ? `上周练了 ${r.done} 次${r.planned ? `（计划 ${r.planned} 次）` : ""}${r.minutes ? `，一共 ${r.minutes} 分钟` : ""}。` : "上周没有训练记录。",
    rec ? `破了 ${r.records.length} 个纪录，${rec.exercise} 做到了 ${rec.weight_kg} 公斤 × ${rec.reps}。` : "",
    `下周重点：${r.focus}`,
  ]
    .filter(Boolean)
    .join("");
}

// ---- 预览卡片的状态（同网页版 cardView）-----------------------------------------------------------

export const CARD_STATE: Record<string, string> = { pending: "", confirmed: "已保存", cancelled: "已取消", undone: "已撤销" };

export function cardExpired(data: CardData, state: string, now = Date.now()): boolean {
  if (state !== "pending" || !data.expires) return false;
  const t = Date.parse(data.expires);
  return !Number.isNaN(t) && t < now;
}
