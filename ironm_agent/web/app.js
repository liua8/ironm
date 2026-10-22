// IronM 功能页：首页、动作、饮食、数据、我的。只调用 mirobody 与 iron-m 的接口，不加载外部资源。
"use strict";

const KEY = "iron.token";
const store = {
  get() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } },
  set(v) { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* 隐私模式 */ } },
};
let cache = { metrics: null, profile: null };

// ---- 小工具 -------------------------------------------------------------------------------
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const headers = { "content-type": "application/json", ...(opts.headers || {}) };
  const token = store.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 || res.status === 403) { store.set(""); render(); throw new Error("登录已失效，请重新登录"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.msg || `请求失败（${res.status}）`);
  return body;
}

async function metrics(force = false) {
  if (!cache.metrics || force) cache.metrics = await api("/iron/api/metrics");
  return cache.metrics;
}
async function profile(force = false) {
  if (!cache.profile || force) cache.profile = await api("/iron/api/profile");
  return cache.profile;
}
function byKey(list) { return Object.fromEntries(list.metrics.map((m) => [m.key, m])); }

function num(v) {
  if (v == null) return "";
  return Math.abs(v) >= 100 ? Math.round(v).toLocaleString("zh-CN") : String(Math.round(v * 100) / 100);
}

// ---- 指标卡 -------------------------------------------------------------------------------
function spark(series) {
  if (!series || series.length < 2) return null;
  const vs = series.map((p) => p[1]);
  const lo = Math.min(...vs), hi = Math.max(...vs), span = hi - lo || 1;
  const pts = vs.map((v, i) => `${(i / (vs.length - 1)) * 100},${36 - ((v - lo) / span) * 32}`).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "spark"); svg.setAttribute("viewBox", "0 0 100 38"); svg.setAttribute("preserveAspectRatio", "none");
  const area = document.createElementNS(svg.namespaceURI, "polygon");
  area.setAttribute("class", "area"); area.setAttribute("points", `0,38 ${pts} 100,38`);
  const line = document.createElementNS(svg.namespaceURI, "polyline");
  line.setAttribute("points", pts);
  svg.append(area, line);
  return svg;
}

function details(m) {
  const rows = [["怎么算的", m.how], ["用了哪些数据", m.data], ["依据", m.source + (m.ref ? `〔${m.ref}〕` : "")]].filter((r) => r[1]);
  if (!rows.length) return null;
  return h("details", {}, h("summary", {}, "怎么算的"), h("dl", {}, rows.map(([t, d]) => [h("dt", {}, t), h("dd", {}, d)])));
}

function metricCard(m, { compact = false } = {}) {
  if (!m) return null;
  if (m.value == null) {
    return h("div", { class: "card metric empty" },
      h("div", { class: "name" }, h("span", { class: "dot" }), m.name),
      h("div", { class: "value" }, "暂无"),
      h("div", { class: "text" }, m.text),
      m.missing.some((x) => x.includes("我的")) ? h("a", { class: "btn ghost", href: "#me" }, "去填写") : null);
  }
  const shown = m.key === "blood_pressure" ? m.text.match(/\d+\/\d+/)?.[0] || num(m.value) : num(m.value);
  return h("div", { class: "card metric" },
    h("div", { class: "name" }, h("span", { class: `dot ${m.tone}` }), m.name),
    h("div", { class: "value" }, shown, m.unit ? h("small", {}, m.unit) : null),
    compact ? null : spark(m.series),
    h("div", { class: "text" }, m.text),
    compact ? null : details(m));
}

function stale(meta) {
  if (meta.stale_days == null || meta.stale_days <= 2) return null;
  return h("div", { class: "note" }, `数据截至 ${meta.as_of}（${meta.stale_days} 天前）。"最近 7 天"按最后一条记录往前算；同步新数据后会自动更新。`);
}

function failed(err) { return h("div", { class: "card" }, h("div", { class: "error" }, err.message || String(err))); }

// ---- 页面 ---------------------------------------------------------------------------------
const PAGES = {
  async home(view) {
    const today = new Date();
    view.append(h("h1", {}, `${today.getMonth() + 1} 月 ${today.getDate()} 日 · 今天`));
    const list = await metrics(); const m = byKey(list);
    view.append(stale(list) || "");
    view.append(h("h2", {}, "今日状态"));
    view.append(h("div", { class: "grid" },
      metricCard(m.sleep, { compact: true }), metricCard(m.resting_hr, { compact: true }),
      metricCard(m.steps, { compact: true }), metricCard(m.weight_trend.value != null ? m.weight_trend : m.weight, { compact: true })));
    view.append(h("h2", {}, "今日营养目标"));
    view.append(h("div", { class: "grid" }, metricCard(m.kcal_target, { compact: true }), metricCard(m.protein_target, { compact: true })));
    view.append(h("h2", {}, "今日训练"));
    view.append(h("div", { class: "card soon" },
      h("span", { class: "tag" }, "下一轮上线"),
      h("strong", {}, "今日训练计划"),
      h("span", { class: "muted" }, "由训练规划、恢复和安全官根据你的目标、今天的状态和最近的训练一起生成，每一项都说明为什么这样安排。"),
      h("div", { class: "row" }, h("a", { class: "btn", href: "/chat" }, "先问问教练今天练什么"))));
  },

  async moves(view) {
    view.append(h("h1", {}, "动作"));
    view.append(h("p", { class: "lede" }, "动作库与你的训练记录。"));
    view.append(h("div", { class: "card soon" },
      h("span", { class: "tag" }, "下一轮上线"),
      h("strong", {}, "动作库"),
      h("span", { class: "muted" }, "按部位、器械筛选；每个动作的做法、要点、常见错误、替代动作和不适合的情况。"),
      h("strong", {}, "训练记录"),
      h("span", { class: "muted" }, "按组记录重量和次数，看每个动作的进步（估算最大重量、训练量）。")));
    view.append(h("div", { class: "card" },
      h("strong", {}, "现在就可以问动作教练"),
      h("span", { class: "muted" }, "比如：深蹲膝盖疼怎么办、硬拉怎么不伤腰、卧推的替代动作。"),
      h("div", { class: "row" }, h("a", { class: "btn", href: "/chat" }, "去提问"))));
  },

  async food(view) {
    view.append(h("h1", {}, "饮食"));
    const list = await metrics(); const m = byKey(list);
    view.append(h("h2", {}, "今日目标"));
    view.append(h("div", { class: "grid" }, metricCard(m.kcal_target), metricCard(m.protein_target)));
    view.append(h("h2", {}, "能量估算"));
    view.append(h("div", { class: "grid" }, metricCard(m.bmr), metricCard(m.tdee)));
    view.append(h("div", { class: "card soon" },
      h("span", { class: "tag" }, "下一轮上线"),
      h("strong", {}, "拍照算热量"),
      h("span", { class: "muted" }, "拍一张饭菜照片，认出有哪几样、各多少，你确认份量后按食物营养数据算热量和蛋白质，给出范围，记进今天。")));
  },

  async data(view) {
    view.append(h("h1", {}, "数据"));
    const list = await metrics(); const m = byKey(list);
    view.append(stale(list) || "");
    const group = (title, keys) => {
      const cards = keys.map((k) => metricCard(m[k])).filter(Boolean);
      if (cards.length) { view.append(h("h2", {}, title)); view.append(h("div", { class: "grid wide" }, cards)); }
    };
    group("身体", ["weight", "weight_trend", "bmi"]);
    group("恢复", ["resting_hr", "hrv_sdnn", "hrv_rmssd", "hrv", "sleep"]);
    group("活动", ["steps"]);
    group("血压", ["blood_pressure"]);
    group("能量", ["bmr", "tdee", "kcal_target", "protein_target"]);
    view.append(h("p", { class: "muted" }, "点“怎么算的”可以看每个数的计算方式、用了哪些数据和依据。"));
  },

  async me(view) {
    view.append(h("h1", {}, "我的"));
    const data = await profile(); const p = data.profile; const src = data.sources;
    const hint = (k) => (src[k] === "账户" ? h("span", { class: "hint" }, "（来自账户资料，可修改）") : null);
    const opts = (map, value) => [h("option", { value: "" }, "请选择"),
      ...Object.entries(map).map(([k, v]) => h("option", { value: k, selected: k === value }, v))];
    const msg = h("div", { class: "muted" });
    const form = h("form", { class: "card" },
      h("label", {}, h("span", {}, "身高（厘米）", hint("height_cm")), h("input", { name: "height_cm", type: "number", step: "0.1", min: "100", max: "250", value: p.height_cm ?? "" })),
      h("label", {}, h("span", {}, "出生日期", hint("birth")), h("input", { name: "birth", type: "date", value: p.birth ?? "" })),
      h("label", {}, h("span", {}, "性别", hint("sex")), h("select", { name: "sex" }, opts({ male: "男", female: "女" }, p.sex))),
      h("label", {}, "目标", h("select", { name: "goal" }, opts(data.options.goal, p.goal))),
      h("label", {}, "日常活动水平", h("select", { name: "activity" }, opts(data.options.activity, p.activity))),
      h("button", { type: "submit" }, "保存"), msg);
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const body = {};
      for (const [k, v] of new FormData(form)) if (v !== "") body[k] = k === "height_cm" ? Number(v) : v;
      msg.textContent = "保存中…";
      try {
        await api("/iron/api/profile", { method: "PUT", body: JSON.stringify(body) });
        cache = { metrics: null, profile: null };
        msg.textContent = "已保存，指标已按新档案重新计算。";
      } catch (err) { msg.textContent = err.message; }
    });
    view.append(h("p", { class: "lede" }, "这些信息用来计算 BMI、基础代谢、每日热量和蛋白质目标。"), form);
    view.append(h("button", { class: "ghost", onclick: () => { store.set(""); cache = { metrics: null, profile: null }; render(); } }, "退出登录"));
  },
};
const TITLES = { home: "首页", moves: "动作", food: "饮食", data: "数据", me: "我的" };

// ---- 登录 ---------------------------------------------------------------------------------
function loginView(view) {
  const msg = h("div", { class: "error" });
  const email = h("input", { name: "email", type: "email", placeholder: "邮箱", autocomplete: "email", value: "you@mirobody.ai" });
  const code = h("input", { name: "code", inputmode: "numeric", placeholder: "验证码", autocomplete: "one-time-code" });
  const send = h("button", { type: "button", class: "ghost" }, "获取验证码");
  send.addEventListener("click", async () => {
    msg.textContent = "";
    try { await api("/email/login", { method: "POST", body: JSON.stringify({ email: email.value.trim() }) }); msg.textContent = "验证码已发送（演示账号是 111111）"; }
    catch (err) { msg.textContent = err.message; }
  });
  const form = h("form", { class: "card" }, email, h("div", { class: "row" }, code, send), h("button", { type: "submit" }, "登录"), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); msg.textContent = "";
    try {
      const r = await api("/email/verify", { method: "POST", body: JSON.stringify({ email: email.value.trim(), code: code.value.trim() }) });
      const token = r?.data?.access_token;
      if (!token) throw new Error(r.msg || "登录没有成功");
      store.set(token); render();
    } catch (err) { msg.textContent = err.message; }
  });
  view.append(h("div", { class: "login" }, h("h1", {}, "Iron", h("span", { style: "color:var(--accent)" }, "M")),
    h("p", { class: "lede" }, "你的健身教练团队。用 mirobody 的账号登录。"), form));
}

// ---- 路由 ---------------------------------------------------------------------------------
async function render() {
  const view = $("view"); view.replaceChildren();
  const signedIn = Boolean(store.get());
  for (const id of ["top", "tabs", "ask"]) $(id).hidden = !signedIn;
  if (!signedIn) { loginView(view); return; }
  const page = (location.hash || "#home").slice(1);
  const name = PAGES[page] ? page : "home";
  $("title").textContent = TITLES[name];
  for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.tab === name);
  try { await PAGES[name](view); } catch (err) { view.append(failed(err)); }
}

window.addEventListener("hashchange", render);
document.addEventListener("DOMContentLoaded", () => { $("me").addEventListener("click", () => { location.hash = "#me"; }); render(); });
