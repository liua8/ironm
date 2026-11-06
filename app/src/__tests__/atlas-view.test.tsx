// 图鉴页面（spec §136、§149、§161）：三段和小标签；动作库按部位收纳、"全部 N 个"展开、搜索时平铺；
// 动作详情"开始训练"带上这个动作开一场再去训练页；器械拍一张认（§164 第四期）；食谱按标签筛、记一餐调对接口。
import { fireEvent, render, screen } from "@testing-library/react-native";
import { router } from "expo-router";
import { Alert } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { configureApi, setFetcher } from "@/api/client";
import Atlas from "@/app/(tabs)/atlas";

jest.mock("expo-router", () => ({ router: { push: jest.fn(), navigate: jest.fn() }, useLocalSearchParams: () => ({}) }));
jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: async () => ({ granted: true, canAskAgain: true }),
  launchCameraAsync: async () => ({ canceled: false, assets: [{ uri: "file:///gym.jpg", width: 800, height: 600 }] }),
}));
jest.mock("expo-image-manipulator", () => {
  const ref = { width: 800, height: 600, saveAsync: async () => ({ uri: "file:///gym-small.jpg", width: 800, height: 600 }) };
  const ctx = { resize: () => ctx, renderAsync: async () => ref };
  return { SaveFormat: { JPEG: "jpeg" }, ImageManipulator: { manipulate: () => ctx } };
});

const ex = (id: string, name: string, part: string, over: object = {}) => ({
  id, name, part, muscles: "肌肉", equipment: ["哑铃"], level: "入门", steps: ["一", "二", "三"], cues: ["稳住", "慢放"],
  mistakes: ["耸肩"], easier: "跪姿", harder: "负重", avoid: "肩伤时", images: [], gif: null, ...over,
});
const LIB = {
  parts: ["胸", "背"],
  equipment: ["哑铃", "徒手"],
  note: "动作资料由 IronM 整理。",
  exercises: [
    ex("a", "哑铃卧推", "胸"), ex("b", "俯卧撑", "胸"), ex("c", "上斜卧推", "胸"), ex("d", "飞鸟", "胸"), ex("e", "夹胸", "胸", { common: false }),
    ex("f", "划船", "背"),
  ],
};
const MACHINES = { machines: [{ id: "m1", name: "坐姿推胸机", aka: ["推胸器"], group: "gym", trains: "胸", setup: ["座椅调到把手齐胸"], careful: ["别锁死肘"], moves: [{ id: "a", name: "哑铃卧推" }], picture: null }] };
const recipe = (id: string, name: string, tags: string[]) => ({
  id, name, tags, servings: 1, parts: [{ food_id: "f", name: "鸡胸肉", grams: 150 }], oil: 5, steps: ["煎熟"], mine: false, image: null,
  per_serving: { kcal: 420, protein_g: 38, carbs_g: 30, fat_g: 10 },
});
const RECIPES = { tags: ["减脂", "增肌", "早餐", "带饭"], recommended: [recipe("r1", "鸡胸沙拉", ["减脂"]), recipe("r2", "燕麦碗", ["早餐"])], mine: [], note: "营养按食物库算" };

const METRICS = { frame: { x: 0, y: 0, width: 375, height: 812 }, insets: { top: 0, left: 0, right: 0, bottom: 0 } };
const page = () => render(<SafeAreaProvider initialMetrics={METRICS}><Atlas /></SafeAreaProvider>);

function reply(body: unknown, status = 200) {
  return Promise.resolve({ status, ok: status < 300, json: () => Promise.resolve(body) } as Response);
}

let seen: { path: string; method: string; body: unknown }[] = [];
let recognized: object = { status: "none" };
let recognizeStatus = 200;

beforeEach(() => {
  seen = [];
  recognized = { status: "none" };
  recognizeStatus = 200;
  (router.navigate as jest.Mock).mockClear();
  jest.spyOn(Alert, "alert").mockImplementation((_t, _m, buttons) => buttons?.[0].onPress?.()); // 拍一张
  (router.push as jest.Mock).mockClear();
  configureApi({ token: () => "tok", onUnauthorized: () => {} });
  setFetcher((url, init) => {
    const method = init?.method ?? "GET";
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    seen.push({ path, method, body: init?.body });
    if (path === "/iron/api/exercises") return reply(LIB);
    if (path === "/iron/api/live") return reply({ live: null });
    if (path === "/iron/api/live/start") return reply({ live: {} });
    if (path === "/iron/api/machines") return reply(MACHINES);
    if (path === "/iron/api/machines/recognize") return reply(recognized, recognizeStatus);
    if (path === "/iron/api/recipes") return reply(RECIPES);
    if (path === "/iron/api/meals" && method === "GET") return reply({ meals: [{ kind: "午餐", name: "牛肉饭" }] });
    if (path.startsWith("/iron/api/recipes/") && method === "POST") return reply({ replaced: ["牛肉饭"], meals: [] });
    return reply({ detail: "没有这个接口" }, 404);
  });
});

afterEach(() => jest.restoreAllMocks());

it("动作库：按部位收纳，全部 N 个展开，搜索时平铺；详情里开始训练", async () => {
  await page();
  expect(await screen.findByText("全部 5 个 ›")).toBeTruthy();
  expect(screen.queryByText("夹胸")).toBeNull(); // 冷门的排在后面，先收起
  await fireEvent.press(screen.getByText("全部 5 个 ›"));
  expect(screen.getByText("夹胸")).toBeTruthy();
  await fireEvent.changeText(screen.getByLabelText("搜索动作"), "划");
  expect(screen.getByText("1 项")).toBeTruthy();
  await fireEvent.press(screen.getByText("划船"));
  expect(await screen.findByText("主要练：肌肉")).toBeTruthy();
  expect(screen.getByText("什么情况先别做：", { exact: false })).toBeTruthy();
  await fireEvent.press(await screen.findByText("开始训练"));
  await screen.findByText("自由训练");
  const start = seen.find((x) => x.path === "/iron/api/live/start");
  expect(JSON.parse(String(start?.body))).toEqual({ exercises: ["划船"] });
  expect(router.push).toHaveBeenCalledWith("/live");
});

it("器械：拍一张认出来，弹出怎么用；和清单同一种时能看图鉴里的", async () => {
  recognized = {
    status: "unsure", name: "推胸机", aka: ["坐推"], trains: "胸", setup: ["把手齐胸"], careful: ["别耸肩"], score: 0.5, match: "m1",
    moves: [{ name: "哑铃卧推", id: "a" }, { name: "器械推胸", id: null }],
  };
  await page();
  await fireEvent.press(await screen.findByText("器械"));
  await fireEvent.press(await screen.findByLabelText("拍一张认器械"));
  expect(await screen.findByText("不太确定，看着像这个；不对的话从清单里找一下。")).toBeTruthy();
  const post = seen.find((x) => x.path === "/iron/api/machines/recognize");
  expect(post?.method).toBe("POST");
  expect((post?.body as FormData).has("photo")).toBe(true);
  expect(screen.getByText("把手齐胸")).toBeTruthy();
  expect(screen.getByText("也叫坐推")).toBeTruthy();
  expect(screen.getByText("图鉴里还没有")).toBeTruthy(); // 动作库里没有的只写名字
  expect(screen.getByText("不太确定，可能是推胸机")).toBeTruthy(); // 关了还能再点开
  await fireEvent.press(screen.getByText("看图鉴里的坐姿推胸机"));
  expect(await screen.findByText("座椅调到把手齐胸")).toBeTruthy();
});

it("器械：没认出来时如实说，引导从清单里找", async () => {
  await page();
  await fireEvent.press(await screen.findByText("器械"));
  await fireEvent.press(await screen.findByLabelText("拍一张认器械"));
  expect(await screen.findByText("照片里没看到健身器械，换个角度再拍一张，或者从下面的清单里找。")).toBeTruthy();
  recognized = { status: "no_model" };
  await fireEvent.press(screen.getByLabelText("拍一张认器械"));
  expect(await screen.findByText("先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。")).toBeTruthy();
  expect(screen.getByText("去填模型")).toBeTruthy();
  recognized = { status: "failed", message: "你填的模型没调通，去「模型和 API」里测试" };
  await fireEvent.press(screen.getByLabelText("拍一张认器械"));
  expect(await screen.findByText("你填的模型没调通，去「模型和 API」里测试")).toBeTruthy();
});

// §167：没填自己的模型服务端回 428，当场说清楚并给"去填模型"，点了到「我」打开模型和 API；清单照常能看
it("器械：没填模型时给去填模型", async () => {
  recognizeStatus = 428;
  recognized = { detail: "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。" };
  await page();
  await fireEvent.press(await screen.findByText("器械"));
  await fireEvent.press(await screen.findByLabelText("拍一张认器械"));
  expect(await screen.findByText("先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。")).toBeTruthy();
  expect(screen.queryByText(/出错|没有成功/)).toBeNull();
  await fireEvent.press(screen.getByText("去填模型"));
  expect(router.navigate).toHaveBeenCalledWith({ pathname: "/me", params: { open: "model" } });
  expect(screen.getByText("坐姿推胸机")).toBeTruthy();
});

it("器械：清单点开能看能练的动作", async () => {
  await page();
  await fireEvent.press(await screen.findByText("器械"));
  expect(await screen.findByText("拍一张认器械")).toBeTruthy();
  expect(screen.getByText("照片会发给识别服务，认完不保存。")).toBeTruthy();
  await fireEvent.press(await screen.findByText("坐姿推胸机"));
  expect(await screen.findByText("座椅调到把手齐胸")).toBeTruthy();
  expect(screen.getByText("也叫推胸器")).toBeTruthy();
  expect(screen.getByText("胸 · 入门")).toBeTruthy();
});

it("食谱：按标签筛，按份数记一餐，提示会替换", async () => {
  await page();
  await fireEvent.press(await screen.findByText("食物"));
  await fireEvent.press(await screen.findByText("食谱"));
  expect(await screen.findByText("鸡胸沙拉")).toBeTruthy();
  await fireEvent.press(screen.getByText("早餐"));
  expect(screen.queryByText("鸡胸沙拉")).toBeNull();
  await fireEvent.press(screen.getByText("燕麦碗"));
  expect(await screen.findByText("原料（1 份的量）")).toBeTruthy();
  await fireEvent.press(screen.getByLabelText("多半份"));
  expect(screen.getByText("吃 1.5 份：约 630 千卡、蛋白质 57 克")).toBeTruthy();
  await fireEvent.press(screen.getAllByText("午餐")[0]);
  expect(await screen.findByText("今天已记过午餐：牛肉饭，记下后会替换。")).toBeTruthy();
  await fireEvent.press(screen.getByText("记下"));
  expect(await screen.findByText("记下了，替换了原来的牛肉饭")).toBeTruthy();
  const log = seen.find((x) => x.path === "/iron/api/recipes/r2/log");
  expect(JSON.parse(String(log?.body))).toEqual({ kind: "午餐", servings: 1.5 });
});
