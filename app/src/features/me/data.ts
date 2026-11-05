// "我"用到的接口：iron-m 的直接返回；mirobody 的（/api/v1/...）外面包了一层 {code, msg, data}，这里拆开。
import { api, ApiError } from "@/api/client";

export async function apiData<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const body = await api<{ code?: number; msg?: string; data?: T }>(path, init);
  if (body.code !== undefined && body.code !== 0) throw new ApiError("invalid", body.msg || "请求没有成功");
  return (body.data ?? body) as T;
}

/** 去对话页问 IronM 一句（同网页 askCoach）：对话页从 q 参数里取这句话。 */
export function askPath(question: string) {
  return { pathname: "/chat" as const, params: { q: question } };
}
