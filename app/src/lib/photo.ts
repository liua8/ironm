// 拍照（spec §164 第四期）：拍一张或从相册选，传之前压到长边 1600、JPEG 0.85（同网页版 shrinkPhoto），
// 记一餐、对话拍一张、认器械、打卡照片共用。
// 手机上 FormData 的文件写成 { uri, name, type } 由系统读文件；网页预览里没有这种写法，要先取成真正的 Blob。
// 没给相机权限时只问一次：系统说不能再问了就直接说怎么去设置里打开，不反复弹。
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";
import { Alert, Platform } from "react-native";

export const LONG_EDGE = 1600;
export const QUALITY = 0.85;
export const MAX_PHOTO_BYTES = 5 * 1024 * 1024; // 服务端照片上限 5MB

export type PhotoSource = "camera" | "library";

/** 压好、能直接放进 FormData 的一张照片。 */
export type Photo = {
  uri: string; // 本机能显示的地址（预览小图用）
  type: string;
  width: number;
  height: number;
  blob: Blob | null; // 只有网页预览里有
};

/** 选照片时出的问题：说明能直接给用户看。 */
export class PhotoError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PhotoError";
  }
}

const CAMERA_DENIED =
  "没有相机权限，拍不了照。请到手机的「设置」里找到这个 App（用 Expo Go 调试时是 Expo Go），把「相机」打开后再试；也可以选「从相册选」。";
const LIBRARY_FAILED = "相册没有打开。请到手机的「设置」里找到这个 App（用 Expo Go 调试时是 Expo Go），允许访问照片后再试。";
const OPEN_FAILED = "这次没能打开相机或相册，请再试一次。";
export const TOO_BIG = "照片太大了，换一张试试";

/** 相机权限：已给就用；能问就问一次；系统不让再问了（用户拒过）就直接说怎么开。 */
async function cameraAllowed(): Promise<void> {
  const now = await ImagePicker.getCameraPermissionsAsync();
  if (now.granted) return;
  if (!now.canAskAgain) throw new PhotoError(CAMERA_DENIED);
  const asked = await ImagePicker.requestCameraPermissionsAsync();
  if (!asked.granted) throw new PhotoError(CAMERA_DENIED);
}

/** 拍还是从相册选。网页预览里没有弹框（Alert 什么都不做），直接用浏览器选文件，手机浏览器自己会给"拍照"。 */
export function choosePhoto(title = "照片"): Promise<PhotoSource | null> {
  if (Platform.OS === "web") return Promise.resolve("library");
  return new Promise((done) => {
    Alert.alert(
      title,
      undefined,
      [
        { text: "拍一张", onPress: () => done("camera") },
        { text: "从相册选", onPress: () => done("library") },
        { text: "取消", style: "cancel", onPress: () => done(null) },
      ],
      { cancelable: true, onDismiss: () => done(null) },
    );
  });
}

/** 压到长边 1600、JPEG；压不了就用原图（同网页版）。 */
export async function shrink(uri: string, width: number, height: number): Promise<{ uri: string; type: string; width: number; height: number }> {
  try {
    const ctx = ImageManipulator.manipulate(uri);
    let w = width;
    let h = height;
    if (!w || !h) {
      // 系统没给尺寸：先读一次才知道要不要缩
      const ref0 = await ctx.renderAsync();
      w = ref0.width;
      h = ref0.height;
    }
    if (Math.max(w, h) > LONG_EDGE) ctx.resize(w >= h ? { width: LONG_EDGE } : { height: LONG_EDGE });
    const ref = await ctx.renderAsync();
    const out = await ref.saveAsync({ compress: QUALITY, format: SaveFormat.JPEG });
    return { uri: out.uri, type: "image/jpeg", width: out.width, height: out.height };
  } catch {
    return { uri, type: "", width, height };
  }
}

/** 拍或选一张，压好；用户取消时为 null。出问题抛 PhotoError（中文说明）。 */
export async function takePhoto(from: PhotoSource): Promise<Photo | null> {
  if (from === "camera" && Platform.OS !== "web") await cameraAllowed();
  let got: ImagePicker.ImagePickerResult;
  try {
    const opts: ImagePicker.ImagePickerOptions = { mediaTypes: ["images"], quality: 1, allowsEditing: false, exif: false };
    got = from === "camera" ? await ImagePicker.launchCameraAsync(opts) : await ImagePicker.launchImageLibraryAsync(opts);
  } catch {
    throw new PhotoError(from === "library" ? LIBRARY_FAILED : OPEN_FAILED);
  }
  const asset = got.canceled ? null : got.assets?.[0];
  if (!asset) return null;
  const small = await shrink(asset.uri, asset.width, asset.height);
  const type = small.type || asset.mimeType || "image/jpeg";
  if (Platform.OS !== "web") {
    // 没压成功时只有系统给的大小可查；压过的远小于 5MB
    if (!small.type && asset.fileSize && asset.fileSize > MAX_PHOTO_BYTES) throw new PhotoError(TOO_BIG);
    return { uri: small.uri, type, width: small.width, height: small.height, blob: null };
  }
  let blob: Blob;
  try {
    blob = await (await fetch(small.uri)).blob();
  } catch {
    throw new PhotoError(OPEN_FAILED);
  }
  if (blob.size > MAX_PHOTO_BYTES) throw new PhotoError(TOO_BIG);
  return { uri: small.uri, type: blob.type || type, width: small.width, height: small.height, blob };
}

/** 先问拍还是选，再拍或选。取消时为 null。 */
export async function getPhoto(title?: string): Promise<Photo | null> {
  const from = await choosePhoto(title);
  return from ? takePhoto(from) : null;
}

/** 照片放进表单：网页预览里放 Blob；手机上放 { uri, name, type }，由系统读文件上传。 */
export function appendPhoto(form: FormData, field: string, photo: Photo, name: string): void {
  if (photo.blob) form.append(field, photo.blob, name);
  else form.append(field, { uri: photo.uri, name, type: photo.type || "image/jpeg" } as unknown as Blob);
}

export const photoErrText = (e: unknown) => (e instanceof Error && e.message ? e.message : OPEN_FAILED);
