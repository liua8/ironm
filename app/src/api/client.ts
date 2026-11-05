// 和服务端说话的唯一入口（spec §164 第一期）：带上登录凭证；凭证失效（401、403）交给会话回到登录页；
// 失败一律变成 ApiError，说明能直接显示给用户，不带凭证和用户填的内容。
// 428：要用模型的功能，这个人还没在「我 → 模型和 API」填自己的模型（spec §167 每个人用自己的模型），
// 单独一类 no_model，页面据此多给一个"去填模型"。
import { API_BASE } from "@/config";

export type ApiErrorKind = "network" | "unauthorized" | "invalid" | "server" | "no_model";

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const NETWORK = "连不上服务，请检查网络后再试。";
const SERVER = "服务器出了问题，请稍后再试。";
export const NO_MODEL = "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。";

/** 这次失败是不是因为还没填自己的模型（服务端回 428）。 */
export const isNoModel = (e: unknown): e is ApiError => e instanceof ApiError && e.kind === "no_model";

type Hooks = { token: () => string; onUnauthorized: () => void };
let hooks: Hooks = { token: () => "", onUnauthorized: () => {} };

/** 会话启动时登记：从哪拿凭证、凭证失效时怎么办。 */
export function configureApi(next: Hooks): void {
  hooks = next;
}

export type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;
let fetcher: Fetcher = (input, init) => fetch(input, init);

/** 测试时换成假的。 */
export function setFetcher(next: Fetcher): void {
  fetcher = next;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> | undefined) };
  const token = hooks.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let res: Response;
  try {
    res = await fetcher(`${API_BASE}${path}`, { ...init, headers, body });
  } catch {
    throw new ApiError("network", NETWORK);
  }
  if (res.status === 401 || res.status === 403) {
    hooks.onUnauthorized();
    throw new ApiError("unauthorized", "登录已失效，请重新登录。", res.status);
  }
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    // 只透传服务端写给用户的中文说明；框架自带的英文（"Not Found" 之类）换成中文兜底
    const detail = typeof data.detail === "string" && /[\u4e00-\u9fff]/.test(data.detail) ? data.detail : "";
    if (res.status === 428) throw new ApiError("no_model", detail || NO_MODEL, res.status);
    throw new ApiError(res.status >= 500 ? "server" : "invalid", detail || (res.status >= 500 ? SERVER : "没有成功，请再试一次。"), res.status);
  }
  return data as T;
}
