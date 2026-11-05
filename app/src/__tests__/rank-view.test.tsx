// 排行榜页面（spec §161）：榜单整个没人评时只说"还没人评过"，不写"0 人参与""待评 N 个""没人评"；
// 有人评过时有排法、名次、待评；条目页投票调对接口；榜单首页搜索不记热搜、回车才记。
import { fireEvent, render, screen } from "@testing-library/react-native";

import { configureApi, setFetcher } from "@/api/client";
import { RankBoardView } from "@/features/rank/board";
import { RankHomeView } from "@/features/rank/home";
import { RankItemView } from "@/features/rank/item";

jest.mock("expo-router", () => ({ router: { push: jest.fn(), setParams: jest.fn(), canGoBack: () => true, back: jest.fn(), replace: jest.fn() } }));

const TIERS = [
  { key: "hang", name: "夯" },
  { key: "top", name: "顶级" },
  { key: "elite", name: "人上人" },
  { key: "npc", name: "NPC" },
  { key: "la", name: "拉" },
];
const META = { tiers: TIERS, min_votes: 3, hide_reports: 3, comment_max: 200 };
const counts = { hang: 0, top: 0, elite: 0, npc: 0, la: 0 };
const row = (key: string, name: string, over: object = {}) => ({
  key, name, part: "", custom: false, added: "", desc: "", tag: "", votes: 0, mean: null, score: null, tier: "",
  counts, mine: "", rank: null, trend: "", image: null, credit: null, comments: 0, top_comment: null, ...over,
});
const board = (people: number, items: unknown[]) => ({
  ...META, board: "meal", name: "健身餐榜", icon: "", part: "", parts: [], items, people,
  disclaimer: "用户评分，不代表平台观点。", no_claims: false, can_add: true,
});

function reply(body: unknown, status = 200) {
  return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
}

let seen: { path: string; method: string; body: unknown }[] = [];
let routes: (path: string, method: string) => unknown;

beforeEach(() => {
  seen = [];
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ path, method, body: init?.body });
    const got = routes(path, method);
    return got === undefined ? reply({ detail: "没有这个接口" }, 404) : reply(got);
  });
});

it("没人评的榜不写空话", async () => {
  routes = () => board(0, [row("a", "鸡胸饭"), row("b", "牛肉饭")]);
  await render(<RankBoardView board="meal" part="" />);
  expect(await screen.findByText("还没人评过，点进去打第一个分。用户评分，不代表平台观点。")).toBeTruthy();
  expect(screen.getByText("鸡胸饭")).toBeTruthy();
  expect(screen.queryByText(/0 人参与|待评/)).toBeNull();
  expect(screen.queryByText("没人评")).toBeNull();
  expect(screen.queryByText("评论多")).toBeNull(); // 没人评时不出排法
});

it("有人评过时有排法、名次、待评", async () => {
  routes = () => board(4, [
    row("a", "鸡胸饭", { rank: 1, tier: "top", votes: 4, mean: 4.2, score: 4 }),
    row("b", "牛肉饭", { votes: 1 }),
  ]);
  await render(<RankBoardView board="meal" part="" />);
  expect(await screen.findByText(/^4 人参与/)).toBeTruthy();
  expect(screen.getByText("评论多")).toBeTruthy();
  expect(screen.getByText("顶级")).toBeTruthy();
  expect(screen.getByText("待评 1 个 · 3 个人评过才上榜")).toBeTruthy();
  expect(screen.getByText("还差 2 票")).toBeTruthy();
});

it("条目页投一票", async () => {
  const item = (mine: string) => ({
    ...META, board: "meal", name: "健身餐榜", nick: "", disclaimer: "说明", no_claims: false, plan: null, comments: [],
    item: row("a", "鸡胸饭", { mine, votes: mine ? 1 : 0, counts: { ...counts, hang: mine ? 1 : 0 } }),
  });
  routes = (path, method) => (method === "PUT" && path === "/iron/api/rank/vote" ? item("hang") : path.startsWith("/iron/api/rank/item") ? item("") : undefined);
  await render(<RankItemView board="meal" itemKey="a" />);
  expect(await screen.findByText("还没人评过，来投第一票")).toBeTruthy();
  expect(screen.getByText("还没有评论，说说你的看法。")).toBeTruthy();
  await fireEvent.press(screen.getByText("夯"));
  expect(await screen.findByText("我投的：夯")).toBeTruthy();
  const put = seen.find((x) => x.method === "PUT");
  expect(JSON.parse(String(put?.body))).toEqual({ board: "meal", key: "a", tier: "hang" });
});

it("榜单首页：热搜点了按记热搜去搜", async () => {
  routes = (path) => {
    if (path === "/iron/api/rank") return { ...META, hot: [{ term: "深蹲", flag: "热" }], boards: [{ board: "move", name: "动作榜", icon: "", people: 0, top: [], fill: [row("squat", "深蹲")], waiting: 1 }] };
    if (path.startsWith("/iron/api/rank/search")) return { items: [{ board: "move", board_name: "动作榜", icon: "", key: "squat", name: "杠铃深蹲", tier: "", mean: null, votes: 0 }] };
    return undefined;
  };
  await render(<RankHomeView />);
  expect(await screen.findByText("动作榜")).toBeTruthy();
  await fireEvent.press(screen.getByText(/^1 深蹲/));
  expect(await screen.findByText("杠铃深蹲")).toBeTruthy();
  expect(seen.some((x) => x.path === `/iron/api/rank/search?q=${encodeURIComponent("深蹲")}&record=true`)).toBe(true);
});
