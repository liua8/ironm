// 手机本地提醒（spec §164 第四期细则第三条）：训练日提醒默认关、只按计划的训练日和自己定的时间排；
// 组间休息开始时排到点通知，跳过、改时长、结束训练、离开训练页时取消或重排；网页预览不排、写明要在手机上用。
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Platform } from "react-native";

import { configureApi, setFetcher } from "@/api/client";
import LivePage from "@/app/live";
import { ReminderBox } from "@/features/me/reminders";
import {
  DEFAULT_TRAIN_REMINDER, loadTrainReminder, REST_ID, saveTrainReminder, scheduleRestEnd, scheduleTraining, trainingSlots, WEB_TEXT,
} from "@/lib/notify";

jest.mock("expo-notifications", () => ({
  setNotificationHandler: jest.fn(),
  setNotificationChannelAsync: jest.fn(() => Promise.resolve(null)),
  getPermissionsAsync: jest.fn(() => Promise.resolve({ granted: true, status: "granted", canAskAgain: true })),
  requestPermissionsAsync: jest.fn(() => Promise.resolve({ granted: true, status: "granted", canAskAgain: true })),
  scheduleNotificationAsync: jest.fn((req: { identifier: string }) => Promise.resolve(req.identifier)),
  cancelScheduledNotificationAsync: jest.fn(() => Promise.resolve()),
  SchedulableTriggerInputTypes: { DATE: "date", WEEKLY: "weekly" },
  AndroidImportance: { DEFAULT: 5, HIGH: 6 },
}));
jest.mock("expo-secure-store", () => {
  const mem = new Map<string, string>();
  return {
    __mem: mem,
    getItemAsync: jest.fn((k: string) => Promise.resolve(mem.get(k) ?? null)),
    setItemAsync: jest.fn((k: string, v: string) => { mem.set(k, v); return Promise.resolve(); }),
    deleteItemAsync: jest.fn((k: string) => { mem.delete(k); return Promise.resolve(); }),
  };
});
jest.mock("expo-router", () => ({
  router: { push: jest.fn(), replace: jest.fn(), back: jest.fn(), canGoBack: () => false },
  useFocusEffect: (cb: () => void) => require("react").useEffect(cb, []),
}));

type Req = { identifier: string; content: { sound?: boolean; data?: { kind?: string } }; trigger: { type: string; weekday?: number; hour?: number; minute?: number; date?: number; channelId?: string } };
const N = jest.requireMock<{
  scheduleNotificationAsync: jest.Mock;
  cancelScheduledNotificationAsync: jest.Mock;
  getPermissionsAsync: jest.Mock;
  requestPermissionsAsync: jest.Mock;
}>("expo-notifications");
const mem = jest.requireMock<{ __mem: Map<string, string> }>("expo-secure-store").__mem;
const scheduled = (): Req[] => N.scheduleNotificationAsync.mock.calls.map((c) => c[0] as Req);
const cancelled = (): string[] => N.cancelScheduledNotificationAsync.mock.calls.map((c) => c[0] as string);

// 计划：周一、周三、周五练（1 = 周一 … 7 = 周日）
const sessions = [
  { day: 5, name: "下肢", minutes: 50, items: [{ exercise: "深蹲", sets: 3, reps: "8" }] },
  { day: 1, name: "上肢", minutes: 45, items: [{ exercise: "卧推", sets: 3, reps: "8" }] },
  { day: 3, name: "全身", minutes: 40, items: [{ exercise: "硬拉", sets: 3, reps: "5" }] },
];
const training = { plan: { title: "三分化", days_per_week: 3, sessions }, targets: {}, workouts: [] };
const liveSet = (w: number, r: number) => ({ weight_kg: w, reps: r, seconds: null, done: false, at: null });
const live = {
  id: "L1", started: new Date(Date.now() - 5 * 60000).toISOString(), updated: "", session: "上肢", no_heavier: false,
  items: [{ exercise: "卧推", timed: false, rest: 90, target: "3×8 40 公斤", best: null, plan_kg: 40, sets: [liveSet(40, 8), liveSet(40, 8), liveSet(40, 8)], cardio: false }],
};
const reply = (body: unknown, status = 200) => Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);

let planNow: typeof training = training;
beforeEach(() => {
  jest.clearAllMocks();
  mem.clear();
  planNow = training;
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path === "/iron/api/training") return reply(planNow);
    if (path === "/iron/api/exercises") return reply({ exercises: [] });
    if (path === "/iron/api/live" && method === "GET") return reply({ live: structuredClone(live), now: new Date().toISOString(), steps: {} });
    if (path === "/iron/api/live" && method === "PUT") return reply({ live });
    if (path === "/iron/api/live/finish") return reply({ summary: { minutes: 6, exercises: 1, sets: 1, volume: 320 }, workout: { id: "w1", celebrate: {} } });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

describe("训练日提醒", () => {
  it("默认关：没存过设置就是关，关着不排任何提醒", async () => {
    expect(await loadTrainReminder()).toEqual({ on: false, hour: 19, minute: 0 });
    expect(DEFAULT_TRAIN_REMINDER.on).toBe(false);
    expect(trainingSlots(sessions, DEFAULT_TRAIN_REMINDER)).toEqual([]);
    expect(await scheduleTraining(DEFAULT_TRAIN_REMINDER, sessions)).toEqual({ ok: true });
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();
    expect(N.requestPermissionsAsync).not.toHaveBeenCalled();  // 关着不要权限
  });

  it("只按计划的训练日、自己定的时间排：周一三五 → 每周触发的 2、4、6（1 是周日）", async () => {
    const v = { on: true, hour: 7, minute: 30 };
    expect(trainingSlots(sessions, v).map((x) => [x.weekday, x.hour, x.minute])).toEqual([[2, 7, 30], [4, 7, 30], [6, 7, 30]]);
    expect(trainingSlots([{ day: 7, name: "拉伸", minutes: 20 }], v)[0].weekday).toBe(1);  // 周日
    await scheduleTraining(v, sessions);
    const got = scheduled();
    expect(got).toHaveLength(3);
    expect(got.every((x) => x.trigger.type === "weekly" && x.trigger.hour === 7 && x.trigger.minute === 30)).toBe(true);
    expect(got.map((x) => x.trigger.weekday)).toEqual([2, 4, 6]);
    expect(got[0].content).toMatchObject({ data: { kind: "train" } });
    // 先清掉一周七天原来排的，再排计划里的
    expect(cancelled()).toEqual(expect.arrayContaining([1, 2, 3, 4, 5, 6, 7].map((d) => `iron-train-${d}`)));
  });

  it("设置存在设备上，读回来一样；读不懂的按默认", async () => {
    await saveTrainReminder({ on: true, hour: 6, minute: 45 });
    expect(await loadTrainReminder()).toEqual({ on: true, hour: 6, minute: 45 });
    mem.set("iron.remind.train", "{\"on\":true,\"hour\":99}");
    expect(await loadTrainReminder()).toEqual({ on: true, hour: 19, minute: 0 });
  });

  it("没权限且系统不让再问：不弹窗、不排，如实说去哪里打开", async () => {
    N.getPermissionsAsync.mockResolvedValueOnce({ granted: false, status: "denied", canAskAgain: false });
    const p = await scheduleTraining({ on: true, hour: 19, minute: 0 }, sessions);
    expect(p.ok).toBe(false);
    expect(p.ok ? "" : p.why).toContain("设置");
    expect(N.requestPermissionsAsync).not.toHaveBeenCalled();
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();
  });

  it("设置页：默认关；打开按计划的训练日排，改时间重排，关掉全部取消", async () => {
    await render(<ReminderBox />);
    expect(await screen.findByText("训练日提醒")).toBeTruthy();
    expect(screen.getByText(/关着。打开后按计划里的训练日提醒/)).toBeTruthy();
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();

    await fireEvent.press(screen.getByText("开"));
    await waitFor(() => expect(scheduled()).toHaveLength(3));
    expect(scheduled().map((x) => [x.trigger.weekday, x.trigger.hour, x.trigger.minute])).toEqual([[2, 19, 0], [4, 19, 0], [6, 19, 0]]);
    expect(await screen.findByText("按计划在周一、周三、周五的 19:00 提醒。计划改了，提醒的日子跟着改。")).toBeTruthy();
    expect(await loadTrainReminder()).toEqual({ on: true, hour: 19, minute: 0 });

    N.scheduleNotificationAsync.mockClear();
    await fireEvent.press(screen.getByLabelText("时加"));
    await fireEvent.press(screen.getByLabelText("分减"));
    await waitFor(() => expect(scheduled().slice(-3).map((x) => [x.trigger.hour, x.trigger.minute])).toEqual([[20, 55], [20, 55], [20, 55]]));
    expect(await loadTrainReminder()).toEqual({ on: true, hour: 20, minute: 55 });

    N.scheduleNotificationAsync.mockClear();
    N.cancelScheduledNotificationAsync.mockClear();
    await fireEvent.press(screen.getByText("关"));
    await waitFor(() => expect(cancelled()).toEqual(expect.arrayContaining(["iron-train-1", "iron-train-3", "iron-train-5"])));
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();
    expect((await loadTrainReminder()).on).toBe(false);
  });

  it("没有计划：打开也不排", async () => {
    planNow = { ...training, plan: null as unknown as typeof training.plan };
    await render(<ReminderBox />);
    await fireEvent.press(await screen.findByText("开"));
    expect(await screen.findByText("现在还没有训练计划：有了计划后，按计划里的训练日提醒。")).toBeTruthy();
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();
  });
});

describe("网页预览", () => {
  const os = Platform.OS;
  afterEach(() => { (Platform as { OS: string }).OS = os; });
  it("不排通知，设置里写明要在手机 App 里用", async () => {
    (Platform as { OS: string }).OS = "web";
    expect(await scheduleRestEnd(Date.now() + 60000, true)).toEqual({ ok: false, why: WEB_TEXT });
    expect(await scheduleTraining({ on: true, hour: 19, minute: 0 }, sessions)).toEqual({ ok: false, why: WEB_TEXT });
    expect(N.scheduleNotificationAsync).not.toHaveBeenCalled();
    await render(<ReminderBox />);
    expect(screen.getByText(WEB_TEXT)).toBeTruthy();
    expect(screen.queryByText("开")).toBeNull();
  });
});

describe("组间休息到点", () => {
  const restReqs = () => scheduled().filter((x) => x.identifier === REST_ID);
  const restCancels = () => cancelled().filter((x) => x === REST_ID).length;

  it("打勾开始休息时排到点通知；+15 秒重排；跳过时取消", async () => {
    await render(<LivePage />);
    await fireEvent.press(await screen.findByText("完成第 1 组"));
    expect(await screen.findByText("组间休息中")).toBeTruthy();
    await waitFor(() => expect(restReqs()).toHaveLength(1));
    const first = restReqs()[0];
    expect(first.trigger.type).toBe("date");
    expect(first.trigger.date! - Date.now()).toBeGreaterThan(85000);  // 卧推休息 90 秒
    expect(first.trigger.date! - Date.now()).toBeLessThanOrEqual(90000);
    expect(first.content).toMatchObject({ sound: true, data: { kind: "rest" } });

    await fireEvent.press(screen.getByText("+15 秒"));
    await waitFor(() => expect(restReqs()).toHaveLength(2));
    expect(restReqs()[1].trigger.date! - first.trigger.date!).toBe(15000);

    const before = restCancels();
    await fireEvent.press(screen.getByText("跳过休息"));
    await waitFor(() => expect(restCancels()).toBeGreaterThan(before));
    expect(restReqs()).toHaveLength(2);  // 跳过后不再排
  });

  it("铃铛关了：照样提醒，只是通知不出声", async () => {
    await render(<LivePage />);
    await fireEvent.press(await screen.findByText("完成第 1 组"));
    await waitFor(() => expect(restReqs()).toHaveLength(1));
    await fireEvent.press(screen.getByLabelText("提示音"));
    await waitFor(() => expect(restReqs()).toHaveLength(2));
    expect(restReqs()[1].content.sound).toBe(false);
    await fireEvent.press(screen.getByLabelText("提示音"));  // 还原，别影响后面的用例
    await waitFor(() => expect(restReqs()).toHaveLength(3));
  });

  it("休息中保存结束训练：取消到点通知", async () => {
    await render(<LivePage />);
    await fireEvent.press(await screen.findByText("完成第 1 组"));
    await waitFor(() => expect(restReqs()).toHaveLength(1));
    const before = restCancels();
    await fireEvent.press(screen.getByText("结束训练"));
    await fireEvent.press(screen.getByText("保存这次训练"));
    await waitFor(() => expect(restCancels()).toBeGreaterThan(before));
    expect(restReqs()).toHaveLength(1);
  });

  it("离开训练页：取消到点通知", async () => {
    const view = await render(<LivePage />);
    await fireEvent.press(await screen.findByText("完成第 1 组"));
    await waitFor(() => expect(restReqs()).toHaveLength(1));
    const before = restCancels();
    await act(async () => { await view.unmount(); });
    await waitFor(() => expect(restCancels()).toBeGreaterThan(before));
  });
});
