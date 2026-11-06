// 首页"今天"（§163）：出错了能重试、重试后旧结果先当作正在看；"今天有点累"只发一次。
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { Text } from "react-native";

import { configureApi, setFetcher } from "@/api/client";
import { heroLine } from "@/features/home/today-logic";
import { TodayVersion, useToday } from "@/features/home/today-version";

const S = { day: 4, name: "上肢", minutes: 45, items: [{ exercise: "卧推", sets: 3, reps: "8" }] };
const SCALED = { ...S, items: [{ exercise: "卧推", sets: 2, reps: "8" }] };
let queue: unknown[] = [];
let seen: string[] = [];

function Page() {
  const today = useToday();
  return (
    <>
      <Text>{heroLine(today.shown)?.text ?? "（没提示）"}</Text>
      <TodayVersion today={today} lib={null} targets={{}} onCheckin={jest.fn()} />
    </>
  );
}

beforeEach(() => {
  jest.useFakeTimers();
  queue = [];
  seen = [];
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push(`${init?.method ?? "GET"} ${path}`);
    const body = path === "/iron/api/coach/retry" ? { status: "reviewing" } : queue.length > 1 ? queue.shift() : queue[0];
    return Promise.resolve({ status: 200, ok: true, json: () => Promise.resolve(body) } as Response);
  });
});
afterEach(() => jest.useRealTimers());

it("coach error → 重试 → old errors read as reviewing → the adjusted version shows", async () => {
  queue = [{ status: "coach_error", original: S }];
  await render(<Page />);
  expect(await screen.findByText("IronM 出错了，还没看今天的情况，下面是原计划")).toBeTruthy();
  expect(screen.getByText("原计划 · 上肢")).toBeTruthy();
  queue = [{ status: "coach_error", original: S }, { status: "ok", original: S, today: SCALED, changed: true, changes: ["每个动作少 1 组"], reasons: ["昨晚睡得少"] }];
  await fireEvent.press(screen.getByText("重试"));
  expect(seen).toContain("POST /iron/api/coach/retry");
  expect(screen.getByText("IronM 正在看今天的情况，下面先列原计划")).toBeTruthy();
  await act(async () => { jest.advanceTimersByTime(5000); });
  expect(screen.getByText("IronM 正在看今天的情况，下面先列原计划")).toBeTruthy();  // 还是旧的"出错了"：先当作正在看
  await act(async () => { jest.advanceTimersByTime(5000); });
  expect(screen.getByText("IronM 调整了今天：每个动作少 1 组")).toBeTruthy();
  expect(screen.getByText("IronM 按你今天的情况调整过 · 为什么")).toBeTruthy();
});

it("今天有点累 is sent once; polling after it goes without parameters", async () => {
  queue = [{ status: "ok", original: S, today: S, changed: false, changes: [], reasons: [] }];
  await render(<Page />);
  expect(await screen.findByText("今天有点累")).toBeTruthy();
  await fireEvent.press(screen.getByText("今天有点累"));
  await fireEvent.press(screen.getByText("今天有点累"));
  await act(async () => { jest.advanceTimersByTime(5000); });
  expect(seen.filter((x) => x.includes("tired=true")).length).toBe(1);
  expect(seen.filter((x) => x === "GET /iron/api/today").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("IronM 正在看今天的情况，下面先列原计划")).toBeTruthy();  // 还是原来的版本：等着
});
