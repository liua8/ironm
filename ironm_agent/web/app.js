// IronM 网页：首页、动作、教练（对话）、饮食、数据、我的，都在这一个页面里。
// 只调用 mirobody 与 iron-m 的接口，不加载外部资源；浏览器里只存登录凭证。
"use strict";

const KEY = "iron.token";
const store = {
  get() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } },
  set(v) { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* 隐私模式 */ } },
};
let cache = { metrics: null, profile: null, exercises: null, files: null, me: null };

// ---- 小工具 -------------------------------------------------------------------------------
const $ = (id) => document.getElementById(id);
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : String(kid));
  return el;
}
const SVG = "http://www.w3.org/2000/svg";
function s(tag, attrs = {}) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}
const ICONS = {
  home: [["path", { d: "M3 10.5 12 4l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" }]],
  dumbbell: [["path", { d: "M6.5 6.5v11M3.5 9v6M17.5 6.5v11M20.5 9v6M6.5 12h11" }]],
  coach: [["path", { d: "M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v9a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 4v-4h0A1.5 1.5 0 0 1 4 14.5z" }], ["path", { d: "M8.5 9.5h7M8.5 12.5h4" }]],
  food: [["path", { d: "M7 3v8a2 2 0 0 0 2 2v8M5 3v6M9 3v6M17 21V3c-2 1-3 3.5-3 7h3" }]],
  chart: [["path", { d: "M4 20h16M6 16l4-5 3 3 5-7" }]],
  back: [["path", { d: "M15 5l-7 7 7 7" }]],
  plus: [["path", { d: "M12 5v14M5 12h14" }]],
  send: [["path", { d: "M12 19V5M5.5 11.5 12 5l6.5 6.5" }]],
  stop: [["rect", { x: "7", y: "7", width: "10", height: "10", rx: "2" }]],
  chevron: [["path", { d: "M9 6l6 6-6 6" }]],
  search: [["circle", { cx: "11", cy: "11", r: "6.5" }], ["path", { d: "M20 20l-4.2-4.2" }]],
  close: [["path", { d: "M6 6l12 12M18 6 6 18" }]],
  check: [["path", { d: "M5 12.5l4.5 4.5L19 7.5" }]],
  x: [["path", { d: "M7 7l10 10M17 7 7 17" }]],
  info: [["circle", { cx: "12", cy: "12", r: "9" }], ["path", { d: "M12 11v5M12 8h.01" }]],
  alert: [["path", { d: "M12 4 2.8 19.5h18.4z" }], ["path", { d: "M12 10v4M12 17h.01" }]],
  heart: [["path", { d: "M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.4a4.3 4.3 0 0 1 7.5 2.4C19.5 15.4 12 20 12 20z" }]],
  wave: [["path", { d: "M3 12h3.5l2-5 4 10 2.5-6 1.5 1H21" }]],
  moon: [["path", { d: "M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z" }]],
  up: [["path", { d: "M7.5 10.5V20H4.5v-9.5zM7.5 10.5 11 3.5a2 2 0 0 1 3 2.2l-.9 3.8h5a2 2 0 0 1 2 2.4l-1.3 6.4a2 2 0 0 1-2 1.7H7.5" }]],
  down: [["path", { d: "M7.5 13.5V4H4.5v9.5zM7.5 13.5 11 20.5a2 2 0 0 0 3-2.2l-.9-3.8h5a2 2 0 0 0 2-2.4l-1.3-6.4a2 2 0 0 0-2-1.7H7.5" }]],
  logout: [["path", { d: "M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 16l4-4-4-4M14 12H4" }]],
  edit: [["path", { d: "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4" }]],
  upload: [["path", { d: "M12 15V4M7.5 8.5 12 4l4.5 4.5" }], ["path", { d: "M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" }]],
  note: [["path", { d: "M6 3.5h9l3.5 3.5v13.5h-12.5z" }], ["path", { d: "M9 11h6M9 15h4" }]],
  phone: [["rect", { x: "6.5", y: "2.5", width: "11", height: "19", rx: "2.5" }], ["path", { d: "M12 14s-3-1.8-3-3.9A1.6 1.6 0 0 1 12 9a1.6 1.6 0 0 1 3 1.1C15 12.2 12 14 12 14z" }]],
  dna: [["path", { d: "M7 3c0 4.5 10 4.5 10 9s-10 4.5-10 9M17 3c0 4.5-10 4.5-10 9s10 4.5 10 9" }], ["path", { d: "M9.2 6.5h5.6M9.2 17.5h5.6" }]],
  watch: [["rect", { x: "6.5", y: "6.5", width: "11", height: "11", rx: "3" }], ["path", { d: "M9 6.5l.6-3.5h4.8l.6 3.5M9 17.5l.6 3.5h4.8l.6-3.5M12 9.5V12l1.6 1" }]],
  file: [["path", { d: "M6 3h8l4 4v14H6z" }], ["path", { d: "M14 3v4h4M9 13h6M9 17h4" }]],
  open: [["path", { d: "M14 4h6v6M20 4l-8.5 8.5M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" }]],
  more: [["circle", { cx: "6", cy: "12", r: "1.4" }], ["circle", { cx: "12", cy: "12", r: "1.4" }], ["circle", { cx: "18", cy: "12", r: "1.4" }]],
  sun: [["circle", { cx: "12", cy: "12", r: "4" }], ["path", { d: "M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" }]],
  cloud: [["path", { d: "M7 18h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.3 3.3 0 0 0 7 18z" }]],
  rain: [["path", { d: "M7 15h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.3 3.3 0 0 0 7 15z" }], ["path", { d: "M9 18l-1 2.5M13 18l-1 2.5M17 18l-1 2.5" }]],
  storm: [["path", { d: "M7 14h10.5a4 4 0 0 0 .4-8 6 6 0 0 0-11.6 1.6A3.3 3.3 0 0 0 7 14z" }], ["path", { d: "M12.5 15.5 10.5 19h3l-2 3.5" }]],
  camera: [["path", { d: "M4 8.5A1.5 1.5 0 0 1 5.5 7h2.3l1.5-2h5.4l1.5 2h2.3A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z" }], ["circle", { cx: "12", cy: "13", r: "3.5" }]],
  play: [["path", { d: "M8 5.5v13l10.5-6.5z" }]],
};
function icon(name, cls = "") {
  const svg = s("svg", { viewBox: "0 0 24 24", class: `i ${cls}`.trim(), "aria-hidden": "true" });
  for (const [tag, attrs] of ICONS[name] || []) svg.append(s(tag, attrs));
  if (name === "stop" || name === "play") svg.style.fill = "currentColor";
  return svg;
}

async function api(path, opts = {}) {
  const headers = { "content-type": "application/json", ...(opts.headers || {}) };
  const token = store.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try { res = await fetch(path, { ...opts, headers }); } catch { throw new Error("连不上服务，请检查网络后再试"); }
  if (res.status === 401 || res.status === 403) { signOut(); throw new Error("登录已失效，请重新登录"); }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || body.msg || `请求失败（${res.status}）`);
  return body;
}
// mirobody 的接口外面包了一层 {code, msg, data}
async function apiData(path, opts) {
  const body = await api(path, opts);
  if (body.code !== undefined && body.code !== 0) throw new Error(body.msg || "请求没有成功");
  return body.data ?? body;
}

async function metrics(force = false) {
  if (!cache.metrics || force) cache.metrics = await api("/iron/api/metrics");
  return cache.metrics;
}
async function profile(force = false) {
  if (!cache.profile || force) cache.profile = await api("/iron/api/profile");
  return cache.profile;
}
async function exercises() {
  if (!cache.exercises) cache.exercises = await api("/iron/api/exercises");
  return cache.exercises;
}
const byKey = (list) => Object.fromEntries(list.metrics.map((m) => [m.key, m]));

function num(v) {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString("zh-CN");
  return String(Math.round(v * 100) / 100);
}
function md(iso) {
  const [, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return m && d ? `${m}月${d}日` : "";
}
function todayLabel() {
  const d = new Date();
  return `${d.getMonth() + 1}月${d.getDate()}日 星期${"日一二三四五六"[d.getDay()]}`;
}
function tokenEmail() {
  try {
    const part = store.get().split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return JSON.parse(decodeURIComponent(escape(atob(part + "=".repeat((4 - (part.length % 4)) % 4))))).email || "";
  } catch { return ""; }
}
function signOut() { store.set(""); cache = { metrics: null, profile: null, exercises: null, files: null, me: null }; resetChat(); render(); }

// ---- 通用组件 -----------------------------------------------------------------------------
function section(title, action, ...body) {
  return h("section", { class: "section" }, h("div", { class: "section-head" }, h("h2", {}, title), action), ...body);
}
function more(label, href) { return h("a", { href }, label, icon("chevron", "xs")); }
function chip(text, tone = "") { return text ? h("span", { class: `chip ${tone}` }, text) : null; }
function failed(err, retry) {
  return h("div", { class: "card" },
    h("div", { class: "error-card" }, icon("alert"), h("div", {}, h("strong", {}, "没能加载"), h("p", { class: "muted" }, err.message || String(err)))),
    retry ? h("button", { class: "btn ghost small", type: "button", onclick: retry }, "重试") : null);
}
function skeleton(...heights) { return heights.map((px) => h("div", { class: "skeleton", style: `height:${px}px` })); }
function askChip(label, question) {
  return h("button", { class: "ask-chip", type: "button", onclick: () => askCoach(question || label) }, label);
}

// 趋势图：bars 为柱状（步数），其余为折线；最后一个点标出来
function spark(series, { bars = false } = {}) {
  const vs = series.map((p) => p[1]);
  const n = vs.length;
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (bars) { lo = 0; hi = hi * 1.08 || 1; } else { const pad = (hi - lo || Math.abs(hi) || 1) * 0.15; lo -= pad; hi += pad; }
  const X = (i) => (n === 1 ? 50 : (i / (n - 1)) * 100);
  const Y = (v) => 100 - ((v - lo) / (hi - lo)) * 100;
  const svg = s("svg", { viewBox: "0 0 100 100", preserveAspectRatio: "none", "aria-hidden": "true" });
  if (bars) {
    const w = 100 / n;
    vs.forEach((v, i) => svg.append(s("rect", { class: `bar${i === n - 1 ? " last" : ""}`, x: i * w + w * 0.18, width: w * 0.64, y: Y(v), height: 100 - Y(v), rx: 0.6 })));
  } else {
    const pts = vs.map((v, i) => `${X(i).toFixed(2)},${Y(v).toFixed(2)}`).join(" ");
    svg.append(s("polygon", { class: "area", points: `0,100 ${pts} 100,100` }), s("polyline", { class: "line", points: pts }));
  }
  const box = h("div", { class: "spark" }, svg);
  if (!bars) box.append(h("span", { class: "end", style: `left:${X(n - 1)}%;top:${Y(vs[n - 1])}%` }));
  return box;
}
function chart(m) {
  const vs = m.series.map((p) => p[1]);
  return h("div", { class: "section" },
    spark(m.series, { bars: m.key === "steps" }),
    h("div", { class: "tile-foot" },
      h("span", {}, `${md(m.series[0][0])} – ${md(m.series[m.series.length - 1][0])}`),
      h("span", {}, `最高 ${num(Math.max(...vs))} · 最低 ${num(Math.min(...vs))}`)));
}

function valueText(m) {
  if (m.display) return m.display;
  if (m.value == null) return "—";
  if (m.key === "weight_trend") return `${m.value > 0 ? "+" : m.value < 0 ? "−" : ""}${Math.abs(m.value).toFixed(2)}`;
  return num(m.value);
}
function pressable(el, action) {
  el.setAttribute("role", "button"); el.setAttribute("tabindex", "0");
  el.addEventListener("click", action);
  el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); action(); } });
  return el;
}
function tile(m, { wide = false, brief, tone } = {}) {
  const series = m.series || [];
  const shown = valueText(m);
  return pressable(h("div", { class: `tile${wide ? " wide" : ""}`, "aria-label": `${m.name}，点开看怎么算的` },
    h("div", { class: "tile-head" }, h("span", { class: "tile-name" }, m.name), chip(brief ?? m.brief, tone ?? m.tone)),
    h("div", { class: `tile-value${shown.length > 6 ? " long" : ""}` }, shown, m.unit ? h("small", {}, m.unit) : null),
    series.length > 1 ? spark(series, { bars: m.key === "steps" }) : null,
    wide && series.length > 1 ? h("div", { class: "tile-foot" }, h("span", {}, md(series[0][0])), h("span", {}, md(series[series.length - 1][0]))) : null),
  () => metricSheet(m));
}

// ---- 详情：底部弹出 -----------------------------------------------------------------------
function openSheet(title, ...content) {
  closeSheet();
  const close = h("button", { class: "icon-btn", type: "button", "aria-label": "关闭", onclick: closeSheet }, icon("close", "sm"));
  const sheet = h("div", { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
    h("div", { class: "sheet-grip" }),
    h("div", { class: "sheet-head" }, h("h2", {}, title), close),
    h("div", { class: "sheet-body" }, ...content));
  $("sheet-root").replaceChildren(h("div", { class: "sheet-overlay", onclick: closeSheet }), sheet);
  document.body.classList.add("locked");
  close.focus({ preventScroll: true });
}
function closeSheet() {
  const root = $("sheet-root");
  if (root && root.childElementCount) root.replaceChildren();
  document.body.classList.remove("locked");
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

function metricSheet(m) {
  const facts = [["结论", m.text], ["怎么算的", m.how], ["用了哪些数据", m.data], ["依据", m.source]].filter(([, v]) => v);
  openSheet(m.name,
    m.value != null ? h("div", { class: "sheet-big" }, h("span", { class: "v" }, valueText(m), m.unit ? h("small", {}, m.unit) : null), chip(m.brief, m.tone)) : null,
    (m.series || []).length > 1 ? chart(m) : null,
    h("dl", { class: "facts" }, facts.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))),
    (m.missing || []).some((x) => x.includes("我的")) ? h("a", { class: "btn block", href: "#me" }, "去「我的」填写") : null,
    (m.missing || []).some((x) => x.includes("手表")) ? h("button", { class: "btn block", type: "button", onclick: appleSheet }, icon("phone", "sm"), "导入苹果健康数据") : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我的${m.name}最近怎么样？说明什么？`) }, icon("coach", "sm"), "问问教练"));
}

// ---- 首页：状态卡、计划表、训练日历（spec [2026-10-23] §13）-------------------------------------
const QUICK = {
  "只有 30 分钟": "今天只有 30 分钟，怎么练最有效？",
  "在家没有器械": "今天在家、没有器械，怎么练？",
  "今天想练腿": "今天想练腿，怎么安排？",
  "今天有点累": "今天有点累，还要练吗？怎么安排？",
};
const BRIEF_TONE = { good: "good", fair: "neutral", poor: "attention", unknown: "neutral" };
const BRIEF_HEAD = { good: "状态不错，可以按计划练", fair: "状态一般，量力而行", poor: "今天注意恢复", unknown: "最近缺少恢复数据" };
const WEEK = ["一", "二", "三", "四", "五", "六", "日"];
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

async function home(view) {
  const [brief, wx, training] = await Promise.all([
    api("/iron/api/brief").catch(() => null),
    api("/iron/api/weather").catch(() => ({ status: "unavailable", message: "暂时取不到天气" })),
    api("/iron/api/training").catch(() => null),
  ]);
  view.append(statusCard(brief, wx), planTable(training, brief), calendarCard(brief));
}

function wxIcon(text) {
  if (/雷/.test(text)) return "storm";
  if (/雨|雪/.test(text)) return "rain";
  if (/云|阴|雾/.test(text)) return "cloud";
  return "sun";
}
const aqiTone = (a) => (a <= 100 ? "good" : a <= 150 ? "mid" : "bad");

function statusCard(brief, wx) {
  const day = brief?.today, rd = day?.readiness;
  const head = rd ? BRIEF_HEAD[rd.level] || rd.name : "今天的状态暂时算不出来";
  const why = rd?.reasons?.length ? `${rd.reasons.join("；")}。` : day?.alert || "";
  return h("div", { class: "hero" },
    h("div", { class: "hero-kicker" }, h("span", { class: `hero-dot ${BRIEF_TONE[rd?.level] || "neutral"}` }), "今天的状态"),
    h("div", {}, h("h2", {}, head), why ? h("p", {}, why) : null),
    weatherRow(wx),
    day?.alert && rd?.reasons?.length ? h("p", { class: "hero-alert" }, icon("alert", "xs"), day.alert) : null);
}

function weatherRow(wx) {
  if (wx.status === "no_city") {
    return h("a", { class: "wx-row", href: "#me" }, icon("sun", "sm"), h("span", {}, "在「我的」里设置城市，就能看到天气和训练提示"), icon("chevron", "xs"));
  }
  if (wx.status !== "ok") return h("div", { class: "wx-row" }, icon("cloud", "sm"), h("span", {}, wx.message || "暂时取不到天气"));
  const advice = wx.advice.reasons.length ? `${wx.advice.name}：${wx.advice.reasons[0]}` : `${wx.advice.name}，天气不影响训练`;
  return pressable(h("div", { class: "wx", "aria-label": "天气详情" },
    h("div", { class: "wx-main" },
      icon(wxIcon(wx.text), "sm"),
      h("b", {}, `${wx.temperature}°`),
      h("span", { class: "wx-text" }, `${wx.place} · ${wx.text} · 体感 ${wx.feels_like}°`),
      wx.aqi != null ? h("span", { class: `aqi ${aqiTone(wx.aqi)}` }, `${wx.aqi_level} ${wx.aqi}`) : null),
    h("p", { class: `wx-advice ${wx.advice.level}` }, advice)), () => weatherSheet(wx));
}

function weatherSheet(wx) {
  const rows = [
    ["天气", `${wx.text}，${wx.temperature}℃（体感 ${wx.feels_like}℃）`],
    wx.humidity != null ? ["湿度", `${Math.round(wx.humidity)}%`] : null,
    wx.wind_kmh != null ? ["风速", `${Math.round(wx.wind_kmh)} 公里/小时`] : null,
    wx.aqi != null ? ["空气质量", `${wx.aqi_level}（指数约 ${wx.aqi}，按 PM2.5、PM10 估算）`] : null,
  ].filter(Boolean);
  openSheet(`${wx.place}的天气`,
    h("div", {}, rows.map(([k, v]) => h("div", { class: "kv" }, h("span", {}, k), h("span", {}, v)))),
    h("div", {}, h("h3", {}, "对训练的影响"), h("p", { class: "lede" }, wx.advice.name),
      wx.advice.reasons.length ? h("ul", { class: "tips" }, wx.advice.reasons.map((t) => h("li", {}, t))) : null),
    wx.advice.sources.length ? h("p", { class: "caption" }, `依据：${wx.advice.sources.join("；")}`) : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach("按今天的天气，我今天怎么练比较合适？") }, icon("coach", "sm"), "按天气问问教练"));
}

function planTable(tr, brief) {
  const plan = tr?.plan, t = brief?.today?.training;
  if (!plan) {
    return h("div", { class: "card plan-card" },
      h("div", { class: "plan-top" }, h("div", { class: "plan-icon" }, icon("dumbbell")),
        h("div", {}, h("h3", {}, "训练计划"), h("p", { class: "muted" }, "还没有计划：让教练按你的目标、时间和器械排一份。"))),
      h("button", { class: "btn block", type: "button", onclick: () => askCoach("帮我排一个每周训练计划") }, "让教练排一份计划"),
      h("div", { class: "asks" }, Object.entries(QUICK).map(([label, q]) => askChip(label, q))));
  }
  const todayNo = new Date().getDay() || 7;
  const byDay = Object.fromEntries(plan.sessions.map((x) => [x.day, x]));
  const rows = WEEK.map((w, i) => {
    const d = i + 1, x = byDay[d], isToday = d === todayNo;
    const row = h("div", { class: `pt-row${isToday ? " today" : ""}${x ? "" : " rest"}` },
      h("span", { class: "pt-day" }, isToday ? "今天" : `周${w}`),
      h("span", { class: "pt-name" }, x ? x.name : "休息"),
      h("span", { class: "pt-min" }, x ? `${x.minutes} 分钟` : ""),
      x ? icon("chevron", "xs") : h("span"));
    return x ? pressable(row, () => sessionSheet(x, isToday, t)) : row;
  });
  const todaySession = byDay[todayNo];
  return h("div", { class: "card plan-card" },
    h("div", { class: "pt-head" },
      h("div", {}, h("h3", {}, plan.title), h("p", { class: "muted" }, `每周 ${plan.days_per_week} 练${plan.goal ? ` · 目标：${plan.goal}` : ""}`)),
      h("button", { class: "link", type: "button", onclick: () => askCoach("帮我看看现在的训练计划，需要调整吗？") }, "调整", icon("chevron", "xs"))),
    t?.tip ? h("div", { class: "notice-line" }, icon("alert", "xs"), t.tip) : null,
    h("div", { class: "pt" }, rows),
    todaySession ? h("div", { class: "btn-row" },
      t?.done ? h("button", { class: "btn ghost", type: "button", disabled: true }, icon("check", "sm"), "今天已打卡")
        : h("button", { class: "btn", type: "button", onclick: () => doneSheet(todaySession.name) }, icon("check", "sm"), "完成打卡"),
      h("button", { class: "btn ghost", type: "button", onclick: () => askCoach("今天练什么？按我的计划和今天的状态说") }, icon("coach", "sm"), "今天怎么练"))
      : null);
}

function sessionSheet(x, isToday, t) {
  openSheet(`${isToday ? "今天" : weekdayName(x.day)} · ${x.name}`,
    h("p", { class: "muted" }, `约 ${x.minutes} 分钟`),
    h("ol", { class: "plan-items" }, x.items.map((it) => h("li", {}, `${it.exercise} ${it.sets}×${it.reps}${it.load || it.note ? `（${[it.load, it.note].filter(Boolean).join("，")}）` : ""}`))),
    isToday && !t?.done ? h("button", { class: "btn block", type: "button", onclick: () => doneSheet(x.name) }, icon("check", "sm"), "完成打卡") : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`${x.name}这次训练怎么练？每个动作要注意什么？`) }, icon("coach", "sm"), "问教练怎么练"));
}
const weekdayName = (d) => `周${WEEK[d - 1]}`;

let calMonth = "";
function calendarCard(brief) {
  const box = h("div", { class: "card cal" });
  const draw = async () => {
    let cal;
    try { cal = await api(`/iron/api/calendar${calMonth ? `?month=${calMonth}` : ""}`); }
    catch (err) { box.replaceChildren(failed(err, draw)); return; }
    const [y, m] = cal.month.split("-").map(Number);
    const first = new Date(y, m - 1, 1), days = new Date(y, m, 0).getDate();
    const lead = (first.getDay() + 6) % 7;
    const lit = new Set(cal.done_days);
    const shift = (n) => { const d = new Date(y, m - 1 + n, 1); calMonth = isoDay(d).slice(0, 7); draw(); };
    const cells = [...Array.from({ length: lead }, () => h("span", { class: "cal-cell blank" }))];
    for (let d = 1; d <= days; d++) {
      const iso = `${cal.month}-${String(d).padStart(2, "0")}`;
      const entries = cal.days[iso] || [];
      const cls = `cal-cell${lit.has(iso) ? " lit" : ""}${iso === cal.today ? " today" : ""}${entries.length ? " has" : ""}`;
      const cell = h("span", { class: cls, "aria-label": `${m}月${d}日${lit.has(iso) ? "，练过" : ""}` }, String(d));
      cells.push(entries.length ? pressable(cell, () => openSheet(`${m}月${d}日`,
        h("div", { class: "rows" }, entries.map((e) => h("div", { class: "row-item" },
          h("span", { class: `dot-state ${e.done ? "on" : ""}` }), h("div", { class: "row-main" }, h("span", { class: "row-title" }, e.line))))))) : cell);
    }
    const thisMonth = cal.today.slice(0, 7) === cal.month;
    const doneToday = lit.has(cal.today);
    const session = brief?.today?.training?.kind === "session" ? brief.today.training.name : "";
    box.replaceChildren(
      h("div", { class: "cal-head" },
        h("button", { class: "icon-btn", type: "button", "aria-label": "上个月", onclick: () => shift(-1) }, icon("back", "sm")),
        h("b", {}, `${y}年${m}月`),
        h("button", { class: "icon-btn", type: "button", "aria-label": "下个月", onclick: () => shift(1), disabled: thisMonth }, icon("chevron", "sm"))),
      h("div", { class: "cal-grid cal-week" }, WEEK.map((w) => h("span", {}, w))),
      h("div", { class: "cal-grid" }, cells),
      h("div", { class: "cal-foot" },
        h("span", { class: "muted" }, `这个月练了 ${cal.done_days.length} 天`),
        thisMonth && !doneToday ? h("button", { class: "btn small", type: "button", onclick: () => doneSheet(session || "训练") }, icon("check", "sm"), "今天打卡") : null));
  };
  box.append(...skeleton(260));
  draw();
  return section("训练日历", null, box);
}

function doneSheet(session) {
  let rpe = 0;
  const scale = h("div", { class: "rpe" });
  const draw = () => scale.replaceChildren(...Array.from({ length: 10 }, (_, i) => h("button", {
    type: "button", class: rpe === i + 1 ? "on" : "", "aria-pressed": String(rpe === i + 1), onclick: () => { rpe = i + 1; draw(); } }, String(i + 1))));
  draw();
  const note = h("input", { type: "text", maxlength: "60", placeholder: "备注（可不填），比如有点累、膝盖没疼" });
  const msg = h("p", { class: "muted" });
  const save = h("button", { class: "btn block", type: "button", onclick: async () => {
    save.disabled = true; msg.textContent = "正在记下…";
    try {
      await api("/iron/api/workouts", { method: "POST", body: JSON.stringify({ session: session === "训练" ? "" : session, done: true, rpe: rpe || null, note: note.value.trim() }) });
      closeSheet(); render();
    } catch (err) { msg.textContent = err.message; save.disabled = false; }
  } }, "打卡");
  openSheet(`打卡：${session}`,
    h("p", { class: "muted" }, "这次感觉怎么样？1 很轻松，10 到极限（可不选）"), scale, note, save, msg);
}

function weekCard(w) {
  const rows = [];
  if (w.planned) rows.push(["训练", `完成 ${w.done} / ${w.planned} 次`, w.sessions.map((x) => `${x.day}${x.name}${x.done ? " ✓" : ""}`).join("　")]);
  else rows.push(["训练", `本周练了 ${w.done} 次`, "还没有计划"]);
  if (w.weight) rows.push(["体重", w.weight.brief || "—", w.weight.text]);
  if (w.sleep) rows.push(["睡眠", `平均 ${num(w.sleep.value)} 小时`, w.sleep.brief]);
  if (w.resting_hr) rows.push(["静息心率", `${num(w.resting_hr.value)} 次/分`, w.resting_hr.brief]);
  if (w.hrv) rows.push([w.hrv.name, `${num(w.hrv.value)} 毫秒`, w.hrv.brief]);
  return h("div", { class: "card" },
    h("div", { class: "rows" }, rows.map(([k, v, sub]) => h("div", { class: "row-item" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, k), sub ? h("span", { class: "row-sub" }, sub) : null),
      h("span", { class: "row-end" }, v)))),
    w.tips.length ? h("ul", { class: "tips" }, w.tips.map((t) => h("li", {}, t))) : h("p", { class: "muted" }, "这周没有需要调整的地方，照计划来。"),
    w.tips.length && w.planned ? h("button", { class: "btn block", type: "button", onclick: proposalSheet }, icon("check", "sm"), "生成调整方案") : null);
}

// 每周复盘直接出调整方案（spec [2026-10-23] §18 需求 1）：训练规划按复盘改计划，确认后才替换，可以撤销
async function proposalSheet() {
  const box = h("div", { class: "sheet-stack" }, h("p", { class: "muted" }, "训练规划在按这周的复盘改计划，大约要半分钟…"));
  openSheet("按复盘调整计划", box);
  let r;
  try { r = await api("/iron/api/review/proposal", { method: "POST" }); }
  catch (err) { box.replaceChildren(h("p", { class: "error" }, err.message)); return; }
  if (r.status !== "ok") {
    box.replaceChildren(h("p", { class: "muted" }, r.message), r.answer ? h("p", {}, r.answer) : null,
      h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach("按这周的复盘帮我调整训练计划") }, icon("coach", "sm"), "到对话里让教练改"));
    return;
  }
  draftView(box, r.draft, r.answer, r.warning);
}

function draftView(box, d, answer, warning) {
  const msg = h("p", { class: "muted", role: "status" });
  const actions = h("div", { class: "btn-row" });
  const act = async (action, done) => {
    for (const b of actions.querySelectorAll("button")) b.disabled = true;
    try { await api(`/iron/api/drafts/${d.id}/${action}`, { method: "POST" }); done(); cache.metrics = null; }
    catch (err) { msg.className = "error"; msg.textContent = err.message; for (const b of actions.querySelectorAll("button")) b.disabled = false; }
  };
  const undo = h("button", { class: "btn ghost", type: "button", onclick: () => act("undo", () => { msg.textContent = "已撤销，计划回到改之前的样子。"; actions.replaceChildren(); }) }, "撤销");
  actions.append(
    h("button", { class: "btn", type: "button", onclick: () => act("confirm", () => { msg.textContent = "已保存，新的计划从今天起生效。"; actions.replaceChildren(undo); }) }, icon("check", "sm"), "确认"),
    h("button", { class: "btn ghost", type: "button", onclick: () => act("cancel", () => { msg.textContent = "已取消，计划没有改动。"; actions.replaceChildren(); }) }, "取消"));
  const sessions = d.plan?.sessions || [];
  box.replaceChildren(
    answer ? h("p", { class: "lede" }, answer) : null,
    d.changes ? h("div", { class: "notice-line" }, icon("info", "xs"), `改了什么：${d.changes}`) : null,
    warning ? h("div", { class: "notice-line" }, icon("alert", "xs"), warning) : null,
    h("ol", { class: "plan-items" }, sessions.map((x) => h("li", {}, `${weekdayName(x.day)} ${x.name}（约 ${x.minutes} 分钟）：${x.items.map((it) => `${it.exercise} ${it.sets}×${it.reps}`).join("、")}`))),
    actions, msg,
    h("p", { class: "caption" }, "确认后才会替换现在的计划，之后可以撤销；这份方案 24 小时内有效。"));
}

// ---- 动作：卡片流，官方视频，"没看懂"请动作教练用大白话讲（spec [2026-10-23] §13）--------------------
const PART_MARK = { 腿臀: "腿", 胸: "胸", 背: "背", 肩: "肩", 手臂: "臂", 核心: "核", 全身: "全", 有氧: "氧" };
const moveFilter = { part: "全部", equip: "全部器械", q: "" };
const VIDEO_EXT = [".mp4", ".webm", ".mov"];
const videoUrl = (id) => `/iron/api/exercises/${encodeURIComponent(id)}/video`;
async function whoami() {
  if (!cache.me) cache.me = await api("/iron/api/me").catch(() => ({ admin: false }));
  return cache.me;
}

function pills(options, current, onPick) {
  const box = h("div", { class: "pills", role: "group" });
  for (const opt of options) {
    box.append(h("button", { class: `pill${opt === current ? " on" : ""}`, type: "button", "aria-pressed": String(opt === current),
      onclick: (e) => {
        for (const b of box.children) { b.classList.remove("on"); b.setAttribute("aria-pressed", "false"); }
        e.currentTarget.classList.add("on"); e.currentTarget.setAttribute("aria-pressed", "true");
        onPick(opt);
      } }, opt));
  }
  return box;
}

async function moves(view) {
  const [lib, vids, me] = await Promise.all([exercises(), api("/iron/api/videos").catch(() => ({ videos: [] })), whoami()]);
  const has = new Set(vids.videos);
  const count = h("div", { class: "muted", style: "padding:0 2px" });
  const grid = h("div", { class: "move-grid" });
  const input = h("input", { type: "search", placeholder: "搜索动作或部位，比如深蹲、肩", value: moveFilter.q, "aria-label": "搜索动作" });
  function draw() {
    const q = moveFilter.q.trim();
    const items = lib.exercises.filter((x) =>
      (moveFilter.part === "全部" || x.part === moveFilter.part)
      && (moveFilter.equip === "全部器械" || x.equipment.includes(moveFilter.equip))
      && (!q || `${x.name}${x.muscles}${x.part}`.includes(q)));
    count.textContent = `${items.length} 个动作${has.size ? ` · ${items.filter((x) => has.has(x.id)).length} 个有视频` : ""}`;
    grid.replaceChildren(...(items.length ? items.map((x) => moveCard(x, has.has(x.id), () => exerciseSheet(x, lib.note, has, me.admin, draw)))
      : [h("div", { class: "card" }, h("div", { class: "empty" }, icon("search"), "没有符合的动作，换个条件试试，或者直接问动作教练。"))]));
  }
  input.addEventListener("input", () => { moveFilter.q = input.value; draw(); });
  draw();
  view.append(
    h("label", { class: "search" }, icon("search", "sm"), input),
    pills(["全部", ...lib.parts], moveFilter.part, (v) => { moveFilter.part = v; draw(); }),
    pills(["全部器械", ...lib.equipment], moveFilter.equip, (v) => { moveFilter.equip = v; draw(); }),
    count, grid,
    h("div", { class: "card plan-card" },
      h("div", { class: "plan-top" }, h("div", { class: "plan-icon" }, icon("coach")),
        h("div", {}, h("h3", {}, "不知道练哪个？"), h("p", { class: "muted" }, "告诉动作教练你想练哪里、有什么器械、哪里不舒服。"))),
      h("div", { class: "asks" }, askChip("在家用哑铃练全身"), askChip("膝盖不好能练什么腿"), askChip("久坐圆肩怎么改善"))));
}

function moveCard(x, video, open) {
  const cover = h("div", { class: `move-cover p-${x.part}` },
    video ? h("video", { src: `${videoUrl(x.id)}#t=0.5`, muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true" })
      : h("span", { class: "cover-mark" }, PART_MARK[x.part] || x.part[0]),
    video ? h("span", { class: "play" }, icon("play", "sm")) : null,
    h("span", { class: "cover-level" }, x.level));
  return pressable(h("div", { class: "move-card", "aria-label": `${x.name}，点开看做法` }, cover,
    h("div", { class: "move-info" }, h("b", {}, x.name), h("span", {}, `${x.part} · ${x.equipment.slice(0, 2).join("、")}`))), open);
}

function exerciseSheet(x, note, has, admin, redraw) {
  const list = (items, cls, ic) => h("ul", { class: `marks ${cls}` }, items.map((t) => h("li", {}, icon(ic, "xs"), h("span", {}, t))));
  const video = has.has(x.id)
    ? h("video", { class: "move-video", src: videoUrl(x.id), controls: true, playsinline: true, preload: "metadata" })
    : h("div", { class: `move-video empty-video p-${x.part}` }, h("span", { class: "cover-mark" }, PART_MARK[x.part] || x.part[0]), h("span", { class: "caption" }, "官方视频还在制作，先看下面的做法和要点"));
  openSheet(x.name,
    video,
    h("div", { class: "tags" }, chip(x.part), x.equipment.map((e) => chip(e)), chip(x.level)),
    h("p", { class: "lede" }, `主要练：${x.muscles}`),
    h("div", {}, h("h3", {}, "怎么做"), h("ol", { class: "steps-ol" }, x.steps.map((t) => h("li", {}, t)))),
    h("div", {}, h("h3", {}, "要点"), list(x.cues, "ok", "check")),
    h("div", {}, h("h3", {}, "常见错误"), list(x.mistakes, "bad", "x")),
    h("div", {}, h("h3", {}, "替代动作"), h("div", { class: "swap" }, h("div", {}, h("b", {}, "更容易"), x.easier), h("div", {}, h("b", {}, "更难"), x.harder))),
    h("div", { class: "callout" }, icon("alert", "sm"), h("div", {}, h("strong", {}, "什么情况先别做："), x.avoid)),
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: () => askCoach(`${x.name}我没看懂，请用大白话、打个比方再给我讲讲怎么做，最容易做错的地方是什么`) }, icon("coach", "sm"), "没看懂？讲简单点"),
      h("button", { class: "btn ghost", type: "button", onclick: () => askCoach(`${x.name}有什么替代动作？按我的器械和身体情况选`) }, "换个动作")),
    h("p", { class: "caption" }, note),
    admin ? videoAdmin(x, has, redraw) : null);
}

// 管理员：给动作上传、更换、删除官方视频
function videoAdmin(x, has, redraw) {
  const bar = progressBar();
  const msg = h("div", { class: "muted", role: "status" });
  const zone = picker({ accept: VIDEO_EXT, maxBytes: 200 * MB, multiple: false, hint: "MP4、WebM、MOV，不超过 200MB；只用自己拍的或有授权的视频",
    onPick: async (ok, bad) => {
      if (bad.length) { msg.className = "error"; msg.textContent = bad.join("；"); return; }
      if (!ok.length) return;
      const form = new FormData(); form.append("file", ok[0]);
      msg.className = "muted"; msg.textContent = "上传中…";
      try {
        await send(videoUrl(x.id), form, (p) => bar.set(p));
        has.add(x.id); msg.textContent = "已上传"; closeSheet(); redraw();
      } catch (err) { msg.className = "error"; msg.textContent = err.message; }
    } });
  const del = has.has(x.id) ? h("button", { class: "btn danger block", type: "button", onclick: async () => {
    if (!confirm(`删除「${x.name}」的视频？`)) return;
    try { await api(videoUrl(x.id), { method: "DELETE" }); has.delete(x.id); closeSheet(); redraw(); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; }
  } }, "删除视频") : null;
  return h("div", { class: "admin-box" }, h("h3", {}, has.has(x.id) ? "管理员：更换视频" : "管理员：上传视频"), zone, bar.el, msg, del);
}

// ---- 饮食：饮食记录（照片 + 描述）、推荐这一餐、减脂餐、今日目标（spec [2026-10-23] §13）----------------
const MEAL_KINDS = ["早餐", "午餐", "晚餐", "加餐"];
const APPETITES = ["清淡", "正常", "很饿"];
const SCENES = ["全部", "外卖", "食堂", "便利店", "自己做"];
const foodState = { kind: null, appetite: "正常", scene: "全部" };
function mealKindNow() {
  const hr = new Date().getHours();
  return hr < 10 ? "早餐" : hr < 15 ? "午餐" : hr < 21 ? "晚餐" : "加餐";
}
const macroLine = (m) => `${Math.round(m.kcal)} 千卡 · 蛋白质 ${Math.round(m.protein_g)} 克 · 碳水 ${Math.round(m.carbs_g)} 克 · 脂肪 ${Math.round(m.fat_g)} 克`;

// 手机照片常常好几 MB：先缩到长边 1600 像素、存成 JPEG 再上传
async function shrinkPhoto(file) {
  try {
    const img = await createImageBitmap(file);
    const scale = Math.min(1, 1600 / Math.max(img.width, img.height));
    const canvas = h("canvas", { width: Math.round(img.width * scale), height: Math.round(img.height * scale) });
    canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
    return await new Promise((ok) => canvas.toBlob((b) => ok(b || file), "image/jpeg", 0.85));
  } catch { return file; }
}

async function food(view) {
  foodState.kind = foodState.kind || mealKindNow();
  const [day, m] = await Promise.all([api("/iron/api/meals"), metrics().then(byKey).catch(() => ({}))]);
  const summary = h("div");
  const list = h("div");
  const redraw = (d) => { summary.replaceChildren(daySummary(d, m)); list.replaceChildren(mealList(d, redraw)); };
  redraw(day);
  view.append(summary,
    dietReviewCard(),
    section("记一餐", null, mealForm(redraw)),
    section("今天吃了什么", null, list),
    section("推荐这一餐", null, recommendBox(redraw)),
    section("减脂餐", null, await presetsBox(redraw)),
    section("问营养师", null, h("div", { class: "asks" },
      ["早餐怎么吃够蛋白质", "练前练后吃什么", "外卖怎么点更健康", "要不要吃肌酸", "减脂期饿了怎么办"].map((q) => askChip(q)))));
}

// 两周饮食复盘（spec [2026-10-23] §18 需求 2）：按体重趋势提出热量调整，确认后才生效，可以撤销
function dietReviewCard() {
  const box = h("div", { class: "card" }, ...skeleton(70));
  const kcal = (n) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
  const act = async (path) => {
    for (const b of box.querySelectorAll("button")) b.disabled = true;
    try { draw(await api(path, { method: "POST" })); cache.metrics = null; render(); }
    catch (err) { box.append(h("p", { class: "error" }, err.message)); for (const b of box.querySelectorAll("button")) b.disabled = false; }
  };
  const draw = (r) => {
    const p = r.proposal, c = r.current;
    box.replaceChildren(
      c ? h("div", { class: "kv" }, h("span", {}, "现在的调整"), h("span", {}, `${kcal(c.kcal)} 千卡/天（${md(c.since)}起）`)) : null,
      c ? h("p", { class: "caption" }, `原因：${c.reason}`) : null,
      p ? h("p", { class: "lede" }, `${p.reason}：建议每天${p.delta > 0 ? "多" : "少"}吃约 ${Math.abs(p.delta)} 千卡，目标从 ${p.before} 调到 ${p.after} 千卡。`) : h("p", { class: "muted" }, r.message),
      p ? h("p", { class: "caption" }, `依据：${p.basis}`) : null,
      h("div", { class: "btn-row" },
        p ? h("button", { class: "btn", type: "button", onclick: () => act("/iron/api/diet/adjust") }, icon("check", "sm"), "确认调整") : null,
        c ? h("button", { class: "btn ghost", type: "button", onclick: () => act("/iron/api/diet/adjust/undo") }, "撤销上次调整") : null),
      h("p", { class: "caption" }, "每两周按体重趋势复盘一次；调整后的目标不会低于基础代谢和安全下限。"));
  };
  api("/iron/api/diet/review").then(draw).catch((err) => box.replaceChildren(h("p", { class: "muted" }, err.message)));
  return section("两周饮食复盘", null, box);
}

function meter(label, have, target, unit) {
  const pct = target ? Math.min(100, (have / target) * 100) : 0;
  const over = target && have > target * 1.05;
  return h("div", { class: "fmeter" },
    h("div", { class: "fmeter-top" }, h("span", {}, label),
      h("span", {}, h("b", {}, Math.round(have)), target ? ` / ${Math.round(target)} ${unit}` : ` ${unit}`)),
    h("div", { class: "meter" }, h("span", { class: over ? "over" : "", style: `width:${pct}%` })));
}

function daySummary(d, m) {
  const t = d.target, tot = d.totals;
  if (!t) {
    return h("div", { class: "card" },
      h("div", { class: "empty" }, icon("info"), "在「我的」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。"),
      h("a", { class: "btn ghost small", href: "#me" }, "去填写"),
      tot.kcal ? h("p", { class: "muted" }, `今天已记：${macroLine(tot)}`) : null);
  }
  const kcal = m.kcal_target, protein = m.protein_target;
  const left = Math.max(0, Math.round(t.kcal - tot.kcal));
  return h("div", { class: "card food-sum" },
    h("div", { class: "tile-head" }, h("span", { class: "tile-name" }, `今天${d.goal ? ` · 目标${d.goal}` : ""}`), chip(`还能吃约 ${left} 千卡`, left ? "good" : "attention")),
    meter("热量", tot.kcal, t.kcal, "千卡"),
    meter("蛋白质", tot.protein_g, protein?.display ? Number(String(protein.display).split("–")[0]) : t.protein_g, "克"),
    h("p", { class: "caption" }, `碳水 ${Math.round(tot.carbs_g)} 克 · 脂肪 ${Math.round(tot.fat_g)} 克（记录里的营养都是估算）`),
    h("button", { class: "link", type: "button", onclick: () => openSheet("今日目标怎么算的",
      ...[kcal, protein, m.bmr, m.tdee].filter((x) => x && x.value != null).map((x) => h("div", {}, h("h3", {}, x.name), h("dl", { class: "facts" },
        [["结论", x.text], ["怎么算的", x.how], ["依据", x.source]].filter(([, v]) => v).map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v))))))) }, "目标怎么算的", icon("chevron", "xs")));
}

function mealForm(redraw) {
  let photo = null;
  const preview = h("div", { class: "photo-preview", hidden: true });
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", capture: "environment", class: "sr-only" });
  const pick = h("label", { class: "photo-pick" }, input, icon("camera"), h("span", {}, "拍照或选照片"));
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { msg.className = "error"; msg.textContent = "照片只支持 JPG、PNG、WebP（iPhone 可以在相机设置里选“兼容性最佳”）"; return; }
    photo = await shrinkPhoto(f);
    if (photo.size > 5 * MB) { msg.className = "error"; msg.textContent = "照片太大了，换一张试试"; photo = null; return; }
    msg.textContent = "";
    preview.hidden = false;
    preview.replaceChildren(h("img", { src: URL.createObjectURL(photo), alt: "这一餐的照片" }),
      h("button", { class: "icon-btn", type: "button", "aria-label": "去掉照片", onclick: () => { photo = null; preview.hidden = true; preview.replaceChildren(); } }, icon("close", "sm")));
  });
  const said = h("input", { type: "text", maxlength: "120", placeholder: "说一句：比如一碗牛肉面，吃了一半" });
  const msg = h("div", { class: "muted", role: "status" });
  const go = h("button", { class: "btn block", type: "button" }, "记下，估算热量");
  go.addEventListener("click", async () => {
    if (!photo && !said.value.trim()) { msg.className = "error"; msg.textContent = "拍张照片或写一句描述"; return; }
    const form = new FormData();
    form.append("said", said.value.trim()); form.append("kind", foodState.kind);
    if (photo) form.append("photo", photo, "meal.jpg");
    go.disabled = true; msg.className = "muted"; msg.textContent = "营养师在估算…";
    try {
      const r = await send("/iron/api/meals", form);
      said.value = ""; photo = null; preview.hidden = true; preview.replaceChildren();
      msg.textContent = `已记下：${r.meal.name}，约 ${Math.round(r.meal.macros.kcal)} 千卡（估算）`;
      redraw(r);
    } catch (err) { msg.className = "error"; msg.textContent = err.message; }
    go.disabled = false;
  });
  return h("div", { class: "card" },
    pills(MEAL_KINDS, foodState.kind, (v) => { foodState.kind = v; }),
    h("div", { class: "photo-row" }, pick, preview), said, go, msg,
    h("p", { class: "caption" }, "照片加一句描述估得更准；照片只存在你的记录里。"));
}

function mealList(d, redraw) {
  if (!d.meals.length) return h("div", { class: "card" }, h("div", { class: "empty" }, icon("food"), "今天还没记，拍一张或者从下面的减脂餐里选。"));
  return h("div", { class: "card" }, h("div", { class: "rows" }, d.meals.map((x) => {
    const thumb = h("div", { class: "meal-thumb" }, icon("food", "sm"));
    if (x.has_photo) loadPhoto(x.id, thumb);
    return pressable(h("div", { class: "row-item" }, thumb,
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, `${x.kind} · ${x.name}`), h("span", { class: "row-sub" }, macroLine(x.macros))),
      h("span", { class: "row-end" }, `${Math.round(x.macros.kcal)}`, icon("chevron", "xs"))), () => mealSheet(x, redraw));
  })));
}

async function loadPhoto(id, box) {
  try {
    const res = await fetch(`/iron/api/meals/${id}/photo`, { headers: { Authorization: `Bearer ${store.get()}` } });
    if (!res.ok) return;
    box.replaceChildren(h("img", { src: URL.createObjectURL(await res.blob()), alt: "" }));
  } catch { /* 照片取不到就显示图标 */ }
}

function mealSheet(x, redraw) {
  const photo = h("div", { class: "meal-photo", hidden: !x.has_photo });
  if (x.has_photo) loadPhoto(x.id, photo);
  openSheet(`${x.kind} · ${x.name}`, photo,
    h("div", { class: "macro-grid" }, [["热量", x.macros.kcal, "千卡"], ["蛋白质", x.macros.protein_g, "克"], ["碳水", x.macros.carbs_g, "克"], ["脂肪", x.macros.fat_g, "克"]]
      .map(([k, v, u]) => h("div", {}, h("b", {}, Math.round(v), h("small", {}, u)), h("span", {}, k)))),
    x.items.length ? h("div", {}, h("h3", {}, "吃了什么"), h("ul", { class: "tips" }, x.items.map((t) => h("li", {}, t)))) : null,
    h("p", { class: "caption" }, ["营养是估算的", x.confidence ? `把握：${x.confidence}` : "", x.note].filter(Boolean).join("；")),
    h("button", { class: "btn danger block", type: "button", onclick: async () => {
      try { const r = await api(`/iron/api/meals/${x.id}`, { method: "DELETE" }); closeSheet(); redraw(await api("/iron/api/meals")); }
      catch (err) { alert(err.message); }
    } }, "删除这条"));
}

function recommendBox(redraw) {
  const out = h("div");
  const go = h("button", { class: "btn block", type: "button" }, icon("food", "sm"), "推荐这一餐");
  go.addEventListener("click", async () => {
    go.disabled = true; out.replaceChildren(h("p", { class: "muted" }, "营养师在按你的目标、今天还差多少、天气和状态挑…"));
    try {
      const r = await api("/iron/api/meals/recommend", { method: "POST", body: JSON.stringify({ kind: foodState.kind, appetite: foodState.appetite }) });
      out.replaceChildren(recCard(r, redraw));
    } catch (err) { out.replaceChildren(h("p", { class: "error" }, err.message)); }
    go.disabled = false;
  });
  return h("div", { class: "card" },
    h("div", { class: "muted" }, "胃口"), pills(APPETITES, foodState.appetite, (v) => { foodState.appetite = v; }),
    h("p", { class: "caption" }, "按上面「记一餐」选的餐次推荐。"), go, out);
}

function recCard(r, redraw) {
  const rec = r.recommendation, tot = r.total;
  const save = h("button", { class: "btn ghost block", type: "button" }, icon("check", "sm"), "就吃这个，记下来");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const d = await api("/iron/api/meals/record", { method: "POST", body: JSON.stringify({
        kind: foodState.kind, name: rec.title, items: rec.dishes.map((x) => `${x.name}${x.amount ? ` ${x.amount}` : ""}`), macros: tot }) });
      save.textContent = "已记下"; redraw(d);
    } catch (err) { save.disabled = false; alert(err.message); }
  });
  return h("div", { class: "rec" },
    h("h3", {}, rec.title),
    rec.why ? h("p", { class: "lede" }, rec.why) : null,
    h("div", { class: "tags" }, r.considered.map((x) => chip(x))),
    h("div", { class: "rows" }, rec.dishes.map((x) => h("div", { class: "row-item" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, [x.amount, `蛋白质 ${Math.round(x.protein_g)} 克`].filter(Boolean).join(" · "))),
      h("span", { class: "row-end" }, `${Math.round(x.kcal)} 千卡`)))),
    h("div", { class: "macro-grid" }, [["热量", tot.kcal, "千卡"], ["蛋白质", tot.protein_g, "克"], ["碳水", tot.carbs_g, "克"], ["脂肪", tot.fat_g, "克"]]
      .map(([k, v, u]) => h("div", {}, h("b", {}, Math.round(v), h("small", {}, u)), h("span", {}, k)))),
    r.remaining ? h("p", { class: "caption" }, `今天还剩约 ${Math.round(r.remaining.kcal)} 千卡、蛋白质约 ${Math.round(r.remaining.protein_g)} 克`) : null,
    r.warning ? h("div", { class: "notice-line" }, icon("alert", "xs"), r.warning) : null,
    rec.tips ? h("p", { class: "muted" }, rec.tips) : null,
    save, h("p", { class: "caption" }, "营养是估算的。"));
}

async function presetsBox(redraw) {
  const data = await api("/iron/api/meals/presets").catch(() => ({ presets: [], note: "" }));
  const grid = h("div", { class: "rows" });
  const draw = () => grid.replaceChildren(...data.presets.filter((p) => foodState.scene === "全部" || p.scene === foodState.scene).map((p) =>
    h("div", { class: "row-item preset" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, p.name, h("span", { class: "scene" }, p.scene)),
        h("span", { class: "row-sub" }, `${p.kcal} 千卡 · 蛋白质 ${p.protein_g} 克 · 碳水 ${p.carbs_g} 克 · 脂肪 ${p.fat_g} 克`),
        p.tip ? h("span", { class: "row-sub" }, p.tip) : null),
      h("button", { class: "btn small ghost", type: "button", onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { redraw(await api("/iron/api/meals/preset", { method: "POST", body: JSON.stringify({ preset: p.id, kind: foodState.kind }) })); e.target.textContent = "已记"; }
        catch (err) { alert(err.message); }
      } }, "记一餐"))));
  draw();
  return h("div", { class: "card" }, pills(SCENES, foodState.scene, (v) => { foodState.scene = v; draw(); }), grid,
    h("p", { class: "caption" }, data.note));
}

// ---- 数据：人体图 → 常看指标 → 每周复盘 → 其余指标 → 导入数据（spec [2026-10-23] §13）-------------------
const COMMON = ["weight", "resting_hr", "sleep", "steps"];
const OTHER = [
  ["身体", ["weight_trend", "bmi"]],
  ["恢复", ["hrv_sdnn", "hrv_rmssd", "hrv"]],
  ["血压", ["blood_pressure"]],
  ["能量", ["bmr", "tdee", "kcal_target", "protein_target"]],
];

async function data(view) {
  const [list, muscles, brief] = await Promise.all([
    metrics(), api("/iron/api/muscles").catch(() => null), api("/iron/api/brief").catch(() => null)]);
  const m = byKey(list);
  view.append(section("肌肉人体图", h("span", { class: "caption" }, "最近 28 天"), muscles ? bodyMap(muscles) : failed(new Error("人体图暂时算不出来"), () => render())));
  view.append(h("div", { class: "fresh" }, icon("info", "xs"),
    list.as_of ? `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开任一项看怎么算的` : "还没有同步到健康数据"));
  view.append(metricGroup("常看指标", COMMON.map((k) => m[k]).filter(Boolean)));
  if (brief) view.append(section("每周复盘", h("span", { class: "caption" }, `${md(brief.week.from)}–${md(brief.week.to)}`), weekCard(brief.week)));
  const rest = OTHER.map(([title, keys]) => [title, keys.map((k) => m[k]).filter(Boolean)]).filter(([, xs]) => xs.length);
  if (rest.length) {
    const more = h("details", { class: "more-metrics" }, h("summary", {}, "更多指标", icon("chevron", "xs")),
      ...rest.map(([title, xs]) => metricGroup(title, xs)));
    view.append(more);
  }
  const [catalog, files] = await Promise.all([catalogSection(), filesSection()]);
  view.append(catalog, files, section("导入数据", null, addGrid()));
}

function metricGroup(title, present) {
  const have = present.filter((x) => x.value != null);
  const miss = present.filter((x) => x.value == null);
  const wide = have.filter((x) => (x.series || []).length > 1);
  const small = have.filter((x) => (x.series || []).length <= 1);
  const tiles = [...wide.map((x) => tile(x, { wide: true })), ...small.map((x, i) => tile(x, { wide: small.length % 2 === 1 && i === small.length - 1 }))];
  return section(title, null,
    tiles.length ? h("div", { class: "tiles" }, tiles) : null,
    miss.length ? h("div", { class: "card missing-list" }, h("div", { class: "rows" }, miss.map((x) => h("button", { class: "row-item", type: "button", onclick: () => metricSheet(x) },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, missingHint(x))),
      h("span", { class: "row-end" }, "暂无", icon("chevron", "sm")))))) : null);
}

// 人体图：正面、背面两张，每个肌群按近期练没练着色（规则计算，见 protools/muscle_map.py）
const BODY = {
  front: [
    ["肩", [["ellipse", { cx: 35, cy: 47, rx: 9, ry: 8 }], ["ellipse", { cx: 85, cy: 47, rx: 9, ry: 8 }]]],
    ["胸", [["ellipse", { cx: 50, cy: 54, rx: 10, ry: 9 }], ["ellipse", { cx: 70, cy: 54, rx: 10, ry: 9 }]]],
    ["肱二头肌", [["rect", { x: 23, y: 58, width: 10, height: 26, rx: 5 }], ["rect", { x: 87, y: 58, width: 10, height: 26, rx: 5 }]]],
    ["核心", [["rect", { x: 46, y: 66, width: 28, height: 38, rx: 8 }]]],
    ["股四头肌", [["rect", { x: 42, y: 120, width: 16, height: 50, rx: 7 }], ["rect", { x: 62, y: 120, width: 16, height: 50, rx: 7 }]]],
  ],
  back: [
    ["肩", [["ellipse", { cx: 35, cy: 47, rx: 9, ry: 8 }], ["ellipse", { cx: 85, cy: 47, rx: 9, ry: 8 }]]],
    ["背", [["path", { d: "M42 42 H78 L76 94 Q60 102 44 94 Z" }]]],
    ["肱三头肌", [["rect", { x: 23, y: 58, width: 10, height: 26, rx: 5 }], ["rect", { x: 87, y: 58, width: 10, height: 26, rx: 5 }]]],
    ["臀", [["ellipse", { cx: 51, cy: 112, rx: 10, ry: 10 }], ["ellipse", { cx: 69, cy: 112, rx: 10, ry: 10 }]]],
    ["腘绳肌", [["rect", { x: 42, y: 124, width: 16, height: 44, rx: 7 }], ["rect", { x: 62, y: 124, width: 16, height: 44, rx: 7 }]]],
    ["小腿", [["ellipse", { cx: 50, cy: 188, rx: 7, ry: 15 }], ["ellipse", { cx: 70, cy: 188, rx: 7, ry: 15 }]]],
  ],
};
// 身体的轮廓（不着色的部分）
const SILHOUETTE = [
  ["circle", { cx: 60, cy: 20, r: 12 }], ["rect", { x: 55, y: 31, width: 10, height: 8, rx: 3 }],
  ["rect", { x: 38, y: 38, width: 44, height: 68, rx: 14 }],
  ["rect", { x: 21, y: 84, width: 9, height: 30, rx: 4 }], ["rect", { x: 90, y: 84, width: 9, height: 30, rx: 4 }],
  ["rect", { x: 40, y: 102, width: 40, height: 20, rx: 8 }],
  ["rect", { x: 43, y: 168, width: 14, height: 46, rx: 6 }], ["rect", { x: 63, y: 168, width: 14, height: 46, rx: 6 }],
];

function bodyFigure(side, groups, onPick) {
  const svg = s("svg", { viewBox: "0 0 120 222", class: "body-svg", role: "img", "aria-label": side === "front" ? "正面" : "背面" });
  for (const [tag, attrs] of SILHOUETTE) svg.append(s(tag, { ...attrs, class: "body-base" }));
  const by = Object.fromEntries(groups.map((g) => [g.name, g]));
  for (const [name, shapes] of BODY[side]) {
    const g = by[name];
    const part = s("g", { class: `muscle m-${g?.status || "none"}`, tabindex: "0", role: "button", "aria-label": `${name}：${g?.status_name || ""}` });
    for (const [tag, attrs] of shapes) part.append(s(tag, attrs));
    const t = s("title", {}); t.textContent = `${name}：${g?.status_name || ""}`; part.append(t);
    part.addEventListener("click", () => onPick(g));
    part.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(g); } });
    svg.append(part);
  }
  return h("figure", { class: "body-fig" }, svg, h("figcaption", {}, side === "front" ? "正面" : "背面"));
}

function bodyMap(mm) {
  const pick = (g) => g && openSheet(g.name,
    h("div", { class: "sheet-big" }, chip(g.status_name, g.status === "recent" ? "good" : g.status === "none" ? "attention" : "")),
    h("div", { class: "kv" }, h("span", {}, "最近一次"), h("span", {}, g.last ? md(g.last) : "最近 28 天没练")),
    h("div", { class: "kv" }, h("span", {}, "近 7 天"), h("span", {}, `${g.sets_7d} 组`)),
    g.history.length ? h("div", {}, h("h3", {}, "最近练过"), h("ul", { class: "tips" }, g.history.map((x) => h("li", {}, x)))) : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(g.status === "none" ? `我的${g.name}很久没练了，怎么补上？` : `我的${g.name}最近练得够吗？`) }, icon("coach", "sm"), "问问教练"));
  const untrained = mm.untrained || [];
  return h("div", { class: "card body-card" },
    h("div", { class: "body-pair" }, bodyFigure("front", mm.front, pick), bodyFigure("back", mm.back, pick)),
    h("div", { class: "legend" },
      h("span", {}, h("i", { class: "m-recent" }), "两天内练过"), h("span", {}, h("i", { class: "m-week" }), "本周练过"), h("span", {}, h("i", { class: "m-none" }), "7 天以上没练")),
    mm.sessions === 0 ? h("p", { class: "muted" }, "最近 28 天还没有训练记录：在首页打卡，或在对话里说“今天练了……”就会记下来。")
      : untrained.length ? h("div", { class: "notice-line" }, icon("info", "xs"), `7 天以上没练：${untrained.join("、")}`) : h("p", { class: "muted" }, "这周主要肌群都练到了。"),
    untrained.length && mm.sessions ? h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我最近${untrained.join("、")}没怎么练，下次训练怎么补上？`) }, icon("coach", "sm"), "让教练帮我补上") : null,
    h("p", { class: "caption" }, mm.note));
}

function missingHint(m) {
  const missing = m.missing || [];
  const how = missing.join("；").match(/（(.+?)）/);
  if (how) return `${how[1]}后显示`;
  return missing.length ? `还缺：${missing.join("、")}` : "暂无数据";
}

// ---- 添加数据：上传报告、随手记一条、导入苹果健康、基因数据、连接设备 ----------------------------
const MB = 1024 * 1024;
const REPORT_EXT = [".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".heif", ".tif", ".tiff",
  ".xlsx", ".xlsm", ".csv", ".docx", ".pptx", ".txt", ".md", ".markdown", ".json", ".xml", ".html", ".htm", ".log"];
const GENE_EXT = [".txt", ".csv", ".vcf", ".gz", ".bgz", ".bgzf", ".zip"];
const ADD = [
  ["upload", "上传报告", "体检报告、化验单，自动识别指标", () => uploadSheet()],
  ["note", "随手记一条", "症状、血压、用药，一句话就行", () => journalSheet()],
  ["phone", "导入苹果健康", "睡眠、心率、步数一次导入", () => appleSheet()],
  ["dna", "基因数据", "WeGene、23andMe 等原始数据", () => geneSheet()],
  ["watch", "连接设备", "Garmin、Oura、Whoop", () => devicesSheet()],
];
function addGrid() {
  return h("div", { class: "adds" }, ADD.map(([ic, title, sub, go]) => pressable(h("div", { class: "add" },
    h("span", { class: "add-icon" }, icon(ic)), h("span", { class: "add-text" }, h("b", {}, title), h("span", {}, sub))), go)));
}
function addRow() {
  const items = [...ADD.slice(0, 3), ["more", "更多", "", () => { location.hash = "#data"; }]];
  return h("div", { class: "add-row" }, items.map(([ic, title, , go]) => h("button", { class: "add-mini", type: "button", onclick: go },
    h("span", { class: "add-icon" }, icon(ic)), title)));
}
const extOf = (name) => { const m = String(name).toLowerCase().match(/\.[a-z0-9]+$/); return m ? m[0] : ""; };
function sizeText(n) { return n >= MB ? `${(n / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`; }
function progressBar() {
  const fill = h("span"); const box = h("div", { class: "progress", hidden: true }, fill);
  return { el: box, set(p) { box.hidden = false; fill.style.width = `${Math.round(Math.min(1, Math.max(0, p)) * 100)}%`; }, hide() { box.hidden = true; } };
}
// 上传用 XHR：要看得到上传进度（fetch 拿不到）
function send(url, form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.setRequestHeader("Authorization", `Bearer ${store.get()}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress?.(e.loaded / e.total); };
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText || "{}"); } catch { /* 不是 JSON */ }
      if (xhr.status === 401 || xhr.status === 403) { signOut(); reject(new Error("登录已失效，请重新登录")); return; }
      if (xhr.status >= 300) { reject(new Error(body.detail || body.msg || `上传失败（${xhr.status}）`)); return; }
      resolve(body);
    };
    xhr.onerror = () => reject(new Error("上传失败，请检查网络后再试"));
    xhr.send(form);
  });
}
// 选文件：点选或拖进来；不支持的类型、太大的文件当场提示，不上传
function picker({ accept, maxBytes, multiple = true, hint, onPick }) {
  const input = h("input", { type: "file", accept: accept.join(","), multiple, class: "sr-only" });
  const zone = h("label", { class: "drop" }, input, icon("upload"), h("b", {}, "选择文件，或拖到这里"), h("span", {}, hint));
  const take = (files) => {
    const ok = [], bad = [];
    for (const f of files) {
      if (!accept.includes(extOf(f.name))) bad.push(`${f.name}：不支持这种文件`);
      else if (f.size > maxBytes) bad.push(`${f.name}：超过 ${sizeText(maxBytes)}`);
      else if (!f.size) bad.push(`${f.name}：文件是空的`);
      else ok.push(f);
    }
    onPick(multiple ? ok : ok.slice(0, 1), bad);
  };
  input.addEventListener("change", () => { take([...input.files]); input.value = ""; });
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); take([...e.dataTransfer.files]); });
  return zone;
}

function uploadSheet() {
  let picked = [];
  const list = h("div", { class: "rows" });
  const bar = progressBar();
  const msg = h("div", { class: "muted", role: "status" });
  const go = h("button", { class: "btn block", type: "button", disabled: true }, "上传并识别");
  const zone = picker({ accept: REPORT_EXT, maxBytes: 20 * MB, hint: "PDF、图片、Excel/CSV、Word、文本，单个不超过 20MB，可以一次选多个",
    onPick: (ok, bad) => {
      picked = ok;
      list.replaceChildren(...ok.map((f) => h("div", { class: "row-item" }, icon("file", "sm"), h("div", { class: "row-main" }, h("span", { class: "row-title" }, f.name)), h("span", { class: "row-end" }, sizeText(f.size)))));
      msg.textContent = bad.join("；"); msg.className = bad.length ? "error" : "muted";
      go.disabled = !ok.length;
    } });
  go.addEventListener("click", async () => {
    const form = new FormData();
    for (const f of picked) form.append("files", f);
    go.disabled = true; msg.className = "muted"; msg.textContent = "上传中…";
    try {
      const r = await send("/files/upload?file=true", form, (p) => bar.set(p));
      const n = (r.data || []).length;
      msg.textContent = r.code === 0 ? `已上传 ${n} 个文件，正在识别，结果会出现在「数据」页的「我的文件」和「全部指标」里。` : `有的文件没有上传成功：${r.msg || ""}`;
      picked = []; list.replaceChildren();
      cache.files = null; watchFiles();
    } catch (err) { msg.className = "error"; msg.textContent = err.message; go.disabled = false; }
  });
  openSheet("上传报告", zone, list, bar.el, msg, go,
    h("p", { class: "caption" }, "上传后自动识别报告里的指标，一般几十秒到几分钟。只进你自己的记录。"));
}

// ---- 随手记一条 ----
const KIND_NAMES = { symptom: "症状", condition: "病情", note: "笔记", measurement: "读数", medication: "用药" };
function journalError(err) {
  const text = String(err.message || err);
  if (/text model/i.test(text)) return "服务器还没有配置文字模型，暂时不能按句子记录。";
  if (/could not be read/i.test(text)) return "这句话没读懂，换个说法再试试。";
  return text;
}
async function journalSheet() {
  const box = h("textarea", { rows: "3", placeholder: "比如：今天有点头疼；早上血压 128/82；开始吃维生素 D", "aria-label": "记一条" });
  const go = h("button", { class: "btn block", type: "button" }, "记下");
  const out = h("div", { class: "section" });
  const recent = h("div", { class: "card" }, h("div", { class: "muted" }, "正在读取…"));
  async function loadRecent() {
    try {
      const r = await apiData("/api/v1/journal");
      const days = r.days || [];
      recent.replaceChildren(days.length ? h("div", { class: "rows" }, days.flatMap((d) => d.entries.map((x) => h("div", { class: "row-item" },
        h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.text), h("span", { class: "row-sub" }, `${md(d.date)} · ${KIND_NAMES[x.kind] || x.kind}${x.display && x.display !== x.text ? ` · ${x.display}` : ""}`)),
        x.kind === "medication" ? null : h("button", { class: "icon-btn", type: "button", "aria-label": "删除这条", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { await apiData(`/api/v1/journal/${x.id}`, { method: "DELETE" }); loadRecent(); } catch (err) { out.replaceChildren(h("div", { class: "error" }, err.message)); }
        } }, icon("x", "sm"))))))
        : h("div", { class: "empty" }, icon("note"), "最近 30 天还没有记录。"));
    } catch (err) { recent.replaceChildren(h("div", { class: "error" }, err.message)); }
  }
  go.addEventListener("click", async () => {
    const text = box.value.trim();
    if (!text) return;
    go.disabled = true; out.replaceChildren(h("div", { class: "muted" }, "正在记…"));
    try {
      const r = await apiData("/api/v1/journal/sentence", { method: "POST", body: JSON.stringify({ text, tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "" }) });
      const lines = [
        ...(r.written || []).map((x) => ["记下了", `${x.text}${x.value ? ` ${x.value}${x.unit || ""}` : ""}（${KIND_NAMES[x.kind] || x.kind}）`]),
        ...(r.medications || []).map((x) => ["用药", `${x.text}${x.reason ? `：${x.reason}` : ""}`]),
        ...(r.skipped || []).map((x) => ["没有记", `${x.text || x.quote || ""}${x.reason ? `：${x.reason}` : ""}`]),
      ];
      out.replaceChildren(h("div", { class: "card" }, lines.length ? lines.map(([k, v]) => h("div", { class: "kv" }, h("span", {}, k), h("span", {}, v))) : h("div", { class: "muted" }, r.already_logged ? "这条已经记过了。" : "没有可记的内容。")));
      box.value = ""; cache.metrics = null; loadRecent();
    } catch (err) { out.replaceChildren(h("div", { class: "error" }, journalError(err))); }
    go.disabled = false;
  });
  openSheet("随手记一条", h("p", { class: "lede" }, "用自己的话写，一句话里写几件也行。症状、病情会对上标准名称，提到的用药会加进用药清单，其他的记为笔记。"),
    box, go, out, h("div", {}, h("h3", {}, "最近 30 天"), recent));
  loadRecent();
}

// ---- 导入苹果健康 ----
let appleTimer = null;
async function appleSheet() {
  const bar = progressBar();
  const status = h("div", { class: "section" });
  function show(job) {
    if (!job) { status.replaceChildren(); return; }
    if (job.state === "running") {
      status.replaceChildren(h("div", { class: "card" }, h("div", { class: "prog-head" }, h("span", { class: "spin" }), `${job.stage}…`),
        job.written ? h("p", { class: "caption" }, `已写入 ${job.written.toLocaleString("zh-CN")} 条读数`) : null));
    } else if (job.state === "done") {
      status.replaceChildren(h("div", { class: "card" },
        h("div", { class: "prog-head" }, h("span", { class: "ok-dot" }, icon("check")), job.error || "导入完成"),
        h("div", { class: "kv" }, h("span", {}, "读到的记录"), h("span", {}, `${job.records.toLocaleString("zh-CN")} 条`)),
        h("div", { class: "kv" }, h("span", {}, "新增读数"), h("span", {}, `${job.added.toLocaleString("zh-CN")} 条${job.added ? "" : "（之前导入过）"}`)),
        job.first ? h("div", { class: "kv" }, h("span", {}, "覆盖日期"), h("span", {}, `${job.first} 至 ${job.last}`)) : null,
        h("a", { class: "btn ghost block", href: "#data", onclick: () => { cache.metrics = null; closeSheet(); render(); } }, "去看数据")));
    } else {
      status.replaceChildren(h("div", { class: "error" }, job.error || "导入没有成功"));
    }
  }
  async function poll() {
    clearTimeout(appleTimer);
    try {
      const { job } = await api("/iron/api/import/apple");
      show(job);
      if (job?.state === "running") appleTimer = setTimeout(poll, 2000);
      else if (job?.state === "done") cache.metrics = null;
    } catch (err) { status.replaceChildren(h("div", { class: "error" }, err.message)); }
  }
  const zone = picker({ accept: [".zip", ".xml"], maxBytes: 2048 * MB, multiple: false, hint: "健康 App 导出的「导出.zip」（export.zip），最大 2GB",
    onPick: async (ok, bad) => {
      if (bad.length) { status.replaceChildren(h("div", { class: "error" }, bad.join("；"))); return; }
      if (!ok.length) return;
      const form = new FormData();
      form.append("file", ok[0]);
      form.append("tz", Intl.DateTimeFormat().resolvedOptions().timeZone || "");
      status.replaceChildren(h("div", { class: "muted" }, `正在上传 ${ok[0].name}（${sizeText(ok[0].size)}）…`));
      try { await send("/iron/api/import/apple", form, (p) => bar.set(p)); bar.hide(); poll(); }
      catch (err) { bar.hide(); status.replaceChildren(h("div", { class: "error" }, err.message)); }
    } });
  openSheet("导入苹果健康",
    h("ol", { class: "steps-ol" },
      h("li", {}, "在 iPhone 上打开「健康」App，点右上角的头像"),
      h("li", {}, "选「导出所有健康数据」，等它生成「导出.zip」"),
      h("li", {}, "把压缩包存到「文件」，或用隔空投送发到电脑"),
      h("li", {}, "在这里选择这个压缩包上传，后台会自动导入")),
    zone, bar.el, status,
    h("p", { class: "caption" }, "会导入睡眠、心率、心率变异性、步数、体重等能识别的数据；同一个包再导入不会重复计数。只进你自己的记录。"));
  poll();
}

// ---- 基因数据 ----
async function geneSheet() {
  const bar = progressBar();
  const msg = h("div", { class: "muted", role: "status" });
  const current = h("div", { class: "card" }, h("div", { class: "muted" }, "正在读取…"));
  async function load() {
    try {
      const { active_set: a } = await apiData("/api/v1/genomics/active-set");
      current.replaceChildren(...(a ? [
        h("div", { class: "kv" }, h("span", {}, "来源"), h("span", {}, a.vendor || a.format_id || "—")),
        h("div", { class: "kv" }, h("span", {}, "位点数"), h("span", {}, `${num(a.n_rows)}（已检出 ${num(a.n_called)}）`)),
        h("div", { class: "kv" }, h("span", {}, "参考基因组"), h("span", {}, a.build_detected || a.build_declared || "—")),
        a.activated_at ? h("div", { class: "kv" }, h("span", {}, "生效时间"), h("span", {}, md(a.activated_at))) : null,
      ] : [h("div", { class: "empty" }, icon("dna"), "还没有生效的基因数据。")]));
    } catch (err) { current.replaceChildren(h("div", { class: "error" }, err.message)); }
  }
  const zone = picker({ accept: GENE_EXT, maxBytes: 200 * MB, multiple: false, hint: "WeGene、23andMe、AncestryDNA、MyHeritage、FTDNA 的原始数据，或 VCF；可以是压缩包",
    onPick: async (ok, bad) => {
      if (bad.length) { msg.className = "error"; msg.textContent = bad.join("；"); return; }
      if (!ok.length) return;
      const form = new FormData(); form.append("files", ok[0]);
      msg.className = "muted"; msg.textContent = "上传中…";
      try {
        const r = await send("/files/upload?file=true", form, (p) => bar.set(p));
        msg.textContent = r.code === 0 ? "已上传，正在处理；处理完成后会替换当前的基因数据。" : `没有上传成功：${r.msg || ""}`;
        setTimeout(load, 5000);
      } catch (err) { msg.className = "error"; msg.textContent = err.message; }
    } });
  openSheet("基因数据", h("div", {}, h("h3", {}, "当前生效的集合"), current), zone, bar.el, msg,
    h("p", { class: "caption" }, "每人只有一份生效的基因数据，新文件处理成功后替换当前的。这里只显示概况，不显示具体基因型。"));
  load();
}

// ---- 连接设备 ----
async function devicesSheet() {
  const body = h("div", { class: "section" }, h("div", { class: "muted" }, "正在读取…"));
  async function load() {
    try {
      const { providers = [] } = await apiData("/api/v1/pulse/providers");
      if (!providers.length) {
        body.replaceChildren(h("div", { class: "card" },
          h("div", { class: "empty" }, icon("watch"), "这台服务器还没有配置可以连接的设备。连接 Garmin、Oura、Whoop 需要先在服务端配置各家的开发者凭证。"),
          h("p", { class: "caption" }, "现在可以先导入苹果健康数据，或上传报告。"),
          h("div", { class: "form-actions" },
            h("button", { class: "btn ghost", type: "button", onclick: appleSheet }, "导入苹果健康"),
            h("button", { class: "btn ghost", type: "button", onclick: uploadSheet }, "上传报告"))));
        return;
      }
      body.replaceChildren(h("div", { class: "card" }, h("div", { class: "rows" }, providers.map((p) => {
        const on = p.status === "connected";
        return h("div", { class: "row-item" },
          h("div", { class: "row-main" }, h("span", { class: "row-title" }, p.name || p.slug), h("span", { class: "row-sub" }, p.description || (on ? "已连接" : "未连接"))),
          h("button", { class: `btn small ${on ? "ghost" : ""}`, type: "button", onclick: () => (on ? unlink(p) : link(p)) }, on ? "断开" : "连接"));
      }))));
    } catch (err) { body.replaceChildren(h("div", { class: "error" }, err.message)); }
  }
  async function link(p) {
    try {
      const r = await apiData("/api/v1/pulse/user/providers/link", { method: "POST", body: JSON.stringify({ provider_slug: p.slug, platform: p.platform || "theta", auth_type: p.auth_type || "oauth2" }) });
      if (r?.link_web_url) {
        window.open(r.link_web_url, "_blank", "noopener");
        body.prepend(h("p", { class: "caption" }, "在新打开的页面里授权，完成后回到这里刷新。"));
      }
      setTimeout(load, 3000);
    } catch (err) { body.prepend(h("div", { class: "error" }, err.message)); }
  }
  async function unlink(p) {
    try { await apiData("/api/v1/pulse/user/providers/unlink", { method: "POST", body: JSON.stringify({ provider_slug: p.slug, platform: p.platform || "theta" }) }); load(); }
    catch (err) { body.prepend(h("div", { class: "error" }, err.message)); }
  }
  openSheet("连接设备", body);
  load();
}

// ---- 我的文件 ----
let filesTimer = null;
async function files(force = false) {
  if (!cache.files || force) cache.files = await apiData("/api/v1/data/uploaded-files?limit=20&offset=0");
  return cache.files;
}
// mirobody 先把文件标成"已处理"，过几秒才写入识别出的项数：刚上传 2 分钟内还是 0 项的，仍算识别中
const recent = (f) => Date.now() - Date.parse(f.upload_time || 0) < 2 * 60 * 1000;
const busy = (f) => !f.error && f.upload_status !== "failed" && (!f.processed || (!f.indicators_count && recent(f)));
function fileState(f) {
  if (f.error || f.upload_status === "failed") return ["没识别出来", "attention"];
  if (busy(f)) return ["识别中", ""];
  return f.indicators_count ? [`识别出 ${f.indicators_count} 项`, "good"] : ["没有识别出指标", ""];
}
function viewUrl(f) {
  const url = f.url_full || "";
  return url ? `${url}${url.includes("?") ? "&" : "?"}access_token=${encodeURIComponent(store.get())}` : "";
}
function fileRows(list) {
  return list.length ? h("div", { class: "rows" }, list.map((f) => {
    const [state, tone] = fileState(f);
    return h("button", { class: "row-item", type: "button", onclick: () => fileSheet(f) },
      h("span", { class: "mark" }, icon("file", "sm")),
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, f.original_name || f.file_name),
        h("span", { class: "row-sub" }, `上传于 ${md(f.upload_time)}${f.report_date ? ` · 报告 ${md(f.report_date)}` : ""}`)),
      h("span", { class: "row-end" }, chip(state, tone)));
  })) : h("div", { class: "empty" }, icon("upload"), "还没有上传过报告。");
}
async function filesSection() {
  const box = h("div", { class: "card", id: "files-box" });
  try { box.append(fileRows((await files(true)).files || [])); } catch (err) { box.append(h("div", { class: "error" }, err.message)); }
  if ((cache.files?.files || []).some(busy)) watchFiles();
  return section("我的文件", h("button", { class: "link", type: "button", onclick: uploadSheet }, icon("upload", "xs"), "上传"), box);
}
// 上传后每 3 秒看一次识别进度，最多 3 分钟；数据页开着时就地更新
function watchFiles(left = 60) {
  clearTimeout(filesTimer);
  filesTimer = setTimeout(async () => {
    try {
      const data = await files(true);
      const box = document.getElementById("files-box");
      if (box) box.replaceChildren(fileRows(data.files || []));
      if ((data.files || []).some(busy) && left > 0) watchFiles(left - 1);
      else { cache.metrics = null; const cat = document.getElementById("catalog-box"); if (cat) catalogSection().then((s) => cat.closest("section")?.replaceWith(s)); }
    } catch { /* 下次再看 */ }
  }, 3000);
}
function fileSheet(f) {
  const [state, tone] = fileState(f);
  const msg = h("div", { class: "muted", role: "status" });
  const date = h("input", { type: "date", value: String(f.report_date || "").slice(0, 10), max: new Date().toISOString().slice(0, 10), "aria-label": "报告日期" });
  const saveDate = h("button", { class: "btn ghost small", type: "button" }, "保存日期");
  saveDate.addEventListener("click", async () => {
    if (!date.value) return;
    try {
      await apiData("/api/v1/health-indicators/file-date", { method: "POST", body: JSON.stringify({ file_key: f.file_key, report_date: date.value }) });
      msg.className = "muted"; msg.textContent = "已改好，这份报告里的数据按新日期记。";
      cache.metrics = null; files(true).then((d) => { const box = document.getElementById("files-box"); if (box) box.replaceChildren(fileRows(d.files || [])); });
    } catch (err) { msg.className = "error"; msg.textContent = err.message; }
  });
  const del = h("div", { class: "form-actions" });
  const ask = () => del.replaceChildren(h("button", { class: "btn danger", type: "button", onclick: askDelete }, "删除这份文件"));
  const askDelete = () => del.replaceChildren(
    h("button", { class: "btn ghost", type: "button", onclick: ask }, "取消"),
    h("button", { class: "btn", style: "background:var(--warn);color:#fff", type: "button", onclick: async () => {
      try {
        await apiData("/api/v1/data/delete-files", { method: "POST", body: JSON.stringify({ message_id: f.created_source_id || f.id, file_keys: [f.file_key] }) });
        cache.files = null; cache.metrics = null; closeSheet(); render();
      } catch (err) { msg.className = "error"; msg.textContent = err.message; }
    } }, "确定删除"));
  ask();
  openSheet(f.original_name || f.file_name,
    h("div", { class: "tags" }, chip(state, tone), chip(String(f.file_type || f.type || "").toUpperCase()), chip(sizeText(f.file_size || 0))),
    h("div", {},
      h("div", { class: "kv" }, h("span", {}, "上传时间"), h("span", {}, md(f.upload_time))),
      h("div", { class: "kv" }, h("span", {}, "报告日期"), h("span", {}, f.report_date ? `${md(f.report_date)}${f.date_confirmed ? "" : "（未确认）"}` : "未识别出")),
      f.error ? h("div", { class: "kv" }, h("span", {}, "原因"), h("span", {}, f.error)) : null),
    viewUrl(f) ? h("a", { class: "btn ghost block", href: viewUrl(f), target: "_blank", rel: "noopener" }, icon("open", "sm"), "查看原文件") : null,
    h("div", {}, h("h3", {}, "报告日期不对？"), h("div", { class: "row" }, date, saveDate)),
    msg,
    h("div", {}, h("h3", {}, "删除"), h("p", { class: "caption" }, "删除后，从这份文件识别出的数据也会一起去掉。"), del));
}

// ---- 全部指标（含报告里识别出的化验值） ----
const LOINC_ZH = {
  "29463-7": "体重", "8302-2": "身高", "39156-5": "BMI", "8480-6": "收缩压", "8462-4": "舒张压",
  "40443-4": "静息心率", "8867-4": "心率", "41950-7": "步数", "80404-7": "心率变异性（SDNN）", "93832-4": "睡眠时长",
  "14647-2": "总胆固醇", "2093-3": "总胆固醇", "14646-4": "高密度脂蛋白胆固醇", "2085-9": "高密度脂蛋白胆固醇",
  "22748-8": "低密度脂蛋白胆固醇", "13457-7": "低密度脂蛋白胆固醇", "2089-1": "低密度脂蛋白胆固醇",
  "14927-8": "甘油三酯", "2571-8": "甘油三酯", "14771-0": "空腹血糖", "1558-6": "空腹血糖", "4548-4": "糖化血红蛋白",
  "718-7": "血红蛋白", "1742-6": "谷丙转氨酶（ALT）", "1920-8": "谷草转氨酶（AST）", "14682-9": "肌酐", "2160-0": "肌酐",
  "14933-6": "尿酸", "3084-1": "尿酸", "3016-3": "促甲状腺激素（TSH）", "2276-4": "铁蛋白", "1989-3": "25-羟维生素 D",
  "14635-7": "25-羟维生素 D", "6690-2": "白细胞", "789-8": "红细胞", "777-3": "血小板", "30522-7": "超敏 C 反应蛋白",
  "59408-5": "血氧饱和度", "2708-6": "血氧饱和度", "9279-1": "呼吸频率", "8310-5": "体温",
};
// 苹果健康导入后的每日汇总：名字是 dailyTotalSteps.apple_health_export 这种内部名，换成中文、注明来源
const DAILY_ZH = {
  dailytotalsteps: "步数", dailysteps: "步数", "dailytotalsleepanalysis_asleep(total)": "睡眠时长",
  "dailytotalsleepanalysis_asleep(core)": "核心睡眠", "dailytotalsleepanalysis_asleep(deep)": "深睡",
  "dailytotalsleepanalysis_asleep(rem)": "快速眼动睡眠", "dailytotalsleepanalysis_inbed": "在床时间",
  dailytotalactiveenergyburned: "活动能量", dailytotalbasalenergyburned: "静息能量",
  dailytotaldistancewalkingrunning: "步行跑步距离", dailytotalflightsclimbed: "爬楼层数", dailyavgheartrate: "平均心率",
};
const SOURCES_ZH = { apple_health_export: "苹果健康", apple_health: "苹果健康", garmin: "Garmin", oura: "Oura", whoop: "Whoop" };
function zhName(r) {
  if (LOINC_ZH[r.code]) return LOINC_ZH[r.code];
  const [base, source] = String(r.name || r.indicator || "").split(".");
  const zh = DAILY_ZH[base.toLowerCase()];
  if (zh) return source ? `${zh}（${SOURCES_ZH[source] || source}）` : zh;
  return r.indicator || r.name;
}
// 值按单位换成好读的写法：毫秒的睡眠换成小时，计数取整
function readable(r) {
  const n = Number(r.latest_value);
  const unit = String(r.unit || "");
  if (unit === "ms" && Number.isFinite(n)) return [String(Math.round((n / 3_600_000) * 10) / 10), "小时"];
  if ((unit === "{#}" || unit === "count") && Number.isFinite(n)) return [num(Math.round(n)), ""];
  return [Number.isFinite(n) && /\.0+$/.test(String(r.latest_value)) ? num(n) : String(r.latest_value), unit];
}
async function catalogSection() {
  const box = h("div", { class: "card", id: "catalog-box" });
  try {
    const rows = ((await apiData("/api/v1/health-indicators")).rows || []).filter((r) => r.latest_value != null)
      .sort((a, b) => String(b.last_date).localeCompare(String(a.last_date)));
    const row = (r) => h("button", { class: "row-item", type: "button", onclick: () => indicatorSheet(r) },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, zhName(r)), h("span", { class: "row-sub" }, `${md(r.last_date)} · ${r.count} 条记录`)),
      h("span", { class: "row-end" }, h("b", { style: "color:var(--ink)" }, readable(r)[0]), readable(r)[1], icon("chevron", "sm")));
    const list = h("div", { class: "rows" }, rows.slice(0, 8).map(row));
    box.append(rows.length ? list : h("div", { class: "empty" }, icon("chart"), "还没有指标数据。"));
    if (rows.length > 8) {
      const all = h("button", { class: "link", type: "button", style: "align-self:flex-start" }, `显示全部 ${rows.length} 项`);
      all.addEventListener("click", () => { list.replaceChildren(...rows.map(row)); all.remove(); });
      box.append(all);
    }
  } catch (err) { box.append(h("div", { class: "error" }, err.message)); }
  return section("全部指标", null, box, h("p", { class: "caption", style: "padding:0 2px" }, "包括从上传的报告里识别出的化验值。"));
}
function indicatorSheet(r) {
  const name = zhName(r);
  openSheet(name,
    h("div", { class: "sheet-big" }, h("span", { class: "v" }, readable(r)[0], readable(r)[1] ? h("small", {}, readable(r)[1]) : null)),
    h("div", {},
      h("div", { class: "kv" }, h("span", {}, "最近一次"), h("span", {}, md(r.last_date))),
      h("div", { class: "kv" }, h("span", {}, "第一次"), h("span", {}, md(r.first_date))),
      h("div", { class: "kv" }, h("span", {}, "记录数"), h("span", {}, `${r.count} 条`)),
      h("div", { class: "kv" }, h("span", {}, "标准名"), h("span", {}, `${r.indicator || r.name}${r.code ? `（LOINC ${r.code}）` : ""}`))),
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我的${name}最近一次是 ${readable(r).join(" ").trim()}，正常吗？要注意什么？`) }, icon("coach", "sm"), "问问教练"));
}

// ---- 我的 ---------------------------------------------------------------------------------
const SEX = { male: "男", female: "女" };
async function me(view) {
  const data = await profile();
  const email = tokenEmail();
  view.append(h("div", { class: "card" }, h("div", { class: "profile-head" },
    h("span", { class: "avatar" }, (email[0] || "我").toUpperCase()),
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, email || "已登录"), h("span", { class: "row-sub" }, "IronM 账号")))));
  const box = h("div", { class: "card" });
  const edit = h("button", { class: "link", type: "button" }, icon("edit", "xs"), "编辑");
  edit.addEventListener("click", () => { edit.hidden = true; profileForm(box, data, () => { edit.hidden = false; }); });
  profileView(box, data);
  view.append(section("档案", edit, box, h("p", { class: "caption", style: "padding:0 2px" }, "用来计算 BMI、基础代谢、每日热量和蛋白质目标。")));
  view.append(citySection());
  view.append(section("说明", null, h("div", { class: "card" }, h("p", { class: "muted" }, "AI 健身管家会把你的问题交给最合适的专业角色（训练规划、动作教练、营养、恢复、数据分析），涉及几个方面时再把他们的意见整合起来。建议仅供参考，不能代替医生；身体不适请及时就医。"))));
  view.append(h("button", { class: "btn danger block", type: "button", onclick: signOut }, icon("logout", "sm"), "退出登录"));
}
// 城市：用来取实时天气（spec [2026-10-23] §13）
function citySection() {
  const box = h("div", { class: "card" });
  const draw = (place) => box.replaceChildren(h("div", { class: "kv" }, h("span", {}, "城市"),
    h("span", {}, place.label || place.city || "未设置", " ", h("button", { class: "link", type: "button", onclick: () => edit(place) }, icon("edit", "xs"), place.city ? "修改" : "设置"))));
  const edit = (place) => {
    const input = h("input", { type: "text", maxlength: "30", value: place.city || "", placeholder: "比如：杭州、北京朝阳" });
    const msg = h("div", { class: "error" });
    const form = h("form", {}, h("label", {}, "所在城市", input), msg,
      h("div", { class: "form-actions" },
        h("button", { class: "btn ghost", type: "button", onclick: () => draw(place) }, "取消"),
        h("button", { class: "btn", type: "submit" }, "保存")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); msg.textContent = "正在查找…";
      try { draw(await api("/iron/api/place", { method: "PUT", body: JSON.stringify({ city: input.value.trim() }) })); }
      catch (err) { msg.textContent = err.message; }
    });
    box.replaceChildren(form); input.focus();
  };
  api("/iron/api/place").then(draw).catch(() => draw({}));
  return section("天气", null, box, h("p", { class: "caption", style: "padding:0 2px" }, "按城市取实时天气和空气质量，首页和教练安排训练、饮食时会用上。"));
}

function profileView(box, data) {
  const p = data.profile, src = data.sources || {};
  const from = (k) => (src[k] === "账户" ? h("span", { class: "hint" }, "（来自账户）") : null);
  const rows = [
    ["身高", p.height_cm ? `${num(p.height_cm)} 厘米` : "未填写", null],
    ["出生日期", p.birth ? p.birth.replace(/^(\d+)-0?(\d+)-0?(\d+)$/, "$1年$2月$3日") : "未填写", from("birth")],
    ["性别", SEX[p.sex] || "未填写", from("sex")],
    ["目标", data.options.goal[p.goal] || "未选择", null],
    ["日常活动", data.options.activity[p.activity] || "未选择", null],
  ];
  box.replaceChildren(...rows.map(([k, v, hint]) => h("div", { class: "kv" }, h("span", {}, k), h("span", {}, v, hint))));
}
function profileForm(box, data, done) {
  const p = data.profile;
  const opts = (map, value) => [h("option", { value: "" }, "请选择"), ...Object.entries(map).map(([k, v]) => h("option", { value: k, selected: k === value }, v))];
  const msg = h("div", { class: "error" });
  const today = new Date().toISOString().slice(0, 10);
  const form = h("form", {},
    h("label", {}, "身高（厘米）", h("input", { name: "height_cm", type: "number", inputmode: "decimal", step: "0.1", min: "100", max: "250", value: p.height_cm ?? "" })),
    h("label", {}, "出生日期", h("input", { name: "birth", type: "date", max: today, value: p.birth ?? "" })),
    h("label", {}, "性别", h("select", { name: "sex" }, opts(SEX, p.sex))),
    h("label", {}, "目标", h("select", { name: "goal" }, opts(data.options.goal, p.goal))),
    h("label", {}, "日常活动", h("select", { name: "activity" }, opts(data.options.activity, p.activity))),
    msg,
    h("div", { class: "form-actions" },
      h("button", { class: "btn ghost", type: "button", onclick: () => { profileView(box, data); done(); } }, "取消"),
      h("button", { class: "btn", type: "submit" }, "保存")));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = {};
    for (const [k, v] of new FormData(form)) if (v !== "") body[k] = k === "height_cm" ? Number(v) : v;
    msg.textContent = "保存中…";
    try {
      await api("/iron/api/profile", { method: "PUT", body: JSON.stringify(body) });
      cache.metrics = null;
      const fresh = await profile(true);
      Object.assign(data, fresh);
      profileView(box, data); done();
    } catch (err) { msg.textContent = err.message; }
  });
  box.replaceChildren(form);
}

// ---- 教练（对话） ---------------------------------------------------------------------------
const chat = { session: null, messages: [], busy: false, ctrl: null, loaded: false, pending: null, back: "home", els: null, files: [] };
function resetChat() { chat.ctrl?.abort(); Object.assign(chat, { session: null, messages: [], busy: false, ctrl: null, loaded: false, pending: null, files: [] }); }
// 对话附件（spec [2026-10-23] §11）：图片和报告，单个不超过 20MB；先传到存储，发问时带上，由这一轮登记和识别
const CHAT_EXT = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"];
function attachPick(input) {
  const picked = [...input.files]; input.value = "";
  for (const f of picked) {
    if (!CHAT_EXT.includes(extOf(f.name))) { chat.files.push({ name: f.name, error: "只能附图片或 PDF" }); continue; }
    if (f.size > 20 * MB) { chat.files.push({ name: f.name, error: "超过 20MB" }); continue; }
    const item = { name: f.name, progress: 0, data: null, error: "" };
    chat.files.push(item);
    const form = new FormData(); form.append("files", f);
    send("/files/upload", form, (x) => { item.progress = x; drawFiles(); })
      .then((body) => { const d = (body.data || [])[0]; if (d?.file_key) item.data = d; else item.error = body.msg || "上传失败"; })
      .catch((err) => { item.error = err.message; })
      .finally(() => { drawFiles(); syncComposer(); });
  }
  drawFiles(); syncComposer();
}
function drawFiles() {
  const box = chat.els?.files;
  if (!box) return;
  box.hidden = !chat.files.length;
  box.replaceChildren(...chat.files.map((f, i) => h("span", { class: `attach${f.error ? " bad" : ""}` },
    icon(extOf(f.name) === ".pdf" ? "file" : "upload", "xs"),
    h("span", { class: "attach-name" }, f.name),
    f.error ? h("small", {}, f.error) : f.data ? null : h("small", {}, `${Math.round(f.progress * 100)}%`),
    h("button", { type: "button", "aria-label": "去掉这个附件", onclick: () => { chat.files.splice(i, 1); drawFiles(); syncComposer(); } }, icon("x", "xs")))));
}
function askCoach(question) { chat.pending = question; closeSheet(); location.hash = "#chat"; }

const STARTERS = [
  ["给我安排今天的训练", "按你的目标和状态"],
  ["深蹲时膝盖疼怎么办", "动作教练 · 恢复"],
  ["早餐怎么吃够蛋白质", "营养"],
  ["我最近的静息心率正常吗", "数据分析"],
];

function chatPage(view) {
  const thread = h("div", { class: "thread" });
  const input = h("textarea", { rows: "1", placeholder: "问训练、动作、饮食或恢复…", "aria-label": "输入问题", enterkeyhint: "send" });
  const send = h("button", { class: "send", type: "submit", "aria-label": "发送" }, icon("send"));
  const fileInput = h("input", { type: "file", accept: CHAT_EXT.join(","), multiple: true, class: "sr-only", onchange: (e) => attachPick(e.currentTarget) });
  const clip = h("label", { class: "clip", "aria-label": "附图片或报告", title: "附图片或报告" }, fileInput, icon("plus", "sm"));
  const files = h("div", { class: "attach-row", hidden: true });
  const form = h("form", { class: "composer" }, clip, input, send);
  const fresh = h("button", { class: "icon-btn", type: "button", "aria-label": "新对话", title: "新对话", onclick: () => { resetChat(); chat.loaded = true; drawThread(); input.focus(); } }, icon("plus", "sm"));
  view.append(h("div", { class: "chat" },
    h("div", { class: "chat-bar" },
      h("a", { class: "icon-btn", href: `#${chat.back}`, "aria-label": "返回" }, icon("back", "sm")),
      h("div", { class: "who" }, h("b", {}, "教练"), h("span", {}, "训练规划 · 动作教练 · 营养 · 恢复 · 数据分析")),
      fresh),
    thread, files, form));
  chat.els = { thread, input, send, files };
  drawFiles();
  const grow = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; syncComposer(); };
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (chat.busy) { chat.ctrl?.abort(); return; }
    if (chat.files.some((f) => !f.data && !f.error)) return;  // 附件还在上传：回车也不发
    const q = input.value; input.value = ""; grow(); ask(q || (chat.files.some((f) => f.data) ? "帮我看看这个" : ""));
  });
  (async () => {
    if (!chat.loaded) { thread.replaceChildren(h("div", { class: "welcome" }, h("div", { class: "typing" }, h("i"), h("i"), h("i")))); await loadLatest(); }
    if (chat.els?.thread !== thread) return;  // 已经离开对话页
    drawThread();
    if (chat.pending) {
      const q = chat.pending; chat.pending = null;
      if (chat.busy) { input.value = q; grow(); } else ask(q);
    } else if (matchMedia("(min-width: 760px)").matches) input.focus();
  })();
}

function syncComposer() {
  if (!chat.els) return;
  const { input, send } = chat.els;
  send.classList.toggle("stop", chat.busy);
  send.replaceChildren(icon(chat.busy ? "stop" : "send"));
  send.setAttribute("aria-label", chat.busy ? "停止" : "发送");
  const uploading = chat.files.some((f) => !f.data && !f.error);
  const ready = chat.files.some((f) => f.data);
  send.disabled = !chat.busy && (uploading || (!input.value.trim() && !ready));
}

function drawThread() {
  if (!chat.els) return;
  const { thread } = chat.els;
  if (!chat.messages.length) {
    thread.replaceChildren(h("div", { class: "welcome" },
      h("div", { class: "mark-big" }, icon("coach")),
      h("div", {}, h("h2", {}, "你的教练团队"), h("p", { class: "muted" }, "管家会把问题交给合适的专业角色，涉及几个方面时再整合起来；每条回答都能展开看依据和来源。")),
      h("div", { class: "starters" }, STARTERS.map(([q, who]) => h("button", { class: "starter", type: "button", onclick: () => ask(q) }, q, h("span", {}, who))))));
  } else {
    thread.replaceChildren(...chat.messages.map((msg) => (msg.el = msgView(msg))));
  }
  syncComposer();
  thread.scrollTop = thread.scrollHeight;
}

function refresh(msg) {
  if (!chat.els || !msg.el || !msg.el.isConnected) return;
  const { thread } = chat.els;
  const near = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 160;
  const el = msgView(msg);
  msg.el.replaceWith(el); msg.el = el;
  if (near) thread.scrollTop = thread.scrollHeight;
}

function paragraphs(text) {
  return text.trim().split(/\n{2,}/).map((p) => h("p", {}, p.split("\n").flatMap((line, i) => (i ? [h("br"), line] : [line]))));
}

function msgView(msg) {
  if (msg.role === "user") return h("div", { class: "msg-user" }, msg.text,
    (msg.files || []).length ? h("div", { class: "msg-files" }, msg.files.map((n) => h("span", {}, icon("file", "xs"), n))) : null);
  const running = !msg.done;
  const experts = msg.steps.filter((x) => x.id !== "coach");
  let head;
  if (running) {
    const busy = msg.steps.filter((x) => !x.done);
    head = msg.text ? "正在整理回答…"
      : busy.length ? `${busy.map((x) => x.name).join("、")}正在${busy.some((x) => x.id === "coach") ? "安排" : "回答"}…`
        : msg.steps.length ? "管家正在整合…" : "正在理解你的问题…";
  } else {
    head = experts.length ? `${experts.length} 位专业角色参与` : msg.steps.length ? "管家直接回答" : "";
  }
  const showList = msg.open || (running && !msg.text);
  const prog = msg.steps.length || running ? h("div", { class: "prog" },
    h("button", { class: "prog-head", type: "button", "aria-expanded": String(showList), onclick: () => { msg.open = !showList; refresh(msg); } },
      running ? h("span", { class: "spin" }) : h("span", { class: "ok-dot" }, icon("check")), head,
      !running && msg.steps.length ? h("span", { style: "color:var(--accent)" }, showList ? " · 收起" : " · 查看过程") : null),
    showList && msg.steps.length ? h("ol", { class: "prog-list" }, msg.steps.map((x) => h("li", {},
      h("span", { class: "who" }, x.done ? h("span", { class: "ok-dot" }, icon("check")) : h("span", { class: "spin" }), x.name),
      x.task ? h("span", { class: "what" }, x.task) : null,
      x.done && x.result && !running ? h("div", { class: "res" }, x.result) : null))) : null) : null;
  return h("div", { class: "msg-coach" },
    prog,
    msg.text ? h("div", { class: "answer" }, paragraphs(msg.text)) : running ? h("div", { class: "typing", "aria-label": "正在回答" }, h("i"), h("i"), h("i")) : null,
    msg.notices.map((t) => h("div", { class: "msg-note" }, t)),
    msg.cards.map((c) => cardView(msg, c)),
    msg.error ? h("div", { class: "msg-note" }, msg.error) : null,
    msg.sources ? h("details", { class: "sources", open: msg.srcOpen, ontoggle: (e) => { msg.srcOpen = e.currentTarget.open; } },
      h("summary", {}, icon("chevron", "xs"), "依据与来源"), h("div", { class: "src" }, msg.sources)) : null,
    msg.done && msg.id && msg.text ? h("div", { class: "rate" },
      h("button", { type: "button", class: msg.rating === 1 ? "on" : "", onclick: () => rate(msg, 1) }, icon("up", "xs"), "有用"),
      h("button", { type: "button", class: msg.rating === -1 ? "on" : "", onclick: () => rate(msg, -1) }, icon("down", "xs"), "没用")) : null);
}

function applyBlock(msg, b) {
  switch (b.type) {
    case "start": msg.id = b.id || msg.id; break;
    case "tool_call":
      if (b.id === "sources") break;
      if (String(b.id || "").startsWith("card-")) { if (!msg.cards.some((c) => c.id === b.id)) msg.cards.push({ id: b.id, kind: b.args?.kind, draft: b.args?.draft, data: null, state: "", busy: false, error: "" }); break; }
      if (!msg.steps.some((x) => x.id === b.id)) msg.steps.push({ id: b.id, name: b.name || "", task: b.args?.["任务"] || "", result: "", done: false });
      break;
    case "tool_result": {
      if (b.tool_call_id === "sources") { msg.sources = String(b.content || ""); break; }
      if (String(b.tool_call_id || "").startsWith("card-")) {
        const card = msg.cards.find((c) => c.id === b.tool_call_id);
        if (card) { try { card.data = JSON.parse(b.content || "{}"); } catch { card.data = null; } }
        break;
      }
      const step = msg.steps.find((x) => x.id === b.tool_call_id);
      if (step) { step.done = true; step.result = String(b.content || ""); }
      break;
    }
    case "text": msg.text += b.text || ""; break;
    case "notice": if (b.text) msg.notices.push(b.text); break;
    case "error": msg.error = b.message || "这次没能回答，请稍后再试。"; break;
    case "end": msg.done = true; break;
    default: break;
  }
}

function coachMsg() { return { role: "coach", steps: [], text: "", notices: [], sources: "", cards: [], id: "", error: "", done: false, open: false, srcOpen: false, rating: 0, el: null }; }

// 预览卡片（计划、训练记录）：确认才写入，写入后能撤销；状态从服务端取（刷新后也对）
const CARD_STATE = { pending: "", confirmed: "已保存", cancelled: "已取消", undone: "已撤销" };
function cardView(msg, card) {
  const d = card.data;
  if (!d) return null;
  if (!card.state && !card.busy) { card.busy = true; loadCard(msg, card); }
  const state = card.state || "pending";
  const expired = state === "pending" && Date.parse(d.expires) < Date.now();
  const plan = card.kind === "plan";
  const body = plan
    ? [d.changes ? h("p", { class: "card-changes" }, d.changes) : null,
      ...(d.sessions || []).map((x) => h("div", { class: `pv-session${x.changed && d.replaces ? " changed" : ""}` },
        h("div", { class: "pv-head" }, h("b", {}, `${x.day} · ${x.name}`), h("span", { class: "muted" }, `约 ${x.minutes} 分钟`)),
        h("ul", {}, x.items.map((it) => h("li", {}, it))))),
      (d.removed || []).length ? h("p", { class: "muted" }, `去掉：${d.removed.join("、")}`) : null]
    : [(d.items || []).length ? h("ul", {}, d.items.map((it) => h("li", {}, it))) : null,
      d.rpe ? h("p", { class: "muted" }, `感受 ${d.rpe} 分`) : null, d.note ? h("p", { class: "muted" }, d.note) : null];
  const act = (action) => cardAction(msg, card, action);
  const buttons = state === "pending" && !expired
    ? [h("button", { class: "btn small", type: "button", disabled: card.busy, onclick: () => act("confirm") }, plan ? "确认，保存计划" : "确认，记下"),
      h("button", { class: "btn quiet small", type: "button", disabled: card.busy, onclick: () => act("cancel") }, "取消")]
    : state === "confirmed"
      ? [h("span", { class: "chip good" }, plan ? "计划已保存" : "已记下"), h("button", { class: "btn quiet small", type: "button", disabled: card.busy, onclick: () => act("undo") }, "撤销")]
      : [h("span", { class: "chip" }, expired ? "已过期，让教练重新生成" : CARD_STATE[state] || state)];
  return h("div", { class: `preview ${state}` },
    h("div", { class: "pv-title" }, icon(plan ? "dumbbell" : "check", "sm"), h("b", {}, d.title), h("span", { class: "muted" }, d.headline || "")),
    ...body,
    h("div", { class: "pv-actions" }, buttons),
    card.error ? h("p", { class: "msg-note" }, card.error) : null);
}
async function loadCard(msg, card) {
  try { card.state = (await api(`/iron/api/drafts/${encodeURIComponent(card.draft)}`)).draft.state; }
  catch { card.state = "pending"; }
  card.busy = false; refresh(msg);
}
async function cardAction(msg, card, action) {
  card.busy = true; card.error = ""; refresh(msg);
  try {
    card.state = (await api(`/iron/api/drafts/${encodeURIComponent(card.draft)}/${action}`, { method: "POST", body: "{}" })).draft.state;
    cache.metrics = null;
  } catch (err) { card.error = err.message; }
  card.busy = false; refresh(msg);
}

async function ask(question) {
  const q = String(question || "").trim();
  if (!q || chat.busy) return;
  const msg = coachMsg();
  const attached = chat.files.filter((f) => f.data).map((f) => f.data);
  chat.files = []; drawFiles();
  chat.messages.push({ role: "user", text: q, files: attached.map((f) => f.file_name) }, msg);
  chat.busy = true;
  drawThread();
  try {
    if (!chat.session) chat.session = (await apiData("/api/session", { method: "POST", body: "{}" })).session_id;
    await stream(q, msg, attached);
    if (!msg.text && !msg.error) msg.error = "这次没有收到回答，请稍后再试。";
  } catch (err) {
    if (err.name === "AbortError") msg.notices.push("已停止。");
    else msg.error = err.message || "这次没能回答，请稍后再试。";
  } finally {
    msg.done = true; chat.busy = false; chat.ctrl = null;
    refresh(msg); syncComposer();
  }
}

async function stream(question, msg, attached = []) {
  chat.ctrl = new AbortController();
  syncComposer();
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json", Authorization: `Bearer ${store.get()}` },
    body: JSON.stringify({
      question, session_id: chat.session, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "",
      file_list: attached.map((f) => ({ file_key: f.file_key, file_name: f.file_name, file_type: f.file_type, file_url: f.file_url, file_size: f.file_size })),
    }),
    signal: chat.ctrl.signal,
  });
  if (res.status === 401 || res.status === 403) { signOut(); throw new Error("登录已失效，请重新登录"); }
  if (!res.ok || !res.body) throw new Error(`请求失败（${res.status}）`);
  if (!(res.headers.get("content-type") || "").includes("event-stream")) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.msg || "这次没能回答，请稍后再试。");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith("data:")) continue;
      let block;
      try { block = JSON.parse(line.slice(5)); } catch { continue; }
      if (block.type === "heartbeat") continue;
      applyBlock(msg, block);
      refresh(msg);
    }
  }
}

async function rate(msg, value) {
  if (msg.rating === value) return;
  try {
    await apiData("/api/rating", { method: "POST", body: JSON.stringify({ rating: value, responseId: msg.id }) });
    msg.rating = value; refresh(msg);
  } catch { msg.notices.push("评价没有保存成功，请稍后再试。"); refresh(msg); }
}

async function loadLatest() {
  chat.loaded = true;
  try {
    const list = (await apiData("/api/history")).summaries || [];
    if (!list.length) return;
    const latest = list[0];
    const rows = (await apiData(`/api/history?session_id=${encodeURIComponent(latest.session_id)}`)).history || [];
    chat.session = latest.session_id;
    chat.messages = rows.slice(-30).map((row) => {
      if (row.role === "user") return { role: "user", text: String(row.content || "") };
      const msg = coachMsg();
      msg.id = row.id || ""; msg.done = true;
      if (Array.isArray(row.content_dict)) row.content_dict.forEach((b) => applyBlock(msg, b));
      if (!msg.text) msg.text = String(row.content || "");
      msg.done = true;
      return msg;
    });
  } catch { /* 读不到以前的对话就从空白开始 */ }
}

// ---- 登录 ---------------------------------------------------------------------------------
function loginView(view) {
  const msg = h("div", { class: "error", role: "status" });
  const email = h("input", { name: "email", type: "email", placeholder: "邮箱", autocomplete: "email", value: "you@mirobody.ai" });
  const code = h("input", { name: "code", inputmode: "numeric", placeholder: "验证码", autocomplete: "one-time-code" });
  const send = h("button", { type: "button", class: "btn ghost" }, "获取验证码");
  send.addEventListener("click", async () => {
    msg.textContent = "";
    try { await api("/email/login", { method: "POST", body: JSON.stringify({ email: email.value.trim() }) }); msg.textContent = "验证码已发送（演示账号的验证码是 111111）"; }
    catch (err) { msg.textContent = err.message; }
  });
  const form = h("form", { class: "card" }, email, h("div", { class: "row" }, code, send), h("button", { class: "btn block", type: "submit" }, "登录"), msg);
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); msg.textContent = "";
    try {
      const r = await api("/email/verify", { method: "POST", body: JSON.stringify({ email: email.value.trim(), code: code.value.trim() }) });
      const token = r?.data?.access_token;
      if (!token) throw new Error(r.msg || "登录没有成功");
      store.set(token); render();
    } catch (err) { msg.textContent = err.message; }
  });
  view.append(h("div", { class: "login" },
    h("div", {}, h("div", { class: "wordmark" }, "Iron", h("b", {}, "M")), h("p", { class: "lede", style: "margin-top:10px" }, "AI 健身管家：训练、动作、饮食、恢复和身体数据，交给对的专业角色帮你练。")),
    form));
}

// ---- 路由 ---------------------------------------------------------------------------------
const PAGES = {
  home: { title: "今天", kicker: todayLabel, render: home, skeleton: [200, 300, 320] },
  moves: { title: "动作", render: moves, skeleton: [46, 40, 520] },
  chat: { title: "教练", full: true, render: chatPage },
  food: { title: "饮食", render: food, skeleton: [180, 220, 150] },
  data: { title: "数据", render: data, skeleton: [320, 180, 180] },
  me: { title: "我的", render: me, skeleton: [80, 240] },
};
let renderSeq = 0;

async function render() {
  closeSheet();
  const seq = ++renderSeq;
  const view = $("view");
  const signedIn = Boolean(store.get());
  document.body.classList.remove("chatting");
  if (!signedIn) {
    $("bar").hidden = true; $("tabs").hidden = true; chat.els = null;
    view.replaceChildren(); loginView(view); return;
  }
  const name = (location.hash.slice(1) || "home").split("/")[0];
  const page = PAGES[name] ? name : "home";
  const cfg = PAGES[page];
  document.title = `${cfg.title} · AI 健身管家`;
  for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.tab === page);
  $("tabs").hidden = Boolean(cfg.full);
  $("bar").hidden = Boolean(cfg.full);
  if (cfg.full) {
    document.body.classList.add("chatting");
    view.replaceChildren(); cfg.render(view); return;
  }
  chat.els = null;
  chat.back = page;
  $("title").textContent = cfg.title;
  $("kicker").textContent = cfg.kicker ? cfg.kicker() : "";
  $("avatar").textContent = (tokenEmail()[0] || "我").toUpperCase();
  view.replaceChildren(...skeleton(...(cfg.skeleton || [200])));
  window.scrollTo(0, 0);
  const box = document.createDocumentFragment();
  const holder = h("div");
  try {
    await cfg.render(holder);
    if (seq !== renderSeq) return;
    box.append(...holder.childNodes);
    view.replaceChildren(box);
  } catch (err) {
    if (seq !== renderSeq) return;
    view.replaceChildren(failed(err, () => { cache.metrics = null; cache.profile = null; render(); }));
  }
}

window.addEventListener("hashchange", render);
document.addEventListener("DOMContentLoaded", () => {
  for (const el of document.querySelectorAll(".ti[data-icon]")) el.append(icon(el.dataset.icon));
  render();
});
