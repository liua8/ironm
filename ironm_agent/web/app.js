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
// replaceChildren、append 和 h() 一样跳过 null、false（否则页面上会显示 "null"）
for (const name of ["replaceChildren", "append"]) {
  const raw = Element.prototype[name];
  Element.prototype[name] = function (...kids) { return raw.apply(this, kids.flat(Infinity).filter((k) => k != null && k !== false)); };
}

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
// 图标：造型来自 Lucide（lucide.dev，ISC 许可，见 web/THIRD-PARTY.md），按原样内联，不加载外部资源（spec [2026-10-23] §28）
const P = (d) => ["path", { d }];
const ICONS = {
  home: [P("M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"), P("M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z")],
  dumbbell: [P("M17.596 12.768a2 2 0 1 0 2.829-2.829l-1.768-1.767a2 2 0 0 0 2.828-2.829l-2.828-2.828a2 2 0 0 0-2.829 2.828l-1.767-1.768a2 2 0 1 0-2.829 2.829z"), P("m2.5 21.5 1.4-1.4"), P("m20.1 3.9 1.4-1.4"), P("M5.343 21.485a2 2 0 1 0 2.829-2.828l1.767 1.768a2 2 0 1 0 2.829-2.829l-6.364-6.364a2 2 0 1 0-2.829 2.829l1.768 1.767a2 2 0 0 0-2.828 2.829z"), P("m9.6 14.4 4.8-4.8")],
  coach: [P("M12 8V4H8"), ["rect", { width: "16", height: "12", x: "4", y: "8", rx: "2" }], P("M2 14h2"), P("M20 14h2"), P("M15 13v2"), P("M9 13v2")],
  food: [P("M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"), P("M7 2v20"), P("M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7")],
  chart: [P("M22 12h-4l-3 9L9 3l-3 9H2")],
  body: [["circle", { cx: "12", cy: "5", r: "1" }], P("m9 20 3-6 3 6"), P("m6 8 6 2 6-2"), P("M12 10v4")],
  user: [P("M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"), ["circle", { cx: "12", cy: "7", r: "4" }]],
  trophy: [P("M6 9H4.5a2.5 2.5 0 0 1 0-5H6"), P("M18 9h1.5a2.5 2.5 0 0 0 0-5H18"), P("M4 22h16"), P("M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"), P("M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"), P("M18 2H6v7a6 6 0 0 0 12 0V2Z")],
  back: [P("m15 18-6-6 6-6")],
  plus: [P("M5 12h14"), P("M12 5v14")],
  history: [P("M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"), P("M3 3v5h5"), P("M12 7v5l4 2")],
  send: [P("m5 12 7-7 7 7"), P("M12 19V5")],
  stop: [["rect", { x: "6", y: "6", width: "12", height: "12", rx: "2" }]],
  chevron: [P("m9 18 6-6-6-6")],
  search: [["circle", { cx: "11", cy: "11", r: "8" }], P("m21 21-4.3-4.3")],
  close: [P("M18 6 6 18"), P("m6 6 12 12")],
  check: [P("M20 6 9 17l-5-5")],
  timer: [["circle", { cx: "12", cy: "13", r: "8" }], P("M12 9v4l2 2"), P("M10 2h4")],
  arrowUp: [P("m18 15-6-6-6 6")],
  arrowDown: [P("m6 9 6 6 6-6")],
  bell: [P("M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"), P("M10.3 21a1.94 1.94 0 0 0 3.4 0")],
  mute: [P("M6 8a6 6 0 0 1 9.3-5"), P("M18 8c0 7 3 9 3 9H9"), P("M10.3 21a1.94 1.94 0 0 0 3.4 0"), P("m2 2 20 20")],
  x: [P("M18 6 6 18"), P("m6 6 12 12")],
  info: [["circle", { cx: "12", cy: "12", r: "10" }], P("M12 16v-4"), P("M12 8h.01")],
  alert: [P("m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"), P("M12 9v4"), P("M12 17h.01")],
  heart: [P("M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z")],
  wave: [P("M22 12h-4l-3 9L9 3l-3 9H2")],
  moon: [P("M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z")],
  up: [P("M7 10v12"), P("M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z")],
  down: [P("M17 14V2"), P("M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z")],
  logout: [P("m16 17 5-5-5-5"), P("M21 12H9"), P("M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4")],
  edit: [P("M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"), P("m15 5 4 4")],
  upload: [P("M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"), P("m17 8-5-5-5 5"), P("M12 3v12")],
  note: [P("M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"), P("M14 2v4a2 2 0 0 0 2 2h4"), P("M10 9H8"), P("M16 13H8"), P("M16 17H8")],
  phone: [["rect", { width: "14", height: "20", x: "5", y: "2", rx: "2" }], P("M12 18h.01")],
  dna: [P("m10 16 1.5 1.5"), P("m14 8-1.5-1.5"), P("M15 2c-1.798 1.998-2.518 3.995-2.807 5.993"), P("m16.5 10.5 1 1"), P("m17 6-2.891-2.891"), P("M2 15c6.667-6 13.333 0 20-6"), P("m20 9 .891.891"), P("M3.109 14.109 4 15"), P("m6.5 12.5 1 1"), P("m7 18 2.891 2.891"), P("M9 22c1.798-1.998 2.518-3.995 2.807-5.993")],
  watch: [["circle", { cx: "12", cy: "12", r: "6" }], P("M12 10v2l1 1"), P("m16.13 7.66-.81-4.05a2 2 0 0 0-2-1.61h-2.68a2 2 0 0 0-2 1.61l-.78 4.05"), P("m7.88 16.36.8 4a2 2 0 0 0 2 1.61h2.72a2 2 0 0 0 2-1.61l.81-4.05")],
  file: [P("M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"), P("M14 2v4a2 2 0 0 0 2 2h4")],
  open: [P("M15 3h6v6"), P("M10 14 21 3"), P("M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6")],
  more: [["circle", { cx: "12", cy: "12", r: "1" }], ["circle", { cx: "19", cy: "12", r: "1" }], ["circle", { cx: "5", cy: "12", r: "1" }]],
  sun: [["circle", { cx: "12", cy: "12", r: "4" }], P("M12 2v2"), P("M12 20v2"), P("m4.93 4.93 1.41 1.41"), P("m17.66 17.66 1.41 1.41"), P("M2 12h2"), P("M20 12h2"), P("m6.34 17.66-1.41 1.41"), P("m19.07 4.93-1.41 1.41")],
  cloud: [P("M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z")],
  rain: [P("M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"), P("M16 14v6"), P("M8 14v6"), P("M12 16v6")],
  storm: [P("M6 16.326A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 .5 8.973"), P("m13 12-3 5h4l-3 5")],
  camera: [P("M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"), ["circle", { cx: "12", cy: "13", r: "3" }]],
  play: [P("M6 3l14 9-14 9z")],
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
  const head = title || action ? h("div", { class: "section-head" }, title ? h("h2", {}, title) : null, action) : null;
  return h("section", { class: "section" }, head, ...body);
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
    (m.missing || []).some((x) => x.includes("个人中心")) ? h("a", { class: "btn block", href: "#me" }, "去个人中心填写") : null,
    (m.missing || []).some((x) => x.includes("手表")) ? h("button", { class: "btn block", type: "button", onclick: appleSheet }, icon("phone", "sm"), "导入苹果健康数据") : null,
    CALC_FROM[m.key] ? h("div", { class: "calc-from" }, h("h3", {}, "这个数不能直接改"), h("p", {}, CALC_FROM[m.key][0]), h("p", { class: "muted" }, CALC_FROM[m.key][1]),
      h("a", { class: "btn ghost block", href: "#me", onclick: closeSheet }, "去个人中心修改")) : null,
    MANUAL[m.key] ? h("div", {}, h("h3", {}, "自己记一条、改或删"), recordBox(MANUAL[m.key])) : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我的${m.name}最近怎么样？说明什么？`) }, icon("coach", "sm"), "问问教练"));
}

// ---- 首页：状态卡、计划表、训练日历（spec [2026-10-23] §13）-------------------------------------
const QUICK = {
  "只有 30 分钟": "今天只有 30 分钟，怎么练最有效？",
  "在家没有器械": "今天在家、没有器械，怎么练？",
  "今天想练腿": "今天想练腿，怎么安排？",
  "今天有点累": "今天有点累，还要练吗？怎么安排？",
};
const WEEK = ["一", "二", "三", "四", "五", "六", "日"];
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// 首页（spec [2026-10-23] §34、§64）：一句鼓励的话、安全提醒、今日任务、战报（含月历）、本周计划（带天气）
async function home(view) {
  const [brief, training, week, meals, lib, gear] = await Promise.all([
    api("/iron/api/brief").catch(() => null),
    api("/iron/api/training").catch(() => null),
    api("/iron/api/week").catch(() => null),
    api("/iron/api/meals").catch(() => null),
    exercises().catch(() => null),
    api("/iron/api/gear").catch(() => null),
    checkLive(),
  ]);
  planSessions = training?.plan?.sessions || []; planTargets = training?.targets || {};
  view.append(
    liveNow ? liveEntry({}) : null,
    gearCard(gear),
    alertsBox(brief),
    brief?.checkin ? h("section", { class: "card hc" }, checkinRow(brief.checkin)) : null,
    trainCard(brief, training, week, lib),
    dietCard(meals),
    coachCard(),
    askBox());
}

// ---- 场所与器材（spec [2026-10-23] §107）：首页卡片和"我的"用同一张表，存进记忆里同一份 ----
const GEAR_PLACES = [["gym", "健身房"], ["home", "家里"], ["both", "都有"]];
const GEAR = [["哑铃", "哑铃"], ["壶铃", "壶铃"], ["弹力带", "弹力带"], ["杠铃", "杠铃"], ["单杠", "单杠"], ["器械", "健身器械"]];
const GEAR_WORDS = Object.fromEntries(GEAR);
const gearLine = (g) => {
  const have = [...g.gear.map((x) => GEAR_WORDS[x]), ...(g.custom || [])];
  const home = have.length ? `家里有${have.join("、")}` : "家里只有自重";
  return g.place === "gym" ? "在健身房练，器械都有" : g.place === "both" ? `健身房和家里都练，${home}` : `在家练，${home.slice(2)}`;
};
let gearLater = false;  // 首页卡片点了"以后再说"：这次先收起，下次进首页再出现

function gearForm(g, done) {
  const st = { place: g?.place || null, gear: new Set(g?.gear || []), custom: [...(g?.custom || [])] };
  const home = h("div", { class: "st-row" });
  const msg = h("p", { class: "muted", role: "status" });
  const save = h("button", { class: "btn block", type: "button", onclick: async () => {
    save.disabled = true;
    try { done(await api("/iron/api/gear", { method: "PUT", body: JSON.stringify({ place: st.place, gear: [...st.gear], custom: st.custom }) })); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; save.disabled = false; }
  } }, "好了");
  // 自己加器材（§107 补充）：只写有的；和上面同名的、重复的不再加
  const input = h("input", { type: "text", maxlength: "12", placeholder: "其他器材，比如跳绳、TRX", "aria-label": "其他器材", enterkeyhint: "done" });
  const add = () => {
    const v = input.value.replace(/[、，,；;。\s]+/g, "");
    msg.className = "muted"; msg.textContent = "";
    if (!v) return;
    if (/没有|无|不/.test(v)) { msg.textContent = "写有的器材就行，没有的不用写"; return; }
    if (st.custom.length >= 8) { msg.textContent = "最多加 8 样"; return; }
    const same = GEAR.find(([k, w]) => k === v || w === v);
    if (same) st.gear.add(same[0]); else if (!st.custom.includes(v)) st.custom.push(v);
    input.value = ""; draw(); input.focus();
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); add(); } });  // 输入法选字时的回车不算
  const draw = () => {
    home.hidden = !st.place || st.place === "gym";
    home.replaceChildren(h("span", { class: "label" }, "家里有什么"),
      choice([...GEAR, ["none", "只有自重"]], (k) => k === "none" ? !st.gear.size && !st.custom.length : st.gear.has(k),
        (k) => { if (k === "none") { st.gear.clear(); st.custom = []; } else if (!st.gear.delete(k)) st.gear.add(k); draw(); }),
      st.custom.length ? h("div", { class: "st-chips" }, st.custom.map((n) => h("span", { class: "gear-tag" }, n,
        h("button", { type: "button", "aria-label": `删掉${n}`, onclick: () => { st.custom = st.custom.filter((x) => x !== n); msg.textContent = ""; draw(); } }, icon("x", "xs"))))) : null,
      h("div", { class: "gear-add" }, input, h("button", { class: "btn small ghost", type: "button", onclick: add }, "加上")));
    save.disabled = !st.place;
  };
  draw();
  return h("div", { class: "gear-form" },
    h("div", { class: "st-row" }, h("span", { class: "label" }, "一般在哪练"),
      choice(GEAR_PLACES, (k) => st.place === k, (k) => { st.place = k; draw(); })),
    home, save, msg);
}

// 存完：计划里有要用他没有的器械的动作时，给一个进对话的按钮，改不改由他和管家定
function gearResult(r) {
  if (!r.lacking?.length) return null;
  return h("div", { class: "gear-lack" },
    h("p", {}, `计划里有 ${r.lacking.length} 个动作要用你没有的器械：${r.lacking.join("、")}`),
    h("button", { class: "btn small", type: "button", onclick: () => askCoach(`我的场所和器材改成了：${gearLine(r)}。计划里${r.lacking.join("、")}要用我没有的器械，帮我按现在的器械调一下计划`) }, icon("coach", "sm"), "让管家按现在的器械调"));
}

function gearCard(g) {
  if (!g || g.known || gearLater) return null;
  const card = h("section", { class: "card hc gear-card" });
  card.append(hcHead("场所与器材"),
    h("p", { class: "muted" }, "填一次就好，排计划、换动作都按这个。以后在「我的」里改，或者直接跟管家说。"),
    gearForm(null, (r) => {
      flash("记下了");
      const lack = gearResult(r);
      if (lack) card.replaceChildren(hcHead("场所与器材"), h("p", { class: "muted" }, gearLine(r)), lack); else card.remove();
    }),
    h("button", { class: "link gear-later", type: "button", onclick: () => { gearLater = true; card.remove(); } }, "以后再说"));
  return card;
}

function gearSection() {
  const row = h("div", { class: "card gear-row" }, h("p", { class: "muted" }, "正在读取…"));
  const draw = (g) => row.replaceChildren(
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, g.known && g.place ? gearLine(g) : g.known ? "管家记过，但没说在哪练" : "还没填"),
      g.text && !g.form ? h("span", { class: "row-sub" }, `管家记的：${g.text}`) : null,
      h("span", { class: "row-sub" }, "也可以直接跟管家说，比如「搬家了，家里只有哑铃」。")),
    h("div", { class: "btn-row" },
      h("button", { class: "btn small", type: "button", onclick: () => {
        const box = h("div", { class: "sheet-stack" });
        box.append(gearForm(g, (r) => {
          draw(r); flash("记下了");
          const lack = gearResult(r);
          if (lack) box.replaceChildren(lack); else closeSheet();
        }));
        openSheet("场所与器材", box);
      } }, g.known ? "修改" : "填一下"),
      h("button", { class: "btn quiet small", type: "button", onclick: () => { location.hash = "#chat"; } }, icon("coach", "sm"), "跟管家说")));
  api("/iron/api/gear").then(draw).catch(() => row.replaceChildren(h("p", { class: "muted" }, "暂时读不到，稍后再试。")));
  return section("场所与器材", null, row);
}

// ---- 首页三块（spec [2026-10-23] §104 需求 3）：看一部分，点开就地展开 ----
const exImg = (lib, name) => lib?.exercises?.find((x) => x.name === name)?.images?.[0]?.url || "";
function thumb(lib, name, cls = "thumb") {
  const url = exImg(lib, name);
  return url ? h("img", { class: cls, src: url, alt: "", loading: "lazy" }) : h("span", { class: `${cls} none` }, icon("dumbbell", "sm"));
}
const hcHead = (label, extra) => h("div", { class: "hc-head" }, h("span", { class: "label" }, label), extra || null);
// 读不到和没有分开：读不到时说读不到，不当成"没有计划"（§104 需求 1）
const notLoaded = (label, what) => h("section", { class: "card hc" }, hcHead(label),
  h("p", { class: "muted" }, `没读到${what}。`), h("button", { class: "btn ghost small", type: "button", onclick: () => render() }, "重试"));

function trainCard(brief, tr, week, lib) {
  if (!tr || !week) return notLoaded("训练", "今天的训练安排");
  const t = brief?.today?.training, today = week.days?.find((d) => d.today);
  const card = (...kids) => h("section", { class: "card hc" }, ...kids);
  if (!tr.plan) {
    return card(hcHead("训练"), h("div", { class: "hc-title" }, "还没有训练计划"),
      h("div", { class: "btn-row" },
        h("button", { class: "btn small", type: "button", onclick: () => askCoach("帮我排一个每周训练计划") }, "让管家排一份"),
        h("a", { class: "btn ghost small", href: tierHref("plan") }, "从方案库挑")));
  }
  if (!today?.session) return card(hcHead("训练"), h("div", { class: "hc-title" }, "今天休息"), h("p", { class: "muted" }, "散散步、拉拉伸，让身体恢复"));
  if (week.sick?.mode === "rest" && !(t?.done || today.done)) return card(hcHead("训练"), h("div", { class: "hc-title" }, "今天先休息"), h("p", { class: "muted" }, week.sick.why));
  const v = today.version || today.session;
  if (t?.done || today.done) return card(hcHead("训练"), h("div", { class: "hc-title" }, `${v.name} · 练完了`), h("p", { class: "muted" }, "好好恢复"));
  const adjusted = Boolean(today.version || today.changes.length);
  const detail = h("div", { class: "hc-detail", hidden: true },
    todayVersion(today.session, { compact: true }),
    h("a", { class: "link hc-more", href: "#train" }, "完整计划", icon("chevron", "xs")));
  const toggle = h("button", { class: "link hc-toggle", type: "button", "aria-expanded": "false" }, "展开");
  toggle.addEventListener("click", () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = detail.hidden ? "展开" : "收起";
    toggle.setAttribute("aria-expanded", String(!detail.hidden));
  });
  return card(hcHead("训练", adjusted ? h("span", { class: "hc-tag" }, "已调整") : null),
    h("div", { class: "hc-title" }, v.name),
    h("div", { class: "hc-meta" }, `${v.minutes} 分钟 · ${v.items.length} 个动作`),
    h("div", { class: "hc-thumbs" }, v.items.slice(0, 3).map((it) => h("div", { class: "hc-move" }, thumb(lib, it.exercise), h("span", {}, it.exercise)))),
    h("button", { class: "btn block", type: "button", onclick: () => startLive({ today_plan: true }) }, icon("timer", "sm"), liveNow ? "继续训练" : "开始训练"),
    toggle, detail);
}

function dietCard(meals) {
  if (!meals) return notLoaded("饮食", "今天的饮食");
  const tg = meals.target, tot = meals.totals;
  const go = h("button", { class: "btn quiet small", type: "button", onclick: () => logMealSheet(null, meals, () => render()) }, "记一餐");
  if (!tg) {
    return h("section", { class: "card hc" }, hcHead("饮食"),
      h("p", { class: "muted" }, tot.kcal ? `今天已记 ${Math.round(tot.kcal)} 千卡` : "在「我的」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。"),
      h("div", { class: "btn-row" }, go, h("a", { class: "btn ghost small", href: "#me" }, "去填写")));
  }
  const left = Math.max(0, Math.round(tg.kcal - tot.kcal)), lack = Math.max(0, Math.round(tg.protein_g - tot.protein_g));
  const pct = Math.min(100, Math.round((tot.kcal / tg.kcal) * 100));
  return h("section", { class: "card hc" }, hcHead("饮食"),
    h("div", { class: "hc-nums" },
      h("div", {}, h("b", { class: "num" }, String(left)), h("span", {}, "还能吃 · 千卡")),
      h("div", {}, h("b", { class: "num accent" }, String(lack)), h("span", {}, "蛋白质还差 · 克"))),
    h("div", { class: "thin-bar" }, h("span", { style: `width:${pct}%` })),
    h("div", { class: "btn-row" }, go, h("a", { class: "link", href: "#food" }, "看今天吃了什么", icon("chevron", "xs"))));
}

// 管家的调整（§104 需求 3）：在首页直接点"好 / 暂不 / 不用这样调"，不跳进对话
function coachCard() {
  const box = h("section", { class: "hc-coach", hidden: true });
  api("/iron/api/coach/inbox").then((r) => {
    const rows = [];
    const decide = (key, decision, row, done) => async () => {
      for (const b of row.querySelectorAll("button")) b.disabled = true;
      try {
        await api("/iron/api/coach/decide", { method: "POST", body: JSON.stringify({ key, decision }) });
        row.replaceChildren(h("p", { class: "muted" }, done));
      } catch (err) {
        row.append(h("p", { class: "msg-note" }, err.message));
        for (const b of row.querySelectorAll("button")) b.disabled = false;
      }
    };
    for (const x of r.pending) {
      const row = h("div", { class: "card hc-msg" });
      row.append(h("p", {}, x.title), h("div", { class: "btn-row" },
        h("button", { class: "btn small", type: "button", onclick: decide(x.key, "accept", row, "好的，已经按这个安排。") }, "好"),
        h("button", { class: "btn quiet small", type: "button", onclick: decide(x.key, "later", row, "先不调。") }, "暂不")));
      rows.push(row);
    }
    for (const c of r.changes.filter((c) => c.after).slice(0, 3)) {
      const row = h("div", { class: "card hc-msg" });
      row.append(h("p", {}, c.after), h("div", { class: "btn-row" },
        h("button", { class: "btn quiet small", type: "button", onclick: decide(c.key, "undo", row, "好的，已经恢复原来的安排。") }, "不用这样调")));
      rows.push(row);
    }
    if (!rows.length) return;
    if (r.changes.length) api("/iron/api/coach/seen", { method: "POST", body: JSON.stringify({ version: r.version }) }).catch(() => {});
    box.replaceChildren(h("span", { class: "label hc-label" }, "管家"), ...rows);
    box.hidden = false;
  }).catch(() => {});
  return box;
}

// "＋"快捷记录（§104 需求 7）：补打卡、记一餐、记体重（直接填）、记腰围体脂
async function quickAdd() {
  const [m, meals] = await Promise.all([metrics().then(byKey).catch(() => ({})), api("/iron/api/meals").catch(() => null)]);
  let w = Number(m.weight?.value) || 60;
  const shown = h("b", { class: "num qa-w" }, w.toFixed(1));
  const msg = h("p", { class: "muted", role: "status" });
  const step = (d) => () => { w = Math.max(20, Math.round((w + d) * 10) / 10); shown.textContent = w.toFixed(1); };
  const save = h("button", { class: "btn small", type: "button" }, "记下");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await api("/iron/api/readings", { method: "POST", body: JSON.stringify({ kind: "weight", value: w }) });
      cache.metrics = null; msg.textContent = `记下了：${w.toFixed(1)} 公斤`;
    } catch (err) { msg.className = "error"; msg.textContent = err.message; save.disabled = false; }
  });
  const tile = (ic, title, sub, go) => h("button", { class: "qa-tile", type: "button", onclick: go },
    h("span", { class: "qa-icon" }, icon(ic, "sm")), h("span", { class: "qa-text" }, h("b", {}, title), h("small", {}, sub)));
  const checkin = async () => {
    const wk = await api("/iron/api/week").catch(() => null);
    const d = wk?.days?.find((x) => x.today);
    if (d?.session && !d.done) doneSheet((d.version || d.session).name, d.version || null);
    else if (d?.done) doneSheet("训练");  // 今天打过卡了：再记一次加练
    else restSheet(h("p", { class: "muted" }, "今天计划里没有训练。练了别的，直接跟管家说一句练了什么，它会帮你记下。"));
  };
  openSheet("记一下",
    h("div", { class: "qa-grid" },
      tile("check", "练完打卡", "没练也能记", checkin),
      tile("food", "记一餐", "拍一张或说一句", () => logMealSheet(null, meals || { meals: [] }, () => render())),
      tile("note", "记腰围体脂", "和体重一起看", () => recordSheet("腰围和体脂", ["waist", "body_fat"])),
      tile("upload", "上传化验单", "自动识别指标", () => uploadSheet())),
    h("div", { class: "qa-weight" }, h("span", { class: "label" }, "体重 · 直接填"),
      h("div", { class: "qa-row" },
        h("button", { class: "icon-btn", type: "button", "aria-label": "减 0.1 公斤", onclick: step(-0.1) }, "−"),
        h("span", { class: "qa-val" }, shown, h("small", {}, "公斤")),
        h("button", { class: "icon-btn", type: "button", "aria-label": "加 0.1 公斤", onclick: step(0.1) }, "+"), save), msg));
}

// ---- 训练（§104 需求 4、5）：计划 / 轨迹 / 动作库 ----
const TRAIN_TABS = [["plan", "计划"], ["log", "轨迹"], ["moves", "动作库"]];
async function train(view, sub) {
  const cur = TRAIN_TABS.some(([k]) => k === sub) ? sub : "plan";
  view.append(h("div", { class: "seg page-seg", role: "tablist" }, TRAIN_TABS.map(([k, label]) =>
    h("a", { href: `#train/${k}`, role: "tab", class: k === cur ? "on" : "", "aria-selected": String(k === cur) }, label))));
  if (cur === "moves") return moves(view);
  if (cur === "log") return trainLog(view);
  return trainPlan(view);
}

let planDay = null;  // 计划页选中的那天（日期），离开训练页再回来回到今天
async function trainPlan(view) {
  const [tr, week, lib, brief] = await Promise.all([
    api("/iron/api/training").catch(() => null), api("/iron/api/week").catch(() => null), exercises().catch(() => null),
    api("/iron/api/brief").catch(() => null), checkLive()]);
  if (!tr || !week) { view.append(notLoaded("计划", "训练计划")); return; }
  planSessions = tr.plan?.sessions || []; planTargets = tr.targets || {};
  if (!tr.plan) {
    view.append(h("div", { class: "card" }, h("div", { class: "empty" }, icon("dumbbell"), "还没有训练计划"),
      h("div", { class: "btn-row" },
        h("button", { class: "btn small", type: "button", onclick: () => askCoach("帮我排一个每周训练计划") }, "让管家排一份"),
        h("a", { class: "btn ghost small", href: tierHref("plan") }, "从方案库挑"))));
    return;
  }
  let pick = week.days.findIndex((d) => d.date === planDay);  // 改完重画时停在刚才那天（§106）
  if (pick < 0) pick = week.days.findIndex((d) => d.today);
  if (pick < 0) pick = 0;
  const strip = h("div", { class: "day-strip" });
  const detail = h("div");
  const t = brief?.today?.training;
  const rested = (tr.workouts || []).find((x) => x.rest && x.day === week.days.find((d) => d.today)?.date);
  let ordering = null;  // 排顺序时排到一半的动作名
  const orderScope = { v: "today" };
  const draw = () => {
    strip.replaceChildren(...week.days.map((c, i) => h("button", {
      type: "button", class: `ds-day${c.session ? " plan" : ""}${i === pick ? " on" : ""}${c.done ? " done" : ""}`,
      "aria-pressed": String(i === pick), onclick: () => { pick = i; planDay = c.date; ordering = null; draw(); },
    }, h("i", {}, c.today ? "今" : c.weekday.slice(1)), h("b", {}, c.session ? c.session.name.slice(0, 3) : "休"))));
    const c = week.days[pick], shown = c.version || c.session;
    if (!shown) { detail.replaceChildren(h("div", { class: "card" }, h("p", { class: "muted" }, "这天休息。"))); return; }
    // 估算消耗怎么算的（§116）：点标题下的千卡数展开；没体重时直接说要先记体重
    const burnHow = c.burn ? h("p", { class: "caption pd-burn-how", hidden: true }, c.burn.how)
      : h("p", { class: "caption" }, "记了体重才能估消耗");
    const live = c.today && !c.done && !t?.done;
    // 点动作就能改（§106）：按计划本身那一次改（天气改出的版本只是显示），今天那天可以只改今天
    const base = c.session, edited = c.edited || [];
    const ctx = { day: base.day, isToday: c.today, lib, items: base.items, name: weekdayName(base.day) };
    const saveOrder = async () => {
      if (await planEdit(ctx, orderScope, { kind: "order", names: ordering })) ordering = null;
    };
    const list = ordering
      ? [h("div", { class: "card pd-list" }, ordering.map((n, i) => h("div", { class: "pd-item" }, thumb(lib, n),
          h("div", { class: "row-main" }, h("span", { class: "row-title" }, n)),
          h("button", { class: "icon-btn", type: "button", "aria-label": `${n}上移`, disabled: i === 0, onclick: () => { [ordering[i - 1], ordering[i]] = [ordering[i], ordering[i - 1]]; draw(); } }, icon("arrowUp", "sm")),
          h("button", { class: "icon-btn", type: "button", "aria-label": `${n}下移`, disabled: i === ordering.length - 1, onclick: () => { [ordering[i + 1], ordering[i]] = [ordering[i], ordering[i + 1]]; draw(); } }, icon("arrowDown", "sm"))))),
        scopeSeg(c.today, orderScope),
        h("div", { class: "btn-row" },
          h("button", { class: "btn", type: "button", onclick: saveOrder }, "保存顺序"),
          h("button", { class: "btn quiet", type: "button", onclick: () => { ordering = null; draw(); } }, "取消"))]
      : [h("div", { class: "card pd-list" }, shown.items.map((it) => {
        const tg = planTargets[it.exercise];
        const mine = base.items.find((x) => x.exercise === it.exercise) || it;
        return pressable(h("div", { class: "pd-item" }, thumb(lib, it.exercise),
          h("div", { class: "row-main" }, h("span", { class: "row-title" }, it.exercise),
            h("span", { class: "row-sub num" }, `${it.sets} × ${it.reps}${it.load ? ` · ${it.load}` : ""}`),
            tg && !c.version && !edited.length ? h("span", { class: "row-sub accent-text" }, `下次 ${tg.text}`) : null),
          h("span", { class: "pd-edit" }, icon("edit", "xs"))), () => itemSheet(ctx, mine, { v: "today" }));
      }))];
    detail.replaceChildren(
      h("div", { class: "pd-head" },
        h("div", {}, h("h2", {}, shown.name), h("p", { class: "muted" }, `${shown.minutes} 分钟 · ${shown.items.length} 个动作`),
          c.burn ? h("button", { class: "link pd-burn", type: "button", "aria-expanded": "false", onclick: (e) => {
            const open = burnHow.hidden; burnHow.hidden = !open; e.currentTarget.setAttribute("aria-expanded", String(open));
          } }, `约 ${c.burn.low}–${c.burn.high} 千卡（估算）`) : null),
        h("div", { class: "pd-tools" },
          base.items.length > 1 && !ordering ? h("button", { class: "btn quiet small", type: "button", onclick: () => { ordering = base.items.map((x) => x.exercise); orderScope.v = "today"; draw(); } }, "排顺序") : null,
          h("button", { class: "btn quiet small", type: "button", onclick: () => askCoach("帮我看看现在的训练计划，需要调整吗？") }, "让管家改"))),
      burnHow,
      c.warmup && !ordering ? warmupCard(c.warmup) : null,
      c.today && edited.length ? h("div", { class: "pd-edited" }, h("span", {}, `今天改过：${edited.join("；")}`),
        h("button", { class: "link", type: "button", onclick: async () => {
          try { await api("/iron/api/plan/today", { method: "DELETE" }); flash("回到原计划了"); render(); } catch (err) { flash(err.message); }
        } }, "恢复原计划")) : null,
      ...list,
      live && !ordering ? h("div", { class: "btn-row pd-go" },
        h("button", { class: "btn", type: "button", onclick: () => startLive({ today_plan: true }) }, icon("timer", "sm"), liveNow ? "继续训练" : "开始训练"),
        h("button", { class: "btn quiet", type: "button", onclick: () => doneSheet(shown.name, c.version || null) }, "练完直接打卡"),
        rested ? h("span", { class: "muted pd-rest" }, `今天记了没练（${REST_WORDS[rested.rest]}）`)
          : h("button", { class: "link", type: "button", onclick: () => restSheet() }, "今天没练？")) : null);
  };
  draw();
  view.append(strip, detail);
}

// 热身（§116）：由代码按这天的动作生成，默认收起
function warmupCard(w) {
  return h("details", { class: "pd-warmup" },
    h("summary", {}, icon("timer", "xs"), h("span", {}, `热身约 ${w.minutes} 分钟`), h("em", {}, "怎么做"), icon("chevron", "xs")),
    h("ol", {}, w.steps.map((s) => h("li", {}, s))),
    h("p", { class: "caption" }, w.basis));
}

// ---- 计划页直接改（spec [2026-10-23] §106）----
// 只改今天 / 以后都改：今天那天才有得选，别的天改的就是计划本身
function scopeSeg(isToday, st) {
  if (!isToday) { st.v = "always"; return h("p", { class: "caption" }, "改的是每周这一天的计划"); }
  const seg = () => h("div", { class: "seg rep-seg scope-seg", role: "tablist", "aria-label": "改动范围" },
    [["today", "只改今天"], ["always", "以后都改"]].map(([k, w]) => h("button", {
      type: "button", role: "tab", class: st.v === k ? "on" : "", "aria-selected": String(st.v === k),
      onclick: (e) => { st.v = k; e.currentTarget.parentNode.replaceWith(seg()); } }, w)));
  return seg();
}

async function planEdit(ctx, st, edit, msg = null) {
  const scope = ctx.isToday ? st.v : "always";
  try {
    const r = await api("/iron/api/plan/edit", { method: "POST", body: JSON.stringify({ day: ctx.day, scope, edit }) });
    closeSheet(); render(); planEdited(r, scope);
    return true;
  } catch (err) {
    if (msg) { msg.className = "error"; msg.textContent = err.message; } else flash(err.message);
    return false;
  }
}

// 改完的提示：以后都改的带"撤销"（回到改之前那一版）
function planEdited(r, scope) {
  const said = [...r.lines, ...r.notes, ...r.warnings.map((w) => `提醒：${w.split("：")[0]}`)].join("；");
  if (scope === "today" || !r.draft) { flash(`今天改好了：${said}`); return; }
  const undo = h("button", { class: "link", type: "button", onclick: async () => {
    undo.disabled = true;
    try { await api(`/iron/api/drafts/${r.draft.id}/undo`, { method: "POST" }); flash("撤销了，回到改之前"); render(); }
    catch (err) { flash(err.message); }
  } }, "撤销");
  flash(h("span", { class: "flash-row" }, h("span", {}, `改好了：${said}`), undo), 8000);
}

// 次数：一个数或一个范围才能加减（"每侧 8 次""30 秒"这类让管家改）
const parseReps = (s) => {
  const m = String(s).trim().match(/^(\d+)(?:\s*[–~\-]\s*(\d+))?$/);
  return m ? [Number(m[1]), ...(m[2] ? [Number(m[2])] : [])] : null;
};
const repsText = (r) => r.length === 2 ? `${r[0]}–${r[1]}` : String(r[0]);

function itemSheet(ctx, it, st) {
  let sets = it.sets, reps = parseReps(it.reps);
  const was = reps ? repsText(reps) : it.reps;
  const msg = h("p", { class: "muted", role: "status" });
  const steps = h("div", { class: "ie-steps" });
  const save = h("button", { class: "btn block", type: "button", onclick: () => planEdit(ctx, st,
    { kind: "edit", exercise: it.exercise, sets, ...(reps && repsText(reps) !== was ? { reps: repsText(reps) } : {}) }, msg) }, "保存组次");
  const step = (label, value, unit, d, f) => h("div", { class: "stepper" },
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}减`, onclick: () => { f(-d); draw(); } }, "−"),
    h("span", { class: "step-val" }, h("b", { class: "num" }, value), h("small", {}, unit)),
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}加`, onclick: () => { f(d); draw(); } }, "+"));
  const draw = () => {
    steps.replaceChildren(
      step("组数", String(sets), "组", 1, (d) => { sets = Math.min(10, Math.max(1, sets + d)); }),
      reps ? step("每组次数", repsText(reps), "次", 1, (d) => { if (reps.every((x) => x + d >= 1 && x + d <= 50)) reps = reps.map((x) => x + d); })
        : h("p", { class: "caption" }, `每组 ${it.reps}：这种写法用加减改不了，可以让管家改`));
    save.disabled = sets === it.sets && (!reps || repsText(reps) === was);
  };
  draw();
  const only = ctx.items.length <= 1;
  let sure = false;
  const drop = h("button", { class: "link danger-text", type: "button", disabled: only, onclick: () => {
    if (!sure) { sure = true; drop.textContent = "再点一次，确认去掉"; return; }
    planEdit(ctx, st, { kind: "remove", exercise: it.exercise }, msg);
  } }, only ? "这天只剩这一个动作，不能去掉" : "去掉这个动作");
  openSheet(it.exercise,
    h("div", { class: "ie-head" }, thumb(ctx.lib, it.exercise), h("p", { class: "muted" }, `${ctx.name} · 现在 ${it.sets} 组 × ${it.reps}`)),
    scopeSeg(ctx.isToday, st), steps, save,
    h("button", { class: "btn ghost block", type: "button", onclick: () => swapSheet(ctx, it, st) }, icon("dumbbell", "sm"), "换动作"),
    drop, msg);
}

async function swapSheet(ctx, it, st) {
  const box = h("div", { class: "alt-list" }, ...skeleton(64, 64, 64));
  const msg = h("p", { class: "muted", role: "status" });
  openSheet(`换掉 ${it.exercise}`, scopeSeg(ctx.isToday, st), box, msg,
    h("button", { class: "link", type: "button", onclick: () => askCoach(`${ctx.name}的${it.exercise}想换个动作，换成什么好？`) }, "都不合适？问管家"));
  let r;
  try { r = await api(`/iron/api/plan/alternatives?day=${ctx.day}&exercise=${encodeURIComponent(it.exercise)}`); }
  catch (err) { box.replaceChildren(failed(err, () => swapSheet(ctx, it, st))); return; }
  if (!r.alternatives.length) {
    box.replaceChildren(h("p", { class: "muted" }, "按你的器械和身体情况，没找到合适的替代动作，可以问问管家。"));
    return;
  }
  box.replaceChildren(...r.alternatives.map((a) => h("div", { class: "alt-row" }, thumb(ctx.lib, a.name),
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, a.name),
      h("span", { class: "row-sub" }, [a.same ? "同一类" : "相近", a.equipment.join("、"), a.level].join(" · ")),
      a.last ? h("span", { class: "row-sub num" }, a.last) : null),
    h("button", { class: "btn small ghost", type: "button", onclick: async (e) => {
      const b = e.currentTarget; b.disabled = true;
      if (!(await planEdit(ctx, st, { kind: "swap", exercise: it.exercise, to: a.name }, msg))) b.disabled = false;
    } }, "换"))));
}

async function trainLog(view) {
  const [brief, cal, tr] = await Promise.all([
    api("/iron/api/brief").catch(() => null), api("/iron/api/calendar").catch(() => null), api("/iron/api/training").catch(() => null)]);
  if (cal) view.append(h("div", { class: "card log-stats" },
    [["连续打卡", cal.streak_days, "天"], ["本月练了", cal.done_days.length, "天"], ["本月时长", cal.month_minutes, "分钟"]].map(([k, v, u]) =>
      h("div", {}, h("span", { class: "label" }, k), h("b", { class: "num" }, String(v ?? 0), h("small", {}, ` ${u}`))))));
  view.append(reportCard(brief, cal));
  const logs = (tr?.workouts || []).filter((x) => x.done !== false || x.rest).slice(0, 20);
  view.append(section("每天的记录", null, logs.length
    ? h("div", { class: "card log-list" }, logs.map((x) => h("div", { class: `log-row${x.rest ? " rest" : ""}` },
      h("span", { class: "log-day num" }, md(x.day)),
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.rest ? `没练（${REST_WORDS[x.rest]}）` : x.session || "训练"),
        h("span", { class: "row-sub" }, [x.rpe ? `感受 ${x.rpe}` : "", stateText(x), x.note || ""].filter(Boolean).join(" · ") || (x.rest ? "" : x.line))),
      x.photo ? checkinThumb(x) : null)))
    : h("div", { class: "card" }, h("p", { class: "muted" }, "还没有训练记录。练完打个卡，这里就会按天排出来。"))));
}

// ---- 身体（§104 需求 2）：指标、人体图、复盘、原始记录 ----
async function body(view) {
  const mine = await profile().catch(() => null);
  await dataPart(view, mine, "body");
}

// 首页问教练（spec [2026-10-23] §59 需求 2）：发出去就进入对话直接问
function askBox() {
  const input = h("input", { type: "text", placeholder: "跟管家说，比如今天练什么", "aria-label": "跟管家说", enterkeyhint: "send", maxlength: "500" });
  const form = h("form", { class: "ask-box" },
    h("span", { class: "ask-icon" }, icon("coach", "sm")), input,
    h("button", { class: "send", type: "submit", "aria-label": "发送" }, icon("send", "sm")));
  form.addEventListener("submit", (e) => { e.preventDefault(); const q = input.value.trim(); if (q) askCoach(q); else location.hash = "#chat"; });
  return h("div", { class: "ask-wrap" }, form,
    h("button", { class: "link ask-past", type: "button", onclick: historySheet }, icon("history", "xs"), "以前的对话"));
}

// 进度环（spec [2026-10-23] §19）：本周按次数，本月按天数（§64）
function ring(done, planned, label = "本周", unit = "次") {
  const p = planned ? Math.min(1, done / planned) : 0;
  const el = h("div", { class: `ring${planned && done >= planned ? " full" : ""}`, style: `--p:${matchMedia("(prefers-reduced-motion: reduce)").matches ? p : 0}`, role: "img", "aria-label": planned ? `${label}完成 ${done} / ${planned} ${unit}` : `${label}还没有计划` },
    h("div", { class: "ring-in" }, h("b", {}, String(done)), h("span", {}, planned ? `/ ${planned}` : unit), h("small", {}, label)));
  setTimeout(() => { if (el.style.getPropertyValue("--p") === "0") el.style.setProperty("--p", String(p)); }, 60);  // 打开时从 0 涨上来（§93）
  return el;
}

// 打卡成功的庆祝画面：写明本周第几练；点一下或 2.4 秒后自动消失
async function celebrate() {
  const b = await api("/iron/api/brief").catch(() => null);
  const w = b?.week, n = w?.done || 0;
  const won = w?.planned && n >= w.planned;
  const el = h("div", { class: "cheer", role: "status" },
    h("div", { class: "cheer-burst" }, icon("check")),
    h("b", { class: "cheer-title" }, "打卡成功"),
    h("p", {}, n ? `本周第 ${n} 练${won ? "，本周目标达成！" : "，继续保持！"}` : "又进步了一点，继续保持！"));
  const close = () => el.remove();
  el.addEventListener("click", close);
  document.body.append(el);
  if (won) confetti();
  setTimeout(close, 2400);
}

// ---- 完成反馈（spec [2026-10-23] §92）：系统设了减少动态效果时只留文字和静态标记 ----------------------
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const e1rm = (w, r) => (w && r && r <= 30 ? (r === 1 ? w : w * (1 + r / 30)) : null);  // 和服务端同一个公式
const buzz = (p) => { try { if (!calm()) navigator.vibrate?.(p); } catch { /* 不支持振动 */ } };

// 彩带：撒一阵，1.5 秒内结束；颜色取主题里的
function confetti() {
  if (calm()) return;
  const cs = getComputedStyle(document.documentElement);
  const colors = ["--accent", "--warn", "--ink", "--heat"].map((v) => cs.getPropertyValue(v).trim()).filter(Boolean);
  const dpr = devicePixelRatio || 1;
  const c = h("canvas", { class: "confetti", "aria-hidden": "true" });
  document.body.append(c);
  const W = (c.width = innerWidth * dpr), H = (c.height = innerHeight * dpr);
  const g = c.getContext("2d");
  const bits = Array.from({ length: 90 }, () => ({
    x: W / 2 + (Math.random() - 0.5) * W * 0.3, y: H * 0.38,
    vx: (Math.random() - 0.5) * 18 * dpr, vy: (-Math.random() * 16 - 6) * dpr,
    r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.4, s: (4 + Math.random() * 5) * dpr,
    k: colors[Math.floor(Math.random() * colors.length)],
  }));
  const t0 = performance.now();
  const step = (t) => {
    const p = (t - t0) / 1500;
    g.clearRect(0, 0, W, H);
    for (const b of bits) {
      b.vy += 0.55 * dpr; b.x += b.vx; b.y += b.vy; b.r += b.vr;
      g.save(); g.translate(b.x, b.y); g.rotate(b.r); g.globalAlpha = Math.max(0, 1 - p); g.fillStyle = b.k;
      g.fillRect(-b.s / 2, -b.s / 4, b.s, b.s / 2); g.restore();
    }
    if (p < 1) requestAnimationFrame(step); else c.remove();
  };
  requestAnimationFrame(step);
}

// 从 0 数到目标，0.9 秒
function countUp(el, to, fmt = (x) => String(Math.round(x))) {
  if (calm()) { el.textContent = fmt(to); return; }
  const t0 = performance.now();
  const step = (t) => {
    const p = Math.min(1, (t - t0) / 900);
    el.textContent = fmt(to * (1 - (1 - p) ** 3));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// 一句短提示，2.4 秒后消失（破纪录时用）
function flash(node, ms = 2400) {
  const el = h("div", { class: "flash", role: "status" }, node);
  if (ms !== 2400) el.style.animationDuration = `.35s, ${ms}ms`;  // 淡出跟着停留时间走（带撤销的停久一点）
  document.querySelectorAll(".flash").forEach((x) => x.remove());  // 同时只留一条
  document.body.append(el);
  setTimeout(() => el.remove(), ms);
}

// 目标与进度（spec [2026-10-23] §18 需求 6；§65 设定和进度合成一块，放在个人中心）
const fmtDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${y}年${m}月${d}日`; };
function goalBlock() {
  const box = h("div", { class: "goal-box" });
  let state = { goal: null };
  const btn = h("button", { class: "link", type: "button", onclick: () => edit(state.goal) });
  const draw = (st) => {
    state = st;
    const g = st.goal, p = st.progress;
    btn.hidden = false; btn.replaceChildren(icon("edit", "xs"), g ? "修改" : "设置");
    if (!g) {
      box.replaceChildren(h("div", { class: "card" }, h("p", { class: "muted" }, "还没有设目标体重和日期。设好后这里显示起点、当前、目标和按体重趋势预计达成的日期，每 4 周提醒复测一次。")));
      return;
    }
    const kg = (v) => (v == null ? "—" : `${num(v)}`);
    const tone = { reached: "good", on_track: "good", ahead: "good", behind: "warn", wrong_way: "warn" }[p.status] || "";
    if (p.status === "reached") {  // 达到目标（§93）：换成"目标达成"，第一次看到放彩带，服务端记下
      const days = Math.max(0, Math.floor((Date.now() - new Date(`${g.set_day}T00:00:00`).getTime()) / 86400000));
      const moved = p.changed != null ? `${p.changed < 0 ? "减了" : "增了"} ${num(Math.abs(p.changed))} 公斤` : "";
      box.replaceChildren(h("div", { class: "card goal goal-won" },
        h("div", { class: "done-hero" }, h("div", { class: "cheer-burst" }, icon("check")),
          h("b", { class: "done-title" }, "目标达成"),
          h("p", {}, p.start != null ? `从 ${kg(p.start)} 到 ${kg(p.current)} 公斤，${moved}，用了 ${days} 天` : `现在 ${kg(p.current)} 公斤，到目标了`)),
        h("button", { class: "btn block", type: "button", onclick: () => edit(null) }, "定下一个目标"),
        h("p", { class: "muted" }, "也可以转为保持：体重在目标上下波动就算保持住了。")));
      if (p.celebrate) {
        p.celebrate = false;  // 取消改目标再画一次时不重放
        confetti(); buzz([40, 60, 40]);
        api("/iron/api/goal/celebrated", { method: "POST" }).catch(() => {});
      }
      return;
    }
    const pct = p.percent;
    const bar = pct != null ? h("div", { class: "goal-bar", role: "img", "aria-label": `完成 ${pct}%` },
      h("div", { class: "goal-fill", style: `width:${calm() ? pct : 0}%` }),
      ...[25, 50, 75, 100].map((m) => h("i", { class: `goal-dot${pct >= m ? " on" : ""}`, style: `left:${m}%` }))) : null;
    if (bar && !calm()) setTimeout(() => { bar.firstChild.style.width = `${pct}%`; }, 60);
    box.replaceChildren(h("div", { class: "card goal" },
      h("div", { class: "goal-head" }, h("b", {}, `目标体重 ${kg(g.value)} 公斤`), h("span", { class: "muted" }, `${fmtDay(g.by)}前`)),
      h("div", { class: "goal-nums" },
        ...[["起点", p.start], ["当前", p.current], ["目标", p.target]].map(([k, v]) => h("div", {}, h("span", { class: "muted" }, k), h("b", {}, kg(v)), h("span", { class: "muted" }, "公斤")))),
      bar ? h("div", { class: "goal-progress" }, bar,
        h("p", {}, p.changed ? `已${p.changed < 0 ? "减" : "增"} ${num(Math.abs(p.changed))} 公斤 · ` : "", h("b", {}, `完成 ${pct}%`))) : null,
      p.predicted ? h("p", {}, "预计达成：", h("b", {}, fmtDay(p.predicted))) : null,
      p.message ? h("p", { class: tone ? `tone-${tone}` : "" }, p.message) : null,
      p.missing ? h("p", { class: "muted" }, p.missing) : null,
      p.pace ? h("div", { class: "notice-line" }, icon("alert", "xs"), p.pace) : null,
      p.retest.due ? h("div", { class: "notice-line" }, icon("alert", "xs"), h("div", {}, p.retest.text,
        h("button", { class: "link", type: "button", onclick: async () => draw(await api("/iron/api/goal/retest", { method: "POST" })) }, "已复测"))) : null));
  };
  const edit = (g) => {
    btn.hidden = true;
    const value = h("input", { type: "number", inputmode: "decimal", min: "30", max: "250", step: "0.1", value: g ? String(g.value) : "", placeholder: "比如 65" });
    const by = h("input", { type: "date", value: g ? g.by : "" });
    const msg = h("div", { class: "error" });
    const form = h("form", {}, h("label", {}, "目标体重（公斤）", value), h("label", {}, "目标日期", by), msg,
      h("div", { class: "form-actions" },
        g ? h("button", { class: "btn ghost", type: "button", onclick: async () => draw(await api("/iron/api/goal", { method: "DELETE" })) }, "清除") : null,
        h("button", { class: "btn ghost", type: "button", onclick: () => draw(state) }, "取消"),
        h("button", { class: "btn", type: "submit" }, "保存")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!value.value || !by.value) { msg.textContent = "目标体重和日期都要填"; return; }
      msg.textContent = "正在保存…";
      try { draw(await api("/iron/api/goal", { method: "PUT", body: JSON.stringify({ value: Number(value.value), by: by.value }) })); }
      catch (err) { msg.textContent = err.message; }
    });
    box.replaceChildren(h("div", { class: "card" }, form)); value.focus();
  };
  api("/iron/api/goal").then(draw).catch(() => draw({ goal: null }));
  return section("目标与进度", btn, box);
}

function wxIcon(text) {
  if (/雷/.test(text)) return "storm";
  if (/雨|雪/.test(text)) return "rain";
  if (/云|阴|雾/.test(text)) return "cloud";
  return "sun";
}
const aqiTone = (a) => (a <= 100 ? "good" : a <= 150 ? "mid" : "bad");

// ---- 首页各块（spec [2026-10-23] §34） ----
function cardHead(title, extra) {
  return h("div", { class: "home-head" }, h("h3", {}, title), extra || null);
}


// 生病追问（spec [2026-10-23] §46）：从第二天起每天问一次"好些了吗"，三个按钮，回答后显示一句回复
function checkinRow(c) {
  if (!c) return null;
  const box = h("div", { class: "checkin" });
  const reply = (answer) => async () => {
    for (const b of box.querySelectorAll("button")) b.disabled = true;
    try {
      const r = await api(`/iron/api/illness/${encodeURIComponent(c.id)}/check`, { method: "POST", body: JSON.stringify({ answer }) });
      box.replaceChildren(h("p", {}, r.message));
      cache.metrics = null;
    } catch (err) {
      box.append(h("p", { class: "msg-note" }, err.message));
      for (const b of box.querySelectorAll("button")) b.disabled = false;
    }
  };
  box.append(
    h("b", {}, c.text),
    c.doctor ? h("p", { class: "msg-note" }, c.doctor) : null,
    h("div", { class: "btn-row" },
      h("button", { class: "btn small", type: "button", onclick: reply("resolved") }, "好了"),
      h("button", { class: "btn quiet small", type: "button", onclick: reply("better") }, "好一些"),
      h("button", { class: "btn quiet small", type: "button", onclick: reply("unwell") }, "还不舒服")));
  return box;
}

// 安全提醒放首页（spec [2026-10-23] §42；§64 挪到今日任务上面）：一行标题，点开看原文
function alertsBox(brief) {
  const alerts = brief?.alerts || [];
  return alerts.length ? h("div", { class: "home-alerts" }, alerts.map((a) => h("details", { class: "rep-alert" },
    h("summary", {}, icon("alert", "sm"), a.title), h("p", {}, a.text)))) : null;
}

// 战报（spec [2026-10-23] §64）：本周 / 本月两档统计，下面是月历；在本周翻到别的月份自动切到本月
function reportCard(brief, first) {
  const w = brief?.week, wdone = w?.done || 0, wplan = w?.planned || 0;
  let range = "week", cal = first;
  const tabs = h("div", { class: "seg rep-seg", role: "tablist", "aria-label": "战报范围" });
  const body = h("div", { class: "rep-body" });
  const stat = (k, v, u) => h("div", { class: "rep-stat" }, h("span", {}, k), h("b", {}, v, h("small", {}, u)));
  const load = async (month) => {
    body.replaceChildren(...skeleton(260));
    try { cal = await api(`/iron/api/calendar${month ? `?month=${month}` : ""}`); }
    catch (err) { body.replaceChildren(failed(err, () => load(month))); return; }
    draw();
  };
  const shift = (n) => {
    const [y, m] = cal.month.split("-").map(Number);
    const month = isoDay(new Date(y, m - 1 + n, 1)).slice(0, 7);
    if (month !== cal.today.slice(0, 7)) range = "month";
    load(month);
  };
  const pick = (k) => {
    range = k;
    if (k === "week" && cal && cal.month !== cal.today.slice(0, 7)) load(""); else draw();
  };
  const draw = () => {
    const now = !cal || cal.month === cal.today.slice(0, 7);
    const m = cal ? Number(cal.month.slice(5)) : 0;
    tabs.replaceChildren(...[["week", "本周"], ["month", now ? "本月" : `${m}月`]].map(([k, name]) =>
      h("button", { type: "button", role: "tab", class: range === k ? "on" : "", "aria-selected": String(range === k), onclick: () => pick(k) }, name)));
    if (!cal) { body.replaceChildren(failed(new Error("战报暂时取不到"), () => load(""))); return; }
    const won = wplan && wdone >= wplan, s = cal.month_stats, rpe = cal.week?.rpe;
    const stats = range === "week"
      ? h("div", { class: "report" }, ring(wdone, wplan),
        h("div", { class: "rep-stats" },
          stat("本周练了", `${wdone}`, wplan ? ` / ${wplan} 次` : " 次"),
          stat(won ? "本周目标" : "本周还差", won ? "达成" : `${Math.max(0, wplan - wdone)}`, won ? "" : " 练"),
          stat("平均感受", rpe != null ? rpe.toFixed(1) : "未记", rpe != null ? " 分" : "")))
      : h("div", { class: "report" }, s.planned_days != null ? ring(s.done_days, s.planned_days, now ? "本月" : `${m}月`, "天") : null,
        h("div", { class: "rep-stats" },
          stat(now ? "本月练了" : `${m}月练了`, `${s.done_days}`, s.planned_days != null ? ` / ${s.planned_days} 天` : " 天"),
          stat("连续达标", `${s.streak_weeks}`, " 周"),
          stat(`${s.versus_label}${s.versus > 0 ? "多" : s.versus < 0 ? "少" : ""}`, s.versus ? `${Math.abs(s.versus)}` : "持平", s.versus ? " 天" : "")));
    body.replaceChildren(stats, monthGrid(cal, range === "week", shift));
  };
  draw();
  return h("section", { class: "card home-card" }, cardHead("战报", tabs), body);
}

// 月历：练过的日子点亮，点一天看那天的记录；本周范围时本周那一行高亮（§64 不再显示天气）
function monthGrid(cal, markWeek, shift) {
  const [y, m] = cal.month.split("-").map(Number);
  const days = new Date(y, m, 0).getDate(), lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;
  const lit = new Set(cal.done_days), rested = new Set(cal.rest_days || []);
  const t = new Date(`${cal.today}T00:00:00`), mon = new Date(t.getFullYear(), t.getMonth(), t.getDate() - (t.getDay() + 6) % 7);
  const thisWeek = new Set(Array.from({ length: 7 }, (_, i) => isoDay(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + i))));
  const cells = Array.from({ length: lead }, () => h("span", { class: "cal-cell blank" }));
  for (let d = 1; d <= days; d++) {
    const iso = `${cal.month}-${String(d).padStart(2, "0")}`;
    const entries = cal.days[iso] || [];
    const n = cal.sets?.[iso] || 0, lv = n >= 16 ? 3 : n >= 8 ? 2 : 1, rest = rested.has(iso);
    const cls = `cal-cell${lit.has(iso) ? ` lit lv${lv}` : ""}${rest ? " rest" : ""}${iso === cal.today ? " today" : ""}${entries.length ? " has" : ""}${markWeek && thisWeek.has(iso) ? " wk" : ""}`;
    const cell = h("span", { class: cls, "aria-label": `${m}月${d}日${lit.has(iso) ? `，练过${n ? ` ${n} 组` : ""}` : rest ? "，记了没练" : ""}` }, String(d));
    cells.push(entries.length ? pressable(cell, () => openSheet(`${m}月${d}日`,
      h("div", { class: "rows" }, entries.map((e) => h("div", { class: "row-item" },
        h("span", { class: `dot-state ${e.done ? "on" : ""}` }), h("div", { class: "row-main" }, h("span", { class: "row-title" }, e.line))))))) : cell);
  }
  return h("div", { class: "cal" },
    h("div", { class: "cal-head" },
      h("button", { class: "icon-btn", type: "button", "aria-label": "上个月", onclick: () => shift(-1) }, icon("back", "sm")),
      h("b", {}, `${y}年${m}月`),
      h("button", { class: "icon-btn", type: "button", "aria-label": "下个月", onclick: () => shift(1), disabled: cal.today.slice(0, 7) === cal.month }, icon("chevron", "sm"))),
    h("div", { class: "cal-grid cal-week" }, WEEK.map((x) => h("span", {}, x))),
    h("div", { class: "cal-grid" }, cells));
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

let planSessions = [], planTargets = {};
// 今天的版本（spec [2026-10-23] §18 需求 3）：按状态、天气、可用时间用规则改，原计划不变
const itemLine = (it) => `${it.exercise} ${it.sets}×${it.reps}${it.load || it.note ? `（${[it.load, it.note].filter(Boolean).join("，")}）` : ""}`;
function todayVersion(session, { compact = false } = {}) {
  const box = h("div", { class: "tv" });
  const ask = { minutes: null, tired: false };
  const draw = async () => {
    const q = new URLSearchParams();
    if (ask.minutes) q.set("minutes", ask.minutes);
    if (ask.tired) q.set("tired", "true");
    let v;
    try { v = await api(`/iron/api/today${q.size ? `?${q}` : ""}`); }
    catch (err) { box.replaceChildren(failed(err, draw)); return; }
    if (v.status !== "ok") { box.replaceChildren(); return; }
    const toggle = (label, on, flip) => h("button", { type: "button", class: `pill${on ? " on" : ""}`, "aria-pressed": String(on), onclick: () => { flip(); draw(); } }, label);
    const items = (v.changed ? v.today : v.original).items;
    box.replaceChildren(
      compact ? null : h("div", { class: "tv-head" },
        h("div", {}, h("h3", {}, `今天 · ${v.today.name}`), h("p", { class: "muted" }, `约 ${v.today.minutes || session.minutes} 分钟 · ${items.length} 个动作`)),
        h("button", { class: "icon-btn", type: "button", "aria-label": "问教练怎么练", onclick: () => askCoach("今天练什么？按我的计划和今天的状态说") }, icon("coach", "sm"))),
      v.changed ? h("details", { class: "tv-adjusted" },
        h("summary", {}, icon("alert", "xs"), h("span", {}, "今天的版本按状态和天气调整过"), h("em", {}, "为什么"), icon("chevron", "xs")),
        h("p", {}, v.changes.join("；")),
        h("p", { class: "muted" }, `原因：${v.reasons.join("；")}`),
        h("p", { class: "muted" }, `原计划：${v.original.items.map(itemLine).join("、")}`)) : null,
      h("ol", { class: "plan-items tv-list" }, items.map((it) => {
        const tg = planTargets[it.exercise];
        return h("li", {}, h("span", {}, itemLine(it)), tg && !v.changed ? h("small", { class: "muted" }, `下次 ${tg.text}`) : null);
      })),
      h("div", { class: "asks" },
        toggle("只有 30 分钟", ask.minutes === 30, () => { ask.minutes = ask.minutes === 30 ? null : 30; }),
        toggle("今天有点累", ask.tired, () => { ask.tired = !ask.tired; })),
      h("button", { class: compact ? "btn quiet block" : "btn block", type: "button", onclick: () => doneSheet(v.today.name, v.changed ? v.today : null) },
        icon("check", "sm"), compact ? "没用记录器，直接打卡" : "练完打卡"));  // 首页展开时"开始训练"是主按钮（§104）
  };
  draw();
  return box;
}

function sessionSheet(x, isToday, t) {
  openSheet(`${isToday ? "今天" : weekdayName(x.day)} · ${x.name}`,
    h("p", { class: "muted" }, `约 ${x.minutes} 分钟`),
    h("ol", { class: "plan-items" }, x.items.map((it) => {
      const tg = planTargets[it.exercise];
      return h("li", {}, itemLine(it), tg ? h("div", { class: `next-target ${tg.action}` }, `下次：${tg.text}`, h("span", { class: "muted" }, `（${tg.why}）`)) : null);
    })),
    isToday && !t?.done ? h("button", { class: "btn block", type: "button", onclick: () => startLive({ today_plan: true }) }, icon("timer", "sm"), liveNow ? "继续训练" : "开始训练（边练边记）") : null,
    isToday && !t?.done ? h("button", { class: "btn ghost block", type: "button", onclick: () => doneSheet(x.name) }, icon("check", "sm"), "练完了，直接打卡") : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`${x.name}这次训练怎么练？每个动作要注意什么？`) }, icon("coach", "sm"), "问教练怎么练"));
}
const weekdayName = (d) => `周${WEEK[d - 1]}`;

// 打卡多记的状态（spec [2026-10-23] §105）：精力、昨晚睡得怎样、哪里酸，都可不填；和后端 SORE_PARTS 一致
const SORE_PARTS = ["胸", "背", "肩", "手臂", "大腿前", "大腿后", "臀", "小腿", "核心"];
const FEELINGS = [["good", "好"], ["ok", "一般"], ["poor", "差"]];
const FEELING_WORDS = Object.fromEntries(FEELINGS);
const REST_WHY = [["rest", "休息"], ["sick", "生病"], ["travel", "出差"], ["busy", "太忙"]];
const REST_WORDS = Object.fromEntries(REST_WHY);
const stateText = (x) => [x.energy ? `精力${FEELING_WORDS[x.energy]}` : "", x.slept ? `睡得${FEELING_WORDS[x.slept]}` : "",
  x.sore?.length ? `${x.sore.join("、")}酸` : ""].filter(Boolean).join("，");
const choice = (opts, isOn, tap) => h("div", { class: "st-chips" }, opts.map(([k, w]) =>
  h("button", { type: "button", class: `pill${isOn(k) ? " on" : ""}`, "aria-pressed": String(isOn(k)), onclick: (e) => {
    tap(k); e.currentTarget.parentNode.replaceWith(choice(opts, isOn, tap));
  } }, w)));
function stateBox() {
  const pick = { energy: null, slept: null, sore: new Set() };
  const one = (key) => choice(FEELINGS, (k) => pick[key] === k, (k) => { pick[key] = pick[key] === k ? null : k; });
  const shot = photoSlot("打卡照片", "随手拍一张，不用摆姿势");  // §117：挂在这次记录上，不进体态对比
  const el = h("details", { class: "state-pick" }, h("summary", {}, "更多：精力、睡眠、哪里酸、照片（可不填）"),
    h("div", { class: "st-body" },
      h("div", { class: "st-row" }, h("span", { class: "label" }, "精力"), one("energy")),
      h("div", { class: "st-row" }, h("span", { class: "label" }, "昨晚睡得"), one("slept")),
      h("div", { class: "st-row" }, h("span", { class: "label" }, "哪里酸"),
        choice(SORE_PARTS.map((p) => [p, p]), (p) => pick.sore.has(p), (p) => { if (!pick.sore.delete(p)) pick.sore.add(p); })),
      h("div", { class: "st-row" }, h("span", { class: "label" }, "照片"), shot.el)));
  const read = () => ({ ...(pick.energy ? { energy: pick.energy } : {}), ...(pick.slept ? { slept: pick.slept } : {}),
    ...(pick.sore.size ? { sore: [...pick.sore] } : {}) });
  // 记录存好以后再传照片；传不上不影响打卡，只提示一句
  const attach = async (workoutId) => {
    if (!shot.blob || !workoutId) return "";
    const form = new FormData(); form.append("photo", shot.blob, "checkin.jpg");
    try { await send(`/iron/api/workouts/${workoutId}/photo`, form); return ""; } catch (err) { return `打卡记下了，照片没传上：${err.message}`; }
  };
  return { el, read, attach };
}

// 今天没练也能打卡（§105）：记下原因，不算练了，连续打卡照算
function restSheet(lead = null) {
  let why = "rest";
  const note = h("input", { type: "text", maxlength: "60", placeholder: "备注（可不填）" });
  const msg = h("p", { class: "muted", role: "status" });
  const save = h("button", { class: "btn block", type: "button", onclick: async () => {
    save.disabled = true;
    try {
      await api("/iron/api/workouts", { method: "POST", body: JSON.stringify({ done: false, rest: why, note: note.value.trim() }) });
      closeSheet(); render(); flash("记下了，连续打卡照算");
    } catch (err) { msg.className = "error"; msg.textContent = err.message; save.disabled = false; }
  } }, "记下今天没练");
  openSheet("今天没练", lead, h("p", { class: "muted" }, "为什么没练？不算练了，连续打卡照算。"),
    choice(REST_WHY, (k) => why === k, (k) => { why = k; }), note, save, msg);
}

// 打卡时可以按计划里的动作填每组的重量和次数（spec [2026-10-23] §18 需求 4，可不填）
function setsForm(items) {
  const rows = items.map((it) => {
    const t = planTargets[it.exercise];
    const sets = Array.from({ length: Math.min(it.sets || 1, 8) }, (_, i) => {
      const w = h("input", { type: "number", inputmode: "decimal", min: "0", max: "500", step: "0.5", placeholder: t?.weight_kg ? String(t.weight_kg) : "公斤", "aria-label": `${it.exercise}第 ${i + 1} 组重量` });
      const r = h("input", { type: "number", inputmode: "numeric", min: "0", max: "100", placeholder: "次", "aria-label": `${it.exercise}第 ${i + 1} 组次数` });
      w.addEventListener("change", () => { // 后面几组没填重量时沿用这一组的
        for (const x of sets.slice(i + 1)) if (!x.w.value) x.w.value = w.value;
      });
      return { w, r };
    });
    const el = h("div", { class: "sets-ex" },
      h("div", { class: "sets-name" }, h("b", {}, it.exercise), h("span", { class: "muted" }, t ? `目标 ${t.text}` : `${it.sets}×${it.reps}`)),
      h("div", { class: "sets-grid" }, sets.map((x, i) => h("label", {}, h("span", { class: "muted" }, `第${i + 1}组`), x.w, h("span", { class: "muted" }, "×"), x.r))));
    return { it, sets, el };
  });
  const read = () => rows.map(({ it, sets }) => {
    const done = sets.filter((x) => x.r.value !== "").map((x) => ({ reps: Number(x.r.value), weight_kg: x.w.value === "" ? null : Number(x.w.value) }));
    return done.length ? { exercise: it.exercise, sets: done.length, done_sets: done } : null;
  }).filter(Boolean);
  return { el: h("details", { class: "sets-form" }, h("summary", {}, "填每组的重量和次数（可不填，用来算下次目标）"), rows.map((x) => x.el)), read };
}

function doneSheet(session, version = null) {
  let rpe = 0;
  const scale = h("div", { class: "rpe" });
  const draw = () => scale.replaceChildren(...Array.from({ length: 10 }, (_, i) => h("button", {
    type: "button", class: rpe === i + 1 ? "on" : "", "aria-pressed": String(rpe === i + 1), onclick: () => { rpe = i + 1; draw(); } }, String(i + 1))));
  draw();
  const planned = version?.items || planSessions.find((x) => x.name === session)?.items || [];
  const form = planned.length ? setsForm(planned) : null;
  const st = stateBox();
  const note = h("input", { type: "text", maxlength: "60", placeholder: "备注（可不填），比如有点累、膝盖没疼" });
  const msg = h("p", { class: "muted" });
  const save = h("button", { class: "btn block", type: "button", onclick: async () => {
    save.disabled = true; msg.textContent = "正在记下…";
    const filled = form ? form.read() : [];
    const byName = Object.fromEntries(filled.map((x) => [x.exercise, x]));
    const items = version ? version.items.map((it) => byName[it.exercise] || { exercise: it.exercise, sets: it.sets, reps: it.reps }) : filled;
    try {
      const r = await api("/iron/api/workouts", { method: "POST", body: JSON.stringify({ session: session === "训练" ? "" : session, done: true, rpe: rpe || null,
        note: (version ? [note.value.trim(), "按今天的版本"].filter(Boolean).join("；") : note.value.trim()).slice(0, 80),
        items, ...(version ? { minutes: version.minutes } : {}), ...st.read() }) });
      const warn = await st.attach(r.workout?.id);
      closeSheet(); render(); celebrate(); if (warn) flash(warn);
    } catch (err) { msg.textContent = err.message; save.disabled = false; }
  } }, "打卡");
  openSheet(`打卡：${session}${version ? "（今天的版本）" : ""}`,
    h("p", { class: "muted" }, "这次感觉怎么样？1 很轻松，10 到极限（可不选）"), scale, form?.el, st.el, note, save, msg,
    h("button", { class: "link", type: "button", onclick: () => restSheet() }, "今天没练？"));
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
    w.tips.length && w.planned ? h("button", { class: "btn block", type: "button", onclick: () => proposalSheet() }, icon("check", "sm"), "生成调整方案") : null);
}

// 每周复盘直接出调整方案（spec [2026-10-23] §18 需求 1）：训练教练按复盘改计划，确认后才替换，可以撤销
async function proposalSheet(trigger = null) {
  const box = h("div", { class: "sheet-stack" }, h("p", { class: "muted" }, `训练教练在按${trigger ? "提醒" : "这周的复盘"}改计划，大约要半分钟…`));
  openSheet(trigger ? trigger.title : "按复盘调整计划", box);
  let r;
  try { r = await api(`/iron/api/review/proposal${trigger ? `?trigger=${trigger.kind}` : ""}`, { method: "POST" }); }
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

// ---- 动作：卡片流，官方视频，"没看懂"请训练教练用大白话讲（spec [2026-10-23] §13）--------------------
const PART_MARK = { 腿臀: "腿", 胸: "胸", 背: "背", 肩: "肩", 手臂: "臂", 核心: "核", 全身: "全", 有氧: "氧", 拉伸放松: "拉" };
const moveFilter = { part: "全部", equip: "全部器械", q: "" };
const moveOpen = new Set();  // 展开了全部动作的部位（spec [2026-10-23] §32）
const GROUP_SHOW = 4;  // 按部位收纳时每组先显示几个
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
  const [lib, vids, me] = await Promise.all([exercises(), api("/iron/api/videos").catch(() => ({ videos: [] })), whoami(), checkLive()]);
  view.append(liveEntry({}, "自由训练"));
  const has = new Set(vids.videos);
  const count = h("div", { class: "muted", style: "padding:0 2px" });
  const grid = h("div", { class: "move-groups" });
  const input = h("input", { type: "search", placeholder: "搜索动作或部位，比如深蹲、肩", value: moveFilter.q, "aria-label": "搜索动作" });
  function draw() {
    const q = moveFilter.q.trim();
    const items = lib.exercises.filter((x) =>
      (moveFilter.part === "全部" || x.part === moveFilter.part)
      && (moveFilter.equip === "全部器械" || x.equipment.includes(moveFilter.equip))
      && (!q || `${x.name}${x.muscles}${x.part}`.includes(q)));
    count.textContent = `${items.length} 个动作${has.size ? ` · ${items.filter((x) => has.has(x.id)).length} 个有视频` : ""}`;
    const card = (x) => moveCard(x, has.has(x.id), () => exerciseSheet(x, lib.note, has, me.admin, draw));
    if (!items.length) {
      grid.replaceChildren(h("div", { class: "card" }, h("div", { class: "empty" }, icon("search"), "没有符合的动作，换个条件试试，或者直接问训练教练。")));
    } else if (moveFilter.part === "全部" && !q) {
      // 按部位收纳：每组先显示几个，点"全部 N 个"再展开（搜索或选了部位时平铺）
      grid.replaceChildren(...lib.parts.map((part) => {
        const shows = (x) => has.has(x.id) || x.images?.length;  // 有视频或配图的排在前面
        const mine = items.filter((x) => x.part === part).sort((a, b) => Number(Boolean(shows(b))) - Number(Boolean(shows(a))));
        if (!mine.length) return null;
        const all = moveOpen.has(part);
        const toggle = () => { if (all) moveOpen.delete(part); else moveOpen.add(part); draw(); };
        return h("section", { class: "move-group" },
          h("div", { class: "move-group-head" }, h("h2", {}, part, h("small", {}, `${mine.length} 个`),
            MOVE_PARTS.includes(part) ? h("a", { class: "tier-link", href: tierHref("move", part) }, icon("trophy", "xs"), "夯榜") : null),
            mine.length > GROUP_SHOW ? h("button", { class: `link${all ? " open" : ""}`, type: "button", "aria-expanded": String(all), onclick: toggle }, all ? "收起" : `全部 ${mine.length} 个`, icon("chevron", "xs")) : null),
          h("div", { class: "move-grid" }, (all ? mine : mine.slice(0, GROUP_SHOW)).map(card)));
      }).filter(Boolean));
    } else {
      grid.replaceChildren(h("div", { class: "move-grid" }, items.map(card)));
    }
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
        h("div", {}, h("h3", {}, "不知道练哪个？"), h("p", { class: "muted" }, "告诉训练教练你想练哪里、有什么器械、哪里不舒服。"))),
      h("div", { class: "asks" }, askChip("在家用哑铃练全身"), askChip("膝盖不好能练什么腿"), askChip("久坐圆肩怎么改善"))));
}

function moveCard(x, video, open) {
  const cover = h("div", { class: `move-cover p-${x.part}` },
    video ? h("video", { src: `${videoUrl(x.id)}#t=0.5`, muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true" })
      : x.images?.length ? h("img", { class: "move-img", src: x.images[0].url, alt: "", loading: "lazy" })
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
    : x.images?.length ? moveImages(x.images)
      : h("div", { class: `move-video empty-video p-${x.part}` }, h("span", { class: "cover-mark" }, PART_MARK[x.part] || x.part[0]), h("span", { class: "caption" }, "示范图和视频还在补充，先看下面的做法和要点"));
  openSheet(x.name,
    video,
    h("div", { class: "tags" }, chip(x.part), x.equipment.map((e) => chip(e)), chip(x.level)),
    h("p", { class: "lede" }, `主要练：${x.muscles}`),
    h("div", {}, h("h3", {}, "怎么做"), h("ol", { class: "steps-ol" }, x.steps.map((t) => h("li", {}, t)))),
    h("div", {}, h("h3", {}, "要点"), list(x.cues, "ok", "check")),
    h("div", {}, h("h3", {}, "常见错误"), list(x.mistakes, "bad", "x")),
    h("div", {}, h("h3", {}, "替代动作"), h("div", { class: "swap" }, h("div", {}, h("b", {}, "更容易"), x.easier), h("div", {}, h("b", {}, "更难"), x.harder))),
    h("div", { class: "callout" }, icon("alert", "sm"), h("div", {}, h("strong", {}, "什么情况先别做："), x.avoid)),
    h("button", { class: "btn block", type: "button", onclick: () => startLive({ exercises: [x.name] }) }, icon("timer", "sm"), liveNow ? "继续训练" : "开始训练"),
    h("div", { class: "btn-row" },
      h("button", { class: "btn ghost", type: "button", onclick: () => askCoach(`${x.name}我没看懂，请用大白话、打个比方再给我讲讲怎么做，最容易做错的地方是什么`) }, icon("coach", "sm"), "没看懂？讲简单点"),
      h("button", { class: "btn ghost", type: "button", onclick: () => askCoach(`${x.name}有什么替代动作？按我的器械和身体情况选`) }, "换个动作")),
    h("p", { class: "caption" }, note),
    admin ? videoAdmin(x, has, redraw) : null);
}

// 动作配图（来自 wger，CC BY-SA）：起止两张并排，下面署名（spec [2026-10-23] §32）
function moveImages(images) {
  const link = (text, href) => (href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : h("span", {}, text));
  const im = images[0];
  return h("figure", { class: "move-figure" },
    h("div", { class: `move-frames n${images.length}` }, images.map((x, i) => h("img", { src: x.url, alt: i ? "动作结束" : "动作开始", loading: "lazy" }))),
    h("figcaption", { class: "caption" }, "图：", link(im.author, im.author_url), " · 来自 ", link("wger", im.page), " · ", link(im.license, im.license_url)));
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
    if (!del.dataset.sure) { del.dataset.sure = "1"; del.textContent = `再点一次，删除「${x.name}」的视频`; return; }
    try { await api(videoUrl(x.id), { method: "DELETE" }); has.delete(x.id); closeSheet(); redraw(); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; }
  } }, "删除视频") : null;
  return h("div", { class: "admin-box" }, h("h3", {}, has.has(x.id) ? "管理员：更换视频" : "管理员：上传视频"), zone, bar.el, msg, del);
}

// ---- 饮食：饮食记录（照片 + 描述）、推荐这一餐、减脂餐、今日目标（spec [2026-10-23] §13）----------------
const MEAL_KINDS = ["早餐", "午餐", "晚餐", "加餐", "夜宵", "练前", "练后"];
const APPETITES = ["清淡", "正常", "很饿"];
const SCENES = ["全部", "外卖", "食堂", "便利店", "自己做"];
const foodState = { kind: null, appetite: "正常", scene: "全部" };
function mealKindNow() {
  const hr = new Date().getHours();
  return hr < 5 ? "夜宵" : hr < 10 ? "早餐" : hr < 11 ? "加餐" : hr < 14 ? "午餐" : hr < 17 ? "加餐" : hr < 21 ? "晚餐" : "夜宵";
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
  const [day, m] = await Promise.all([api("/iron/api/meals"), metrics().then(byKey).catch(() => ({}))]);
  const summary = h("div");
  const record = h("div");
  let today = day;
  const redraw = (d) => { today = d; summary.replaceChildren(daySummary(d, m)); record.replaceChildren(mealRecord(d, redraw)); };
  redraw(day);
  const editPlan = h("button", { class: "link", type: "button", onclick: async () => {
    const p = await api("/iron/api/diet/plan").catch(() => null);
    if (p) planEditSheet(p, () => redraw(today)); else flash("饮食计划这次没读到");
  } }, icon("edit", "xs"), "改计划");
  view.append(summary, mealEntry(() => today, redraw),
    section("今天吃什么", editPlan, record),
    section("食谱", null, recipesCard(() => today, redraw)),
    h("div", { class: "hscroll more-row" },
      ...[["fat", "减脂餐榜"], ["gain", "增肌餐榜"], ["supplement", "补剂榜"], ["protein", "蛋白粉榜"]].map(([b, n]) => h("a", { class: "pill", href: tierHref(b) }, icon("trophy", "xs"), n)),
      ...["早餐怎么吃够蛋白质", "练前练后吃什么", "外卖怎么点更健康", "要不要吃肌酸", "减脂期饿了怎么办"].map((q) => askChip(q))));
}

// 饮食的图（§119）：有配图用配图（公开的图，<img> 直接取）；没有的用"分类颜色色块 + 名字首字"
const FOOD_HUE = { 主食: 38, 肉蛋: 8, 水产: 200, 奶豆: 48, 蔬菜: 130, 水果: 330, 坚果油: 28, 饮品: 260, 零食: 300, 家常菜: 18, 外卖: 175, 早餐: 52 };
function foodTile(name, image, cat = "", size = "") {
  const box = h("span", { class: `food-tile${size ? ` ${size}` : ""}` });
  if (image?.url) box.append(h("img", { src: image.url, alt: "", loading: "lazy" }));
  else {
    // 没给分类的（一餐、食谱）按名字挑一个食物色调，同一个名字每次一样
    const warm = [18, 32, 45, 95, 130, 160, 200, 340];
    const hash = [...String(name || "")].reduce((a, ch) => (a * 31 + ch.codePointAt(0)) >>> 0, 7);
    box.style.setProperty("--hue", String(FOOD_HUE[cat] ?? warm[hash % warm.length]));
    box.append(h("b", { "aria-hidden": "true" }, String(name || "餐").replace(/^[（(].*?[)）]/, "").slice(0, 1)));
  }
  return box;
}
// 配图署名：作者 · 许可，点了去 Commons 的原图页
function imageCredit(image) {
  if (!image?.url) return null;
  return h("p", { class: "caption img-credit" }, "图：", image.page ? h("a", { href: image.page, target: "_blank", rel: "noopener" }, image.author || "Wikimedia Commons") : image.author,
    ` · ${image.license}`);
}

// 记一餐：拍、填、选一行三个小按钮；常吃的是横向滑动的小卡片（§119）。kind 给了就记成这一餐
function mealEntry(today, redraw, kind = null) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only" });
  const msg = h("div", { class: "muted", role: "status" });
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { msg.className = "error"; msg.textContent = "照片只支持 JPG、PNG、WebP"; return; }
    const photo = await shrinkPhoto(f);
    if (photo.size > 5 * MB) { msg.className = "error"; msg.textContent = "照片太大了，换一张试试"; return; }
    msg.textContent = "";
    logMealSheet(photo, today(), redraw, kind);
  });
  const usual = h("div", { class: "hscroll usual-row", hidden: true });
  api("/iron/api/meals/usual").then((r) => {
    if (!r.usual.length) return;
    usual.hidden = false; usual.previousSibling.hidden = false;
    usual.replaceChildren(...r.usual.map((u) => h("button", { class: "usual-card", type: "button",
      onclick: () => kindSheet(`记一份「${u.name}」`, today(), async (k) => redraw(await api("/iron/api/meals/usual", { method: "POST", body: JSON.stringify({ id: u.id, kind: k }) })), null, kind) },
      foodTile(u.name, u.image, "", "sm"), h("span", { class: "uc-text" }, h("b", {}, u.name), h("small", {}, `${Math.round(u.kcal)} 千卡`)))));
  }).catch(() => {});
  return h("div", { class: "meal-entry-wrap" },
    h("div", { class: "entry-bar" },
      h("label", { class: "entry-chip primary" }, input, icon("camera", "sm"), "拍照记"),
      h("button", { class: "entry-chip", type: "button", onclick: () => logMealSheet(null, today(), redraw, kind) }, icon("edit", "sm"), "写一句"),
      h("button", { class: "entry-chip", type: "button", onclick: () => pickFoodsSheet(today(), redraw, kind) }, icon("search", "sm"), "从库里选")),
    msg, h("div", { class: "usual-wrap" }, h("span", { class: "label usual-label", hidden: true }, "常吃的"), usual));
}

// 拍完或点了"填"之后：确认这一餐是哪一顿，再记下；每种餐每天一份，选到今天记过的就提示会替换
function logMealSheet(photo, day, redraw, kind0 = null) {
  let kind = kind0 || mealKindNow();
  const hint = h("p", { class: "caption replace-hint" });
  const showHint = () => {
    const had = day.meals.filter((x) => x.kind === kind).map((x) => x.name);
    hint.hidden = !had.length;
    hint.textContent = had.length ? `今天已记过${kind}：${had.join("、")}，记下后会替换；要合在一起就把两样都写上。` : "";
  };
  showHint();
  const said = h("textarea", { rows: photo ? "2" : "3", maxlength: "120",
    placeholder: photo ? "补一句更准（可不填）：比如吃了一半、少油" : "吃了什么、大概多少：比如一碗牛肉面，吃了一半" });
  const msg = h("div", { class: "muted", role: "status" });
  const go = h("button", { class: "btn block", type: "button" }, "记下，估算热量");
  go.addEventListener("click", async () => {
    if (!photo && !said.value.trim()) { msg.className = "error"; msg.textContent = "写一句吃了什么"; return; }
    const form = new FormData();
    form.append("said", said.value.trim()); form.append("kind", kind);
    if (photo) form.append("photo", photo, "meal.jpg");
    go.disabled = true; msg.className = "muted"; msg.textContent = "营养师在估算…";
    try { const r = await send("/iron/api/meals", form); closeSheet(); redraw(r); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; go.disabled = false; }
  });
  openSheet(photo ? "这是哪一餐？" : "填一餐",
    photo ? h("div", { class: "meal-photo" }, h("img", { src: URL.createObjectURL(photo), alt: "这一餐的照片" })) : null,
    photo ? null : said,
    h("div", { class: "kind-pick" }, h("span", { class: "caption" }, "哪一餐"), pills(MEAL_KINDS, kind, (v) => { kind = v; showHint(); }), hint),
    photo ? said : null, go, msg,
    h("p", { class: "caption" }, photo ? "照片估算通常偏低，油和酱最容易漏；记下后可以逐样改克数。照片会发给模型服务商识别。"
      : "营养师只认出吃了什么、多少克，热量按食物库算；记下后可以逐样改克数。"));
  if (!photo) setTimeout(() => said.focus(), 50);
}

// 今天吃什么（§119）：按顿一行。记了的显示图、名字、热量；没记、今天这套计划里有的淡色显示和"照计划记"；
// 都没有的一个"＋ 记早餐"。两周复盘的建议有时才在顶上一行出现
const MAIN_KINDS = ["早餐", "午餐", "晚餐", "加餐"];
function mealRecord(d, redraw) {
  const review = h("div", { class: "diet-review", hidden: true });
  api("/iron/api/diet/review").then((r) => {
    const p = r.proposal, c = r.current;
    if (!p && !c) return;
    const act = async (path) => { try { await api(path, { method: "POST" }); cache.metrics = null; render(); } catch (err) { review.append(h("p", { class: "error" }, err.message)); } };
    review.hidden = false;
    review.replaceChildren(
      h("div", { class: "dr-text" }, h("b", {}, p ? `建议每天${p.delta > 0 ? "多" : "少"}吃 ${Math.abs(p.delta)} 千卡` : `热量目标调整过 ${c.kcal > 0 ? "+" : "−"}${Math.abs(c.kcal)} 千卡`),
        h("small", {}, p ? `${p.reason}，目标从 ${p.before} 调到 ${p.after}` : `${c.reason}（${md(c.since)}起）`)),
      p ? h("button", { class: "btn small", type: "button", onclick: () => act("/iron/api/diet/adjust") }, "确认") : null,
      c && !p ? h("button", { class: "link", type: "button", onclick: () => act("/iron/api/diet/adjust/undo") }, "撤销") : null);
  }).catch(() => {});
  const list = h("div", { class: "day-meals" });
  const draw = (plan) => {
    const set = plan?.sets?.[plan.today_set] || {};
    const kinds = MEAL_KINDS.filter((k) => MAIN_KINDS.includes(k) || d.meals.some((x) => x.kind === k));
    list.replaceChildren(...kinds.map((k) => {
      const xs = d.meals.filter((x) => x.kind === k);
      if (xs.length) return h("div", { class: "dm-slot" }, ...xs.map((x) => {
        const tile = foodTile(x.name, x.image, "", "md");
        if (x.has_photo) loadPhoto(x.id, tile);
        return pressable(h("div", { class: "dm-row" }, tile,
          h("div", { class: "row-main" }, h("span", { class: "dm-kind" }, k), h("span", { class: "row-title" }, x.name),
            h("span", { class: "row-sub" }, `${Math.round(x.macros.kcal)} 千卡 · 蛋白质 ${Math.round(x.macros.protein_g)} 克`)),
          icon("chevron", "xs")), () => mealSheet(x, redraw));
      }));
      const planned = set[k] && !set[k].missing ? set[k] : null;
      if (planned) return h("div", { class: "dm-row planned" }, foodTile(planned.name, planned.image, "", "md"),
        h("div", { class: "row-main" }, h("span", { class: "dm-kind" }, `${k} · 计划`), h("span", { class: "row-title" }, planned.name),
          h("span", { class: "row-sub" }, `${Math.round(planned.kcal)} 千卡 · 还没吃`)),
        h("button", { class: "btn quiet small", type: "button", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { redraw(await api("/iron/api/diet/plan/log", { method: "POST", body: JSON.stringify({ slot: k }) })); flash(`记下了${k}`); } catch (err) { flash(err.message); e.currentTarget.disabled = false; }
        } }, "照计划记"));
      return h("button", { class: "dm-row empty", type: "button", onclick: () => addMealSheet(k, d, redraw) },
        h("span", { class: "food-tile md add" }, icon("plus", "sm")),
        h("div", { class: "row-main" }, h("span", { class: "dm-kind" }, k), h("span", { class: "row-title muted" }, `记${k}`)));
    }));
  };
  draw(null);
  api("/iron/api/diet/plan").then(draw).catch(() => {});
  return h("div", { class: "card meal-record" }, review, list);
}

// 点空着的那一顿：拍、写、选、常吃的，都记成这一顿
function addMealSheet(kind, d, redraw) {
  openSheet(`记${kind}`, mealEntry(() => d, (r) => { closeSheet(); redraw(r); }, kind));
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
      h("div", { class: "empty" }, icon("info"), "在个人中心填好身高、出生日期、性别和目标，就能算出每天该吃多少。"),
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
        [["结论", x.text], ["怎么算的", x.how], ["依据", x.source]].filter(([, v]) => v).map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))))),
      observedBox()) }, "目标怎么算的", icon("chevron", "xs")));
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
    !x.has_photo && x.image ? foodTile(x.name, x.image, "", "hero") : null, !x.has_photo ? imageCredit(x.image) : null,
    h("div", { class: "macro-grid" }, [["热量", x.macros.kcal, "千卡"], ["蛋白质", x.macros.protein_g, "克"], ["碳水", x.macros.carbs_g, "克"], ["脂肪", x.macros.fat_g, "克"]]
      .map(([k, v, u]) => h("div", {}, h("b", {}, Math.round(v), h("small", {}, u)), h("span", {}, k)))),
    x.foods?.length ? editFoods(x, redraw)
      : x.items.length ? h("div", {}, h("h3", {}, "吃了什么"), h("ul", { class: "tips" }, x.items.map((t) => h("li", {}, t)))) : null,
    h("p", { class: "caption" }, [x.foods?.length ? "营养按食物库算" : "营养是估算的", x.confidence ? `把握：${x.confidence}` : "", x.note].filter(Boolean).join("；")),
    h("button", { class: "btn danger block", type: "button", onclick: async () => {
      try { const r = await api(`/iron/api/meals/${x.id}`, { method: "DELETE" }); closeSheet(); redraw(await api("/iron/api/meals")); }
      catch (err) { flash(err.message); }
    } }, "删除这条"));
}

// ---- 饮食（spec [2026-10-23] §118）：逐样食物按食物库算，改份量、从库里选、常吃的、食谱、饮食计划都不调用模型 ----
const OILS = ["少油", "正常", "多油"];
const OIL_K = { 少油: 0.5, 正常: 1, 多油: 1.5 };
const kcalOf = (f, grams, oil = "正常") => {  // 和服务端同一个算法：菜品的油按少油 ×0.5、多油 ×1.5
  if (!f?.per100) return null;
  const extra = f.dish && f.unit_g ? ((OIL_K[oil] ?? 1) - 1) * f.oil_g * 8.84 * grams / f.unit_g : 0;
  return Math.round(f.per100.kcal * grams / 100 + extra);
};

// 选哪一餐（常吃的、食谱、从库里选都先选餐次），选到今天记过的提示会替换
function kindSheet(title, day, onPick, extra = null, kind0 = null) {
  let kind = kind0 || mealKindNow();
  const hint = h("p", { class: "caption replace-hint" });
  const show = () => { const had = day.meals.filter((x) => x.kind === kind).map((x) => x.name); hint.hidden = !had.length; hint.textContent = had.length ? `今天已记过${kind}：${had.join("、")}，记下后会替换。` : ""; };
  show();
  const msg = h("p", { class: "muted", role: "status" });
  const go = h("button", { class: "btn block", type: "button", onclick: async () => {
    go.disabled = true;
    try { await onPick(kind); closeSheet(); } catch (err) { msg.className = "error"; msg.textContent = err.message; go.disabled = false; }
  } }, "记下");
  openSheet(title, extra, h("div", { class: "kind-pick" }, h("span", { class: "caption" }, "哪一餐"), pills(MEAL_KINDS, kind, (v) => { kind = v; show(); }), hint), go, msg);
}

// 逐样食物：克数、油量（菜品）、删一样、从库里加一样；read() 给接口用
function foodLines(initial, { oil = true } = {}) {
  const rows = initial.map((x) => ({ ...x }));
  const list = h("div", { class: "fl-list" });
  const total = h("p", { class: "fl-total muted" });
  const draw = () => {
    list.replaceChildren(...rows.map((r, i) => {
      const g = h("input", { type: "number", inputmode: "decimal", min: "1", max: "3000", step: "1", value: String(r.grams), "aria-label": `${r.name}的克数` });
      g.addEventListener("input", () => { r.grams = Number(g.value) || 0; sum(); });
      return h("div", { class: "fl-row" },
        h("div", { class: "fl-name" }, h("b", {}, r.name), r.food_id ? null : h("small", { class: "muted" }, "库里没有，按估算")),
        oil && r.dish ? h("select", { "aria-label": `${r.name}的油量`, onchange: (e) => { r.oil = e.target.value; sum(); } },
          OILS.map((o) => h("option", { value: o, selected: (r.oil || "正常") === o ? true : null }, o))) : null,
        h("label", { class: "fl-g" }, g, h("span", {}, "克")),
        h("button", { class: "icon-btn", type: "button", "aria-label": `删掉${r.name}`, onclick: () => { rows.splice(i, 1); draw(); } }, icon("close", "xs")));
    }));
    sum();
  };
  const sum = () => {
    const known = rows.map((r) => r.f ? kcalOf(r.f, r.grams, r.oil) : r.kcal0 != null && r.grams0 ? Math.round(r.kcal0 * r.grams / r.grams0) : null);
    total.textContent = rows.length ? `大约 ${known.reduce((a, k) => a + (k || 0), 0)} 千卡（保存后按食物库算准）` : "还没有食物";
  };
  const q = h("input", { type: "search", placeholder: "加一样：搜米饭、鸡胸肉、番茄炒蛋…", "aria-label": "在食物库里搜" });
  const hits = h("div", { class: "fl-hits" });
  let timer = 0;
  q.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const s = q.value.trim();
      if (!s) { hits.replaceChildren(); return; }
      const r = await api(`/iron/api/foods?q=${encodeURIComponent(s)}`).catch(() => ({ foods: [] }));
      hits.replaceChildren(...(r.foods.length ? r.foods.slice(0, 8).map((f) => h("button", { class: "fl-hit", type: "button", onclick: () => {
        rows.push({ name: f.name, food_id: f.id, grams: f.unit_g, oil: "正常", dish: f.dish, f });
        q.value = ""; hits.replaceChildren(); draw();
      } }, foodTile(f.name, f.image, f.cat, "sm"), h("span", { class: "fh-text" }, h("span", {}, f.name),
        h("small", { class: "muted" }, `一${f.unit}约 ${Math.round(f.unit_g)} 克 · 每 100 克 ${f.per100.kcal} 千卡`))))
        : [h("p", { class: "caption" }, "库里没找到，换个叫法试试")]));
    }, 200);
  });
  draw();
  // 记下过的那几样：取回食物库的数，改克数和油量时预估才准；库里没有的按原来的估值比例算
  for (const r of rows.filter((x) => x.food_id && !x.f)) {
    api(`/iron/api/foods?q=${encodeURIComponent(r.name)}`).then((res) => { r.f = res.foods.find((f) => f.id === r.food_id); sum(); }).catch(() => {});
  }
  const read = () => rows.filter((r) => r.grams > 0).map((r) => ({ name: r.name, grams: r.grams, oil: r.oil || "正常", ...(r.food_id ? { food_id: r.food_id } : {}) }));
  return { el: h("div", { class: "food-lines" }, list, total, q, hits), read, count: () => rows.length };
}

// 记下的一餐：逐样改份量，按库重算，不调用模型
function editFoods(x, redraw) {
  const lines = foodLines(x.foods.map((f) => ({ name: f.name, food_id: f.food_id, grams: f.grams, oil: f.oil, dish: f.dish,
    kcal0: f.macros.kcal, grams0: f.grams })));
  const msg = h("p", { class: "muted", role: "status" });
  const save = h("button", { class: "btn small", type: "button", onclick: async () => {
    const foods = lines.read();
    if (!foods.length) { msg.className = "error"; msg.textContent = "至少留一样；整条不要了就点下面的删除"; return; }
    save.disabled = true;
    try { await api(`/iron/api/meals/${x.id}`, { method: "PUT", body: JSON.stringify({ day: x.day, foods }) }); closeSheet(); redraw(await api("/iron/api/meals")); flash("改好了"); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; save.disabled = false; }
  } }, "保存份量");
  return h("div", { class: "edit-foods" }, h("h3", {}, "吃了什么（可以改克数）"), lines.el, h("div", { class: "btn-row" }, save), msg);
}

// 按记的吃和体重变化估的实际消耗（§118 需求 7）：和公式算的并排；条件不够时说还差什么
function observedBox() {
  const box = h("div", {}, h("h3", {}, "按你记的估的实际消耗"), h("p", { class: "muted" }, "正在算…"));
  api("/iron/api/diet/review").then((r) => {
    const o = r.observed;
    box.replaceChildren(h("h3", {}, "按你记的估的实际消耗"), o
      ? h("dl", { class: "facts" }, [
        ["结论", `每天约 ${o.tdee} 千卡${o.formula ? `（公式算的是 ${o.formula} 千卡）` : ""}`],
        ["用了哪些数据", `最近 ${o.days} 天平均每天吃 ${o.intake} 千卡；体重每周 ${o.kg_per_week > 0 ? "+" : ""}${o.kg_per_week} 公斤（称了 ${o.weighins} 次）`],
        ["怎么算的", o.how]].map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v))))
      : h("p", { class: "muted" }, `还算不出来：${r.observed_lack || "饮食和体重记录不够"}。`),
      r.proposal ? h("p", { class: "caption" }, `管家的建议：${r.proposal.reason}，目标从 ${r.proposal.before} 调到 ${r.proposal.after} 千卡，在"吃了什么"上面确认。`) : null);
  }).catch(() => box.replaceChildren(h("p", { class: "muted" }, "这次没算出来。")));
  return box;
}

// 不拍不写，直接从食物库挑着记一餐
function pickFoodsSheet(day, redraw, kind0 = null) {
  const lines = foodLines([]);
  kindSheet("从食物库选", day, async (kind) => {
    const foods = lines.read().filter((f) => f.food_id);
    if (!foods.length) throw new Error("先在上面加一样吃的");
    redraw(await api("/iron/api/meals/foods", { method: "POST", body: JSON.stringify({ kind, foods }) }));
  }, h("div", {}, lines.el, h("p", { class: "caption" }, "营养按食物库算（内容待审定），不调用模型。")), kind0);
}

// 食谱（§119）：一排筛选，下面横向滑动的图片卡，最后一张是新建；点开看原料、做法、每份营养，按份数记成一餐
const recipeState = { tag: "推荐" };
function recipesCard(today, redraw) {
  const box = h("div", { class: "recipes" }, h("p", { class: "muted" }, "正在读食谱…"));
  const load = async () => {
    const r = await api("/iron/api/recipes").catch(() => null);
    if (!r) { box.replaceChildren(h("p", { class: "muted" }, "食谱这次没读到，稍后再试。")); return; }
    const draw = () => {
      const tag = recipeState.tag;
      const list = tag === "我的" ? r.mine : r.recommended.filter((x) => tag === "推荐" || x.tags.includes(tag));
      box.replaceChildren(
        h("div", { class: "hscroll tag-row" }, ["推荐", ...r.tags, "我的"].map((k) => h("button", { class: `pill${tag === k ? " on" : ""}`, type: "button", "aria-pressed": String(tag === k),
          onclick: () => { recipeState.tag = k; draw(); } }, k === "我的" && r.mine.length ? `我的 ${r.mine.length}` : k))),
        h("div", { class: "hscroll recipe-row" },
          ...list.map((x) => h("button", { class: "recipe-card", type: "button", onclick: () => recipeSheet(x, today(), redraw, load) },
            foodTile(x.name, x.image, "", "cover"),
            h("span", { class: "rc-text" }, h("b", {}, x.name), h("small", {}, `${Math.round(x.per_serving.kcal)} 千卡 · ${Math.round(x.per_serving.protein_g)} 克蛋白`)))),
          h("button", { class: "recipe-card new", type: "button", onclick: () => recipeEditSheet(null, load) },
            h("span", { class: "food-tile cover add" }, icon("plus")), h("span", { class: "rc-text" }, h("b", {}, "新建食谱"), h("small", {}, "常做的菜存起来")))),
        tag === "我的" && !r.mine.length ? h("p", { class: "caption" }, "常做的菜存成食谱，以后一点就能记。") : null,
        h("p", { class: "caption" }, r.note));
    };
    draw();
  };
  load();
  return box;
}

function recipeSheet(x, day, redraw, reload) {
  let servings = 1;
  const shown = h("b", { class: "num" }, "1");
  const per = h("p", { class: "muted" });
  const upd = () => { shown.textContent = String(servings); per.textContent = `吃 ${servings} 份：约 ${Math.round(x.per_serving.kcal * servings)} 千卡、蛋白质 ${Math.round(x.per_serving.protein_g * servings)} 克`; };
  upd();
  const step = (d) => () => { servings = Math.min(3, Math.max(0.5, servings + d)); upd(); };
  kindSheet(x.name, day, async (kind) => redraw(await api(`/iron/api/recipes/${x.id}/log`, { method: "POST", body: JSON.stringify({ kind, servings }) })),
    h("div", { class: "sheet-stack" },
      foodTile(x.name, x.image, "", "hero"), imageCredit(x.image),
      h("div", { class: "macro-grid" }, [["每份热量", x.per_serving.kcal, "千卡"], ["蛋白质", x.per_serving.protein_g, "克"], ["碳水", x.per_serving.carbs_g, "克"], ["脂肪", x.per_serving.fat_g, "克"]]
        .map(([k, v, u]) => h("div", {}, h("b", {}, Math.round(v), h("small", {}, u)), h("span", {}, k)))),
      h("div", {}, h("h3", {}, `原料（${x.servings} 份的量）`), h("ul", { class: "tips" }, [...x.parts.map((p) => h("li", {}, `${p.name} ${p.grams} 克`)), x.oil ? h("li", {}, `食用油 ${x.oil} 克`) : null])),
      x.steps.length ? h("div", {}, h("h3", {}, "做法"), h("ol", { class: "tips" }, x.steps.map((s) => h("li", {}, s)))) : null,
      h("div", { class: "qa-row" }, h("span", { class: "label" }, "吃了几份"),
        h("button", { class: "icon-btn", type: "button", "aria-label": "少半份", onclick: step(-0.5) }, "−"), shown,
        h("button", { class: "icon-btn", type: "button", "aria-label": "多半份", onclick: step(0.5) }, "+")), per,
      x.mine ? h("div", { class: "btn-row" },
        h("button", { class: "btn quiet small", type: "button", onclick: () => recipeEditSheet(x, reload) }, icon("edit", "sm"), "改"),
        h("button", { class: "link", type: "button", onclick: async (e) => {
          const b = e.currentTarget;
          if (b.dataset.sure !== "1") { b.dataset.sure = "1"; b.textContent = "确定删除？"; return; }
          try { await api(`/iron/api/recipes/${x.id}`, { method: "DELETE" }); closeSheet(); flash("删掉了"); reload(); } catch (err) { flash(err.message); }
        } }, "删除")) : null));
}

function recipeEditSheet(x, reload) {
  const name = h("input", { type: "text", maxlength: "20", placeholder: "名字，比如我的增肌早餐", value: x?.name || "", "aria-label": "食谱名字" });
  let servings = x?.servings || 1;
  const sv = h("b", { class: "num" }, String(servings));
  const tags = new Set(x?.tags || []);
  const lines = foodLines((x?.parts || []).map((p) => ({ name: p.name, food_id: p.food_id, grams: p.grams })), { oil: false });
  const oil = h("input", { type: "number", min: "0", max: "200", step: "1", value: String(x?.oil ?? 0), "aria-label": "油（克）" });
  const steps = h("textarea", { rows: "3", maxlength: "360", placeholder: "做法，一行一步（可不填）" });
  steps.value = (x?.steps || []).join("\n");
  const msg = h("p", { class: "muted", role: "status" });
  const go = h("button", { class: "btn block", type: "button", onclick: async () => {
    const parts = lines.read().filter((p) => p.food_id).map((p) => ({ food_id: p.food_id, grams: p.grams }));
    if (!name.value.trim()) { msg.className = "error"; msg.textContent = "起个名字"; return; }
    if (!parts.length) { msg.className = "error"; msg.textContent = "至少加一样原料"; return; }
    const body = { name: name.value.trim(), servings, tags: [...tags], parts, oil: Number(oil.value) || 0, steps: steps.value.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 6) };
    go.disabled = true;
    try { await api(x ? `/iron/api/recipes/${x.id}` : "/iron/api/recipes", { method: x ? "PUT" : "POST", body: JSON.stringify(body) }); closeSheet(); flash("存好了"); recipeState.tag = "我的"; reload(); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; go.disabled = false; }
  } }, "保存食谱");
  openSheet(x ? "改食谱" : "新建食谱", name,
    h("div", { class: "qa-row" }, h("span", { class: "label" }, "一共几份"),
      h("button", { class: "icon-btn", type: "button", "aria-label": "少一份", onclick: () => { servings = Math.max(1, servings - 1); sv.textContent = String(servings); } }, "−"), sv,
      h("button", { class: "icon-btn", type: "button", "aria-label": "多一份", onclick: () => { servings = Math.min(10, servings + 1); sv.textContent = String(servings); } }, "+")),
    h("div", { class: "pills", role: "group" }, ["减脂", "增肌", "早餐", "带饭"].map((tg) => h("button", { class: `pill${tags.has(tg) ? " on" : ""}`, type: "button", "aria-pressed": String(tags.has(tg)),
      onclick: (e) => { if (!tags.delete(tg)) tags.add(tg); e.currentTarget.classList.toggle("on"); e.currentTarget.setAttribute("aria-pressed", String(tags.has(tg))); } }, tg))),
    h("h3", { class: "pm-title" }, "原料（全部份数的量，生重）"), lines.el,
    h("label", { class: "pm-row" }, h("span", {}, h("b", {}, "油"), h("small", { class: "muted" }, "整锅用了多少克，一勺约 10 克")), oil),
    steps, go, msg, h("p", { class: "caption" }, "只有你自己能看到；营养按食物库算。"));
}

// 饮食计划：工作日、周末各一套；今天那套显示在"今天吃什么"里（§119），这里是改计划
async function planEditSheet(p, reload) {
  let set = p.today_set;
  const body = h("div", { class: "sheet-stack" });
  const [rec, usual, pre] = await Promise.all([api("/iron/api/recipes").catch(() => ({ recommended: [], mine: [] })),
    api("/iron/api/meals/usual").catch(() => ({ usual: [] })), api("/iron/api/meals/presets").catch(() => ({ presets: [] }))]);
  const options = [
    ...usual.usual.map((u) => ({ group: "常吃的", ref: { type: "meal", id: u.id }, name: u.name, kcal: u.kcal })),
    ...rec.mine.map((r) => ({ group: "我的食谱", ref: { type: "mine", id: r.id }, name: r.name, kcal: r.per_serving.kcal })),
    ...rec.recommended.map((r) => ({ group: "推荐食谱", ref: { type: "recipe", id: r.id }, name: r.name, kcal: r.per_serving.kcal })),
    ...pre.presets.map((x) => ({ group: "减脂餐", ref: { type: "preset", id: x.id }, name: x.name, kcal: x.kcal })),
  ];
  const put = async (slot, ref) => {
    try { p = await api("/iron/api/diet/plan", { method: "PUT", body: JSON.stringify({ set, slot, ref }) }); draw(); reload(); } catch (err) { flash(err.message); }
  };
  const draw = () => {
    const slots = p.sets[set], tot = p.totals[set];
    body.replaceChildren(
      h("div", { class: "seg seg-2", role: "tablist" }, [["weekday", "工作日"], ["weekend", "周末"]].map(([k, n]) => h("a", { href: "#food", role: "tab", class: set === k ? "on" : "", onclick: (e) => { e.preventDefault(); set = k; draw(); } }, n))),
      ...p.slots.map((k) => {
        const sel = h("select", { "aria-label": `${k}吃什么`, onchange: (e) => { const o = options[Number(e.target.value)]; put(k, o ? o.ref : null); } },
          h("option", { value: "" }, "空着"),
          ...["常吃的", "我的食谱", "推荐食谱", "减脂餐"].map((g) => {
            const os = options.map((o, i) => [o, i]).filter(([o]) => o.group === g);
            return os.length ? h("optgroup", { label: g }, os.map(([o, i]) => h("option", { value: String(i), selected: slots[k] && slots[k].type === o.ref.type && slots[k].id === o.ref.id ? true : null }, `${o.name} · ${Math.round(o.kcal)} 千卡`))) : null;
          }));
        return h("label", { class: "pm-row" }, h("span", {}, h("b", {}, k), slots[k]?.missing ? h("small", { class: "error" }, "原来选的已经没有了") : null), sel);
      }),
      h("p", { class: "muted" }, `这一套合计 ${tot.kcal} 千卡、蛋白质 ${tot.protein_g} 克${p.target ? `；每天目标 ${p.target.kcal} 千卡、蛋白质 ${p.target.protein_g} 克` : ""}`),
      h("p", { class: "caption" }, "食谱按 1 份算；只有你自己能看到。"));
  };
  draw();
  openSheet("饮食计划", body);
}

// 推荐这一餐、减脂餐：暂时不在页面上（spec [2026-10-23] §35），接口保留，以后要用时放回饮食页
function recommendBox(redraw) {
  const out = h("div");
  const go = h("button", { class: "btn block", type: "button" }, icon("food", "sm"), "推荐这一餐");
  go.addEventListener("click", async () => {
    go.disabled = true; out.replaceChildren(h("p", { class: "muted" }, "营养师在按你的目标、今天还差多少、天气和状态挑…"));
    try {
      const r = await api("/iron/api/meals/recommend", { method: "POST", body: JSON.stringify({ kind: foodState.kind || mealKindNow(), appetite: foodState.appetite }) });
      out.replaceChildren(recCard(r, redraw));
    } catch (err) { out.replaceChildren(h("p", { class: "error" }, err.message)); }
    go.disabled = false;
  });
  return h("div", { class: "card" },
    h("div", { class: "muted" }, "胃口"), pills(APPETITES, foodState.appetite, (v) => { foodState.appetite = v; }),
    go, out);
}

function recCard(r, redraw) {
  const rec = r.recommendation, tot = r.total;
  const save = h("button", { class: "btn ghost block", type: "button" }, icon("check", "sm"), "就吃这个，记下来");
  save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      const d = await api("/iron/api/meals/record", { method: "POST", body: JSON.stringify({
        kind: foodState.kind || mealKindNow(), name: rec.title, items: rec.dishes.map((x) => `${x.name}${x.amount ? ` ${x.amount}` : ""}`), macros: tot }) });
      save.textContent = "已记下"; redraw(d);
    } catch (err) { save.disabled = false; flash(err.message); }
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
        try { redraw(await api("/iron/api/meals/preset", { method: "POST", body: JSON.stringify({ preset: p.id, kind: foodState.kind || mealKindNow() }) })); e.target.textContent = "已记"; }
        catch (err) { flash(err.message); }
      } }, "记一餐"))));
  draw();
  return h("div", { class: "card" }, pills(SCENES, foodState.scene, (v) => { foodState.scene = v; draw(); }), grid,
    h("p", { class: "caption" }, data.note));
}

// ---- 数据：人体图 → 常看指标 → 每周复盘 → 其余指标 → 导入数据（spec [2026-10-23] §13）-------------------
// 数据页（spec [2026-10-23] §26）：重要指标在前；目标与计算一组；其余放在更多指标里，有数据才显示
const IMPORTANT = ["weight", "body_fat", "waist", "resting_hr", "hrv", "sleep", "steps", "active_kcal"];  // 常记的：缺了提示补记录
const METRIC_ORDER = ["weight", "weight_trend", "body_fat", "waist", "lean_mass", "bmi",
  "resting_hr", "hrv", "blood_pressure", "vo2max",
  "steps", "active_kcal", "exercise_min", "sleep", "bmr", "tdee", "kcal_target", "protein_target"];
const IMPORTANT_NAMES = { weight: "体重", body_fat: "体脂率", waist: "腰围", resting_hr: "静息心率", hrv: "心率变异性", sleep: "睡眠时长", steps: "步数", active_kcal: "活动消耗" };
// 能自己记的（指标 → 记录的种类）；血压要记收缩压和舒张压两个数
const MANUAL = { weight: ["weight"], body_fat: ["body_fat"], waist: ["waist"], resting_hr: ["resting_hr"], sleep: ["sleep"], blood_pressure: ["systolic", "diastolic"] };
// 计算出来的指标不能直接改：写明由什么算出、去哪里改
const CALC_FROM = {
  bmi: ["由体重和身高算出。", "体重在个人中心记，身高在个人中心改。"],
  bmr: ["由体重、身高、年龄、性别算出。", "身高、出生日期、性别在个人中心改，体重在个人中心记。"],
  tdee: ["基础代谢乘以日常活动水平。", "活动水平在个人中心改。"],
  kcal_target: ["每日总消耗按目标加减，再加上两周饮食复盘的调整量。", "目标在个人中心改；调整量在饮食页确认或撤销。"],
  protein_target: ["按体重和目标算出。", "目标在个人中心改，体重在个人中心记。"],
};

async function dataPart(view, me, where = "me") {
  const [list, muscles, brief] = await Promise.all([
    metrics(), api("/iron/api/muscles").catch(() => null), api("/iron/api/brief").catch(() => null)]);
  const m = byKey(list);
  view.append(h("div", { class: "fresh" }, icon("info", "xs"),
    list.as_of ? `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开任一项看怎么算的、自己记一条` : "还没有同步到健康数据，可以先自己记一条"));
  // 所有指标合成一块（§94）：身体成分 → 心肺 → 活动 → 睡眠 → 能量和目标；"还缺几项"只看常记的那几项
  const have = METRIC_ORDER.filter((k) => m[k] && m[k].value != null), lack = IMPORTANT.filter((k) => !(m[k] && m[k].value != null));
  view.append(section("身体指标", null,
    have.length ? h("div", { class: "tiles" }, have.map((k, i) => tile(m[k], { wide: have.length % 2 === 1 && i === have.length - 1 }))) : null,
    lack.length ? pressable(h("div", { class: "card lack-row" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, `还缺 ${lack.length} 项`), h("span", { class: "row-sub" }, lack.map((k) => IMPORTANT_NAMES[k]).join("、"))),
      h("span", { class: "row-end" }, "补记录", icon("chevron", "sm"))), () => lackSheet(lack, m)) : null));
  view.append(section("肌肉人体图", h("span", { class: "caption" }, "近 7 天"), muscles ? bodyMap(muscles, brief, me?.sex) : failed(new Error("人体图暂时算不出来"), () => render())));
  if (brief) view.append(section("每周复盘", h("span", { class: "caption" }, `${md(brief.week.from)}–${md(brief.week.to)}`), weekCard(brief.week)));
  const catalog = await catalogSection();
  view.append(h("details", { class: "me-more" }, h("summary", {}, "原始记录", icon("chevron", "xs")), h("div", { class: "me-more-body" }, catalog)));
}

// ---- 打卡照片（spec [2026-10-23] §117）：挂在那次打卡记录上，在轨迹里看；只有本人能取，不交给模型 ----
// 带登录凭证取图（<img src> 带不上凭证）；取不到就留空
async function authedImg(url, box, alt = "") {
  try {
    const res = await fetch(url, { headers: { Authorization: `Bearer ${store.get()}` } });
    if (!res.ok) return;
    box.replaceChildren(h("img", { src: URL.createObjectURL(await res.blob()), alt }));
  } catch { /* 取不到就留空 */ }
}

// 选一张照片：先缩小再留着，打卡记下以后再传
function photoSlot(label, hint) {
  const slot = { blob: null };
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only" });
  const view = h("span", { class: "ps-view" }, icon("camera", "sm"));
  const msg = h("small", { class: "ps-msg" }, hint);
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { msg.className = "ps-msg error"; msg.textContent = "照片只支持 JPG、PNG、WebP"; return; }
    const b = await shrinkPhoto(f);
    if (b.size > 5 * MB) { msg.className = "ps-msg error"; msg.textContent = "照片太大了，换一张试试"; return; }
    slot.blob = b; msg.className = "ps-msg"; msg.textContent = "换一张";
    view.replaceChildren(h("img", { src: URL.createObjectURL(b), alt: label }));
  });
  slot.el = h("label", { class: "photo-slot" }, input, view, h("b", {}, label), msg);
  return slot;
}

// 轨迹里的打卡照片：小图，点开看大图
function checkinThumb(x) {
  const box = h("span", { class: "log-thumb" });
  authedImg(`/iron/api/workouts/${x.id}/photo`, box, "打卡照片");
  return h("button", { class: "log-photo", type: "button", "aria-label": `${md(x.day)}的打卡照片`, onclick: () => {
    const big = h("div", { class: "meal-photo" });
    authedImg(`/iron/api/workouts/${x.id}/photo`, big, "打卡照片");
    openSheet(`${md(x.day)} 打卡照片`, big);
  } }, box);
}

// 还缺的重要指标：一张清单，能自己记的记一条，靠设备的导入（spec [2026-10-23] §29）
function lackSheet(keys, m) {
  openSheet("补记录", h("div", { class: "rows" }, keys.map((k) => {
    const name = IMPORTANT_NAMES[k], manual = MANUAL[k];
    return h("div", { class: "row-item" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, name), h("span", { class: "row-sub" }, manual ? "可以自己记" : "要连接手表或导入苹果健康")),
      manual ? h("button", { class: "btn small", type: "button", onclick: () => recordSheet(name, manual) }, icon("plus", "sm"), "记一条")
        : h("button", { class: "btn ghost small", type: "button", onclick: appleSheet }, "导入"));
  })));
}

// 自己记一条、改值、删一条：写进同一份健康记录，来源"手动记录"；改和删保留原记录（mirobody 的更正与撤回）
function recordSheet(title, kinds) {
  openSheet(`记录${title}`, recordBox(kinds));
}
function recordBox(kinds) {
  const box = h("div", { class: "record-box" });
  const msg = h("p", { class: "muted", role: "status" });
  const list = h("div", { class: "rows" });
  const inputs = {};
  const day = h("input", { type: "date", id: `rec-day-${kinds.join("-")}`, value: isoDay(new Date()), max: isoDay(new Date()) });
  const refresh = async () => {
    const all = await Promise.all(kinds.map((k) => api(`/iron/api/readings?kind=${k}`)));
    list.replaceChildren(...all.flatMap((r) => r.rows.slice(0, 6).map((row) => readingRow(r, row, refresh, msg))));
    if (!list.childElementCount) list.append(h("p", { class: "muted" }, "还没有记录。"));
    return all;
  };
  const save = h("button", { class: "btn", type: "button" }, icon("check", "sm"), "记下");
  save.addEventListener("click", async () => {
    save.disabled = true; msg.className = "muted"; msg.textContent = "正在记下…";
    try {
      for (const k of kinds) {
        const v = Number(inputs[k].value);
        if (!inputs[k].value) throw new Error("请填上数值");
        await api("/iron/api/readings", { method: "POST", body: JSON.stringify({ kind: k, value: v, day: day.value }) });
      }
      msg.textContent = "已记下，指标会按新数据重新算。";
      for (const k of kinds) inputs[k].value = "";
      cache.metrics = null; await refresh(); render();
    } catch (err) { msg.className = "error"; msg.textContent = err.message; }
    save.disabled = false;
  });
  refresh().then((all) => {
    const fields = all.map((r) => {
      inputs[r.kind] = h("input", { type: "number", inputmode: "decimal", step: "0.1", min: String(r.low), max: String(r.high), id: `rec-${r.kind}`, placeholder: `${r.low}–${r.high}` });
      return h("label", {}, `${r.title}（${r.unit}）`, inputs[r.kind]);
    });
    box.replaceChildren(h("div", { class: "record-form" }, ...fields, h("label", {}, "日期", day), save), msg,
      h("h3", {}, "最近的记录"), list,
      h("p", { class: "caption" }, "改和删都会保留原来那条，可以追溯。手表、报告导入的数也能改。"));
  }).catch((err) => box.replaceChildren(h("p", { class: "error" }, err.message)));
  box.append(...skeleton(120));
  return box;
}
function readingRow(r, row, refresh, msg) {
  const el = h("div", { class: "row-item reading" });
  const show = () => {
    el.replaceChildren(
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, `${row.value} ${r.unit}`), h("span", { class: "row-sub" }, `${row.day} · ${r.title} · ${row.manual ? "手动记录" : "设备或报告"}`)),
      h("button", { class: "link", type: "button", onclick: edit }, "改"),
      h("button", { class: "link danger-link", type: "button", onclick: remove }, "删"));
  };
  const edit = () => {
    const input = h("input", { type: "number", inputmode: "decimal", step: "0.1", value: String(row.value), id: `fix-${row.id}`, "aria-label": "改成" });
    const ok = h("button", { class: "btn small", type: "button" }, "保存");
    ok.addEventListener("click", async () => {
      try { await api(`/iron/api/readings/${r.kind}/${row.id}`, { method: "POST", body: JSON.stringify({ value: Number(input.value) }) }); cache.metrics = null; await refresh(); render(); }
      catch (err) { msg.className = "error"; msg.textContent = err.message; }
    });
    el.replaceChildren(h("div", { class: "row-main" }, input), ok, h("button", { class: "btn ghost small", type: "button", onclick: show }, "取消"));
    input.focus();
  };
  const remove = async () => {
    try { await api(`/iron/api/readings/${r.kind}/${row.id}`, { method: "DELETE" }); cache.metrics = null; await refresh(); render(); }
    catch (err) { msg.className = "error"; msg.textContent = err.message; }
  };
  show();
  return el;
}

// 人体图（spec [2026-10-23] §57）：openGym 那种平面图（MuscleMap 原图，MIT），正面、背面并排；
// 图没加载出来时退回按部位分组的列表
let flatShapes = null;
const loadFlat = () => (flatShapes ||= fetch("/iron/musclemap-v1.json").then((r) => { if (!r.ok) throw new Error("图没加载出来"); return r.json(); }));
const NOT_MUSCLE = new Set(["head", "hair", "hands", "feet", "ankles", "knees"]);

// 人体图的五种状态（§94）：颜色和说法都从这里取，图上、选中、列表一致；百分数只在详情里写
const muscleTone = (m) => (m.state === "sore" ? "sore" : m.tier === "ready" ? (m.last ? "t-ready" : "t-none") : `t-${m.tier}`);
const muscleWord = (m) => (m.state === "sore" ? "自述酸痛" : m.tier === "high" ? "刚练过" : m.tier === "ready" ? (m.last ? "可以练" : "最近没练") : "恢复中");
const muscleRow = (m, onPick) => pressable(h("div", { class: "muscle-row" },
  h("span", { class: "mr-name" }, m.name, m.state === "sore" ? h("em", {}, "酸痛") : null),
  h("span", { class: "mr-bar" }, h("i", { class: muscleTone(m), style: `width:${m.recovery}%` })),
  h("span", { class: `mr-sets ${muscleTone(m)}` }, muscleWord(m))), onPick);

function flatBody(mm, pick, sex) {
  const wrap = h("div", { class: "flat-body" }, h("p", { class: "muted" }, "人体图加载中…"));
  const byRegion = {};
  for (const m of mm.muscles) for (const r of m.flat || []) (byRegion[r] ||= []).push(m);
  // 两块肌肉共用一块图（臀、小腿）：先选是哪一块
  const choose = (ms) => {
    if (ms.length === 1) return pick(ms[0]);
    openSheet("是哪一块？", h("div", { class: "muscle-rows" }, ms.map((m) => muscleRow(m, () => { closeSheet(); pick(m); }))));
  };
  // 点一下选中（描轮廓、图下出名字），再点同一块或点"查看"才打开（§70）
  const bar = h("div", { class: "mm-pick", hidden: true });
  let chosen = null;
  const select = (key, ms, ev) => {
    if (chosen === key) { choose(ms); return; }
    chosen = key;
    for (const el of wrap.querySelectorAll(".mm.sel")) el.classList.remove("sel");
    for (const el of wrap.querySelectorAll(`.mm[data-key="${key}"]`)) el.classList.add("sel");
    wrap.classList.add("picking");
    const said = ms.map(muscleWord).join(" / ");
    bar.replaceChildren(h("span", {}, h("b", {}, ms.map((m) => m.name).join(" / ")), h("small", {}, said)),
      h("button", { class: "link", type: "button", onclick: () => choose(ms) }, "查看", icon("chevron", "xs")));
    bar.hidden = false;
    // 点的时候气泡出在手指旁边（§94），不出图的边；键盘选中时留在图下面
    if (ev && ev.clientX) {
      const r = wrap.getBoundingClientRect();
      const half = Math.min(110, r.width / 2);
      bar.classList.add("bubble");
      bar.style.left = `${Math.max(half, Math.min(r.width - half, ev.clientX - r.left))}px`;
      bar.style.top = `${Math.max(56, ev.clientY - r.top)}px`;
    } else { bar.classList.remove("bubble"); bar.style.left = bar.style.top = ""; }
  };
  const figure = (fig, side) => {
    const [x, y, w, hgt] = fig.viewBox;
    const svg = s("svg", { viewBox: `${x} ${y} ${w} ${hgt}`, class: "flat-svg", role: "img", "aria-label": side === "front" ? "正面" : "背面" });
    for (const part of fig.parts) {
      const ms = byRegion[`${side}:${part.slug}`] || [];
      const g = s("g", {});
      if (ms.length) {
        const low = ms.reduce((a, m) => (m.recovery < a.recovery ? m : a));  // 共用一块图的按恢复得少的那块
        const tone = ms.some((m) => m.state === "sore") ? "sore" : muscleTone(low);
        const label = ms.map((m) => `${m.name}：${muscleWord(m)}`).join("；");
        const key = ms.map((m) => m.code).join("+");
        g.setAttribute("class", `mm ${tone}`);
        g.dataset.key = key;
        g.setAttribute("tabindex", "0");
        g.setAttribute("role", "button");
        g.setAttribute("aria-label", label);
        const tip = s("title", {}); tip.textContent = label; g.append(tip);
        g.addEventListener("click", (ev) => select(key, ms, ev));
        // 只有键盘移过来时才在获得焦点时选中；手指、鼠标点的时候焦点先到，不能把这一下算成"再点一次"（§94）
        g.addEventListener("focus", () => { if (chosen !== key && g.matches(":focus-visible")) select(key, ms); });
        g.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(ms); } });
      } else {
        g.setAttribute("class", part.slug === "hair" ? "mm-hair" : NOT_MUSCLE.has(part.slug) ? "mm-base" : "mm-base mm-other");
      }
      for (const d of part.d) g.append(s("path", { d }));
      svg.append(g);
    }
    return h("figure", {}, svg, h("figcaption", {}, side === "front" ? "正面" : "背面"));
  };
  loadFlat().then((data) => {
    const fig = data.figures[sex === "female" ? "female" : "male"];
    wrap.replaceChildren(h("p", { class: "mm-hint" }, icon("info", "xs"), "点一块肌肉看详情"), figure(fig.front, "front"), figure(fig.back, "back"), bar);
  }).catch(() => wrap.replaceChildren(h("p", { class: "muted" }, "人体图没加载出来，按部位列出："), partList(mm, pick)));
  return wrap;
}

function partList(mm, pick) {
  const parts = [];
  for (const m of mm.muscles) {
    let p = parts.find((x) => x.name === m.part);
    if (!p) parts.push((p = { name: m.part, items: [] }));
    p.items.push(m);
  }
  return h("div", { class: "part-list" }, parts.map((p) => h("div", { class: "part-group" },
    h("h3", {}, p.name),
    p.items.map((m) => muscleRow(m, () => pick(m))))));
}

// ---- 夯榜（spec [2026-10-23] §72）：搜索热点、一次滑一个榜、前 10、榜单页、条目详情和评论 ---------------
// 地址：#tier 首页；#tier/<榜> 榜单（动作榜 #tier/move/p:<部位>）；#tier/<榜>/i:<条目> 详情
const MOVE_PARTS = ["胸", "背", "肩", "手臂", "核心", "腿臀"];
const tierHref = (board, part = "") => `#tier/${encodeURIComponent(board)}${part ? `/p:${encodeURIComponent(part)}` : ""}`;
const itemHref = (board, key) => `#tier/${encodeURIComponent(board)}/i:${encodeURIComponent(key)}`;
let rankTimer = null; // 首页转盘自动换榜；离开页面时停掉
const rankTiers = (b) => Object.fromEntries((b.tiers || []).map((t) => [t.key, t.name]));
const tierTag = (b, x) => (x.tier ? h("span", { class: `rk-tag t-${x.tier}` }, rankTiers(b)[x.tier]) : null);
const trendCls = (t) => (t.startsWith("↑") ? "up" : t.startsWith("↓") ? "down" : t === "新" ? "new" : "");
const rkNo = (n) => h("span", { class: `rk-no${n && n <= 3 ? ` r${n}` : ""}` }, n ? String(n) : "–");
const scoreText = (x) => (x.mean != null ? x.mean.toFixed(1) : "—");
// 配图（§80）：有图用图，没有用这个榜的图标
// 缺图时统一用同一种线条图标占位，不用表情符号（§104 需求 1：和实拍图并排太突兀）；动作和计划用哑铃，吃的用碗筷
const rkPic = (x, ic, cls = "rk-pic") => (x.image ? h("img", { class: cls, src: x.image, alt: "", loading: "lazy" })
  : h("span", { class: `${cls} none` }, icon(/🏋|📋/u.test(ic || "") ? "dumbbell" : "food", "sm")));
const rkLabel = (x) => h("span", { class: "rk-label" }, h("span", { class: "rk-name" }, x.name, x.tag ? h("em", { class: "rk-kind" }, x.tag) : null),
  x.desc ? h("small", { class: "rk-desc" }, x.desc) : null);

async function tierPage(view, sub, extra) {
  let board = decodeURIComponent(sub || "");
  let rest = extra || "";
  // §66 的旧地址：#tier/move:胸、#tier/food、#tier/supplement
  if (board.startsWith("move:")) { rest = `p:${board.slice(5)}`; board = "move"; }
  if (board === "food") board = "";
  if (!board) return rankHome(view);
  if (rest.startsWith("i:")) return rankItem(view, board, rest.slice(2));
  return rankBoard(view, board, rest.startsWith("p:") ? rest.slice(2) : "");
}

// 首页：搜索和热搜、转盘（§80 起下面不再放全部榜单）
async function rankHome(view) {
  const d = await api("/iron/api/rank");
  const input = h("input", { type: "search", placeholder: "搜动作、训练计划、健身餐、补剂、器材…", autocomplete: "off", "aria-label": "搜榜单里的条目" });
  const results = h("div", { class: "rk-results", hidden: true });
  const ringBox = h("div", { class: "rk-ring-wrap" });
  let seq = 0;
  const search = async (q, record) => {
    const text = q.trim();
    const mine = ++seq;
    results.hidden = !text; ringBox.hidden = Boolean(text);
    if (!text) { results.replaceChildren(); return; }
    let got;
    try { got = await api(`/iron/api/rank/search?q=${encodeURIComponent(text)}&record=${record}`); }
    catch (err) { if (mine === seq) results.replaceChildren(h("p", { class: "rk-none" }, err.message)); return; }
    if (mine !== seq) return;
    results.replaceChildren(...(got.items.length ? got.items.map((x) => h("a", { class: "rk-hit", href: itemHref(x.board, x.key) },
      h("span", { class: "rk-hit-name" }, x.name), tierTag(d, x), h("small", {}, `${x.icon} ${x.board_name}`)))
      : [h("p", { class: "rk-none" }, `没有找到「${text}」。可以进对应的榜单，点右上角「添加」。`)]));
  };
  let typing = 0;
  input.addEventListener("input", () => { clearTimeout(typing); typing = setTimeout(() => search(input.value, false), 250); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(typing); search(input.value, true); } });
  const hot = d.hot.length ? h("div", { class: "rk-hot" }, h("span", { class: "rk-hot-label" }, "热搜"),
    d.hot.map((x, i) => h("button", { class: "rk-chip", type: "button", onclick: () => { input.value = x.term; search(x.term, true); } },
      h("b", { class: i < 4 ? "hi" : "" }, String(i + 1)), x.term, x.flag ? h("em", { class: `rk-flag f-${{ 热: "hot", 新: "new", 升: "up" }[x.flag]}` }, x.flag) : null))) : null;
  ringBox.append(...rankRing(d));
  view.append(
    h("div", { class: "rk-search" }, icon("search", "sm"), input), hot, results, ringBox,
    h("p", { class: "caption", style: "padding:0 2px" }, "用户评分，不代表平台观点。每人一票（夯 5 分 … 拉 1 分），不到 3 票的在待评。"));
}

// 转盘：正面一个榜，两侧露出前后两个；一次滑动只换一个；不碰时每 4.5 秒换下一个，碰过停 6 秒
function rankRing(d) {
  const N = d.boards.length;
  const cards = d.boards.map((b, i) => {
    const rows = [...b.top, ...b.fill];
    const first = b.top[0];
    return h("article", { class: "rk-card", "data-i": String(i), "aria-label": b.name },
      h("div", { class: "rk-card-head" }, h("span", { class: "rk-ic" }, b.icon),
        h("div", {}, h("h2", {}, b.name), h("small", {}, b.people ? `本周 · ${b.people} 人参与` : "刚开榜，还没人评")),
        h("a", { class: "rk-all", href: tierHref(b.board) }, "全部", icon("chevron", "xs"))),
      h("div", { class: "rk-rows" }, rows.map((x) => [
        h("a", { class: `rk-row${x.rank ? "" : " wait"}`, href: itemHref(b.board, x.key) },
          rkNo(x.rank), rkPic(x, b.icon), rkLabel(x),
          h("span", { class: `rk-tr ${trendCls(x.trend)}` }, x.trend),
          x.rank ? tierTag(d, x) : h("span", { class: "rk-tag t-wait" }, "待评"),
          h("span", { class: "rk-sc" }, x.rank ? scoreText(x) : "")),
        x === first && x.top_comment ? h("div", { class: "rk-quote" }, `“${x.top_comment.text}”`, h("b", {}, ` 👍 ${x.top_comment.likes}`)) : null])));
  });
  const ring = h("div", { class: "rk-ring", tabindex: "0", role: "region", "aria-roledescription": "转盘", "aria-label": "各类榜单，左右滑动切换" }, cards);
  const dots = h("div", { class: "rk-dots" }, d.boards.map((b, i) => h("button", { type: "button", "aria-label": b.name, onclick: () => turn(near(i)) })));
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const mod = (a, n) => ((a % n) + n) % n;
  let pos = 0, anim = 0, touched = 0, drag = null, moved = false;
  const near = (i) => { let k = mod(i - pos, N); if (k > N / 2) k -= N; return Math.round(pos + k); };
  function layout() {
    const cur = mod(Math.round(pos), N);
    cards.forEach((c, i) => {
      let k = mod(i - pos, N); if (k > N / 2) k -= N;
      const a = Math.abs(k);
      c.style.transform = `translateX(${k * 64}%) translateZ(${-a * 170}px) rotateY(${-k * 38}deg)`;
      c.style.opacity = a <= 1 ? "1" : String(Math.max(0, 1 - (a - 1) * 0.9)); // 正面和两侧不透明，免得后面的字透过来
      c.style.filter = `brightness(${(1 - Math.min(a, 1) * 0.5).toFixed(3)})`;
      c.style.zIndex = String(100 - Math.round(a * 10));
      c.style.pointerEvents = a > 1.6 ? "none" : "auto";
      c.classList.toggle("on", i === cur && a < 0.5);
      if (c.dataset.on !== String(i === cur)) { // 键盘和读屏只进正面这张；两侧的还能点（点了转过来）
        c.dataset.on = String(i === cur);
        c.setAttribute("aria-hidden", String(i !== cur));
        for (const a of c.querySelectorAll("a")) a.tabIndex = i === cur ? 0 : -1;
      }
    });
    [...dots.children].forEach((x, i) => x.classList.toggle("on", i === cur));
  }
  function turn(target, dur = 600) {
    cancelAnimationFrame(anim);
    touched = Date.now();
    const from = pos, start = performance.now();
    if (reduce) dur = Math.min(dur, 200);
    const step = (now) => {
      const k = Math.min(1, (now - start) / dur);
      pos = from + (target - from) * (1 - (1 - k) ** 3); layout();
      if (k < 1) anim = requestAnimationFrame(step); else { pos = target; layout(); }
    };
    anim = requestAnimationFrame(step);
  }
  ring.addEventListener("dragstart", (e) => e.preventDefault());
  ring.addEventListener("pointerdown", (e) => {
    cancelAnimationFrame(anim);
    drag = { x: e.clientX, y: e.clientY, pos: Math.round(pos), w: cards[0].offsetWidth, axis: null, id: e.pointerId };
    moved = false; touched = Date.now();
  });
  ring.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.axis && Math.abs(dx) + Math.abs(dy) > 6) {
      drag.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
      if (drag.axis === "x") ring.setPointerCapture(drag.id);
    }
    if (drag.axis !== "x") return;
    moved = true; pos = drag.pos + Math.max(-1.2, Math.min(1.2, -dx / (drag.w * 0.8))); layout();
  });
  const release = () => {
    if (!drag) return;
    const was = drag; drag = null;
    if (moved) { const v = pos - was.pos; turn(was.pos + (Math.abs(v) > 0.15 ? Math.sign(v) : 0)); } // 滑得再远也只换一个
    else if (pos !== Math.round(pos)) turn(Math.round(pos));
  };
  ring.addEventListener("pointerup", release);
  ring.addEventListener("pointercancel", release);
  ring.addEventListener("click", (e) => {
    if (moved) { e.preventDefault(); e.stopPropagation(); moved = false; return; }
    const card = e.target.closest(".rk-card");
    if (card && !card.classList.contains("on")) { e.preventDefault(); e.stopPropagation(); turn(near(Number(card.dataset.i))); }
  }, true);
  ring.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight") turn(Math.round(pos) + 1);
    if (e.key === "ArrowLeft") turn(Math.round(pos) - 1);
  });
  ring.addEventListener("mouseenter", () => { touched = Date.now() + 60000; });
  ring.addEventListener("mouseleave", () => { touched = Date.now(); });
  layout();
  if (rankTimer) clearInterval(rankTimer);
  if (!reduce && N > 1) rankTimer = setInterval(() => {
    if (document.hidden || drag || !ring.isConnected || ring.closest("[hidden]") || Date.now() - touched < 6000) return;
    turn(Math.round(pos) + 1, 800);
  }, 4500);
  return [ring, h("div", { class: "rk-ctl" }, dots, h("span", { class: "caption" }, "左右滑，一次换一个榜"))];
}

// 两步确认（页面里不弹框）：第一次点按钮变成"确认…"，3 秒内再点才执行
function twoStep(label, sure, action, cls = "rk-act") {
  let armed = 0;
  const b = h("button", { class: cls, type: "button" }, label);
  b.addEventListener("click", () => {
    if (Date.now() - armed > 3000) { armed = Date.now(); b.textContent = sure; setTimeout(() => { if (b.isConnected) b.textContent = label; }, 3000); return; }
    armed = 0; action(b);
  });
  return b;
}
const rankBar = (back, title, ...right) => h("div", { class: "rk-bar" },
  h("a", { class: "icon-btn", href: back, "aria-label": "返回" }, icon("back", "sm")), h("h2", {}, title), ...right);

// 榜单页：完整排名、动作榜按部位筛、三种排法、待评、添加
let rankParts = null;
const RANK_SORTS = { 综合: null, 评论多: (a, b) => b.comments - a.comments || (b.score || 0) - (a.score || 0), 新上榜: (a, b) => b.added.localeCompare(a.added) };
async function rankBoard(view, board, part) {
  const d = await api(`/iron/api/rank/board?board=${encodeURIComponent(board)}${part ? `&part=${encodeURIComponent(part)}` : ""}`);
  if (d.parts.length) rankParts = d.parts;
  const ranked = d.items.filter((x) => x.rank);
  const waiting = d.items.filter((x) => !x.rank).sort((a, b) => b.votes - a.votes);
  const list = h("div", { class: "rk-list" });
  const sorts = h("div", { class: "pills" });
  let sort = "综合";
  const draw = () => {
    const by = RANK_SORTS[sort];
    const rows = sort === "新上榜" ? d.items.filter((x) => x.added).sort(by) : by ? [...ranked].sort(by) : ranked;
    sorts.replaceChildren(...Object.keys(RANK_SORTS).filter((k) => d.can_add || k !== "新上榜").map((k) => h("button", { class: `pill${k === sort ? " on" : ""}`, type: "button", onclick: () => { sort = k; draw(); } }, k)));
    list.replaceChildren(...(rows.length ? rows.map((x) => rankLine(d, x)) : [h("p", { class: "rk-none" }, sort === "新上榜" ? "还没有用户添加的条目。" : "还没有上榜的（要 3 个人评过）。下面待评的点进去投一票。")]));
  };
  draw();
  const adder = rankAdd(d);
  adder.hidden = true;
  const addBtn = h("button", { class: "btn ghost small", type: "button", onclick: () => { adder.hidden = !adder.hidden; if (!adder.hidden) adder.querySelector("input").focus(); } }, icon("plus", "xs"), "添加");
  view.append(rankBar("#tier", `${d.icon} ${d.name}`, d.can_add ? addBtn : null), d.can_add ? adder : null,
    board === "move" ? h("div", { class: "pills" }, h("a", { class: `pill${part ? "" : " on"}`, href: tierHref("move") }, "全部"),
      (rankParts || MOVE_PARTS).map((p) => h("a", { class: `pill${p === part ? " on" : ""}`, href: tierHref("move", p) }, p))) : null,
    h("p", { class: "caption" }, `${d.people} 人参与 · ${d.disclaimer}${part ? " 按部位看时名次是这个部位里的，不显示名次变化。" : ""}`),
    sorts, list,
    waiting.length ? h("section", { class: "rk-pending" }, h("h3", {}, `待评 ${waiting.length} 个 · 3 个人评过才上榜`),
      waiting.map((x) => h("a", { href: itemHref(board, x.key) }, rkPic(x, d.icon, "rk-pic sm"), rkLabel(x), h("small", {}, x.votes ? `还差 ${d.min_votes - x.votes} 票` : "没人评")))) : null);
}
function rankLine(d, x) {
  const c = x.top_comment;
  return h("a", { class: "rk-line", href: itemHref(d.board, x.key) },
    rkNo(x.rank), rkPic(x, d.icon), rkLabel(x), tierTag(d, x),
    h("span", { class: "rk-right" }, h("span", { class: "rk-sc" }, scoreText(x)), h("small", { class: `rk-tr ${trendCls(x.trend)}` }, x.trend)),
    h("span", { class: "rk-meta" }, `${x.votes} 人评过 · ${x.comments} 条评论${c ? ` · “${c.text}”` : ""}`));
}

// 添加：同名的直接用已有的；有相似的先问"是不是这个"，都不是再新建；加好后进详情投票
function rankAdd(d) {
  const input = h("input", { type: "text", maxlength: "30", placeholder: `加到${d.name}，写通用名字，不写品牌`, "aria-label": "添加条目" });
  const msg = h("p", { class: "error" });
  const ask = h("div", { class: "tier-similar" });
  const add = async (name, force = false) => {
    msg.textContent = ""; ask.replaceChildren();
    try {
      const r = await api("/iron/api/rank/items", { method: "POST", body: JSON.stringify({ board: d.board, name, force }) });
      if (r.key) { location.hash = itemHref(d.board, r.key); return; }
      ask.replaceChildren(h("p", { class: "caption" }, "榜上已经有相似的，是不是这个？"),
        h("div", { class: "asks" }, r.similar.map((x) => h("a", { class: "ask-chip", href: itemHref(d.board, x.key) }, x.name))),
        h("button", { class: "btn ghost small", type: "button", onclick: () => add(name, true) }, `都不是，新建「${name.trim()}」`));
    } catch (err) { msg.textContent = err.message; }
  };
  const form = h("form", { class: "tier-add" }, input, h("button", { class: "btn small", type: "submit" }, "添加"));
  form.addEventListener("submit", (e) => { e.preventDefault(); add(input.value); });
  return h("div", { class: "card tier-add-card" }, form, h("p", { class: "caption" }, "每人每天最多加 10 个。"), msg, ask);
}

// 条目详情：平均分、档位、几人评过、名次变化；五档各几票；我的一票；评论
async function rankItem(view, board, key) {
  const d = await api(`/iron/api/rank/item?board=${encodeURIComponent(board)}&key=${encodeURIComponent(key)}`);
  const box = h("div", { class: "rk-item" });
  let cmSort = "热门";
  const send = async (path, opts) => {
    const r = await api(path, opts);
    if (r && r.item) Object.assign(d, r);
    else Object.assign(d, await api(`/iron/api/rank/item?board=${encodeURIComponent(board)}&key=${encodeURIComponent(key)}`));
    draw();
  };
  const draw = () => {
    const x = d.item, names = rankTiers(d);
    const top = Math.max(1, ...Object.values(x.counts));
    const msg = h("p", { class: "error" });
    const vote = (tier) => send("/iron/api/rank/vote", { method: "PUT", body: JSON.stringify({ board, key, tier }) }).catch((err) => { msg.textContent = err.message; });
    box.replaceChildren(
      rankBar(tierHref(board), d.name),
      h("div", { class: "rk-hero" },
        x.image ? h("img", { class: "rk-hero-pic", src: x.image, alt: x.name }) : null,
        h("h1", {}, x.name, x.tag ? h("em", { class: "rk-kind" }, x.tag) : null),
        x.desc ? h("p", { class: "rk-hero-desc" }, x.desc) : null,
        x.credit ? h("p", { class: "caption rk-credit" }, "图：", x.credit.page ? h("a", { href: x.credit.page, target: "_blank", rel: "noopener" }, x.credit.author || "Wikimedia Commons") : (x.credit.author || "Wikimedia Commons"),
          ` · ${x.credit.license}`) : null,
        h("div", { class: "rk-score" }, h("span", { class: "rk-big" }, scoreText(x)), x.tier ? h("span", { class: `rk-tag big t-${x.tier}` }, names[x.tier]) : null,
          h("small", {}, x.votes >= d.min_votes ? `第 ${x.rank} 名 · ${x.votes} 人评过${x.trend ? ` · 本周 ${x.trend}` : ""}` : x.votes ? `${x.votes} 人评过，还差 ${d.min_votes - x.votes} 票上榜` : "还没人评过，来投第一票"))),
      x.votes ? h("div", { class: "tier-dist" }, d.tiers.map((t) => h("div", { class: "td-row" },
        h("span", { class: "td-name" }, t.name),
        h("span", { class: "td-bar" }, h("i", { class: `t-${t.key}`, style: `width:${(x.counts[t.key] / top) * 100}%` })),
        h("span", { class: "td-n" }, String(x.counts[t.key]))))) : null,
      h("div", { class: "card" },
        h("div", { class: "rk-vote-head" }, h("strong", {}, x.mine ? `我投的：${names[x.mine]}` : "我的一票"),
          x.mine ? h("button", { class: "rk-act", type: "button", onclick: () => vote("") }, "撤回") : h("small", { class: "muted" }, "夯 5 分 … 拉 1 分")),
        h("div", { class: "tier-pick" }, d.tiers.map((t) => h("button", { class: `tier-btn t-${t.key}${x.mine === t.key ? " on" : ""}`, type: "button", "aria-pressed": String(x.mine === t.key), onclick: () => vote(t.key) }, t.name))),
        msg),
      d.plan ? rankPlan(d.plan) : null,
      h("p", { class: `rk-disclaim${d.no_claims ? " warn" : ""}` }, d.disclaimer),
      rankComments(d, board, key, send, cmSort, (s) => { cmSort = s; draw(); }),
      x.custom ? h("div", { class: "rk-foot" }, twoStep("举报这个条目", "确认举报？3 个人举报后先隐藏", (b) => api("/iron/api/rank/report", { method: "POST", body: JSON.stringify({ board, key }) })
        .then(() => { b.textContent = "已举报"; b.disabled = true; }).catch((err) => { b.textContent = err.message; }))) : null);
  };
  draw();
  view.append(box);
}

// 训练计划榜的条目（§80）：每周怎么练（健身房版）、为什么、进阶、减量、来源；按我的情况用 → 进对话由管家改
function rankPlan(p) {
  const days = p.days.length > 1 ? `有每周 ${p.days.join("、")} 天几个版本，这里是每周 ${p.sessions.length} 天的健身房版。` : "这里是健身房版。";
  return h("section", { class: "card rk-plan" },
    h("h3", {}, "每周怎么练"), h("p", { class: "caption" }, `${days}在家、伤病、时间不够时，管家会按你的情况换动作。`),
    p.sessions.map((s) => h("div", { class: "rk-plan-day" }, h("b", {}, `${weekdayName(s.day)} · ${s.name}`), h("small", { class: "muted" }, ` 约 ${s.minutes} 分钟`),
      h("ul", {}, s.items.map((t) => h("li", {}, t))))),
    h("h3", {}, "为什么这样排"), h("p", {}, p.why),
    h("h3", {}, "强度和进阶"), h("p", {}, p.intensity), h("p", {}, p.progress), h("p", {}, p.deload),
    p.differs.length ? [h("h3", {}, "要注意"), h("ul", {}, p.differs.map((t) => h("li", {}, t)))] : null,
    p.source ? h("p", { class: "caption" }, `参考${p.source.authors.join("、")}的公开计划（`,
      h("a", { href: p.source.url, target: "_blank", rel: "noopener" }, p.source.secondhand ? "第三方整理" : "原发"),
      `，${p.source.seen} 查看），不是官方计划。`) : null,
    h("button", { class: "btn", type: "button", onclick: () => askCoach(p.ask) }, "按我的情况用这个计划"));
}

// 评论：热门 / 最新；写评论（200 字内）；点赞、举报、删自己的；昵称可改
function rankComments(d, board, key, send, sort, setSort) {
  const list = [...d.comments];
  if (sort === "最新") list.sort((a, b) => b.at.localeCompare(a.at));
  const text = h("textarea", { maxlength: String(d.comment_max), rows: "2", placeholder: d.no_claims ? "说说用着怎么样（不写疗效）" : "说说你的看法", "aria-label": "写评论" });
  const count = h("span", { class: "rk-count" }, `0/${d.comment_max}`);
  const msg = h("p", { class: "error" });
  text.addEventListener("input", () => { count.textContent = `${[...text.value].length}/${d.comment_max}`; });
  const form = h("form", { class: "rk-compose" }, text, h("button", { class: "btn small", type: "submit" }, "发送"));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!text.value.trim()) return;
    msg.textContent = "";
    send("/iron/api/rank/comments", { method: "POST", body: JSON.stringify({ board, key, text: text.value }) }).catch((err) => { msg.textContent = err.message; });
  });
  const nick = h("button", { class: "rk-act", type: "button", onclick: () => rankNick(nick) }, d.nick ? `我的昵称：${d.nick}` : "发第一条评论时给你一个随机昵称");
  return h("section", { class: "rk-comments" },
    h("div", { class: "rk-cm-head" }, h("h3", {}, `评论 ${d.comments.length}`),
      h("div", { class: "pills" }, ["热门", "最新"].map((k) => h("button", { class: `pill${k === sort ? " on" : ""}`, type: "button", onclick: () => setSort(k) }, k)))),
    form, h("div", { class: "rk-cm-sub" }, nick, count), msg,
    list.length ? list.map((c) => h("div", { class: "rk-cm" },
      h("div", { class: "rk-who" }, h("b", {}, c.nick), h("small", {}, md(c.at)), c.mine ? h("em", {}, "我") : null),
      h("p", {}, c.text),
      h("div", { class: "rk-acts" },
        h("button", { class: `rk-act${c.liked ? " on" : ""}`, type: "button", "aria-pressed": String(c.liked),
          onclick: () => send(`/iron/api/rank/comments/${c.id}/like`, { method: "POST", body: JSON.stringify({ on: !c.liked }) }).catch((err) => { msg.textContent = err.message; }) }, `👍 ${c.likes}`),
        c.mine ? twoStep("删除", "确认删除？", () => send(`/iron/api/rank/comments/${c.id}`, { method: "DELETE" }).catch((err) => { msg.textContent = err.message; }))
          : twoStep("举报", "确认举报？", (b) => api(`/iron/api/rank/comments/${c.id}/report`, { method: "POST" }).then(() => { b.textContent = "已举报"; b.disabled = true; }).catch((err) => { msg.textContent = err.message; })))))
      : h("p", { class: "rk-none" }, "还没有评论，说说你的看法。"));
}
function rankNick(btn) {
  const input = h("input", { type: "text", maxlength: "12", placeholder: "2–12 个字", "aria-label": "新昵称" });
  const msg = h("p", { class: "error" });
  const form = h("form", { class: "tier-add" }, input, h("button", { class: "btn small", type: "submit" }, "保存"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const r = await api("/iron/api/rank/nick", { method: "PUT", body: JSON.stringify({ nick: input.value }) }); btn.textContent = `我的昵称：${r.nick}`; closeSheet(); }
    catch (err) { msg.textContent = err.message; }
  });
  openSheet("改昵称", h("p", { class: "caption" }, "评论区只显示昵称，不显示账号。"), form, msg);
  input.focus();
}

function bodyMap(mm, brief, sex) {
  const tell = async (m, feel, btns) => {
    for (const b of btns) b.disabled = true;
    try {
      await api("/iron/api/muscles/feel", { method: "POST", body: JSON.stringify({ muscle: m.code, feel }) });
      closeSheet(); render();
    } catch (err) {
      for (const b of btns) b.disabled = false;
      btns.find((b) => b.isConnected)?.parentElement?.after(h("p", { class: "error" }, err.message));
    }
  };
  const pick = (m) => {
    if (!m) return;
    const sore = h("button", { class: "btn ghost small", type: "button" }, "仍有酸痛");
    const fine = h("button", { class: "btn ghost small", type: "button" }, "酸痛已缓解");
    const btns = [sore, fine];
    sore.addEventListener("click", () => tell(m, "sore", btns));
    fine.addEventListener("click", () => tell(m, "fine", btns));
    const aka = [m.formal && `正式名：${m.formal}`, m.says?.length && `也叫：${m.says.join("、")}`].filter(Boolean).join("　");
    openSheet(m.name,
      aka ? h("p", { class: "caption" }, aka) : null,
      h("div", { class: "sheet-big" }, h("span", { class: `v ${muscleTone(m)}` }, muscleWord(m)), m.tier !== "ready" ? h("small", {}, `估算恢复 ${m.recovery}%`) : null),
      h("div", { class: `recover-box ${m.state === "sore" ? "sore" : "ready"}` },
        h("b", {}, m.state === "sore" ? "自述酸痛：建议酸痛缓解后再训练这块肌肉" : m.tier === "ready" ? "已恢复，可以练" : `${muscleWord(m)}，估算恢复 ${m.recovery}%`),
        h("p", { class: "muted" }, "恢复度是估算，你的感受优先。"),
        h("div", { class: "btn-row" }, m.state === "sore" ? fine : sore)),
      h("div", { class: "kv" }, h("span", {}, "近 7 天"), h("span", {}, `${m.sets_7d} 组`)),
      m.sore_too_long ? h("div", { class: "notice-line" }, icon("alert", "xs"), "酸痛已超过一周，可能不是训练后的延迟性肌肉酸痛，建议咨询康复恢复师。") : null,
      h("div", { class: "kv" }, h("span", {}, "最近一次"), h("span", {}, m.last ? md(m.last) : "最近 28 天没练")),
      m.history.length ? h("div", {}, h("h3", {}, "最近练过"), h("ul", { class: "tips" }, m.history.map((x) => h("li", {}, x)))) : null,
      h("p", { class: "caption" }, "组数：主要练到的每组记 1 组，辅助练到的按半组；增肌通常每块肌肉每周 10 组以上效果更好。"),
      h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(m.sore_too_long ? `我的${m.name}酸了一周多还没好，怎么回事？` : m.level === "none" ? `我的${m.name}一周没练了，怎么补上？` : `我的${m.name}这周练了 ${m.sets_7d} 组，够吗？`) }, icon("coach", "sm"), "问问教练"));
  };
  const top = [...mm.muscles].filter((m) => m.tier !== "ready" || m.state === "sore").sort((a, b) => a.recovery - b.recovery);
  const untrained = mm.untrained || [];
  const rd = brief?.today?.readiness;
  return h("div", { class: "card body-card" },
    flatBody(mm, pick, sex),
    h("div", { class: "legend" }, ...[["t-high", "刚练过"], ["t-mid", "恢复中"], ["t-ready", "可以练"], ["t-none", "最近没练"], ["mm-sore", "自述酸痛"]].map(([c, t]) => h("span", {}, h("i", { class: c }), t))),
    rd && (rd.level === "poor" || rd.level === "fair") && rd.reasons?.length ? h("div", { class: "notice-line" }, icon("alert", "xs"), `${rd.reasons[0]}：今天整体恢复偏慢，可以降低强度。`) : null,
    mm.sessions === 0 ? h("p", { class: "muted" }, "最近还没有训练记录：在首页打卡，或在对话里说“今天练了……”就会记下来。") : h("div", { class: "muscle-rows" },
      top.length ? top.slice(0, 6).map((m) => muscleRow(m, () => pick(m)))
        : h("p", { class: "muted" }, "全部肌肉都已恢复，可以练。")),
    untrained.length && mm.sessions ? h("div", { class: "notice-line" }, icon("info", "xs"), `近 7 天没练：${untrained.join("、")}`) : null,
    untrained.length && mm.sessions ? h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我最近${untrained.join("、")}没怎么练，下次训练怎么补上？`) }, icon("coach", "sm"), "让教练帮我补上") : null,
    h("details", { class: "all-muscles" }, h("summary", {}, `全部 ${mm.muscles.length} 块肌肉`), partList(mm, pick)),
    h("p", { class: "caption" }, mm.note));
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
  const items = [...ADD.slice(0, 3), ["more", "更多", "", () => { location.hash = "#me"; }]];
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
      msg.textContent = r.code === 0 ? `已上传 ${n} 个文件，正在识别，结果会出现在个人中心的「我的文件」和「原始记录」里。` : `有的文件没有上传成功：${r.msg || ""}`;
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
        h("a", { class: "btn ghost block", href: "#me", onclick: () => { cache.metrics = null; closeSheet(); render(); } }, "去看数据")));
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
    h("button", { class: "btn", style: "background:var(--heat);color:var(--accent-ink)", type: "button", onclick: async () => {
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

// ---- 原始记录（含报告里识别出的化验值，§94 改名） ----
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
  return section("原始记录", null, box, h("p", { class: "caption", style: "padding:0 2px" }, "同步和导入的每一条数据，包括从上传的报告里识别出的化验值。"));
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

// ---- 个人中心（spec [2026-10-23] §65）：头部摘要、目标与进度、身体数据、设置一页到底 ----------------
const SEX = { male: "男", female: "女" };
async function me(view) {
  const mine = await profile().catch(() => null);
  view.append(meHead(mine), goalBlock());
  const files = await filesSection();
  view.append(gearSection(), section("导入数据", null, addGrid()), files);
  view.append(citySection(),
    section("说明", null, h("div", { class: "card" }, h("p", { class: "muted" }, "AI 健身管家一个人回答训练、饮食、恢复和身体数据的问题，会记得你的情况，按你的数据和状态安排。建议仅供参考，不能代替医生；身体不适请及时就医。"))),
    h("button", { class: "btn danger block", type: "button", onclick: signOut }, icon("logout", "sm"), "退出登录"));
}

// 头部：头像、账号，一行个人信息摘要；点"编辑"就地展开档案表单
function meHead(data) {
  const email = tokenEmail();
  const box = h("div", { class: "me-sum" });
  const edit = h("button", { class: "link", type: "button", hidden: !data }, icon("edit", "xs"), "编辑");
  edit.addEventListener("click", () => { edit.hidden = true; profileForm(box, data, () => { edit.hidden = false; }, summary); });
  if (data) summary(box, data); else box.append(h("p", { class: "muted" }, "档案暂时读不到，稍后再试。"));
  return h("div", { class: "card me-head" },
    h("div", { class: "profile-head" },
      h("span", { class: "avatar" }, (email[0] || "我").toUpperCase()),
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, email || "已登录"), h("span", { class: "row-sub" }, "IronM 账号")),
      edit),
    box);
}
function summary(box, data) {
  const p = data.profile;
  const age = p.birth ? (() => {
    const [y, m, d] = p.birth.split("-").map(Number), now = new Date();
    return now.getFullYear() - y - (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d) ? 1 : 0);
  })() : null;
  const parts = [p.height_cm ? `${num(p.height_cm)} 厘米` : "", age != null ? `${age} 岁` : "", SEX[p.sex] || "",
    data.options.goal[p.goal] || "", data.options.activity[p.activity] || ""].filter(Boolean);
  box.replaceChildren(h("p", { class: "me-line" }, parts.length ? parts.join(" · ") : "还没填身高、出生日期、性别和目标"),
    h("p", { class: "caption" }, "用来计算 BMI、基础代谢、每日热量和蛋白质目标。"));
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

function profileForm(box, data, done, show) {
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
      h("button", { class: "btn ghost", type: "button", onclick: () => { show(box, data); done(); } }, "取消"),
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
      show(box, data); done();
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
  ["深蹲时膝盖疼怎么办", "康复恢复师 · 训练教练"],
  ["早餐怎么吃够蛋白质", "营养师"],
  ["我最近的静息心率正常吗", "康复恢复师"],
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
  const past = h("button", { class: "icon-btn", type: "button", "aria-label": "以前的对话", title: "以前的对话", onclick: historySheet }, icon("history", "sm"));
  view.append(h("div", { class: "chat" },
    h("div", { class: "chat-bar" },
      h("a", { class: "icon-btn", href: `#${chat.back}`, "aria-label": "返回" }, icon("back", "sm")),
      h("div", { class: "who" }, h("b", {}, "教练"), h("span", {}, "训练教练 · 营养师 · 康复恢复师")),
      h("div", { class: "chat-tools" }, past, fresh)),
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
    const inbox = loadInbox();
    if (!chat.loaded) { thread.replaceChildren(h("div", { class: "welcome" }, h("div", { class: "typing" }, h("i"), h("i"), h("i")))); await loadLatest(); }
    await inbox;
    if (coachInbox) coachInbox.view = inboxView(coachInbox);
    if (chat.els?.thread !== thread) return;  // 已经离开对话页
    drawThread();
    if (chat.pending) {
      const q = chat.pending; chat.pending = null;
      if (chat.busy) { input.value = q; grow(); } else ask(q);
    } else if (matchMedia("(min-width: 760px)").matches) input.focus();
  })();
}

// 管家复盘的调整（§85）：模型决定的，写着为什么；自动生效的可以"不用这样调"（计划、热量、今天都恢复原来的）
function reviewExtra(c) {
  const box = h("div", { class: "cc-extra" });
  if (c.why) box.append(h("p", { class: "muted" }, c.why));
  if (c.status === "auto") {
    const undo = h("button", { class: "btn ghost small", type: "button" }, "不用这样调");
    undo.addEventListener("click", async () => {
      undo.disabled = true;
      try {
        await api("/iron/api/coach/decide", { method: "POST", body: JSON.stringify({ key: c.key, decision: "undo" }) });
        box.replaceChildren(h("p", { class: "muted" }, "好的，已经恢复原来的安排。"));
      } catch (err) { undo.disabled = false; box.append(h("p", { class: "error" }, err.message)); }
    });
    box.append(undo);
  }
  return box;
}

// 管家消息（spec [2026-10-23] §26）：上次看过之后的调整和要你确认的调整，放在对话最新的位置，在这里确认或暂不
let coachInbox = null;
async function loadInbox() {
  try { coachInbox = await api("/iron/api/coach/inbox"); } catch { coachInbox = null; }
}
const INBOX_WORD = { added: "新", changed: "调整", removed: "解除" };
function inboxView(r) {
  if (!r || (!r.changes.length && !r.pending.length)) return null;
  const moves = r.changes.filter((c) => c.kind === "target");
  const others = r.changes.filter((c) => c.kind !== "target");
  const decide = async (x, decision, row, btns) => {
    for (const b of btns) b.disabled = true;
    const out = h("div", { class: "inbox-result" });
    try {
      await api("/iron/api/coach/decide", { method: "POST", body: JSON.stringify({ key: x.key, decision }) });
      if (decision === "later") { row.replaceChildren(h("p", { class: "muted" }, `好的，「${x.title}」今天不再提。`)); return; }
      row.replaceChildren(h("b", {}, x.title), out);
      if (x.key === "proposal:diet") {
        const d = await api("/iron/api/diet/adjust", { method: "POST" });
        cache.metrics = null;
        out.append(h("p", {}, `已调整：每日热量目标约 ${Math.round(d.target)} 千卡。想撤销可以在饮食页撤销。`));
        return;
      }
      out.append(h("p", { class: "muted" }, "训练教练在改计划，大约要半分钟…"));
      const trigger = x.kind === "alert" ? `?trigger=${x.value.trigger}` : "";
      const p = await api(`/iron/api/review/proposal${trigger}`, { method: "POST" });
      if (p.status === "ok") draftView(out, p.draft, p.answer, p.warning);
      else out.replaceChildren(h("p", { class: "muted" }, p.message || "这次没能生成方案，可以直接告诉我想怎么改。"));
    } catch (err) {
      out.replaceChildren(h("p", { class: "error" }, err.message));
      row.append(out);
      for (const b of btns) b.disabled = false;
    }
  };
  const el = h("div", { class: "msg-coach inbox" },
    h("div", { class: "inbox-head" }, icon("coach", "sm"), h("b", {}, "管家"), h("span", { class: "muted" }, "按你最新的数据调整了方案")),
    others.length ? h("ul", { class: "inbox-list" }, others.slice(0, 3).map((c) => h("li", {},
      h("span", { class: `cc-tag ${c.change}` }, INBOX_WORD[c.change] || "调整"),
      h("div", { class: "cc-main" }, h("span", {}, c.change === "removed" ? `${c.before}（已解除）` : c.after),
        c.kind === "review" && c.change === "added" ? reviewExtra(c) : null)))) : null,
    r.pending.length ? h("div", { class: "inbox-pending" }, r.pending.map((x) => {
      const row = h("div", { class: "inbox-item" });
      const yes = h("button", { class: "btn small", type: "button" }, x.key === "proposal:diet" ? "确认调整" : "确认，出方案");
      const no = h("button", { class: "btn ghost small", type: "button" }, "暂不");
      yes.addEventListener("click", () => decide(x, "accept", row, [yes, no]));
      no.addEventListener("click", () => decide(x, "later", row, [yes, no]));
      row.append(x.why ? h("details", { class: "inbox-why" }, h("summary", {}, h("b", {}, x.title), icon("chevron", "xs")), h("p", { class: "muted" }, x.why))
        : h("b", {}, x.title), h("div", { class: "btn-row" }, yes, no));
      return row;
    })) : null);
  if (r.changes.length) api("/iron/api/coach/seen", { method: "POST", body: JSON.stringify({ version: r.version }) }).catch(() => {});
  r.changes = [];  // 看过了：这次打开对话之内不再重复
  return el;
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
  if (coachInbox?.view) thread.append(coachInbox.view);
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
  const at = msg.at ? h("time", { class: "msg-time", datetime: msg.at }, sessionTime(msg.at)) : null; // 提问和回答的时间（§50）
  if (msg.role === "user") return h("div", { class: "msg-user" }, msg.text,
    (msg.files || []).length ? h("div", { class: "msg-files" }, msg.files.map((n) => h("span", {}, icon("file", "xs"), n))) : null, at);
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
      h("button", { type: "button", class: msg.rating === -1 ? "on" : "", onclick: () => rate(msg, -1) }, icon("down", "xs"), "没用")) : null,
    msg.done ? at : null);
}

function applyBlock(msg, b) {
  switch (b.type) {
    case "start": msg.id = b.id || msg.id; break;
    case "tool_call":
      if (b.id === "turn") { msg.turn = b.args?.turn || ""; break; }  // 这一轮的编号：评价时带回（spec [2026-10-23] §31）
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

function coachMsg() { return { role: "coach", turn: "", steps: [], text: "", notices: [], sources: "", cards: [], id: "", error: "", done: false, open: false, srcOpen: false, rating: 0, el: null }; }

// 预览卡片（计划、训练记录）：确认才写入，写入后能撤销；状态从服务端取（刷新后也对）
const CARD_STATE = { pending: "", confirmed: "已保存", cancelled: "已取消", undone: "已撤销" };
function cardView(msg, card) {
  const d = card.data;
  if (!d) return null;
  if (!card.state && !card.busy) { card.busy = true; loadCard(msg, card); }
  const state = card.state || "pending";
  const expired = state === "pending" && Date.parse(d.expires) < Date.now();
  const plan = card.kind === "plan";
  const body = plan && d.rows
    ? [d.changes ? h("p", { class: "card-changes" }, d.changes) : null,  // 按操作改的：只列变化的行（spec [2026-10-23] §45）
      h("ul", { class: "pv-rows" }, d.rows.map((r) => h("li", {}, h("b", {}, r.what), " ",
        r.before ? h("span", { class: "muted" }, r.before) : null, r.before ? " → " : "", r.after))),
      ...(d.impact || []).map((x) => h("p", { class: "muted" }, x)),
      ...(d.skipped || []).map((x) => h("p", { class: "msg-note" }, `没改：${x}`)),
      d.hint ? h("p", { class: "muted" }, d.hint) : null]
    : plan
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
  msg.at = new Date().toISOString();
  chat.messages.push({ role: "user", text: q, files: attached.map((f) => f.file_name), at: msg.at }, msg);
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
    if (msg.turn) api(`/iron/api/turns/${encodeURIComponent(msg.turn)}/rating`, { method: "POST", body: JSON.stringify({ rating: value }) }).catch(() => {});
  } catch { msg.notices.push("评价没有保存成功，请稍后再试。"); refresh(msg); }
}

async function loadLatest() {
  chat.loaded = true;
  try {
    const list = (await apiData("/api/history")).summaries || [];
    if (list.length) await loadSession(list[0].session_id);
  } catch { /* 读不到以前的对话就从空白开始 */ }
}

// 打开某一段以前的对话（spec [2026-10-23] §36）：读出消息，接着在这个会话里问
async function loadSession(sessionId) {
  const rows = (await apiData(`/api/history?session_id=${encodeURIComponent(sessionId)}`)).history || [];
  chat.session = sessionId;
  chat.messages = rows.slice(-30).map((row) => {
      if (row.role === "user") return { role: "user", text: String(row.content || ""), at: row.timestamp || "" };
      const msg = coachMsg();
      msg.at = row.timestamp || "";
      msg.id = row.id || ""; msg.done = true;
      if (Array.isArray(row.content_dict)) row.content_dict.forEach((b) => applyBlock(msg, b));
      if (!msg.text) msg.text = String(row.content || "");
      msg.done = true;
      return msg;
    });
}

// 以前的对话：标题和日期，点开回到那段对话
async function historySheet() {
  const box = h("div", { class: "rows" }, ...skeleton(48, 48, 48));
  openSheet("以前的对话", box);
  let list;
  try { list = (await apiData("/api/history")).summaries || []; }
  catch (err) { box.replaceChildren(failed(err, historySheet)); return; }
  if (!list.length) { box.replaceChildren(h("p", { class: "muted" }, "还没有以前的对话。")); return; }
  box.replaceChildren(...list.slice(0, 50).map((x) => pressable(h("div", { class: `row-item${x.session_id === chat.session ? " on" : ""}` },
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.summary || "（没有标题）"), h("span", { class: "row-sub" }, sessionTime(x.timestamp))),
    x.session_id === chat.session ? h("span", { class: "row-end" }, "当前") : icon("chevron", "sm")), async () => {
    if (chat.busy) return;
    closeSheet();
    try { await loadSession(x.session_id); } catch (err) { chat.messages = []; chat.session = x.session_id; }
    chat.loaded = true;
    if (chat.els) drawThread(); else location.hash = "#chat";
  })));
}
function sessionTime(ts) {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const today = isoDay(new Date()), day = isoDay(d), hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return day === today ? `今天 ${hm}` : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
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

// ---- 训练记录器（spec [2026-10-23] §71）：选动作开始训练，一组一组记重量、次数、用时 ------------------------
let liveNow = null;  // 进行中的训练（有就显示"继续训练"）
let liveTick = null;
let liveBack = "home";
const liveSound = { on: true };
async function checkLive() {
  try { liveNow = (await api("/iron/api/live")).live; } catch { liveNow = null; }
  return liveNow;
}
async function startLive(body) {
  try { await api("/iron/api/live/start", { method: "POST", body: JSON.stringify(body) }); }
  catch (err) { flash(err.message); return; }
  const here = location.hash.slice(1) || "home";
  if (here !== "live") liveBack = here;
  closeSheet();
  if (here === "live") render(); else location.hash = "#live";
}
function liveEntry(body, label = "开始训练") {
  if (liveNow) {
    const mins = Math.max(0, Math.round((Date.now() - new Date(liveNow.started).getTime()) / 60000));
    return pressable(h("div", { class: "card live-entry on" }, icon("timer"),
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, "训练进行中"), h("span", { class: "row-sub" }, `已开始 ${mins} 分钟，点这里继续记`)),
      h("span", { class: "row-end" }, "继续", icon("chevron", "sm"))), () => startLive(body));
  }
  return h("button", { class: "btn block live-start", type: "button", onclick: () => startLive(body) }, icon("timer", "sm"), label);
}
const pad2 = (n) => String(n).padStart(2, "0");
function clock(sec) {
  const s = Math.max(0, Math.round(sec)), hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60);
  return hh ? `${hh}:${pad2(mm)}:${pad2(s % 60)}` : `${mm}:${pad2(s % 60)}`;
}
function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = 880; g.gain.value = 0.15; o.connect(g); g.connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.3); setTimeout(() => ctx.close(), 500);
  } catch { /* 没有声音也不影响 */ }
}

async function livePage(view) {
  let data;
  try { data = await api("/iron/api/live"); } catch (err) { view.replaceChildren(failed(err, render)); return; }
  const back = h("a", { class: "icon-btn", href: `#${liveBack}`, "aria-label": "返回（训练不会结束）" }, icon("back", "sm"));
  if (!data.live) {
    view.replaceChildren(h("div", { class: "live" },
      h("div", { class: "chat-bar" }, back, h("div", { class: "who" }, h("b", {}, "训练"))),
      h("div", { class: "card live-none" },
        h("p", {}, data.expired ? `上次训练 6 小时没动，已自动结束，保存了完成的组：${data.expired.line}` : "现在没有进行中的训练。"),
        h("button", { class: "btn block", type: "button", onclick: () => startLive({ today_plan: true }) }, icon("timer", "sm"), "开始训练"))));
    return;
  }
  const L = data.live;
  const steps = data.steps || {};
  const lib = await exercises().catch(() => null);
  const prog = h("div", { class: "live-prog" });
  let warn = null;  // 页面内提示 {i, text, back}：超上限可以确定或改回，空的一组提醒先填
  const okKg = {};  // 已经确认过的重量（每个动作）
  const stepOf = (it) => steps[it.exercise] || 2.5;
  const curPos = () => {
    for (let i = 0; i < L.items.length; i++) { const j = L.items[i].sets.findIndex((s) => !s.done); if (j >= 0) return { i, j }; }
    return null;
  };
  // 上下限：比计划重一档以内、10% 以内不提示；超出要确认；特殊人群和这次说过疼的不能比计划重；比以前最好成绩重 10% 以上提醒防手误
  const checkKg = (i, j, prev) => {
    const it = L.items[i], s = it.sets[j], w = s.weight_kg, plan = it.plan_kg;
    if (w == null || prev == null || w <= prev) { if (warn && warn.i === i) warn = null; return; }
    if (L.no_heavier && plan != null && w > plan) {
      s.weight_kg = prev <= plan ? prev : plan;
      warn = { i, text: "今天不比计划加重（身体情况或刚说过疼），按原来的重量练。" };
      return;
    }
    if (okKg[i] != null && w <= okKg[i]) return;
    const top = plan != null ? plan : prev;
    const over = w - top;
    if (plan != null && (over > stepOf(it) + 1e-9 || over > plan * 0.1 + 1e-9)) {
      warn = { i, text: `比计划重 ${Math.round((over / plan) * 100)}%，超过一档或一成，确定吗？`, back: plan, w };
    } else if (it.best && (e1rm(w, s.reps) || 0) > it.best * 1.1) {
      warn = { i, text: "比你以前最好的成绩重不少，确定没有多按？", back: prev, w };
    }
  };
  const skew = Date.now() - new Date(data.now).getTime();  // 手机和服务器的时钟差
  const t0 = new Date(L.started).getTime() + skew;
  let timing = null;  // 正在计时的一组 {i, j, from}
  let justDone = null;  // 刚点完成的一组：这一次画的时候弹一下（§92）
  let rest = null;    // 组间休息 {i, end}
  let saveT = null;
  const total = h("b", { class: "live-total" }, "0:00");
  const status = h("span", { class: "live-status" });
  const list = h("div", { class: "live-list" });
  const restBar = h("div", { class: "live-rest", hidden: true });
  const coachNote = h("div", { class: "card live-coach", hidden: true });  // 管家刚说的（§90）
  const sound = h("button", { class: "icon-btn", type: "button", "aria-label": "提示音", onclick: () => { liveSound.on = !liveSound.on; sound.replaceChildren(icon(liveSound.on ? "bell" : "mute", "sm")); } }, icon(liveSound.on ? "bell" : "mute", "sm"));

  const save = (now = false) => {
    clearTimeout(saveT);
    const go = async () => {
      try { await api("/iron/api/live", { method: "PUT", body: JSON.stringify({ id: L.id, items: L.items }) }); status.textContent = ""; }
      catch (err) { status.textContent = err.message; if (err.message.includes("刷新")) render(); }
    };
    if (now) return go();
    saveT = setTimeout(go, 500);
  };
  const num = (v) => (v === "" || v == null ? null : Number(v));
  const field = (s, key, attrs, i, j) => {
    const el = h("input", { type: "number", class: "live-in", value: s[key] ?? "", ...attrs });
    let prev = s[key];
    el.addEventListener("input", () => { s[key] = num(el.value); save(); });
    el.addEventListener("change", () => { if (key === "weight_kg") { checkKg(i, j, prev); draw(); } prev = s[key]; });
    return el;
  };
  const bump = (i, j, key, d) => {
    const s = L.items[i].sets[j], prev = s[key];
    s[key] = Math.max(0, Math.round(((prev || 0) + d) * 100) / 100);
    if (key === "weight_kg") checkKg(i, j, prev);
    save(); draw();
  };
  const markDone = (i, j) => {
    const it = L.items[i], s = it.sets[j];
    if (s.done) { s.done = false; s.at = null; save(true); draw(); return; }
    const timingThis = timing && timing.i === i && timing.j === j;
    if (it.timed ? !(s.seconds > 0) && !timingThis : !(s.reps > 0)) {  // 空的一组不能打勾（§104 需求 1）
      warn = { i, text: it.timed ? "先填秒数，或点计时。" : "先填这一组做了几次（和重量），再打勾。" };
      draw(); return;
    }
    if (warn && warn.i === i) warn = null;
    if (timing && timing.i === i && timing.j === j) { s.seconds = Math.max(1, Math.round((Date.now() - timing.from) / 1000)); timing = null; }
    s.done = true; s.at = new Date().toISOString();
    rest = { i, end: Date.now() + it.rest * 1000 };
    // 破纪录：超过以前最好的一组，也超过这次已经做完的（同一次只提示新高的那一下，§92）
    const e = e1rm(s.weight_kg, s.reps);
    const bar = Math.max(it.best || 0, ...it.sets.filter((x, k) => x.done && k !== j).map((x) => e1rm(x.weight_kg, x.reps) || 0));
    if (it.best && e && e > bar + 0.05) {
      buzz([30, 60, 30]);
      flash(h("span", {}, icon("trophy", "sm"), h("b", {}, "新纪录 "),
        `${it.exercise} ${s.weight_kg}×${s.reps}，估算最大重量 ${Math.round(e)} 公斤（以前 ${Math.round(it.best)}）`));
    } else buzz(15);
    // 下一组的建议：这组次数没做够，下一组降一档（还是原来的重量时才改，他自己改过的不动）
    const next = it.sets[j + 1];
    if (!it.timed && next && !next.done && s.weight_kg && next.weight_kg === s.weight_kg && next.reps && s.reps < next.reps) {
      next.weight_kg = Math.max(0, Math.round((s.weight_kg - stepOf(it)) * 100) / 100);
      flash(`这组少了 ${next.reps - s.reps} 次，下一组先用 ${next.weight_kg} 公斤`);
    }
    justDone = { i, j };
    save(true); draw(); tick();
    justDone = null;
  };
  const toggleTiming = (i, j) => {
    timing = timing && timing.i === i && timing.j === j ? null : { i, j, from: Date.now() };
    draw();
  };
  const move = (i, d) => { const k = i + d; if (k < 0 || k >= L.items.length) return; [L.items[i], L.items[k]] = [L.items[k], L.items[i]]; rest = null; timing = null; save(true); draw(); };
  const dropItem = (i) => { L.items.splice(i, 1); rest = null; timing = null; save(true); draw(); };
  const addSet = (i) => {
    const it = L.items[i], last = it.sets[it.sets.length - 1] || {};
    if (it.sets.length >= 20) return;
    it.sets.push({ weight_kg: last.weight_kg ?? null, reps: it.timed ? null : last.reps ?? null, seconds: it.timed ? last.seconds ?? null : null, done: false, at: null });
    save(true); draw();
  };
  const dropSet = (i, j) => { L.items[i].sets.splice(j, 1); timing = null; save(true); draw(); };

  const row = (it, i, s, j) => {
    const live = timing && timing.i === i && timing.j === j;
    const tbtn = h("button", { class: `live-time${live ? " running" : ""}${s.seconds ? " has" : ""}`, type: "button", "aria-label": live ? "停止计时" : "这一组计时（可不计）", onclick: () => toggleTiming(i, j), disabled: s.done },
      icon("timer", "xs"), h("span", { "data-run": live ? "1" : "" }, live ? clock((Date.now() - timing.from) / 1000) : s.seconds ? `${s.seconds}″` : "计时"));
    const inputs = it.timed
      ? [field(s, "seconds", { inputmode: "numeric", min: "1", max: "3600", placeholder: "秒", "aria-label": `第 ${j + 1} 组秒数` }), h("span", { class: "unit" }, "秒")]
      : [field(s, "weight_kg", { inputmode: "decimal", min: "0", max: "500", step: "0.5", placeholder: "公斤", "aria-label": `第 ${j + 1} 组重量` }, i, j), h("span", { class: "unit" }, "×"),
        field(s, "reps", { inputmode: "numeric", min: "0", max: "100", placeholder: "次", "aria-label": `第 ${j + 1} 组次数` }, i, j)];
    const pop = justDone && justDone.i === i && justDone.j === j;
    const pr = s.done && it.best && (e1rm(s.weight_kg, s.reps) || 0) > it.best;
    const here = curPos();
    return h("div", { class: `set-row${s.done ? " done" : ""}${pop ? " pop" : ""}${here && here.i === i && here.j === j ? " cur" : ""}` },
      h("span", { class: "set-n" }, String(j + 1)), ...inputs, it.timed ? null : tbtn,
      pr ? h("span", { class: "pr-tag" }, "新纪录") : null,
      h("button", { class: "live-done", type: "button", "aria-pressed": String(s.done), "aria-label": s.done ? "取消完成" : "完成这一组", onclick: () => markDone(i, j) }, icon("check", "sm")),
      !s.done && it.sets.length > 1 ? h("button", { class: "live-x", type: "button", "aria-label": "删掉这一组", onclick: () => dropSet(i, j) }, icon("x", "xs")) : h("span", { class: "live-x" }));
  };
  // 当前这一组（§104 需求 6）：动作图、一句要点、− / + 一档、一个大按钮
  const stepper = (label, value, unit, onDown, onUp, hot) => h("div", { class: "stepper" },
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}减`, onclick: onDown }, "−"),
    h("span", { class: "step-val" }, h("b", { class: `num${hot ? " hot" : ""}` }, value == null ? "–" : String(value)), h("small", {}, unit)),
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}加`, onclick: onUp }, "+"));
  const focus = (it, i) => {
    const here = curPos();
    if (!here || here.i !== i) return null;
    const j = here.j, s = it.sets[j], move = lib?.exercises?.find((x) => x.name === it.exercise);
    const hot = s.weight_kg != null && it.plan_kg != null && s.weight_kg > it.plan_kg;
    return h("div", { class: "live-focus" },
      h("div", { class: "lf-top" }, thumb(lib, it.exercise, "lf-img"),
        h("div", { class: "row-main" }, move?.cues?.[0] ? h("span", { class: "row-sub" }, move.cues[0]) : null)),
      it.timed ? null : h("div", { class: "lf-steps" },
        stepper("重量", s.weight_kg, "公斤", () => bump(i, j, "weight_kg", -stepOf(it)), () => bump(i, j, "weight_kg", stepOf(it)), hot),
        stepper("次数", s.reps, "次", () => bump(i, j, "reps", -1), () => bump(i, j, "reps", 1))),
      warn && warn.i === i ? h("div", { class: "lf-warn", role: "status" }, h("span", {}, warn.text),
        warn.back != null ? h("button", { class: "btn small warn-ok", type: "button", onclick: () => { okKg[i] = warn.w; warn = null; draw(); } }, "确定") : null,
        warn.back != null ? h("button", { class: "link warn-back", type: "button", onclick: () => { s.weight_kg = warn.back; warn = null; save(); draw(); } }, `改回 ${warn.back}`) : null) : null,
      h("button", { class: "btn block lf-done", type: "button", onclick: () => markDone(i, j) }, `完成第 ${j + 1} 组`));
  };
  const card = (it, i) => h("section", { class: `card live-card${it.sets.length && it.sets.every((s) => s.done) ? " all-done" : ""}${curPos()?.i === i ? " cur" : ""}` },
    h("div", { class: "live-head" },
      h("div", { class: "row-main" }, h("b", {}, it.exercise, it.sets.length && it.sets.every((s) => s.done) ? h("span", { class: "done-mark", "aria-label": "这个动作做完了" }, icon("check", "xs")) : null),
        it.target ? h("span", { class: "row-sub" }, it.target) : null),
      h("button", { class: "icon-btn", type: "button", "aria-label": "上移", onclick: () => move(i, -1), disabled: i === 0 }, icon("arrowUp", "xs")),
      h("button", { class: "icon-btn", type: "button", "aria-label": "下移", onclick: () => move(i, 1), disabled: i === L.items.length - 1 }, icon("arrowDown", "xs")),
      h("button", { class: "icon-btn", type: "button", "aria-label": "删掉这个动作", onclick: () => dropItem(i) }, icon("x", "xs"))),
    focus(it, i),
    warn && warn.i === i && curPos()?.i !== i ? h("p", { class: "lf-warn", role: "status" }, warn.text) : null,
    it.timed ? h("p", { class: "caption" }, "计时动作：填秒数，或点计时") : null,
    it.timed ? h("div", { class: "live-timed" }, h("button", { class: `btn small${timing && timing.i === i ? "" : " ghost"}`, type: "button", onclick: () => { const j = it.sets.findIndex((s) => !s.done); if (j >= 0) (timing && timing.i === i ? markDone(i, timing.j) : toggleTiming(i, j)); } }, icon("timer", "sm"), timing && timing.i === i ? "停，记下这组" : "开始计时")) : null,
    h("div", { class: "set-list" }, it.sets.map((s, j) => row(it, i, s, j))),
    h("button", { class: "link", type: "button", onclick: () => addSet(i) }, icon("plus", "xs"), "加一组"));
  const draw = () => {
    const all = L.items.reduce((a, it) => a + it.sets.length, 0), done = L.items.reduce((a, it) => a + it.sets.filter((s) => s.done).length, 0);
    prog.hidden = !all;
    prog.replaceChildren(h("span", {}, `第 ${Math.min(done + 1, all)} / 共 ${all} 组`), h("div", { class: "thin-bar" }, h("span", { style: `width:${all ? Math.round((done / all) * 100) : 0}%` })));
    list.replaceChildren(...(L.items.length ? L.items.map(card) : [h("div", { class: "card live-none" }, h("p", { class: "muted" }, "还没有动作，点下面的「加动作」。"))]));
  };
  const tick = () => {
    total.textContent = clock((Date.now() - t0) / 1000);
    const run = list.querySelector('[data-run="1"]');
    if (run && timing) run.textContent = clock((Date.now() - timing.from) / 1000);
    if (rest) {
      const left = (rest.end - Date.now()) / 1000;
      if (left <= 0) {
        rest = null; restBar.hidden = true;
        if (liveSound.on) beep();
        navigator.vibrate?.([200, 100, 200]);
        return;
      }
      const it = L.items[rest.i];
      const adj = (d) => { it.rest = Math.min(600, Math.max(15, it.rest + d)); rest.end += d * 1000; save(); tick(); };
      restBar.hidden = false;
      restBar.replaceChildren(h("div", {}, h("span", { class: "muted" }, "组间休息"), h("b", {}, clock(left))),
        h("div", { class: "live-rest-btns" },
          h("button", { class: "btn ghost small", type: "button", onclick: () => adj(-15) }, "−15 秒"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => adj(15) }, "+15 秒"),
          h("button", { class: "btn small", type: "button", onclick: () => { rest = null; restBar.hidden = true; } }, "跳过")));
    }
  };
  const addMove = async () => {
    const lib = await exercises();
    const q = h("input", { type: "search", placeholder: "搜动作，比如卧推", "aria-label": "搜动作" });
    const box = h("div", { class: "rows" });
    const show = () => {
      const k = q.value.trim();
      box.replaceChildren(...lib.exercises.filter((x) => !k || `${x.name}${x.part}${x.muscles}`.includes(k)).slice(0, 30).map((x) => pressable(h("div", { class: "row-item" },
        h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, `${x.part} · ${x.equipment.slice(0, 2).join("、")}`))), async () => {
        await save(true);
        try { const r = await api("/iron/api/live/items", { method: "POST", body: JSON.stringify({ exercise: x.name }) }); L.items = r.live.items; closeSheet(); draw(); }
        catch (err) { flash(err.message); }
      })));
    };
    q.addEventListener("input", show); show();
    openSheet("加动作", q, box);
  };
  // 跟管家说（§90）：太重、很累、哪里疼……由管家改后面的组
  const talk = async () => {
    await save(true);
    const cur = L.items.findIndex((it) => it.sets.some((s) => !s.done));
    let pick = cur;
    const sel = h("select", { "aria-label": "说的是哪个动作" },
      ...L.items.map((it, i) => h("option", { value: String(i), selected: i === pick }, it.exercise)),
      h("option", { value: "-1", selected: pick === -1 }, "整次训练"));
    sel.addEventListener("change", () => { pick = Number(sel.value); });
    const input = h("input", { type: "text", maxlength: "100", placeholder: "比如：膝盖有点疼、只剩 10 分钟", "aria-label": "跟管家说" });
    const msg = h("p", { class: "error" });
    const btns = [];
    const send = async (said) => {
      if (!said.trim()) { input.focus(); return; }
      btns.forEach((b) => { b.disabled = true; });
      msg.textContent = "管家在想……";
      try {
        const r = await api("/iron/api/live/adjust", { method: "POST", body: JSON.stringify({ id: L.id, said: said.trim(), item: pick }) });
        L.items = r.live.items; draw(); closeSheet();
        coachNote.hidden = false;
        coachNote.replaceChildren(h("div", { class: "live-coach-head" }, icon("coach", "sm"), h("b", {}, "管家")), h("p", {}, r.say),
          r.end ? h("button", { class: "btn small", type: "button", onclick: finish }, "结束训练") : null);
      } catch (err) { msg.textContent = err.message; btns.forEach((b) => { b.disabled = false; }); }
    };
    const quick = ["太重了", "太轻了", "很累", "时间不够了"].map((t) => h("button", { class: "btn ghost small", type: "button", onclick: () => send(t) }, t));
    const hurt = h("button", { class: "btn ghost small", type: "button", onclick: () => { input.value = "有点疼"; input.focus(); input.setSelectionRange(0, 0); } }, "哪里疼");
    const go = h("button", { class: "btn small", type: "button", onclick: () => send(input.value) }, "发送");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(input.value); });
    btns.push(...quick, hurt, go);
    openSheet("跟管家说", h("div", { class: "sheet-stack" },
      h("label", {}, "说的是", sel),
      h("div", { class: "btn-row live-quick" }, ...quick, hurt),
      h("div", { class: "live-say" }, input, go), msg));
  };
  const finish = () => {
    const doneSets = L.items.flatMap((it) => it.sets.filter((s) => s.done).map((s) => [it, s]));
    const vol = doneSets.reduce((n, [it, s]) => n + (it.timed ? 0 : (s.weight_kg || 0) * (s.reps || 0)), 0);
    let rpe = null;
    const chips = h("div", { class: "rpe-pick" });
    const drawChips = () => chips.replaceChildren(...Array.from({ length: 10 }, (_, k) => h("button", { type: "button", class: rpe === k + 1 ? "on" : "", "aria-pressed": String(rpe === k + 1), onclick: () => { rpe = rpe === k + 1 ? null : k + 1; drawChips(); } }, String(k + 1))));
    drawChips();
    const st = stateBox();
    const msg = h("p", { class: "error" });
    const sure = h("div", { class: "btn-row", hidden: true },
      h("span", { class: "muted" }, "放弃后这次不留记录，确定吗？"),
      h("button", { class: "btn danger small", type: "button", onclick: async () => { await api("/iron/api/live", { method: "DELETE" }); liveNow = null; closeSheet(); location.hash = `#${liveBack}`; } }, "确定放弃"));
    const body = h("div", { class: "sheet-stack" },
      h("div", { class: "live-sum" },
        ...[["总时长", clock((Date.now() - t0) / 1000)], ["动作", `${new Set(doneSets.map(([it]) => it.exercise)).size} 个`], ["组数", `${doneSets.length} 组`], ["总训练量", `${Math.round(vol)} 公斤`]]
          .map(([k, v]) => h("div", {}, h("span", { class: "muted" }, k), h("b", {}, v)))),
      h("div", {}, h("h3", {}, "这次感受（1 很轻松 … 10 到极限，可不选）"), chips),
      st.el,
      msg,
      h("button", { class: "btn block", type: "button", disabled: !doneSets.length, onclick: async () => {
        await save(true);
        try {
          const r = await api("/iron/api/live/finish", { method: "POST", body: JSON.stringify({ rpe, ...st.read() }) });
          liveNow = null; cache.metrics = null;
          const warn = await st.attach(r.workout?.id);
          if (warn) flash(warn);
          const line = r.workout?.line || "";
          // 练完的卡（§92）：完成动效、数字数上来、破纪录、本周进度环涨上去，刚好达成本周目标时放彩带
          const c = r.workout?.celebrate || {}, wk = c.week || {}, prs = c.prs || [];
          const won = Boolean(wk.reached_now);
          const nums = [["总时长", r.summary.minutes || 0, " 分钟"], ["组数", doneSets.length, " 组"], ["总训练量", Math.round(vol), " 公斤"]];
          const cells = nums.map(([k, v, u]) => { const b = h("b", {}, calm() ? String(v) : "0"); return { el: h("div", {}, h("span", { class: "muted" }, k), h("span", {}, b, h("small", { class: "muted" }, u))), b, v }; });
          const rg = wk.planned ? ring(wk.before ?? wk.done, wk.planned) : null;
          body.replaceChildren(
            h("div", { class: "done-hero" }, h("div", { class: "cheer-burst" }, icon("check")),
              h("b", { class: "done-title" }, won ? "本周目标达成" : prs.length ? "破纪录了" : "练完了"),
              h("p", { class: "muted" }, line)),
            h("div", { class: "live-sum done-sum" }, ...cells.map((x) => x.el)),
            prs.length ? h("div", { class: "pr-list" }, ...prs.map((p) => h("div", { class: "pr-item" }, icon("trophy", "sm"),
              h("div", {}, h("b", {}, `${p.exercise} ${p.weight_kg}×${p.reps}`), h("small", { class: "muted" }, `估算最大重量 ${Math.round(p.e1rm)} 公斤，以前 ${Math.round(p.before)}`))))) : null,
            rg ? h("div", { class: "done-week" }, rg, h("p", {}, won ? "这一练让本周目标刚好达成！" : wk.done >= wk.planned ? "本周目标已经达成，这一练是额外加分。" : `本周第 ${wk.done} 练，还差 ${wk.planned - wk.done} 练。`)) : null,
            h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我刚练完：${line}，总时长 ${r.summary.minutes} 分钟${rpe ? `，感受 ${rpe} 分` : ""}。这次练得怎么样？下次要怎么调？`) }, icon("coach", "sm"), "问问教练"),
            h("a", { class: "btn block", href: "#home", onclick: closeSheet }, "回首页"));
          cells.forEach((x) => countUp(x.b, x.v));
          if (rg) setTimeout(() => {
            rg.style.setProperty("--p", String(Math.min(1, wk.done / wk.planned)));
            rg.querySelector("b").textContent = String(wk.done);
            if (wk.done >= wk.planned) rg.classList.add("full");
          }, calm() ? 0 : 350);
          buzz(won || prs.length ? [40, 60, 40] : 25);
          if (won || prs.length) confetti();
        } catch (err) { msg.textContent = err.message; }
      } }, doneSets.length ? "保存这次训练" : "还没有完成的组"),
      h("button", { class: "link danger-link", type: "button", onclick: () => { sure.hidden = false; } }, "放弃本次"), sure);
    openSheet("结束训练", body);
  };

  view.replaceChildren(h("div", { class: "live" },
    h("div", { class: "chat-bar live-bar" }, back,
      h("div", { class: "who" }, h("span", {}, L.session ? `训练中 · ${L.session}` : "训练中"), total),
      sound, h("button", { class: "btn quiet small", type: "button", onclick: finish }, "结束")),
    prog, status, coachNote, list,
    h("div", { class: "btn-row live-actions" },
      h("button", { class: "btn ghost", type: "button", onclick: addMove }, icon("plus", "sm"), "加动作"),
      h("button", { class: "btn ghost", type: "button", onclick: talk }, icon("coach", "sm"), "跟管家说")),
    restBar));
  draw(); tick();
  liveTick = setInterval(tick, 500);
}

// ---- 路由 ---------------------------------------------------------------------------------
const PAGES = {
  home: { title: "今天", kicker: todayLabel, render: home, skeleton: [200, 300, 320] },
  train: { title: "训练", render: train, skeleton: [44, 60, 420] },
  body: { title: "身体", render: body, skeleton: [120, 320, 320] },
  chat: { title: "教练", full: true, render: chatPage },
  live: { title: "训练中", full: true, render: livePage },
  food: { title: "饮食", render: food, skeleton: [180, 220, 150] },
  tier: { title: "夯榜", render: tierPage, skeleton: [44, 40, 520] },
  me: { title: "我的", render: me, skeleton: [120, 200, 320] },
};
let renderSeq = 0;

async function render() {
  closeSheet();
  if (rankTimer) { clearInterval(rankTimer); rankTimer = null; }
  if (liveTick) { clearInterval(liveTick); liveTick = null; }  // 离开训练页：停掉计时（训练本身存在服务端，回来接着计）
  if (!location.hash.startsWith("#train/plan") && location.hash !== "#train") planDay = null;
  const seq = ++renderSeq;
  const view = $("view");
  const signedIn = Boolean(store.get());
  document.body.classList.remove("chatting");
  if (!signedIn) {
    $("bar").hidden = true; $("tabs").hidden = true; $("fab").hidden = true; chat.els = null;
    view.replaceChildren(); loginView(view); return;
  }
  const [name, sub, ...rest] = (location.hash.slice(1) || "home").split("/");
  // 旧地址（§65）：数据页、"我的"的数据和档案段进个人中心；"我的"里的夯进夯拉榜
  if (name === "data") { location.replace("#body"); return; }
  if (name === "moves") { location.replace("#train/moves"); return; }  // 旧地址（§104）：动作页进了训练
  if (name === "me" && sub && sub !== "tier") { location.replace("#me"); return; }
  if (name === "me" && sub === "tier") { location.replace(`#tier${rest.length ? `/${rest.join("/")}` : ""}`); return; }
  const page = PAGES[name] ? name : "home";
  const cfg = PAGES[page];
  document.title = `${cfg.title} · AI 健身管家`;
  for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.tab === page);
  $("tabs").hidden = Boolean(cfg.full);
  $("bar").hidden = Boolean(cfg.full);
  $("fab").hidden = page !== "home";  // 首页右下角"＋"快捷记录（§104 需求 7）
  $("tierlink").hidden = page !== "home";  // 夯榜入口在首页右上角，不显示榜单内容
  $("avatar").hidden = page === "me"; // 个人中心从右上角头像进（§65）
  $("avatar").textContent = (tokenEmail()[0] || "我").toUpperCase();
  if (cfg.full) {
    document.body.classList.add("chatting");
    view.replaceChildren(); cfg.render(view); return;
  }
  chat.els = null;
  chat.back = sub ? `${page}/${sub}` : page;
  $("title").textContent = cfg.title;
  $("kicker").textContent = cfg.kicker ? cfg.kicker() : "";
  view.replaceChildren(...skeleton(...(cfg.skeleton || [200])));
  window.scrollTo(0, 0);
  const box = document.createDocumentFragment();
  const holder = h("div");
  try {
    await cfg.render(holder, sub, decodeURIComponent(rest.join("/")));
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
  $("fab").addEventListener("click", quickAdd);
  render();
});
