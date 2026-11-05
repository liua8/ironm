// 对话页用到的接口：mirobody 的接口外面包了一层 {code, msg, data}（同网页版 apiData）；
// 发问走流式接口，手机上用 expo/fetch 才能边收边显示（网页预览里 expo/fetch 就是浏览器的 fetch）。
import { fetch as streamFetch } from "expo/fetch";
import { getCalendars } from "expo-localization";

import { api, ApiError } from "@/api/client";
import { API_BASE } from "@/config";
import { appendPhoto, type Photo } from "@/lib/photo";

import { type ChatBlock, parseSseText, readSse } from "./sse";

export async function apiData<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const body = await api<{ code?: number; msg?: string; data?: T }>(path, init);
  if (body.code !== undefined && body.code !== 0) throw new ApiError("invalid", body.msg || "请求没有成功，请再试一次。");
  return (body.data ?? body) as T;
}

/** 出错时给用户看的一句话。 */
export function errorText(err: unknown, fallback = "没有成功，请再试一次。"): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

function timezone(): string {
  try {
    return getCalendars()[0]?.timeZone ?? "";
  } catch {
    return "";
  }
}

/** 传到存储的附件（mirobody /files/upload 回的那几项），发问时原样放进 file_list。 */
export type FileRef = { file_key: string; file_name: string; file_type: string; file_url: string; file_size: number };

/** 对话里拍的一张先传到存储（§152，同网页版 attachPick）：表单字段 files，回 {data:[...]}。 */
export async function uploadPhoto(photo: Photo, name: string): Promise<FileRef> {
  const form = new FormData();
  appendPhoto(form, "files", photo, name);
  const body = await api<{ code?: number; msg?: string; data?: Partial<FileRef>[] }>("/files/upload", { method: "POST", body: form });
  const d = body.data?.[0];
  if (!d?.file_key) throw new ApiError("invalid", "照片没传上，请再试一次。");
  return { file_key: d.file_key, file_name: d.file_name ?? name, file_type: d.file_type ?? "", file_url: d.file_url ?? "", file_size: d.file_size ?? 0 };
}

export type StreamArgs = {
  token: string;
  question: string;
  session: string;
  files?: FileRef[];
  signal: AbortSignal;
  onBlock: (b: ChatBlock) => void;
  onUnauthorized: () => void;
};

/** 发问并一路读回答；停止时抛出的错误由调用方看 signal.aborted 判断。 */
export async function streamChat({ token, question, session, files = [], signal, onBlock, onUnauthorized }: StreamArgs): Promise<void> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Awaited<ReturnType<typeof streamFetch>>;
  try {
    res = await streamFetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers,
      // 附件（§152）：传好的照片原样带上，由这一轮登记和识别
      body: JSON.stringify({
        question,
        session_id: session,
        timezone: timezone(),
        file_list: files.map((f) => ({ file_key: f.file_key, file_name: f.file_name, file_type: f.file_type, file_url: f.file_url, file_size: f.file_size })),
      }),
      signal,
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ApiError("network", "连不上服务，请检查网络后再试。");
  }
  if (res.status === 401 || res.status === 403) {
    onUnauthorized();
    throw new ApiError("unauthorized", "登录已失效，请重新登录。", res.status);
  }
  if (!res.ok) throw new ApiError(res.status >= 500 ? "server" : "invalid", `这次没能回答（${res.status}），请稍后再试。`, res.status);
  if (!(res.headers.get("content-type") || "").includes("event-stream")) {
    const body = (await res.json().catch(() => ({}))) as { msg?: string };
    throw new ApiError("server", body.msg || "这次没能回答，请稍后再试。");
  }
  if (res.body) await readSse(res.body, onBlock);
  else for (const b of parseSseText(await res.text())) onBlock(b); // 不支持边收边读：等全部到了再显示
}
