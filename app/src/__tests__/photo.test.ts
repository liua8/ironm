// 拍照（spec §164 第四期）：压到长边 1600、JPEG 0.85；相机权限只问一次，拒过就直接说怎么开；
// 手机上表单放 { uri, name, type }，网页预览里放 Blob、超过 5MB 不传。
import { Alert, Platform } from "react-native";

import { appendPhoto, choosePhoto, MAX_PHOTO_BYTES, PhotoError, shrink, takePhoto } from "@/lib/photo";

const mockGetPerm = jest.fn();
const mockAskPerm = jest.fn();
const mockCamera = jest.fn();
const mockLibrary = jest.fn();
const mockManipulate = jest.fn();

jest.mock("expo-image-picker", () => ({
  getCameraPermissionsAsync: (...a: unknown[]) => mockGetPerm(...a),
  requestCameraPermissionsAsync: (...a: unknown[]) => mockAskPerm(...a),
  launchCameraAsync: (...a: unknown[]) => mockCamera(...a),
  launchImageLibraryAsync: (...a: unknown[]) => mockLibrary(...a),
}));
jest.mock("expo-image-manipulator", () => ({
  SaveFormat: { JPEG: "jpeg", PNG: "png" },
  ImageManipulator: { manipulate: (...a: unknown[]) => mockManipulate(...a) },
}));

/** 假的压图：记下缩成多大、怎么存。 */
function fakeCtx(w = 4000, h = 3000) {
  const saved: unknown[] = [];
  type Ctx = { resize: jest.Mock; renderAsync: jest.Mock; saved: unknown[] };
  const ctx: Ctx = {
    resize: jest.fn((): Ctx => ctx),
    renderAsync: jest.fn(async () => ({
      width: w,
      height: h,
      saveAsync: async (o: unknown) => {
        saved.push(o);
        return { uri: "file:///small.jpg", width: 1600, height: 1200 };
      },
    })),
    saved,
  };
  mockManipulate.mockReturnValue(ctx);
  return ctx;
}

const shot = (over: object = {}) => ({ canceled: false, assets: [{ uri: "file:///big.heic", width: 4000, height: 3000, mimeType: "image/heic", ...over }] });

beforeEach(() => {
  jest.restoreAllMocks();
  for (const m of [mockGetPerm, mockAskPerm, mockCamera, mockLibrary, mockManipulate]) m.mockReset();
});

it("压到长边 1600、JPEG 0.85，手机上不取 Blob", async () => {
  mockGetPerm.mockResolvedValue({ granted: true, canAskAgain: true });
  mockCamera.mockResolvedValue(shot());
  const ctx = fakeCtx();
  const p = await takePhoto("camera");
  expect(mockManipulate).toHaveBeenCalledWith("file:///big.heic");
  expect(ctx.resize).toHaveBeenCalledWith({ width: 1600 });
  expect(ctx.saved).toEqual([{ compress: 0.85, format: "jpeg" }]);
  expect(p).toEqual({ uri: "file:///small.jpg", type: "image/jpeg", width: 1600, height: 1200, blob: null });
  expect(mockAskPerm).not.toHaveBeenCalled(); // 已经给过就不再问
});

it("竖着的按高缩，本来就小的不缩；系统没给尺寸时先读一次", async () => {
  let ctx = fakeCtx();
  await shrink("file:///a.jpg", 1000, 3000);
  expect(ctx.resize).toHaveBeenCalledWith({ height: 1600 });
  ctx = fakeCtx(800, 600);
  await shrink("file:///b.jpg", 800, 600);
  expect(ctx.resize).not.toHaveBeenCalled();
  ctx = fakeCtx(3200, 2400);
  await shrink("file:///c.jpg", 0, 0);
  expect(ctx.renderAsync).toHaveBeenCalledTimes(2);
  expect(ctx.resize).toHaveBeenCalledWith({ width: 1600 });
});

it("压不了就用原图", async () => {
  mockManipulate.mockImplementation(() => {
    throw new Error("boom");
  });
  expect(await shrink("file:///a.png", 10, 10)).toEqual({ uri: "file:///a.png", type: "", width: 10, height: 10 });
});

it("相机权限：拒过、系统不让再问时不弹，直接说怎么去设置里打开", async () => {
  mockGetPerm.mockResolvedValue({ granted: false, canAskAgain: false });
  await expect(takePhoto("camera")).rejects.toThrow(/设置.*相机/);
  expect(mockAskPerm).not.toHaveBeenCalled();
  expect(mockCamera).not.toHaveBeenCalled();
});

it("相机权限：能问就问一次，这次不给也说怎么开", async () => {
  mockGetPerm.mockResolvedValue({ granted: false, canAskAgain: true });
  mockAskPerm.mockResolvedValue({ granted: false, canAskAgain: false });
  const err = await takePhoto("camera").catch((e: unknown) => e);
  expect(err).toBeInstanceOf(PhotoError);
  expect(mockAskPerm).toHaveBeenCalledTimes(1);
});

it("从相册选不问相机权限；取消时为 null", async () => {
  mockLibrary.mockResolvedValue({ canceled: true, assets: null });
  expect(await takePhoto("library")).toBeNull();
  expect(mockGetPerm).not.toHaveBeenCalled();
  mockLibrary.mockRejectedValue(new Error("denied"));
  await expect(takePhoto("library")).rejects.toThrow(/允许访问照片/);
});

it("手机上先问拍还是选；点外面关掉算取消", async () => {
  const alert = jest.spyOn(Alert, "alert");
  alert.mockImplementationOnce((_t, _m, buttons) => buttons?.[1].onPress?.());
  expect(await choosePhoto()).toBe("library");
  alert.mockImplementationOnce((_t, _m, buttons) => buttons?.[0].onPress?.());
  expect(await choosePhoto()).toBe("camera");
  alert.mockImplementationOnce((_t, _m, _b, opts) => opts?.onDismiss?.());
  expect(await choosePhoto()).toBeNull();
  expect(alert.mock.calls[0][2]?.map((b) => b.text)).toEqual(["拍一张", "从相册选", "取消"]);
});

it("表单：手机上放 { uri, name, type }，网页预览里放 Blob", () => {
  const append = jest.fn();
  const form = { append } as unknown as FormData;
  appendPhoto(form, "photo", { uri: "file:///s.jpg", type: "image/jpeg", width: 1, height: 1, blob: null }, "meal.jpg");
  expect(append).toHaveBeenCalledWith("photo", { uri: "file:///s.jpg", name: "meal.jpg", type: "image/jpeg" });
  const blob = new Blob(["x"], { type: "image/jpeg" });
  appendPhoto(form, "files", { uri: "blob:1", type: "image/jpeg", width: 1, height: 1, blob }, "photo.jpg");
  expect(append).toHaveBeenLastCalledWith("files", blob, "photo.jpg");
});

describe("网页预览", () => {
  beforeEach(() => {
    jest.replaceProperty(Platform, "OS", "web");
  });

  it("不弹框，直接打开浏览器选文件；取回 Blob，超过 5MB 不传", async () => {
    const alert = jest.spyOn(Alert, "alert");
    expect(await choosePhoto()).toBe("library");
    expect(alert).not.toHaveBeenCalled();

    fakeCtx();
    mockLibrary.mockResolvedValue(shot());
    const small = new Blob(["x"], { type: "image/jpeg" });
    const fetchSpy = jest.spyOn(globalThis, "fetch").mockResolvedValue({ blob: async () => small } as Response);
    const p = await takePhoto("library");
    expect(fetchSpy).toHaveBeenCalledWith("file:///small.jpg");
    expect(p?.blob).toBe(small);

    const big = { size: MAX_PHOTO_BYTES + 1, type: "image/jpeg" } as Blob;
    fetchSpy.mockResolvedValue({ blob: async () => big } as Response);
    await expect(takePhoto("library")).rejects.toThrow("照片太大了，换一张试试");
  });
});
