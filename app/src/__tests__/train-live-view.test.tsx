// 首页·练、训练计划、训练记录器整页（spec §164 第二期）：读对接口、开练带上今天的计划、打勾存回、结束保存出练完的卡。
import { fireEvent, render, screen } from "@testing-library/react-native";

import { configureApi, setFetcher } from "@/api/client";
import LivePage from "@/app/live";
import PlanPage from "@/app/plan";
import { TrainSection } from "@/features/home/train";

jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: () => false },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
}));
const mockRouter = jest.requireMock<{ router: { push: jest.Mock } }>("expo-router").router;

const session = { day: 4, name: "上肢", minutes: 45, items: [{ exercise: "卧推", sets: 2, reps: "8", load: "40 公斤" }, { exercise: "划船", sets: 3, reps: "10" }] };
const day = (date: string, weekday: string, today = false, s: typeof session | null = null) => ({
  date, weekday, today, done: false, session: s, version: null, changes: [], edited: [], warmup: s ? { minutes: 5, steps: ["开合跳 1 分钟"], basis: "按动作" } : null, burn: null,
});
const week = { days: [day("2026-11-02", "周一"), day("2026-11-03", "周二"), day("2026-11-04", "周三"), day("2026-11-05", "周四", true, session), day("2026-11-06", "周五"), day("2026-11-07", "周六"), day("2026-11-08", "周日")] };
const training = { plan: { title: "两分化", days_per_week: 1, sessions: [session] }, targets: { 卧推: { text: "42.5 公斤 × 8〔K03〕", why: "", action: "up" } }, workouts: [] };
const brief = { today: { training: { kind: "session", done: false } }, week: { planned: 3, done: 1 }, alerts: [{ key: "bp_high", title: "血压偏高：加大训练前先找医生", text: "最近两次血压偏高" }] };
const lib = { exercises: [{ id: "bench", name: "卧推", part: "胸", muscles: "胸大肌", equipment: ["杠铃"], cues: ["肩胛收紧"] }, { id: "row", name: "划船", part: "背", muscles: "背阔肌", equipment: ["哑铃"] }] };
const liveSet = (w: number, r: number) => ({ weight_kg: w, reps: r, seconds: null, done: false, at: null });
const live = {
  id: "L1", started: new Date(Date.now() - 5 * 60000).toISOString(), updated: "", session: "上肢", no_heavier: false,
  items: [{ exercise: "卧推", timed: false, rest: 90, target: "2×8 40 公斤", best: null, plan_kg: 40, sets: [liveSet(40, 8), liveSet(40, 8)], cardio: false }],
};

function reply(body: unknown, status = 200) {
  return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
}

let seen: { url: string; method: string; body: unknown }[] = [];
let liveNow: typeof live | null = null;

beforeEach(() => {
  seen = [];
  liveNow = null;
  mockRouter.push.mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path === "/iron/api/brief") return reply(brief);
    if (path === "/iron/api/training") return reply(training);
    if (path === "/iron/api/week") return reply(week);
    if (path === "/iron/api/exercises") return reply(lib);
    if (path === "/iron/api/train-images") return reply({ images: {} });
    if (path === "/iron/api/live" && method === "GET") return reply(liveNow ? { live: liveNow, now: new Date().toISOString(), steps: { 卧推: 2.5 } } : { live: null });
    if (path === "/iron/api/live" && method === "PUT") return reply({ live: liveNow });
    if (path === "/iron/api/live/start") return reply({ live });
    if (path === "/iron/api/live/finish") {
      return reply({ summary: { minutes: 6, exercises: 1, sets: 1, volume: 320 }, workout: { id: "w1", line: "上肢：卧推 40×8", celebrate: { prs: [], week: { before: 1, done: 2, planned: 3 } } } });
    }
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("home: today's quest, alert, moves, and 开练 starts with today's plan", async () => {
  await render(<TrainSection />);
  expect(await screen.findByText("今日委托")).toBeTruthy();
  expect(screen.getByText("血压偏高：加大训练前先找医生")).toBeTruthy();
  expect(screen.getByText("周四，练胸和背。")).toBeTruthy();
  expect(screen.getByText("这周练了 1 次，计划 3 次")).toBeTruthy();
  expect(screen.getByText("2×8")).toBeTruthy();
  await fireEvent.press(screen.getByText("开练"));
  const start = seen.find((x) => x.url === "/iron/api/live/start");
  expect(start?.body).toEqual({ today_plan: true });
  expect(mockRouter.push).toHaveBeenCalledWith("/live");
});

it("plan: day strip, items with next target (codes stripped), start button", async () => {
  await render(<PlanPage />);
  expect((await screen.findAllByText("上肢")).length).toBe(2);
  expect(screen.getByText("45 分钟 · 2 个动作")).toBeTruthy();
  expect(screen.getByText("下次 42.5 公斤 × 8")).toBeTruthy();
  expect(screen.getByText("开始训练")).toBeTruthy();
  await fireEvent.press(screen.getByText("划船"));
  expect(await screen.findByText("保存组次")).toBeTruthy();
});

it("live: tick a set, rest starts, finish saves and shows the done card", async () => {
  liveNow = live;
  await render(<LivePage />);
  expect(await screen.findByText("训练中 · 上肢")).toBeTruthy();
  expect(screen.getByText("肩胛收紧")).toBeTruthy();
  expect(screen.queryByText("＋ 加动作")).toBeNull();  // 按计划的不能加动作（§133）
  await fireEvent.press(screen.getByText("完成第 1 组"));
  const put = seen.find((x) => x.method === "PUT");
  expect((put?.body as { items: typeof live.items }).items[0].sets[0].done).toBe(true);
  expect(await screen.findByText("组间休息")).toBeTruthy();
  await fireEvent.press(screen.getByText("结束"));
  await fireEvent.press(screen.getByText("保存这次训练"));
  expect(await screen.findByText("练完了")).toBeTruthy();
  expect(screen.getByText("本周第 2 练，还差 1 练。")).toBeTruthy();
});

it("live: nothing in progress offers to start", async () => {
  await render(<LivePage />);
  expect(await screen.findByText("现在没有进行中的训练。")).toBeTruthy();
});
