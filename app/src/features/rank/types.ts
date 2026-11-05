// 排行榜的接口返回（照 ironm_agent/web_rank.py、rank.py）。

export type Tier = { key: string; name: string };

/** 评论（只带昵称，不带账号）。 */
export type Comment = { id: string; nick: string; text: string; likes: number; liked: boolean; mine: boolean; at: string };

/** 榜上的一条。 */
export type RankRow = {
  key: string;
  name: string;
  part: string;
  custom: boolean;
  added: string;
  desc: string;
  tag: string;
  votes: number;
  mean: number | null;
  score: number | null;
  tier: string;
  counts: Record<string, number>;
  mine: string;
  rank: number | null;
  trend: string;
  image: string | null;
  credit: { url?: string; author?: string; license?: string; page?: string } | null;
  comments?: number;
  top_comment?: Comment | null;
};

type Meta = { tiers: Tier[]; min_votes: number; hide_reports: number; comment_max: number };

export type BoardCard = { board: string; name: string; icon: string; people: number; top: RankRow[]; fill: RankRow[]; waiting: number };

export type RankHome = Meta & { boards: BoardCard[]; hot: { term: string; flag?: string }[] };

export type Board = Meta & {
  board: string;
  name: string;
  icon: string;
  part: string;
  parts: string[];
  items: RankRow[];
  people: number;
  disclaimer: string;
  no_claims: boolean;
  can_add: boolean;
};

export type PlanDetail = {
  days: number[];
  sessions: { day: number; name: string; minutes: number; items: string[] }[];
  why: string;
  intensity: string;
  progress: string;
  deload: string;
  differs: string[];
  source: { authors: string[]; url: string; secondhand: boolean; seen: string } | null;
  ask: string;
};

export type Item = Meta & {
  board: string;
  name: string;
  item: RankRow;
  comments: Comment[];
  nick: string;
  disclaimer: string;
  no_claims: boolean;
  plan: PlanDetail | null;
};

export type Hit = { board: string; board_name: string; icon: string; key: string; name: string; tier: string; mean: number | null; votes: number };
