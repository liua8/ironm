// 拍照接到各处（spec §164 第四期）：拍照记一餐先问哪一餐再传；对话的相机按钮先传 /files/upload、发问带 file_list，
// 传的时候不能发、没写字问"帮我看看这个"；打卡照片在记录存好后传，传不上不影响打卡。
import { fireEvent, render, screen, waitFor } from "@testing-library/react-native";
import { Alert } from "react-native";

import { configureApi, setFetcher } from "@/api/client";
import { streamChat, uploadPhoto } from "@/features/chat/api";
import { Composer } from "@/features/chat/composer";
import type { Attach } from "@/features/chat/store";
import { EatSection } from "@/features/eat/eat";
import { DoneSheet } from "@/features/home/checkin";

const mockGetPerm = jest.fn();
const mockCamera = jest.fn();
const mockStreamFetch = jest.fn();

jest.mock("expo-router", () => ({ router: { push: jest.fn() } }));
jest.mock("expo/fetch", () => ({ fetch: (...a: unknown[]) => mockStreamFetch(...a) }));
jest.mock("expo-localization", () => ({ getCalendars: () => [{ timeZone: "Asia/Shanghai" }] }));
jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: (...a: unknown[]) => mockGetPerm(...a),
  requestCameraPermissionsAsync: jest.fn(),
  launchCameraAsync: (...a: unknown[]) => mockCamera(...a),
  launchImageLibraryAsync: jest.fn(),
}));
jest.mock("expo-image-manipulator", () => {
  const ref = { width: 4000, height: 3000, saveAsync: async () => ({ uri: "file:///small.jpg", width: 1600, height: 1200 }) };
  const ctx = { resize: () => ctx, renderAsync: async () => ref };
  return { SaveFormat: { JPEG: "jpeg" }, ImageManipulator: { manipulate: () => ctx } };
});

function reply(body: unknown, status = 200) {
  return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
}

let seen: { url: string; method: string; body: unknown }[] = [];
let routes: (path: string, method: string) => Promise<Response> | null = () => null;

beforeEach(() => {
  seen = [];
  routes = () => null;
  mockGetPerm.mockReset().mockResolvedValue({ granted: true, canAskAgain: true });
  mockCamera.mockReset().mockResolvedValue({ canceled: false, assets: [{ uri: "file:///big.jpg", width: 4000, height: 3000 }] });
  // 问拍还是选：点"拍一张"
  jest.spyOn(Alert, "alert").mockImplementation((_t, _m, buttons) => buttons?.[0].onPress?.());
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ url: path, method, body: init?.body });
    return routes(path, method) ?? reply({ detail: "没有这个接口" }, 404);
  });
});

afterEach(() => jest.restoreAllMocks());

const posted = (url: string) => waitFor(() => {
  const x = seen.find((s) => s.url === url && s.method === "POST");
  if (!x) throw new Error(`没有发出 ${url}`);
  return x;
});

// ---- 记一餐 ----
const M = (kcal: number) => ({ kcal, protein_g: 0, carbs_g: 0, fat_g: 0 });
const today = { day: "2026-11-05", meals: [], totals: M(0), target: M(2000) };

it("拍照记一餐：拍好先问是哪一餐，带照片和补的一句传", async () => {
  routes = (path, method) => {
    if (path === "/iron/api/meals") return reply(method === "POST" ? { ...today, meals: [{ id: "m1", day: today.day, kind: "晚餐", name: "牛肉面", items: [], macros: M(600) }] } : today);
    if (path === "/iron/api/metrics") return reply({ metrics: [] });
    return null;
  };
  await render(<EatSection />);
  await fireEvent.press(await screen.findByText("拍照记"));
  expect(await screen.findByText("这是哪一餐？")).toBeTruthy();
  expect(screen.getByLabelText("这一餐的照片").props.source).toEqual({ uri: "file:///small.jpg" });
  await fireEvent.changeText(screen.getByLabelText("补一句"), "吃了一半");
  await fireEvent.press(screen.getByRole("radio", { name: "晚餐" }));
  await fireEvent.press(screen.getByText("记下，估算热量"));
  const form = (await posted("/iron/api/meals")).body as FormData;
  expect(form.get("said")).toBe("吃了一半");
  expect(form.get("kind")).toBe("晚餐");
  expect(form.has("photo")).toBe(true);
});

it("拍照记一餐：没给相机权限时在按钮下面说怎么打开", async () => {
  mockGetPerm.mockResolvedValue({ granted: false, canAskAgain: false });
  routes = (path) => (path === "/iron/api/meals" ? reply(today) : path === "/iron/api/metrics" ? reply({ metrics: [] }) : null);
  await render(<EatSection />);
  await fireEvent.press(await screen.findByText("拍照记"));
  expect(await screen.findByText(/没有相机权限.*设置/)).toBeTruthy();
  expect(mockCamera).not.toHaveBeenCalled();
});

// ---- 对话 ----
const REF = { file_key: "k1", file_name: "photo.jpg", file_type: "image/jpeg", file_url: "https://x/k1", file_size: 12 };
const PHOTO = { uri: "file:///small.jpg", type: "image/jpeg", width: 1600, height: 1200, blob: null };

it("对话：照片传到 /files/upload（字段 files），回的那几项原样带进 file_list", async () => {
  routes = (path) => (path === "/files/upload" ? reply({ code: 0, data: [REF] }) : null);
  expect(await uploadPhoto(PHOTO, "photo.jpg")).toEqual(REF);
  expect((seen[0].body as FormData).has("files")).toBe(true);

  routes = (path) => (path === "/files/upload" ? reply({ code: 1, msg: "storage error", data: [] }) : null);
  await expect(uploadPhoto(PHOTO, "photo.jpg")).rejects.toThrow("照片没传上，请再试一次。");

  mockStreamFetch.mockResolvedValue({ status: 200, ok: true, headers: { get: () => "text/event-stream" }, body: null, text: async () => "" });
  await streamChat({ token: "tok", question: "这是什么", session: "s1", files: [REF], signal: new AbortController().signal, onBlock: () => {}, onUnauthorized: () => {} });
  expect(JSON.parse(mockStreamFetch.mock.calls[0][1].body).file_list).toEqual([REF]);
});

async function composer(files: Attach[], value = "") {
  const props = { busy: false, value, onChange: jest.fn(), onSend: jest.fn(), onStop: jest.fn(), onPhoto: jest.fn(), onDrop: jest.fn() };
  return { props, view: await render(<Composer {...props} files={files} />) };
}

it("对话：只有一个相机按钮，拍好交给页面去传", async () => {
  const { props } = await composer([]);
  await screen.findByLabelText("拍一张：吃的、器械都能认");
  expect(screen.queryByLabelText("附图片或报告")).toBeNull();
  await fireEvent.press(screen.getByLabelText("拍一张：吃的、器械都能认"));
  await waitFor(() => expect(props.onPhoto).toHaveBeenCalledWith(expect.objectContaining({ uri: "file:///small.jpg" })));
});

it("对话：传的时候不能发；传好了没写字也能发，问'帮我看看这个'；能去掉", async () => {
  const up = await composer([{ key: "f1", uri: "file:///small.jpg", data: null, error: "" }]);
  expect(await screen.findByText("照片上传中…")).toBeTruthy();
  expect(screen.getByLabelText("发送").props.accessibilityState).toMatchObject({ disabled: true });
  await up.view.unmount();

  const { props } = await composer([{ key: "f1", uri: "file:///small.jpg", data: REF, error: "" }]);
  expect(await screen.findByText("照片传好了")).toBeTruthy();
  await fireEvent.press(screen.getByLabelText("发送"));
  expect(props.onSend).toHaveBeenCalledWith("帮我看看这个");
  await fireEvent.press(screen.getByLabelText("去掉这张照片"));
  expect(props.onDrop).toHaveBeenCalledWith("f1");
});

it("对话：传不上时写明原因", async () => {
  await composer([{ key: "f1", uri: "file:///small.jpg", data: null, error: "连不上服务，请检查网络后再试。" }]);
  expect(await screen.findByText("没传上：连不上服务，请检查网络后再试。")).toBeTruthy();
});

// ---- 打卡照片 ----
async function doneSheet() {
  const onDone = jest.fn();
  return { onDone, view: await render(<DoneSheet open onClose={() => {}} session="上肢" version={null} onDone={onDone} onRest={() => {}} />) };
}

it("打卡照片：记录存好以后传到这次记录上", async () => {
  routes = (path) => {
    if (path === "/iron/api/workouts") return reply({ workout: { id: "w1" } });
    if (path === "/iron/api/workouts/w1/photo") return reply({ ok: true });
    if (path === "/iron/api/brief") return reply({ week: { planned: 3, done: 2 } });
    return null;
  };
  const { onDone } = await doneSheet();
  await fireEvent.press(await screen.findByText("更多：精力、睡眠、哪里酸、照片（可不填）"));
  await fireEvent.press(screen.getByLabelText("拍打卡照片"));
  expect(await screen.findByText("换一张")).toBeTruthy();
  await fireEvent.press(screen.getByText("打卡"));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith("打卡成功。本周第 2 练，继续保持！"));
  const order = seen.filter((x) => x.method === "POST").map((x) => x.url);
  expect(order).toEqual(["/iron/api/workouts", "/iron/api/workouts/w1/photo"]);
  expect((seen.find((x) => x.url === "/iron/api/workouts/w1/photo")?.body as FormData).has("photo")).toBe(true);
});

it("打卡照片：传不上照样打卡，多说一句", async () => {
  routes = (path) => {
    if (path === "/iron/api/workouts") return reply({ workout: { id: "w2" } });
    if (path === "/iron/api/workouts/w2/photo") return reply({ detail: "照片不能超过 5MB" }, 413);
    if (path === "/iron/api/brief") return reply({ week: { planned: 3, done: 1 } });
    return null;
  };
  const { onDone } = await doneSheet();
  await fireEvent.press(await screen.findByText("更多：精力、睡眠、哪里酸、照片（可不填）"));
  await fireEvent.press(screen.getByLabelText("拍打卡照片"));
  await screen.findByText("换一张");
  await fireEvent.press(screen.getByText("打卡"));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith("打卡成功。本周第 1 练，继续保持！照片没传上：照片不能超过 5MB"));
});
