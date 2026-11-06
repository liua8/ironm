// 战绩整页和训练时间线（spec §137、§139、§147）：读对接口，这周、日历、成就、时间线入口、周报都画出来；点日子看记录；翻月取那个月。
import { fireEvent, render, screen } from "@testing-library/react-native";

import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Record from "@/app/(tabs)/record";
import Timeline from "@/app/timeline";

jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: () => false },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
  Redirect: () => null,
}));
jest.mock("react-native-view-shot", () => ({ captureRef: jest.fn(async () => "file:///card.png") }));
jest.mock("expo-sharing", () => ({ isAvailableAsync: jest.fn(async () => true), shareAsync: jest.fn(async () => {}) }));
jest.mock("@/auth/session", () => ({ useSession: () => ({ ready: true, token: "tok", signIn: jest.fn(), signOut: jest.fn() }) }));
const mockRouter = jest.requireMock<{ router: { push: jest.Mock } }>("expo-router").router;

const today = new Date();
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const todayIso = iso(today);
const month = todayIso.slice(0, 7);

const workouts = [
  { id: 2, day: todayIso, session: "下肢", done: true, minutes: 40, rpe: 7, items: [{ exercise: "深蹲", done_sets: [{ weight_kg: 70, reps: 5 }] }], photo: true },
  { id: 1, day: iso(new Date(today.getFullYear(), today.getMonth(), today.getDate() - 40)), session: "下肢", done: true, items: [{ exercise: "深蹲", done_sets: [{ weight_kg: 60, reps: 5 }] }] },
];
const cal = {
  month,
  today: todayIso,
  days: { [todayIso]: [{ id: 2, done: true, line: "下肢：深蹲 70×5" }] },
  done_days: [todayIso],
  rest_days: [],
  sets: { [todayIso]: 6 },
  month_minutes: 40,
  streak_days: 3,
  week: { rpe: 7 },
};
const report = { from: "2026-10-26", to: "2026-11-01", done: 2, planned: 3, minutes: 90, sets: 30, volume_kg: 800, records: [], weight: null, diet: null, rpe: null, focus: "照计划来，保持节奏。" };

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = (el: React.ReactElement) => render(<SafeAreaProvider initialMetrics={METRICS}>{el}</SafeAreaProvider>);

let seen: string[] = [];
beforeEach(() => {
  seen = [];
  mockRouter.push.mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url) => {
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push(path);
    const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
    if (path === "/iron/api/brief") return reply({ week: { planned: 3, done: 1 } });
    if (path === "/iron/api/calendar") return reply(cal);
    if (path.startsWith("/iron/api/calendar?month=")) return reply({ ...cal, month: path.slice(-7), days: {}, done_days: [], month_minutes: 0 });
    if (path === "/iron/api/training") return reply({ workouts });
    if (path === "/iron/api/report/week") return reply(report);
    if (path === "/iron/api/exercises") return reply({ exercises: [{ name: "深蹲", part: "腿臀" }] });
    if (path === "/iron/api/train-images") return reply({ images: { 腿臀: { url: "/iron/api/food-images/legs.jpg", author: "某摄影师", page: "" } } });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("record: this week, calendar, PR, timeline entry and last week's report", async () => {
  await page(<Record />);
  expect(await screen.findByText("这周表现")).toBeTruthy();  // §176 三格：已练次数 1/3
  expect(screen.getByText("1/3次")).toBeTruthy();
  expect(screen.getByText(/连续打卡 3 天，平均感受 7.0 分/)).toBeTruthy();
  expect(screen.queryByText("IronM 这周的建议")).toBeNull();  // 规则的每周建议不再有（§182）
  expect(screen.getByText("本月练了 1 天，共 40 分钟。")).toBeTruthy();
  expect(screen.getByText("70 kg × 5")).toBeTruthy();
  expect(screen.getByText("破 PR")).toBeTruthy();
  expect(screen.getByText(/最近一次：.*，下肢/)).toBeTruthy();
  expect(screen.getByText("上周周报")).toBeTruthy();
  expect(screen.getByText("照计划来，保持节奏。")).toBeTruthy();

  await fireEvent.press(screen.getByLabelText(new RegExp(`${today.getDate()}日，练过 6 组，点开看记录`)));
  expect(await screen.findByText("下肢：深蹲 70×5")).toBeTruthy();

  await fireEvent.press(screen.getByLabelText("上个月"));
  expect(await screen.findByText(/月练了 0 天，共 0 分钟。/)).toBeTruthy();
  expect(seen.some((p) => p.startsWith("/iron/api/calendar?month="))).toBe(true);

  await fireEvent.press(screen.getByLabelText("训练时间线，点开看每一次训练"));
  expect(mockRouter.push).toHaveBeenCalledWith("/timeline");
});

it("timeline: a card per workout with the check-in or part photo, facts, moves and share", async () => {
  await page(<Timeline />);
  expect(await screen.findByText("40 分钟，1 组，感受 7 分")).toBeTruthy();
  expect(screen.getAllByText("下肢")).toHaveLength(2);
  expect(screen.getAllByText(/^\d+月\d+日$/)).toHaveLength(2);
  // 有打卡照片的那次配打卡照片（带凭证取），另一次配部位的训练照片（同网页 timelinePage）
  expect(screen.getAllByText("照片：某摄影师")).toHaveLength(1);
  const shot = screen.getByLabelText("打卡照片");
  expect(shot.props.source).toMatchObject({ uri: expect.stringContaining("/iron/api/workouts/2/photo"), headers: { Authorization: "Bearer tok" } });
  expect(screen.getAllByText("深蹲")).toHaveLength(2);
  // 每张卡下面"晒一下"：打开这次训练的分享卡
  expect(screen.getAllByText("晒一下")).toHaveLength(2);
  await fireEvent.press(screen.getAllByText("晒一下")[0]);
  expect(await screen.findByText("没有这个接口")).toBeTruthy();
  expect(seen.some((p) => p.startsWith("/iron/api/share/workout/"))).toBe(true);
});
