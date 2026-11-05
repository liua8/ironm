// 注册和登录（同网页 spec §155）：底座回的是错误码和英文，这里按错误码换成中文。
import { api, ApiError } from "./client";

type Reply = { code?: number; msg?: string; data?: { access_token?: string } };

const ERRORS: Record<string, Record<string, string>> = {
  "/password/register": { "-2": "邮箱格式不对", "-3": "密码至少 8 位", "-5": "先填邮箱收到的验证码", "-6": "验证码不对或已过期", "-4": "这个邮箱已经注册过，直接登录" },
  "/password/login": { "-2": "填一下邮箱和密码", "-3": "邮箱或密码不对" },
  "/password/reset": { "-2": "填一下邮箱和验证码", "-3": "密码至少 8 位", "-6": "验证码不对或已过期", "-7": "邮件服务还没配好，暂时不能找回密码" },
  "/email/verify": {},
};
const NO_MAIL = "邮件服务还没配好，暂时发不了验证码";

function failed(path: string, r: Reply): string {
  const msg = String(r.msg ?? "");
  return ERRORS[path]?.[String(r.code)] ?? (/SMTP|mail/i.test(msg) ? NO_MAIL : path === "/email/verify" ? "验证码不对或已过期" : "没有成功，稍后再试");
}

/** 登录、注册、重设密码、验证码登录：成功返回登录凭证。 */
export async function signInWith(path: keyof typeof ERRORS, body: Record<string, string>): Promise<string> {
  const r = await api<Reply>(path, { method: "POST", json: body });
  if (r.code !== undefined && r.code !== 0) throw new ApiError("invalid", failed(path, r));
  const token = r.data?.access_token;
  if (!token) throw new ApiError("server", "没有成功，稍后再试");
  return token;
}

/** 发验证码（注册、找回密码、验证码登录共用）。 */
export async function sendCode(email: string): Promise<void> {
  const r = await api<Reply>("/email/login", { method: "POST", json: { email } });
  if (r.code !== undefined && r.code !== 0) throw new ApiError("invalid", /SMTP|mail/i.test(String(r.msg)) ? NO_MAIL : "验证码没发出去，稍后再试");
}

/** 发信服务配好了没有：没配时注册和找回密码如实说不能用。读不到当作不知道（null）。 */
export async function mailReady(): Promise<boolean | null> {
  try {
    return Boolean((await api<{ mail: boolean }>("/iron/api/auth/options")).mail);
  } catch {
    return null;
  }
}
