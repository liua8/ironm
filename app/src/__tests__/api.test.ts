// 第一期（spec §164）：接口客户端带凭证；401 回登录页；出错给中文说明；登录注册的错误码换成中文。
import { mailReady, signInWith, codeReason } from "@/api/auth";
import { api, ApiError, configureApi, isNoModel, NO_MODEL, setFetcher } from "@/api/client";

function reply(status: number, body: unknown) {
  return Promise.resolve({ status, ok: status >= 200 && status < 300, json: () => Promise.resolve(body) } as Response);
}

describe("api client", () => {
  let out = 0;
  let seen: { url: string; init?: RequestInit }[] = [];
  beforeEach(() => {
    out = 0;
    seen = [];
    configureApi({ token: () => "tok", onUnauthorized: () => { out += 1; } });
  });

  it("sends the token and JSON body", async () => {
    setFetcher((url, init) => { seen.push({ url, init }); return reply(200, { ok: 1 }); });
    await api("/iron/api/x", { method: "POST", json: { a: 1 } });
    const h = seen[0].init?.headers as Record<string, string>;
    expect(seen[0].url).toMatch(/\/iron\/api\/x$/);
    expect(h.Authorization).toBe("Bearer tok");
    expect(h["content-type"]).toBe("application/json");
    expect(seen[0].init?.body).toBe('{"a":1}');
  });

  it("goes back to login on 401", async () => {
    setFetcher(() => reply(401, {}));
    await expect(api("/iron/api/me")).rejects.toMatchObject({ kind: "unauthorized" });
    expect(out).toBe(1);
  });

  it("explains failures in Chinese", async () => {
    setFetcher(() => Promise.reject(new Error("offline")));
    await expect(api("/x")).rejects.toThrow("连不上服务，请检查网络后再试。");
    setFetcher(() => reply(422, { detail: "邮箱格式不对" }));
    await expect(api("/x")).rejects.toThrow("邮箱格式不对");
    // 框架自带的英文说明（比如 404 的 "Not Found"）不给用户看
    setFetcher(() => reply(404, { detail: "Not Found" }));
    await expect(api("/x")).rejects.toMatchObject({ kind: "invalid", message: "没有成功，请再试一次。" });
    setFetcher(() => reply(500, {}));
    await expect(api("/x")).rejects.toMatchObject({ kind: "server", message: "服务器出了问题，请稍后再试。" });
  });

  // §167：没填自己的模型时服务端回 428，单独一类 no_model，说明照服务端写的中文
  it("recognizes 428 as no_model", async () => {
    const said = "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。";
    setFetcher(() => reply(428, { detail: said }));
    const e = await api("/iron/api/meals", { method: "POST" }).catch((x: unknown) => x);
    expect(e).toMatchObject({ kind: "no_model", status: 428, message: said });
    expect(isNoModel(e)).toBe(true);
    expect(out).toBe(0);  // 不是凭证失效，不回登录页
    // 没带中文说明也给同一句
    setFetcher(() => reply(428, {}));
    await expect(api("/x")).rejects.toMatchObject({ kind: "no_model", message: NO_MODEL });
    // 别的错不算
    expect(isNoModel(new ApiError("invalid", "x", 422))).toBe(false);
    expect(isNoModel(new Error("x"))).toBe(false);
  });

  it("maps auth error codes", async () => {
    setFetcher(() => reply(200, { code: -3, msg: "Incorrect email or password." }));
    await expect(signInWith("/password/login", { email: "a@b.c", password: "x" })).rejects.toThrow("邮箱或密码不对");
    setFetcher(() => reply(200, { code: -4, msg: "exists" }));
    await expect(signInWith("/password/register", { email: "a@b.c" })).rejects.toThrow("这个邮箱已经注册过，直接登录");
    setFetcher(() => reply(200, { code: 0, data: { access_token: "t1" } }));
    await expect(signInWith("/password/login", { email: "a@b.c", password: "x" })).resolves.toBe("t1");
    setFetcher(() => reply(200, { mail: false }));
    await expect(mailReady()).resolves.toBe(false);
    setFetcher(() => Promise.reject(new Error("x")));
    await expect(mailReady()).resolves.toBeNull();
    expect(new ApiError("invalid", "x").name).toBe("ApiError");
  });
});

describe("code failure reasons (§174)", () => {
  it("says which: wrong, expired, or too many tries", () => {
    expect(codeReason("Invalid code.")).toMatch(/最新一封/);
    expect(codeReason("Code expired.")).toMatch(/过期/);
    expect(codeReason("Too many attempts.")).toMatch(/试错太多次/);
    expect(codeReason("Incorrect email or password.")).toBe("");
  });
});
