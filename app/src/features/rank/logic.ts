// 排行榜的纯逻辑（照网页版 app.js 的 rankHome / rankBoard / rankItem / rankComments，spec §161）：
// 名次、档位、趋势、三种排法、待评、没人评时不写空话、评论排序、条目的状态一行。
import type { Board, BoardCard, Comment, RankRow, Tier } from "./types";

export const MOVE_PARTS = ["胸", "背", "肩", "手臂", "核心", "腿臀"];

export const tierNames = (tiers: Tier[]): Record<string, string> => Object.fromEntries(tiers.map((t) => [t.key, t.name]));

export const scoreText = (x: { mean: number | null }) => (x.mean != null ? x.mean.toFixed(1) : "—");

export type TrendKind = "up" | "down" | "new" | "";
export const trendKind = (t: string): TrendKind => (t.startsWith("↑") ? "up" : t.startsWith("↓") ? "down" : t === "新" ? "new" : "");

/** 首页一个榜卡片里的行：上榜的前几名，不够的用待评的补上。 */
export const cardRows = (b: BoardCard): RankRow[] => [...b.top, ...b.fill];

/** 名次那一格：整个榜没人评时空着（不写"–"，§161），有人评过时没上榜的写"–"。 */
export function rowNo(people: number, rank: number | null): string {
  if (!people) return "";
  return rank ? String(rank) : "–";
}

/** 右边的档位牌：上榜的写档位；榜上有人评过时没上榜的写"待评"；整个榜没人评时什么都不写。 */
export function rowTag(people: number, x: RankRow, names: Record<string, string>): { text: string; tier: string } | null {
  if (x.rank && x.tier) return { text: names[x.tier] ?? x.tier, tier: x.tier };
  if (!x.rank && people) return { text: "待评", tier: "wait" };
  return null;
}

/** 榜卡片标题下的一行：有人评过才写人数。 */
export const peopleLine = (people: number) => (people ? `本周 · ${people} 人参与` : "");

export type SortKey = "综合" | "评论多" | "新上榜";
const SORTS: SortKey[] = ["综合", "评论多", "新上榜"];

/** 能用的排法：不能添加的榜（训练计划榜）没有"新上榜"。 */
export const sortOptions = (d: Pick<Board, "can_add">): SortKey[] => SORTS.filter((k) => d.can_add || k !== "新上榜");

export const rankedOf = (items: RankRow[]) => items.filter((x) => x.rank);

/** 待评：没上榜的，票多的在前。 */
export const waitingOf = (items: RankRow[]) => items.filter((x) => !x.rank).sort((a, b) => b.votes - a.votes);

export function sortRows(items: RankRow[], sort: SortKey): RankRow[] {
  const ranked = rankedOf(items);
  if (sort === "评论多") return [...ranked].sort((a, b) => (b.comments ?? 0) - (a.comments ?? 0) || (b.score ?? 0) - (a.score ?? 0));
  if (sort === "新上榜") return items.filter((x) => x.added).sort((a, b) => b.added.localeCompare(a.added));
  return ranked;
}

/** 列表空着时的那句：整个榜没人评时不说（最上面已经说过）。 */
export function emptyText(people: number, sort: SortKey): string {
  if (!people) return "";
  return sort === "新上榜" ? "还没有用户添加的条目。" : "还没有上榜的（要 3 个人评过）。下面待评的点进去投一票。";
}

/** 榜单页最上面一行（§161）：没人评时只说"还没人评过，点进去打第一个分"，不写"0 人参与"。 */
export function boardCaption(d: Pick<Board, "people" | "disclaimer">, part: string): string {
  const head = d.people ? `${d.people} 人参与 · ` : "还没人评过，点进去打第一个分。";
  return `${head}${d.disclaimer}${part ? " 按部位看时名次是这个部位里的，不显示名次变化。" : ""}`;
}

/** 待评那一块的标题：整个榜没人评时不写"待评 N 个"。 */
export function pendingTitle(people: number, n: number): string {
  return people && n ? `待评 ${n} 个 · 3 个人评过才上榜` : "";
}

/** 待评一行右边：有票时写还差几票。 */
export const shortOf = (x: RankRow, minVotes: number) => (x.votes ? `还差 ${minVotes - x.votes} 票` : "");

/** 榜单里一条下面那行小字。 */
export function lineMeta(x: RankRow): string {
  const c = x.top_comment;
  return `${x.votes} 人评过 · ${x.comments ?? 0} 条评论${c ? ` · “${c.text}”` : ""}`;
}

/** 条目详情的状态一行：名次、几人评过、还差几票，或者"来投第一票"。 */
export function itemStatus(x: RankRow, minVotes: number): string {
  if (x.votes >= minVotes) return `第 ${x.rank} 名 · ${x.votes} 人评过${x.trend ? ` · 本周 ${x.trend}` : ""}`;
  if (x.votes) return `${x.votes} 人评过，还差 ${minVotes - x.votes} 票上榜`;
  return "还没人评过，来投第一票";
}

/** 五档各几票的条长（最多的那档占满）。 */
export function tierBars(x: RankRow, tiers: Tier[]): { key: string; name: string; n: number; frac: number }[] {
  const top = Math.max(1, ...tiers.map((t) => x.counts[t.key] ?? 0));
  return tiers.map((t) => ({ key: t.key, name: t.name, n: x.counts[t.key] ?? 0, frac: (x.counts[t.key] ?? 0) / top }));
}

export type CommentSort = "热门" | "最新";

/** 评论：服务端给的就是热门（点赞多的在前）；最新按时间倒序。 */
export function sortComments(list: Comment[], sort: CommentSort): Comment[] {
  return sort === "最新" ? [...list].sort((a, b) => b.at.localeCompare(a.at)) : list;
}

/** 评论的日期：11月5日。 */
export function md(iso: string): string {
  const [, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return m && d ? `${m}月${d}日` : "";
}

const WEEK = "一二三四五六日";
export const weekdayName = (d: number) => `周${WEEK[d - 1] ?? ""}`;

/** 训练计划榜条目上那句：有几个版本、这里是哪个。 */
export function planDaysText(p: { days: number[]; sessions: unknown[] }): string {
  return p.days.length > 1 ? `有每周 ${p.days.join("、")} 天几个版本，这里是每周 ${p.sessions.length} 天的健身房版。` : "这里是健身房版。";
}

/** 字数（按字算，不按 UTF-16）。 */
export const charCount = (t: string) => [...t].length;

/** 热搜标记的颜色：热、新、升。 */
export const flagKind = (f: string | undefined) => (f === "热" ? "hot" : f === "新" ? "new" : f === "升" ? "up" : "");

/** 配图地址：相对地址补上服务地址（和图鉴同一个规则）。 */
export { imgUrl } from "@/features/atlas/logic";
