// 晒一下和周报存图（spec §147、§164 第四期）：卡上写对字、去掉〔K..〕；手机上截图后交给系统分享；
// 不能分享（网页预览、手机不支持）时只显示卡片和一句说明，不给点了没反应的按钮。
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Platform } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Record from "@/app/(tabs)/record";
import LivePage from "@/app/live";
import { weekCard, workoutCard, type WorkoutShare as Share } from "@/features/share/logic";
import { WeekShare, WorkoutShare } from "@/features/share/share";

jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: () => false },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
  Redirect: () => null,
}));
jest.mock("@/auth/session", () => ({ useSession: () => ({ ready: true, token: "tok", signIn: jest.fn(), signOut: jest.fn() }) }));
jest.mock("react-native-view-shot", () => ({ captureRef: jest.fn(() => Promise.resolve("file:///tmp/card.png")) }));
jest.mock("expo-sharing", () => ({ isAvailableAsync: jest.fn(() => Promise.resolve(true)), shareAsync: jest.fn(() => Promise.resolve()) }));

const shot = jest.requireMock<{ captureRef: jest.Mock }>("react-native-view-shot");
const sharing = jest.requireMock<{ isAvailableAsync: jest.Mock; shareAsync: jest.Mock }>("expo-sharing");

const card: Share = {
  id: "w1",
  photo: false,
  day: "2026-11-05",
  session: "上肢〔K03〕",
  minutes: 48,
  sets: 12,
  volume_kg: 2350,
  moves: ["卧推", "划船"],
  records: [{ exercise: "卧推", weight_kg: 60, reps: 5 }],
  streak_days: 3,
  rpe: 7,
};
const report = {
  from: "2026-10-26", to: "2026-11-01", done: 2, planned: 3, minutes: 90, sets: 30, volume_kg: 800,
  records: [], weight: { from: 70.2, to: 69.8, change: -0.4 }, diet: null, rpe: null, focus: "照计划来，保持节奏〔K12〕",
};
const today = new Date();
const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
const cal = { month: todayIso.slice(0, 7), today: todayIso, days: {}, done_days: [], rest_days: [], sets: {}, month_minutes: 0, streak_days: 0, week: {} };
const live = {
  id: "L1", started: new Date(Date.now() - 5 * 60000).toISOString(), updated: "", session: "上肢", no_heavier: false,
  items: [{ exercise: "卧推", timed: false, rest: 90, target: "1×8 40 公斤", best: null, plan_kg: 40, sets: [{ weight_kg: 40, reps: 8, seconds: null, done: true, at: null }], cardio: false }],
};

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = (el: React.ReactElement) => render(<SafeAreaProvider initialMetrics={METRICS}>{el}</SafeAreaProvider>);

let seen: string[] = [];
let shareReply: { body: unknown; status: number } = { body: card, status: 200 };
beforeEach(() => {
  seen = [];
  shareReply = { body: card, status: 200 };
  shot.captureRef.mockClear();
  sharing.shareAsync.mockClear();
  sharing.isAvailableAsync.mockImplementation(() => Promise.resolve(true));
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const method = init?.method ?? "GET";
    seen.push(path);
    const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
    if (path === "/iron/api/share/workout/w1") return reply(shareReply.body, shareReply.status);
    if (path === "/iron/api/report/week") return reply(report);
    if (path === "/iron/api/brief") return reply({ week: { planned: 3, done: 1 } });
    if (path === "/iron/api/calendar") return reply(cal);
    if (path === "/iron/api/training") return reply({ workouts: [] });
    if (path === "/iron/api/exercises") return reply({ exercises: [{ id: "bench", name: "卧推", part: "胸", muscles: "胸大肌", equipment: ["杠铃"], cues: [] }] });
    if (path === "/iron/api/train-images") return reply({ images: {} });
    if (path === "/iron/api/live" && method === "GET") return reply({ live, now: new Date().toISOString(), steps: {} });
    if (path === "/iron/api/live" && method === "PUT") return reply({ live });
    if (path === "/iron/api/live/finish") {
      return reply({ summary: { minutes: 6, exercises: 1, sets: 1, volume: 320 }, workout: { id: "w1", line: "上肢：卧推 40×8", celebrate: { prs: [], week: { before: 1, done: 2, planned: 3 } } } });
    }
    return reply({ detail: "没有这个接口" }, 404);
  });
});

it("logic: workout card mirrors the web card, codes stripped, tons over 1000 kg", () => {
  const c = workoutCard(card);
  expect(c.title).toBe("委托完成");
  expect(c.date).toBe("11月5日");
  expect(c.head).toBe("上肢");
  expect(c.sub).toBe("感受 7 分");
  expect(c.stats).toEqual([
    { name: "时长", value: "48", unit: "分钟" },
    { name: "组数", value: "12", unit: "组" },
    { name: "总重量", value: "2.4", unit: "吨" },
  ]);
  expect(c.lines.map((x) => x.text)).toEqual(["破纪录：卧推 60 公斤 × 5", "连续打卡 3 天", "卧推、划船"]);
  expect(c.lines[0].red).toBe(true);

  const empty = workoutCard({ ...card, minutes: null, sets: 0, volume_kg: 0, records: [], streak_days: 1, moves: [], rpe: null });
  expect(empty.stats.map((x) => [x.value, x.unit])).toEqual([["—", ""], ["—", ""], ["—", ""]]);
  expect(empty.lines).toEqual([]);
  expect(empty.sub).toBe("");
});

it("logic: week card has the plan count, weight change and next week's focus", () => {
  const c = weekCard(report);
  expect(c.title).toBe("上周周报");
  expect(c.date).toBe("10月26日–11月1日");
  expect(c.head).toBe("练了 2 次，计划 3 次");
  expect(c.stats[2]).toEqual({ name: "总重量", value: "800", unit: "公斤" });
  expect(c.lines.map((x) => x.text)).toEqual(["体重 70.2 → 69.8 公斤（-0.4）", "下周重点：照计划来，保持节奏"]);
  expect(c.foot).toBe("每周一出上周的周报");
});

it("finish: 晒一下 opens the card in the same sheet, captures it and hands the PNG to the system share", async () => {
  await render(<LivePage />);
  await fireEvent.press(await screen.findByText("结束"));
  await fireEvent.press(screen.getByText("保存这次训练"));
  await fireEvent.press(await screen.findByText("晒一下"));
  expect(await screen.findByText("委托完成")).toBeTruthy();
  expect(seen).toContain("/iron/api/share/workout/w1");
  expect(screen.getByText("破纪录：卧推 60 公斤 × 5")).toBeTruthy();
  expect(screen.queryByText(/〔/)).toBeNull();
  expect(screen.queryByText(/第四期/)).toBeNull();

  await fireEvent.press(await screen.findByText("存成图片 / 分享"));
  await waitFor(() => expect(sharing.shareAsync).toHaveBeenCalledWith("file:///tmp/card.png", expect.objectContaining({ mimeType: "image/png" })));
  expect(shot.captureRef).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ format: "png", result: "tmpfile" }));

  await fireEvent.press(screen.getByText("‹ 返回练完的卡"));
  expect(await screen.findByText("本周第 2 练，还差 1 练。")).toBeTruthy();
});

it("workout share: photo toggle when there is a check-in photo; load error is shown", async () => {
  shareReply = { body: { ...card, photo: true }, status: 200 };
  const { unmount } = await render(<WorkoutShare id="w1" />);
  expect(await screen.findByLabelText("打卡照片")).toBeTruthy();
  await fireEvent.press(screen.getByRole("checkbox"));
  expect(screen.queryByLabelText("打卡照片")).toBeNull();
  await unmount();

  shareReply = { body: { detail: "没有这次训练" }, status: 404 };
  await render(<WorkoutShare id="w1" />);
  expect(await screen.findByText("没有这次训练")).toBeTruthy();
});

it("record: 上周周报 存成图片 opens the week card and shares it", async () => {
  await page(<Record />);
  await fireEvent.press(await screen.findByText("存成图片"));
  expect(await screen.findByText("下周重点：照计划来，保持节奏")).toBeTruthy();
  expect(screen.queryByText(/第四期/)).toBeNull();
  await fireEvent.press(await screen.findByText("存成图片 / 分享"));
  await waitFor(() => expect(sharing.shareAsync).toHaveBeenCalledTimes(1));
});

it("no system share on this phone: card only, with a line saying why", async () => {
  sharing.isAvailableAsync.mockImplementation(() => Promise.resolve(false));
  await render(<WeekShare r={report} />);
  expect(await screen.findByText(/这台手机不支持系统分享/)).toBeTruthy();
  expect(screen.queryByText("存成图片 / 分享")).toBeNull();
  expect(screen.getByText("上周周报")).toBeTruthy();
});

it("web preview: no capture, no share button, says to share from the phone app", async () => {
  jest.replaceProperty(Platform, "OS", "web");
  sharing.isAvailableAsync.mockClear();
  try {
    await render(<WeekShare r={report} />);
    expect(await screen.findByText(/网页预览里不能存图和分享/)).toBeTruthy();
    expect(screen.queryByText("存成图片 / 分享")).toBeNull();
    expect(sharing.isAvailableAsync).not.toHaveBeenCalled();
    expect(shot.captureRef).not.toHaveBeenCalled();
  } finally {
    jest.restoreAllMocks();
  }
});
