// 手机本地提醒（spec §164 第四期细则第三条）：只用 expo-notifications 在手机上排本地通知，
// 不要推送凭证、不经过 Expo 或任何外部推送服务，服务端不用改。两种：
// - 组间休息到点：开始休息时排一条到点的通知（App 在后台也响），跳过、改时长、结束训练时取消或重排；
// - 训练日提醒：时间自己定、默认关；只按计划里排了训练的那几天排，不在 App 里判断"该不该练"（§164，改不改由模型判断）。
// 网页预览没有本地通知：这里全部空转，设置里写明要在手机 App 里用。
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

import { api } from "@/api/client";
import type { Session, Training } from "@/features/home/types";

/** 这台设备能不能排本地通知：网页预览不能。 */
export const notifySupported = (): boolean => Platform.OS !== "web";

export const WEB_TEXT = "提醒要在手机 App 里用，网页预览里收不到通知。";
export const DENIED_TEXT = "没有通知权限，提醒发不出来。要用的话到手机的「设置 → 通知」里找到 IronM（用 Expo Go 试的就是 Expo Go），打开「允许通知」。";

export type Perm = { ok: true } | { ok: false; why: string };

// 安卓 8 以后声音跟着通知渠道走、建好就改不了：提示音开和关各用一个渠道
const CH_REST = "iron-rest";
const CH_REST_QUIET = "iron-rest-quiet";
const CH_TRAIN = "iron-train";

let ready = false;

/**
 * 只做一次：前台怎么显示、安卓的通知渠道。
 * 组间休息到点时 App 开在前台，页面里的倒计时已经响铃振动，通知就不再弹，免得提醒两遍；
 * 训练日提醒前台没有别的提示，照常弹出。
 */
export async function setupNotifications(): Promise<void> {
  if (ready || !notifySupported()) return;
  ready = true;
  try {
    Notifications.setNotificationHandler({
      handleNotification: async (n) => {
        const quiet = n.request.content.data?.kind === "rest";
        return { shouldShowBanner: !quiet, shouldShowList: !quiet, shouldPlaySound: !quiet, shouldSetBadge: false };
      },
    });
    if (Platform.OS === "android") {
      // 安卓 13 起要先有渠道，系统才会弹出要通知权限的窗
      await Notifications.setNotificationChannelAsync(CH_REST, {
        name: "组间休息到点",
        importance: Notifications.AndroidImportance.HIGH,
        vibrationPattern: [0, 200, 100, 200],
      });
      await Notifications.setNotificationChannelAsync(CH_REST_QUIET, {
        name: "组间休息到点（静音）",
        importance: Notifications.AndroidImportance.HIGH,
        sound: null,
        vibrationPattern: [0, 200, 100, 200],
      });
      await Notifications.setNotificationChannelAsync(CH_TRAIN, {
        name: "训练日提醒",
        importance: Notifications.AndroidImportance.DEFAULT,
      });
    }
  } catch {
    // 渠道没建上不挡训练，下次再试
    ready = false;
  }
}

/**
 * 要通知权限。ask=false 只看不问；系统已经不让再问（用户拒过）时不再弹，如实说去哪里打开。
 */
export async function ensurePermission(ask = true): Promise<Perm> {
  if (!notifySupported()) return { ok: false, why: WEB_TEXT };
  try {
    await setupNotifications();
    const cur = await Notifications.getPermissionsAsync();
    if (cur?.granted) return { ok: true };
    if (!ask || cur?.canAskAgain === false) return { ok: false, why: DENIED_TEXT };
    const got = await Notifications.requestPermissionsAsync({ ios: { allowAlert: true, allowSound: true, allowBadge: false } });
    return got?.granted ? { ok: true } : { ok: false, why: DENIED_TEXT };
  } catch {
    return { ok: false, why: DENIED_TEXT };
  }
}

// 排和取消一条一条接着做：取消不会被前面还没排完的那次盖掉（排完才取消，就不会留下过期的提醒）
let queue: Promise<unknown> = Promise.resolve();
function inOrder<T>(job: () => Promise<T>): Promise<T> {
  const next = queue.then(job, job);
  queue = next.catch(() => undefined);
  return next;
}

// ---- 组间休息到点 ----

export const REST_ID = "iron-rest-end";
// 这次打开 App 只问一次权限：练着练着不反复弹
let restAsked = false;

/**
 * 休息到 endMs 结束：排一条到点的通知（同一时刻只有一条，再排就替换）。
 * sound 跟着训练页右上角的铃铛：关了照样提醒、只是不出声（同网页：铃铛只管声音，振动照旧）。
 */
export function scheduleRestEnd(endMs: number, sound: boolean): Promise<Perm> {
  return inOrder(async () => {
    if (!notifySupported()) return { ok: false, why: WEB_TEXT } as Perm;
    await cancelRestNow();
    const perm = await ensurePermission(!restAsked);
    restAsked = true;
    if (!perm.ok) return perm;
    if (endMs - Date.now() < 1000) return perm;  // 已经到点：页面里的倒计时会响
    try {
      await Notifications.scheduleNotificationAsync({
        identifier: REST_ID,
        content: { title: "组间休息结束", body: "休息到点了，开始下一组。", sound, data: { kind: "rest" } },
        trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: endMs, channelId: sound ? CH_REST : CH_REST_QUIET },
      });
    } catch {
      // 排不上就只靠页面里的倒计时
    }
    return perm;
  });
}

async function cancelRestNow(): Promise<void> {
  try {
    await Notifications.cancelScheduledNotificationAsync(REST_ID);
  } catch {
    // 本来就没有
  }
}

/** 休息跳过、到点、换动作、结束训练、离开训练页：取消还没响的那条。 */
export function cancelRestEnd(): Promise<void> {
  if (!notifySupported()) return Promise.resolve();
  return inOrder(cancelRestNow);
}

// ---- 训练日提醒 ----

export type TrainReminder = { on: boolean; hour: number; minute: number };
/** 默认关；打开时先给晚上 7 点，自己改。 */
export const DEFAULT_TRAIN_REMINDER: TrainReminder = { on: false, hour: 19, minute: 0 };

const KEY = "iron.remind.train";

// 设置只存在这台设备上：手机存安全存储，网页预览存浏览器（同登录凭证的存法）
const store = {
  async get(): Promise<string> {
    if (Platform.OS === "web") {
      try {
        return globalThis.localStorage?.getItem(KEY) ?? "";
      } catch {
        return "";
      }
    }
    try {
      return (await SecureStore.getItemAsync(KEY)) ?? "";
    } catch {
      return "";
    }
  },
  async set(value: string): Promise<void> {
    if (Platform.OS === "web") {
      try {
        globalThis.localStorage?.setItem(KEY, value);
      } catch {
        // 隐私模式：这次记着就行
      }
      return;
    }
    await SecureStore.setItemAsync(KEY, value);
  },
};

const intIn = (v: unknown, lo: number, hi: number): number | null =>
  typeof v === "number" && Number.isInteger(v) && v >= lo && v <= hi ? v : null;

/** 读设置：没存过或读不懂的都按默认（关）。 */
export async function loadTrainReminder(): Promise<TrainReminder> {
  try {
    const raw = JSON.parse((await store.get()) || "{}") as Partial<TrainReminder>;
    return {
      on: raw.on === true,
      hour: intIn(raw.hour, 0, 23) ?? DEFAULT_TRAIN_REMINDER.hour,
      minute: intIn(raw.minute, 0, 59) ?? DEFAULT_TRAIN_REMINDER.minute,
    };
  } catch {
    return { ...DEFAULT_TRAIN_REMINDER };
  }
}

export async function saveTrainReminder(v: TrainReminder): Promise<void> {
  await store.set(JSON.stringify({ on: v.on, hour: v.hour, minute: v.minute }));
}

const WEEK = ["一", "二", "三", "四", "五", "六", "日"];
const pad2 = (n: number) => String(n).padStart(2, "0");
export const hhmm = (v: { hour: number; minute: number }): string => `${pad2(v.hour)}:${pad2(v.minute)}`;

export type TrainSlot = { id: string; weekday: number; hour: number; minute: number; title: string; body: string };

/**
 * 计划里每个训练日排一条每周重复的提醒：计划里没排的那天就没有，不另加规则。
 * 计划 1 = 周一 … 7 = 周日；通知的每周触发 1 = 周日 … 7 = 周六。
 */
export function trainingSlots(sessions: readonly Pick<Session, "day" | "name" | "minutes">[], v: TrainReminder): TrainSlot[] {
  if (!v.on) return [];
  const seen = new Set<number>();
  return sessions
    .filter((x) => intIn(x.day, 1, 7) != null && !seen.has(x.day) && seen.add(x.day))
    .sort((a, b) => a.day - b.day)
    .map((x) => ({
      id: `iron-train-${x.day}`,
      weekday: (x.day % 7) + 1,
      hour: v.hour,
      minute: v.minute,
      title: "训练日提醒",
      body: `按计划今天练「${x.name}」${x.minutes ? `，约 ${x.minutes} 分钟` : ""}。`,
    }));
}

/** 计划里的训练日写成"周一、周三"。 */
export function planDaysText(sessions: readonly Pick<Session, "day">[]): string {
  return [...new Set(sessions.map((x) => x.day))].filter((d) => d >= 1 && d <= 7).sort((a, b) => a - b).map((d) => `周${WEEK[d - 1]}`).join("、");
}

const TRAIN_IDS = [1, 2, 3, 4, 5, 6, 7].map((d) => `iron-train-${d}`);

async function cancelTrainNow(): Promise<void> {
  await Promise.all(TRAIN_IDS.map((id) => Notifications.cancelScheduledNotificationAsync(id).catch(() => undefined)));
}

/**
 * 按设置和计划重排训练日提醒：先全部取消，开着的再按计划的训练日排。
 * 关着或没有计划时只取消。要权限而没有时如实说，不排。
 */
export function scheduleTraining(v: TrainReminder, sessions: readonly Pick<Session, "day" | "name" | "minutes">[]): Promise<Perm> {
  return inOrder(async () => {
    if (!notifySupported()) return { ok: false, why: WEB_TEXT } as Perm;
    await cancelTrainNow();
    const slots = trainingSlots(sessions, v);
    if (!slots.length) return { ok: true } as Perm;
    const perm = await ensurePermission(true);
    if (!perm.ok) return perm;
    for (const x of slots) {
      try {
        await Notifications.scheduleNotificationAsync({
          identifier: x.id,
          content: { title: x.title, body: x.body, sound: true, data: { kind: "train" } },
          trigger: { type: Notifications.SchedulableTriggerInputTypes.WEEKLY, weekday: x.weekday, hour: x.hour, minute: x.minute, channelId: CH_TRAIN },
        });
      } catch {
        // 一天没排上不影响别的天
      }
    }
    return perm;
  });
}

/**
 * 退出登录：取消这台手机上排好的所有提醒，训练日提醒恢复默认（关）。
 * 提醒是按这个人的计划排的，换了账号不该还响。
 */
export function clearReminders(): Promise<void> {
  if (!notifySupported()) return Promise.resolve();
  return inOrder(async () => {
    await cancelRestNow();
    await cancelTrainNow();
    await saveTrainReminder(DEFAULT_TRAIN_REMINDER).catch(() => undefined);
  });
}

/**
 * 读设置和现在的计划，重排训练日提醒（计划改了、回到 App 时调用）。
 * 关着时什么也不读；计划读不到（没网）时保留原来排好的，不清掉。
 */
export async function syncTrainingReminder(): Promise<Perm | null> {
  if (!notifySupported()) return null;
  const v = await loadTrainReminder();
  if (!v.on) return null;
  let tr: Training | null;
  try {
    tr = await api<Training>("/iron/api/training");
  } catch {
    return null;
  }
  return scheduleTraining(v, tr?.plan?.sessions ?? []);
}
