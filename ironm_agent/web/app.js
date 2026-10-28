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
    (m.missing || []).some((x) => x.includes("我的")) ? h("a", { class: "btn block", href: "#me/profile" }, "去「我的」填写") : null,
    (m.missing || []).some((x) => x.includes("手表")) ? h("button", { class: "btn block", type: "button", onclick: appleSheet }, icon("phone", "sm"), "导入苹果健康数据") : null,
    CALC_FROM[m.key] ? h("div", { class: "calc-from" }, h("h3", {}, "这个数不能直接改"), h("p", {}, CALC_FROM[m.key][0]), h("p", { class: "muted" }, CALC_FROM[m.key][1]),
      h("a", { class: "btn ghost block", href: "#me/profile", onclick: closeSheet }, "去「我的」修改")) : null,
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

// 首页（spec [2026-10-23] §34）：一句鼓励的话、今日任务、战报、本周计划（带天气）、日历
async function home(view) {
  const [brief, training, cal, week, meals] = await Promise.all([
    api("/iron/api/brief").catch(() => null),
    api("/iron/api/training").catch(() => null),
    api("/iron/api/calendar").catch(() => null),
    api("/iron/api/week").catch(() => null),
    api("/iron/api/meals").catch(() => null),
  ]);
  planSessions = training?.plan?.sessions || []; planTargets = training?.targets || {};
  view.append(
    brief?.hero?.cheer ? h("p", { class: "home-cheer" }, brief.hero.cheer) : null,
    askBox(),
    taskCard(brief, training, week, meals),
    reportCard(brief, cal),
    weekPlanCard(week, cal, brief),
    monthCard(brief, week));
}

// 首页问教练（spec [2026-10-23] §59 需求 2）：发出去就进入对话直接问
function askBox() {
  const input = h("input", { type: "text", placeholder: "问教练，比如今天练什么", "aria-label": "问教练", enterkeyhint: "send", maxlength: "500" });
  const form = h("form", { class: "ask-box" },
    h("span", { class: "ask-icon" }, icon("coach", "sm")), input,
    h("button", { class: "send", type: "submit", "aria-label": "发送" }, icon("send", "sm")));
  form.addEventListener("submit", (e) => { e.preventDefault(); const q = input.value.trim(); if (q) askCoach(q); else location.hash = "#chat"; });
  return h("div", { class: "ask-wrap" }, form,
    h("button", { class: "link ask-past", type: "button", onclick: historySheet }, icon("history", "xs"), "以前的对话"));
}

// 本周进度环（spec [2026-10-23] §19）
function ring(done, planned) {
  const p = planned ? Math.min(1, done / planned) : 0;
  return h("div", { class: `ring${planned && done >= planned ? " full" : ""}`, style: `--p:${p}`, role: "img", "aria-label": planned ? `本周完成 ${done} / ${planned} 次` : "本周还没有计划" },
    h("div", { class: "ring-in" }, h("b", {}, String(done)), h("span", {}, planned ? `/ ${planned}` : "次"), h("small", {}, "本周")));
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
  setTimeout(close, 2400);
}

// 目标进度与阶段复测（spec [2026-10-23] §18 需求 6）：没设目标时首页不显示，数据页提示去"我的"设置
const fmtDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${y}年${m}月${d}日`; };
function goalCard({ empty = false } = {}) {
  const box = h("div", { class: "goal-box" });
  const draw = (st) => {
    const g = st.goal, p = st.progress;
    if (!g) {
      if (!empty) { box.replaceChildren(); return; }
      box.replaceChildren(h("div", { class: "card" }, h("p", { class: "muted" }, "还没有设目标体重和日期。"),
        h("a", { class: "link", href: "#me/profile" }, "到「我的」设置", icon("chevron", "xs"))));
      return;
    }
    const kg = (v) => (v == null ? "—" : `${num(v)}`);
    const tone = { reached: "good", on_track: "good", ahead: "good", behind: "warn", wrong_way: "warn" }[p.status] || "";
    box.replaceChildren(h("div", { class: "card goal" },
      h("div", { class: "goal-head" }, h("b", {}, `目标体重 ${kg(g.value)} 公斤`), h("span", { class: "muted" }, `${fmtDay(g.by)}前`)),
      h("div", { class: "goal-nums" },
        ...[["起点", p.start], ["当前", p.current], ["目标", p.target]].map(([k, v]) => h("div", {}, h("span", { class: "muted" }, k), h("b", {}, kg(v)), h("span", { class: "muted" }, "公斤")))),
      p.predicted ? h("p", {}, "预计达成：", h("b", {}, fmtDay(p.predicted))) : null,
      p.message ? h("p", { class: tone ? `tone-${tone}` : "" }, p.message) : null,
      p.missing ? h("p", { class: "muted" }, p.missing) : null,
      p.pace ? h("div", { class: "notice-line" }, icon("alert", "xs"), p.pace) : null,
      p.retest.due ? h("div", { class: "notice-line" }, icon("alert", "xs"), h("div", {}, p.retest.text,
        h("button", { class: "link", type: "button", onclick: async () => draw(await api("/iron/api/goal/retest", { method: "POST" })) }, "已复测"))) : null));
  };
  api("/iron/api/goal").then(draw).catch(() => box.replaceChildren());
  return box;
}

function goalSection() {
  const box = h("div", { class: "card" });
  const view = (st) => {
    const g = st.goal;
    box.replaceChildren(h("div", { class: "kv" }, h("span", {}, "目标体重"),
      h("span", {}, g ? `${num(g.value)} 公斤，${fmtDay(g.by)}前` : "未设置", " ",
        h("button", { class: "link", type: "button", onclick: () => edit(g) }, icon("edit", "xs"), g ? "修改" : "设置"))));
  };
  const edit = (g) => {
    const value = h("input", { type: "number", inputmode: "decimal", min: "30", max: "250", step: "0.1", value: g ? String(g.value) : "", placeholder: "比如 65" });
    const by = h("input", { type: "date", value: g ? g.by : "" });
    const msg = h("div", { class: "error" });
    const form = h("form", {}, h("label", {}, "目标体重（公斤）", value), h("label", {}, "目标日期", by), msg,
      h("div", { class: "form-actions" },
        g ? h("button", { class: "btn ghost", type: "button", onclick: async () => view(await api("/iron/api/goal", { method: "DELETE" })) }, "清除") : null,
        h("button", { class: "btn ghost", type: "button", onclick: () => view({ goal: g }) }, "取消"),
        h("button", { class: "btn", type: "submit" }, "保存")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!value.value || !by.value) { msg.textContent = "目标体重和日期都要填"; return; }
      msg.textContent = "正在保存…";
      try { view(await api("/iron/api/goal", { method: "PUT", body: JSON.stringify({ value: Number(value.value), by: by.value }) })); }
      catch (err) { msg.textContent = err.message; }
    });
    box.replaceChildren(form); value.focus();
  };
  api("/iron/api/goal").then(view).catch(() => view({ goal: null }));
  return section("目标", null, box, h("p", { class: "caption", style: "padding:0 2px" }, "首页和数据页会显示起点、当前、目标和按体重趋势预计达成的日期；每 4 周提醒复测一次。"));
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

// 一条任务：做完的打勾；可以点开（展开详情）或跳转
function taskRow(ic, title, sub, done, onOpen) {
  const row = h("div", { class: `task${done ? " done" : ""}` },
    h("span", { class: "task-check", "aria-hidden": "true" }, done ? icon("check", "xs") : null),
    h("div", { class: "task-main" }, h("b", {}, title), sub ? h("span", {}, sub) : null),
    onOpen ? icon("chevron", "xs") : null);
  return onOpen ? pressable(row, onOpen) : row;
}

// 今日任务：今天的训练（按状态和天气调整过的版本）、记饮食、确认管家的调整
function taskCard(brief, tr, week, meals) {
  const t = brief?.today?.training, today = week?.days?.find((d) => d.today);
  const rows = [];
  let total = 0, finished = 0;
  const count = (done) => { total += 1; if (done) finished += 1; };
  if (!tr?.plan) {
    count(false);
    rows.push(taskRow("dumbbell", "排一份训练计划", "告诉教练你的目标、每周能练几天、有什么器械", false, () => askCoach("帮我排一个每周训练计划")));
  } else if (!today?.session) {
    count(true);
    rows.push(taskRow("dumbbell", "今天休息", "散散步、拉拉伸，让身体恢复", true));
  } else if (week?.sick?.mode === "rest" && !(t?.done || today.done)) {
    count(true);  // 生病还没好：今天先休息（spec [2026-10-23] §46）
    rows.push(taskRow("dumbbell", "今天先休息", week.sick.why, true));
  } else {
    const done = Boolean(t?.done || today.done);
    count(done);
    const minutes = (today.version || today.session).minutes;
    const wx = today.weather;
    const ease = { light: "按轻松版：组数减半、不练到力竭", ease: "病后第一次，按平时的七成" }[week?.sick?.mode];
    const sub = done ? "已完成，好好恢复" : [ease || `约 ${minutes} 分钟`, wx ? `${wx.text} ${wx.temp}°` : "", today.changes.length ? "已按天气调整" : ""].filter(Boolean).join(" · ");
    const detail = h("div", { class: "task-detail", hidden: true });  // 动作清单默认收起，点开再看
    if (!done) detail.append(todayVersion(today.session, { compact: true }));
    rows.push(taskRow("dumbbell", `练${today.session.name}`, sub, done, done ? null : () => { detail.hidden = !detail.hidden; }), detail);
  }
  const n = meals?.meals?.length || 0;
  count(n > 0);
  rows.push(taskRow("food", "记录今天吃了什么", n ? `已记 ${n} 餐，约 ${Math.round(meals.totals.kcal)} 千卡` : "拍一张或说一句就行", n > 0, () => { location.hash = "#food"; }));
  const inbox = h("div", { hidden: true });
  const progress = h("span", { class: "muted mono" }, `${finished}/${total}`);
  api("/iron/api/coach/inbox").then((r) => {
    if (!r.pending.length) return;
    total += 1;
    progress.textContent = `${finished}/${total}`;
    inbox.replaceChildren(taskRow("coach", `确认管家的 ${r.pending.length} 条调整`, r.pending.map((x) => x.title).join("；").slice(0, 40), false, () => { location.hash = "#chat"; }));
    inbox.hidden = false;
  }).catch(() => {});
  return h("section", { class: "card home-card" }, cardHead("今日任务", progress), checkinRow(brief?.checkin), ...rows, inbox);
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

// 战报：本周进度环、本周练了几次、本月练了几天、本周还差几练
function reportCard(brief, cal) {
  const w = brief?.week, done = w?.done || 0, planned = w?.planned || 0;
  const stat = (k, v, u) => h("div", { class: "rep-stat" }, h("span", {}, k), h("b", {}, v, h("small", {}, u)));
  // 安全提醒放首页（spec [2026-10-23] §42）：一行标题，点开看原文
  const alerts = (brief?.alerts || []).map((a) => h("details", { class: "rep-alert" },
    h("summary", {}, icon("alert", "sm"), a.title), h("p", {}, a.text)));
  return h("section", { class: "card home-card" }, cardHead("战报", h("span", { class: "muted" }, "本周")),
    ...alerts,
    h("div", { class: "report" }, ring(done, planned),
      h("div", { class: "rep-stats" },
        stat("本周练了", `${done}`, planned ? ` / ${planned} 次` : " 次"),
        stat("本月练了", `${cal?.done_days?.length ?? 0}`, " 天"),
        stat(planned && done >= planned ? "本周目标" : "本周还差", planned && done >= planned ? "达成" : `${Math.max(0, planned - done)}`, planned && done >= planned ? "" : " 练"))));
}

// 本周计划：七天各练什么、天气、按天气调整过的标出来；下面逐条写按天气做的调整
function weekPlanCard(week, cal, brief) {
  if (!week) return null;
  const cells = week.days.map((c) => {
    const w = c.weather;
    const mark = c.changes.length && !c.past && !c.done;
    const cls = `wc-day${c.session ? " plan" : ""}${c.done ? " done" : ""}${c.today ? " today" : ""}${c.past ? " past" : ""}`;
    return pressable(h("span", { class: cls, "aria-label": `${c.today ? "今天" : c.weekday}，${c.session ? c.session.name : "休息"}${c.done ? "，练过" : ""}${w ? `，${w.text} ${w.temp}度` : ""}${mark ? "，按天气调整过" : ""}` },
      h("i", {}, c.today ? "今" : c.weekday.slice(1)),
      w && !c.past ? h("span", { class: "wc-wx" }, icon(wxIcon(w.text), "xs"), h("small", {}, `${w.temp}°`))
        : h("span", { class: "wc-wx none" }, c.done ? icon("check", "xs") : ""),
      h("b", {}, c.session ? c.session.name.slice(0, 2) : "休"),
      mark ? h("em", { class: `wc-warn ${badWeather(w?.level) ? "bad" : "hot"}`, "aria-hidden": "true" }) : null), () => daySheet(c, cal, brief));
  });
  const moved = week.days.filter((c) => c.changes.length && !c.past && !c.done);
  const notes = moved.map((c) => h("li", {}, h("b", {}, `${c.today ? "今天" : c.weekday}${c.weather ? c.weather.text : ""}`),
    `：${c.changes.join("；")}${c.better ? `，也可以挪到${c.better}（天气好）` : ""}`));
  return h("section", { class: "card home-card" },
    cardHead(week.place ? `本周计划 · ${week.place}` : "本周计划",
      h("button", { class: "link", type: "button", onclick: () => askCoach("帮我看看现在的训练计划，需要调整吗？") }, "调整", icon("chevron", "xs"))),
    h("div", { class: "wc-row" }, cells),
    notes.length ? h("ul", { class: "wc-notes" }, notes)
      : week.weather === "no_city" ? h("a", { class: "wc-note link", href: "#me/profile" }, icon("sun", "xs"), h("span", {}, "设置城市后，管家会按天气安排训练"))
        : week.weather === "ok" ? h("p", { class: "muted small" }, "这周的天气不影响训练安排。") : null);
}
const badWeather = (level) => level === "indoor" || level === "avoid";

// 点本周计划上的某一天：天气和影响、那天练什么（按天气调整过的版本）、练过的记录
function daySheet(c, cal, brief) {
  const [, mm, dd] = c.date.split("-").map(Number);
  const w = c.weather;
  const done = (cal?.days?.[c.date] || []).filter((e) => e.done);
  const shown = c.version || c.session;
  const t = brief?.today?.training;
  openSheet(`${c.today ? "今天" : c.weekday} · ${mm}月${dd}日`,
    w && !c.past ? h("div", { class: `day-wx ${w.level}` },
      h("div", { class: "day-wx-top" }, icon(wxIcon(w.text), "sm"),
        h("b", {}, w.live ? `${w.text} ${w.temp}°` : `${w.text} ${w.tmin}–${w.tmax}°`),
        h("span", { class: "muted" }, [w.live ? `体感 ${w.feels_like}°` : "", w.aqi_level ? `空气${w.aqi_level}` : "", w.rain != null ? `降水概率 ${w.rain}%` : ""].filter(Boolean).join(" · "))),
      h("p", {}, w.reasons.length ? `${w.name}：${w.reasons.join("；")}` : `${w.name}，天气不影响训练`)) : null,
    c.changes.length && !c.past ? h("div", { class: "callout" }, icon("coach", "sm"), h("div", {}, h("strong", {}, "管家按天气调整："), c.changes.join("；"), c.better ? `；也可以挪到${c.better}（天气好）。` : "。")) : null,
    c.session && !c.changes.length && !c.past && badWeather(w?.level) ? h("p", { class: "muted" }, "这天的动作都能在室内做，天气不影响。") : null,
    shown ? h("div", {}, h("h3", {}, `${shown.name} · 约 ${shown.minutes} 分钟`), h("ol", { class: "plan-items" }, shown.items.map((it) => h("li", {}, itemLine(it)))))
      : h("p", { class: "muted" }, "这天是休息日。"),
    done.length ? h("div", {}, h("h3", {}, "练过"), h("ul", { class: "tips" }, done.map((e) => h("li", {}, e.line)))) : null,
    c.today && c.session && !t?.done && !c.done ? h("button", { class: "btn block", type: "button", onclick: () => doneSheet(shown.name, c.version) }, icon("check", "sm"), "练完打卡") : null,
    c.session && !c.past ? h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`${c.today ? "今天" : c.weekday}${w ? `天气${w.text}，${w.tmin ?? w.temp}–${w.tmax ?? w.temp}℃` : ""}，我计划练${c.session.name}，怎么安排比较合适？`) }, icon("coach", "sm"), "问问教练这天怎么练") : null);
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
      h("button", { class: "btn block", type: "button", onclick: () => doneSheet(v.today.name, v.changed ? v.today : null) }, icon("check", "sm"), "练完打卡"));
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
    isToday && !t?.done ? h("button", { class: "btn block", type: "button", onclick: () => doneSheet(x.name) }, icon("check", "sm"), "完成打卡") : null,
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`${x.name}这次训练怎么练？每个动作要注意什么？`) }, icon("coach", "sm"), "问教练怎么练"));
}
const weekdayName = (d) => `周${WEEK[d - 1]}`;

let calMonth = "";
// 日历（spec [2026-10-23] §34）：整月训练记录放在首页；本周以后几天带天气图标
function monthCard(brief, week) {
  calMonth = "";
  const sky = Object.fromEntries((week?.days || []).filter((d) => d.weather && !d.past).map((d) => [d.date, d.weather]));
  const box = h("div", { class: "cal" });
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
      const cell = h("span", { class: cls, "aria-label": `${m}月${d}日${lit.has(iso) ? "，练过" : ""}${sky[iso] ? `，${sky[iso].text}` : ""}` }, String(d),
        sky[iso] && !lit.has(iso) ? h("i", { class: "cal-sky" }, icon(wxIcon(sky[iso].text), "xs")) : null);
      cells.push(entries.length ? pressable(cell, () => openSheet(`${m}月${d}日`,
        h("div", { class: "rows" }, entries.map((e) => h("div", { class: "row-item" },
          h("span", { class: `dot-state ${e.done ? "on" : ""}` }), h("div", { class: "row-main" }, h("span", { class: "row-title" }, e.line))))))) : cell);
    }
    const thisMonth = cal.today.slice(0, 7) === cal.month;
    box.replaceChildren(
      h("div", { class: "cal-head" },
        h("button", { class: "icon-btn", type: "button", "aria-label": "上个月", onclick: () => shift(-1) }, icon("back", "sm")),
        h("b", {}, `${y}年${m}月`),
        h("button", { class: "icon-btn", type: "button", "aria-label": "下个月", onclick: () => shift(1), disabled: thisMonth }, icon("chevron", "sm"))),
      h("div", { class: "cal-grid cal-week" }, WEEK.map((w) => h("span", {}, w))),
      h("div", { class: "cal-grid" }, cells),
      h("div", { class: "cal-foot" },
        h("span", { class: "muted" }, `这个月练了 ${cal.done_days.length} 天`),
));
  };
  box.append(...skeleton(260));
  draw();
  return h("section", { class: "card home-card" }, cardHead("日历"), box);
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
  const note = h("input", { type: "text", maxlength: "60", placeholder: "备注（可不填），比如有点累、膝盖没疼" });
  const msg = h("p", { class: "muted" });
  const save = h("button", { class: "btn block", type: "button", onclick: async () => {
    save.disabled = true; msg.textContent = "正在记下…";
    const filled = form ? form.read() : [];
    const byName = Object.fromEntries(filled.map((x) => [x.exercise, x]));
    const items = version ? version.items.map((it) => byName[it.exercise] || { exercise: it.exercise, sets: it.sets, reps: it.reps }) : filled;
    try {
      await api("/iron/api/workouts", { method: "POST", body: JSON.stringify({ session: session === "训练" ? "" : session, done: true, rpe: rpe || null,
        note: (version ? [note.value.trim(), "按今天的版本"].filter(Boolean).join("；") : note.value.trim()).slice(0, 80),
        items, ...(version ? { minutes: version.minutes } : {}) }) });
      closeSheet(); render(); celebrate();
    } catch (err) { msg.textContent = err.message; save.disabled = false; }
  } }, "打卡");
  openSheet(`打卡：${session}${version ? "（今天的版本）" : ""}`,
    h("p", { class: "muted" }, "这次感觉怎么样？1 很轻松，10 到极限（可不选）"), scale, form?.el, note, save, msg);
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
  const [lib, vids, me] = await Promise.all([exercises(), api("/iron/api/videos").catch(() => ({ videos: [] })), whoami()]);
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
            MOVE_PARTS.includes(part) ? h("a", { class: "tier-link", href: tierHref(`move:${part}`) }, icon("trophy", "xs"), "夯榜") : null),
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
    h("div", { class: "btn-row" },
      h("button", { class: "btn", type: "button", onclick: () => askCoach(`${x.name}我没看懂，请用大白话、打个比方再给我讲讲怎么做，最容易做错的地方是什么`) }, icon("coach", "sm"), "没看懂？讲简单点"),
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
    if (!confirm(`删除「${x.name}」的视频？`)) return;
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
  view.append(summary, mealEntry(() => today, redraw),
    section("吃了什么", null, record),
    h("div", { class: "tier-entry" }, h("a", { class: "pill", href: tierHref("food") }, icon("trophy", "xs"), "食物夯榜"), h("a", { class: "pill", href: tierHref("supplement") }, icon("trophy", "xs"), "补剂和蛋白粉夯榜")),
    section("问营养师", null, h("div", { class: "asks" },
      ["早餐怎么吃够蛋白质", "练前练后吃什么", "外卖怎么点更健康", "要不要吃肌酸", "减脂期饿了怎么办"].map((q) => askChip(q)))));
}

// 记一餐只有两个入口：拍（手机弹出拍照或从相册选）、填；记完再选是哪一餐（spec [2026-10-23] §43）
function mealEntry(today, redraw) {
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only" });
  const msg = h("div", { class: "muted", role: "status" });
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { msg.className = "error"; msg.textContent = "照片只支持 JPG、PNG、WebP"; return; }
    const photo = await shrinkPhoto(f);
    if (photo.size > 5 * MB) { msg.className = "error"; msg.textContent = "照片太大了，换一张试试"; return; }
    msg.textContent = "";
    logMealSheet(photo, today(), redraw);
  });
  return h("div", { class: "meal-entry" },
    h("label", { class: "entry-btn primary" }, input, icon("camera"), h("b", {}, "拍"), h("span", {}, "拍照或从相册选")),
    h("button", { class: "entry-btn", type: "button", onclick: () => logMealSheet(null, today(), redraw) }, icon("edit"), h("b", {}, "填"), h("span", {}, "写一句吃了什么")),
    msg);
}

// 拍完或点了"填"之后：确认这一餐是哪一顿，再记下；每种餐每天一份，选到今天记过的就提示会替换
function logMealSheet(photo, day, redraw) {
  let kind = mealKindNow();
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
    photo ? said : null, go, msg);
  if (!photo) setTimeout(() => said.focus(), 50);
}

// 吃了什么：今天按餐次排的记录 + 两周复盘，一个整体
function mealRecord(d, redraw) {
  const review = h("div", { class: "diet-review", hidden: true });
  api("/iron/api/diet/review").then((r) => {
    const p = r.proposal, c = r.current;
    if (!p && !c && !r.message) return;
    const act = async (path) => { try { await api(path, { method: "POST" }); cache.metrics = null; render(); } catch (err) { review.append(h("p", { class: "error" }, err.message)); } };
    const kcal = (n) => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
    review.hidden = false;
    review.replaceChildren(
      h("div", { class: "review-head" }, h("span", { class: "tile-name" }, "两周复盘"),
        p ? chip(`建议${p.delta > 0 ? "多" : "少"}吃 ${Math.abs(p.delta)} 千卡`, "attention") : c ? chip(`${kcal(c.kcal)} 千卡/天`, "") : chip("不用调", "good")),
      h("p", { class: "caption" }, p ? `${p.reason}：目标从 ${p.before} 调到 ${p.after} 千卡` : c ? `${c.reason}（${md(c.since)}起）。${r.message || ""}` : r.message),
      p || c ? h("div", { class: "review-act" },
        p ? h("button", { class: "btn small", type: "button", onclick: () => act("/iron/api/diet/adjust") }, "确认调整") : null,
        c ? h("button", { class: "link", type: "button", onclick: () => act("/iron/api/diet/adjust/undo") }, "撤销") : null) : null);
  }).catch(() => {});
  const groups = MEAL_KINDS.map((k) => [k, d.meals.filter((x) => x.kind === k)]);
  const rows = groups.filter(([k, xs]) => xs.length || ["早餐", "午餐", "晚餐"].includes(k)).map(([k, xs]) => {
    const sum = xs.reduce((a, x) => a + x.macros.kcal, 0);
    return h("div", { class: `meal-group${xs.length ? "" : " empty"}` },
      h("div", { class: "meal-group-head" }, h("span", {}, k), h("span", { class: "muted" }, xs.length ? `${Math.round(sum)} 千卡` : "还没记")),
      ...xs.map((x) => {
        const thumb = h("div", { class: "meal-thumb" }, icon("food", "sm"));
        if (x.has_photo) loadPhoto(x.id, thumb);
        return pressable(h("div", { class: "row-item" }, thumb,
          h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, macroLine(x.macros))),
          h("span", { class: "row-end" }, icon("chevron", "xs"))), () => mealSheet(x, redraw));
      }));
  });
  return h("div", { class: "card meal-record" }, review, ...rows);
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
      h("a", { class: "btn ghost small", href: "#me/profile" }, "去填写"),
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
        try { redraw(await api("/iron/api/meals/preset", { method: "POST", body: JSON.stringify({ preset: p.id, kind: foodState.kind || mealKindNow() }) })); e.target.textContent = "已记"; }
        catch (err) { alert(err.message); }
      } }, "记一餐"))));
  draw();
  return h("div", { class: "card" }, pills(SCENES, foodState.scene, (v) => { foodState.scene = v; draw(); }), grid,
    h("p", { class: "caption" }, data.note));
}

// ---- 数据：人体图 → 常看指标 → 每周复盘 → 其余指标 → 导入数据（spec [2026-10-23] §13）-------------------
// 数据页（spec [2026-10-23] §26）：重要指标在前；目标与计算一组；其余放在更多指标里，有数据才显示
const IMPORTANT = ["weight", "body_fat", "waist", "resting_hr", "hrv", "sleep", "steps", "active_kcal"];
const CALC = ["bmi", "bmr", "tdee", "kcal_target", "protein_target"];
const MORE = ["weight_trend", "blood_pressure", "hrv_sdnn", "hrv_rmssd", "exercise_min", "lean_mass", "vo2max"];
const IMPORTANT_NAMES = { weight: "体重", body_fat: "体脂率", waist: "腰围", resting_hr: "静息心率", hrv: "心率变异性", sleep: "睡眠时长", steps: "步数", active_kcal: "活动消耗" };
// 能自己记的（指标 → 记录的种类）；血压要记收缩压和舒张压两个数
const MANUAL = { weight: ["weight"], body_fat: ["body_fat"], waist: ["waist"], resting_hr: ["resting_hr"], sleep: ["sleep"], blood_pressure: ["systolic", "diastolic"] };
// 计算出来的指标不能直接改：写明由什么算出、去哪里改
const CALC_FROM = {
  bmi: ["由体重和身高算出。", "体重在数据页记，身高在「我的」里改。"],
  bmr: ["由体重、身高、年龄、性别算出。", "身高、出生日期、性别在「我的」里改，体重在数据页记。"],
  tdee: ["基础代谢乘以日常活动水平。", "活动水平在「我的」里改。"],
  kcal_target: ["每日总消耗按目标加减，再加上两周饮食复盘的调整量。", "目标在「我的」里改；调整量在饮食页确认或撤销。"],
  protein_target: ["按体重和目标算出。", "目标在「我的」里改，体重在数据页记。"],
};

async function data(view) {
  const [list, muscles, brief, me] = await Promise.all([
    metrics(), api("/iron/api/muscles").catch(() => null), api("/iron/api/brief").catch(() => null), profile().catch(() => null)]);
  const m = byKey(list);
  view.append(h("div", { class: "fresh" }, icon("info", "xs"),
    list.as_of ? `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开任一项看怎么算的、自己记一条` : "还没有同步到健康数据，可以先自己记一条"));
  const have = IMPORTANT.filter((k) => m[k] && m[k].value != null), lack = IMPORTANT.filter((k) => !have.includes(k));
  view.append(section("重要指标", null,
    have.length ? h("div", { class: "tiles" }, have.map((k) => tile(m[k]))) : null,
    lack.length ? pressable(h("div", { class: "card lack-row" },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, `还缺 ${lack.length} 项`), h("span", { class: "row-sub" }, lack.map((k) => IMPORTANT_NAMES[k]).join("、"))),
      h("span", { class: "row-end" }, "补记录", icon("chevron", "sm"))), () => lackSheet(lack, m)) : null));
  view.append(section("目标进度", null, goalCard({ empty: true })));
  view.append(section("肌肉人体图", h("span", { class: "caption" }, "近 7 天"), muscles ? bodyMap(muscles, brief, me?.sex) : failed(new Error("人体图暂时算不出来"), () => render())));
  if (brief) view.append(section("每周复盘", h("span", { class: "caption" }, `${md(brief.week.from)}–${md(brief.week.to)}`), weekCard(brief.week)));
  const more = [...CALC, ...MORE].map((k) => m[k]).filter((x) => x && x.value != null);
  if (more.length) {
    view.append(h("details", { class: "more-metrics" }, h("summary", {}, "更多指标", icon("chevron", "xs")), metricGroup("", more)));
  }
  const [catalog, files] = await Promise.all([catalogSection(), filesSection()]);
  view.append(section("导入数据", null, addGrid()), catalog, files);
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

// 人体图（spec [2026-10-23] §57）：openGym 那种平面图（MuscleMap 原图，MIT），正面、背面并排；
// 图没加载出来时退回按部位分组的列表
let flatShapes = null;
const loadFlat = () => (flatShapes ||= fetch("/iron/musclemap-v1.json").then((r) => { if (!r.ok) throw new Error("图没加载出来"); return r.json(); }));
const LEVELS = ["none", "low", "mid", "high"];
const NOT_MUSCLE = new Set(["head", "hair", "hands", "feet", "ankles", "knees"]);

function flatBody(mm, pick, sex) {
  const wrap = h("div", { class: "flat-body" }, h("p", { class: "muted" }, "人体图加载中…"));
  const byRegion = {};
  for (const m of mm.muscles) for (const r of m.flat || []) (byRegion[r] ||= []).push(m);
  // 两块肌肉共用一块图（臀、小腿）：先选是哪一块
  const choose = (ms) => {
    if (ms.length === 1) return pick(ms[0]);
    openSheet("是哪一块？", h("div", { class: "muscle-rows" }, ms.map((m) => pressable(h("div", { class: "muscle-row" },
      h("span", { class: "mr-name" }, m.name, RECOVER_WORD[m.state] ? h("em", {}, RECOVER_WORD[m.state]) : null),
      h("span", { class: "mr-bar" }, h("i", { class: `lv-${m.level}`, style: `width:${Math.min(100, (m.sets_7d / 12) * 100)}%` })),
      h("span", { class: "mr-sets" }, `${m.sets_7d} 组`)), () => { closeSheet(); pick(m); }))));
  };
  const figure = (fig, side) => {
    const [x, y, w, hgt] = fig.viewBox;
    const svg = s("svg", { viewBox: `${x} ${y} ${w} ${hgt}`, class: "flat-svg", role: "img", "aria-label": side === "front" ? "正面" : "背面" });
    for (const part of fig.parts) {
      const ms = byRegion[`${side}:${part.slug}`] || [];
      const g = s("g", {});
      if (ms.length) {
        const lv = LEVELS[Math.max(...ms.map((m) => LEVELS.indexOf(m.level)))];
        const label = ms.map((m) => `${m.name}：近 7 天 ${m.sets_7d} 组，${recoverText(m)}`).join("；");
        g.setAttribute("class", `mm lv-${lv}${ms.some((m) => m.state !== "ready") ? " pulse" : ""}`);
        g.setAttribute("tabindex", "0");
        g.setAttribute("role", "button");
        g.setAttribute("aria-label", label);
        const tip = s("title", {}); tip.textContent = label; g.append(tip);
        g.addEventListener("click", () => choose(ms));
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
    wrap.replaceChildren(figure(fig.front, "front"), figure(fig.back, "back"));
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
    p.items.map((m) => pressable(h("div", { class: "muscle-row" },
      h("span", { class: "mr-name" }, m.name, RECOVER_WORD[m.state] ? h("em", {}, RECOVER_WORD[m.state]) : null),
      h("span", { class: "mr-bar" }, h("i", { class: `lv-${m.level}`, style: `width:${Math.min(100, (m.sets_7d / 12) * 100)}%` })),
      h("span", { class: "mr-sets" }, `${m.sets_7d} 组`)), () => pick(m))))));
}

// ---- 夯（spec [2026-10-23] §60）--------------------------------------------------------------
const MOVE_PARTS = ["胸", "背", "肩", "手臂", "核心", "腿臀"];
const tierHref = (cat) => `#me/tier/${encodeURIComponent(cat)}`;
async function tierTab(view, cat) {
  const category = cat === "supplement" || cat === "food" || MOVE_PARTS.some((p) => cat === `move:${p}`) ? cat : "move:胸";
  const kind = category.startsWith("move:") ? "move" : category;
  const link = (href, name, on) => h("a", { class: `pill${on ? " on" : ""}`, href }, name);
  view.append(
    h("div", { class: "pills" }, link(tierHref("move:胸"), "动作", kind === "move"), link(tierHref("supplement"), "补剂和蛋白粉", kind === "supplement"), link(tierHref("food"), "食物", kind === "food")),
    kind === "move" ? h("div", { class: "pills" }, MOVE_PARTS.map((p) => link(tierHref(`move:${p}`), p, category === `move:${p}`))) : null);
  const box = h("div", { class: "tier-box" });
  view.append(box);
  const draw = (b) => box.replaceChildren(tierBoard(b, draw), b.custom ? tierAdd(b, draw) : null);
  draw(await api(`/iron/api/tier?category=${encodeURIComponent(category)}`));
  view.append(h("p", { class: "caption", style: "padding:0 2px" }, "点一个条目选它在哪一档。榜只有你自己看得到。"));
}

function tierBoard(b, draw) {
  const rows = [...b.tiers.map((t) => [t.key, t.name]), ["", "还没排"]];
  const pick = (x) => {
    const go = async (tier) => {
      try { draw(await api("/iron/api/tier", { method: "PUT", body: JSON.stringify({ category: b.category, key: x.key, tier }) })); closeSheet(); }
      catch (err) { alert(err.message); }
    };
    const del = async () => {
      try { draw(await api(`/iron/api/tier/items?category=${encodeURIComponent(b.category)}&key=${encodeURIComponent(x.key)}`, { method: "DELETE" })); closeSheet(); }
      catch (err) { alert(err.message); }
    };
    openSheet(x.name,
      h("div", { class: "tier-pick" }, b.tiers.map((t) => h("button", { class: `tier-btn t-${t.key}${x.tier === t.key ? " on" : ""}`, type: "button", onclick: () => go(t.key) }, t.name))),
      x.tier ? h("button", { class: "btn ghost block", type: "button", onclick: () => go("") }, "移回还没排") : null,
      b.custom ? h("button", { class: "btn danger block", type: "button", onclick: del }, "删除这一项") : null);
  };
  return h("div", { class: "tier-board" }, rows.map(([key, name]) => {
    const items = b.items.filter((x) => x.tier === key);
    if (!key && !items.length) return null;
    return h("div", { class: `tier-row${key ? "" : " rest"}` },
      h("div", { class: `tier-label t-${key || "rest"}` }, name),
      h("div", { class: "tier-items" }, items.length ? items.map((x) => pressable(h("span", { class: "tier-item", "aria-label": `${x.name}，点了选档` },
        x.image ? h("img", { src: x.image, alt: "", loading: "lazy" }) : null, h("span", {}, x.name)), () => pick(x)))
        : h("span", { class: "tier-empty" }, "空")));
  }));
}

function tierAdd(b, draw) {
  const input = h("input", { type: "text", maxlength: "30", placeholder: b.category === "food" ? "加一种食物，比如鸡胸肉" : "加一种，比如乳清蛋白粉、肌酸", "aria-label": "添加" });
  const msg = h("p", { class: "error" });
  const add = async (name) => {
    msg.textContent = "";
    try { draw(await api("/iron/api/tier/items", { method: "POST", body: JSON.stringify({ category: b.category, name }) })); }
    catch (err) { msg.textContent = err.message; }
  };
  const form = h("form", { class: "tier-add" }, input, h("button", { class: "btn small", type: "submit" }, "添加"));
  form.addEventListener("submit", (e) => { e.preventDefault(); add(input.value); });
  const wrap = h("div", { class: "card tier-add-card" }, form, msg);
  if (b.category === "food") {
    api("/iron/api/tier/food-suggest").then((s) => {
      if (s.names.length) wrap.append(h("p", { class: "caption" }, `最近 ${s.days} 天常吃的：`), h("div", { class: "asks" }, s.names.map((n) => h("button", { class: "ask-chip", type: "button", onclick: () => add(n) }, n))));
    }).catch(() => {});
  }
  return wrap;
}

// 每块肌肉的恢复状态（spec [2026-10-23] §30）
const RECOVER_WORD = { today: "今天刚练", recovering: "恢复中", sore: "还酸" };
function recoverText(m) {
  if (m.state === "sore") return "你说还酸：先别练它，等不酸了再练";
  if (m.state === "ready") return "可以练";
  return `${m.state === "today" ? "今天刚练" : "恢复中"}，${md(m.ready_on)}可以再练`;
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
    const sore = h("button", { class: "btn ghost small", type: "button" }, "还酸");
    const fine = h("button", { class: "btn ghost small", type: "button" }, "已经不酸了");
    const btns = [sore, fine];
    sore.addEventListener("click", () => tell(m, "sore", btns));
    fine.addEventListener("click", () => tell(m, "fine", btns));
    const aka = [m.formal && `正式名：${m.formal}`, m.says?.length && `也叫：${m.says.join("、")}`].filter(Boolean).join("　");
    openSheet(m.name,
      aka ? h("p", { class: "caption" }, aka) : null,
      h("div", { class: "sheet-big" }, h("span", { class: "v" }, String(m.sets_7d), h("small", {}, "组 · 近 7 天")), chip(m.level_name)),
      h("div", { class: `recover-box ${m.state}` },
        h("b", {}, recoverText(m)),
        m.recover_why.length && m.state !== "ready" ? h("p", { class: "muted" }, `为什么：${m.recover_why.join("；")}`) : null,
        h("div", { class: "btn-row" }, m.state === "sore" ? fine : m.state === "ready" ? sore : [sore, fine])),
      m.sore_too_long ? h("div", { class: "notice-line" }, icon("alert", "xs"), "说酸已经超过一周，可能不只是练后酸痛，问问康复恢复师。") : null,
      h("div", { class: "kv" }, h("span", {}, "最近一次"), h("span", {}, m.last ? md(m.last) : "最近 28 天没练")),
      m.history.length ? h("div", {}, h("h3", {}, "最近练过"), h("ul", { class: "tips" }, m.history.map((x) => h("li", {}, x)))) : null,
      h("p", { class: "caption" }, "组数：主要练到的每组记 1 组，辅助练到的按半组；增肌通常每块肌肉每周 10 组以上效果更好。恢复按肌肉、动作、组数和用力程度估算，你说的感受优先。"),
      h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(m.sore_too_long ? `我的${m.name}酸了一周多还没好，怎么回事？` : m.level === "none" ? `我的${m.name}一周没练了，怎么补上？` : `我的${m.name}这周练了 ${m.sets_7d} 组，够吗？`) }, icon("coach", "sm"), "问问教练"));
  };
  const top = [...mm.muscles].filter((m) => m.sets_7d > 0).sort((a, b) => b.sets_7d - a.sets_7d);
  const untrained = mm.untrained || [];
  const resting = mm.muscles.filter((m) => m.state !== "ready");
  const rd = brief?.today?.readiness;
  return h("div", { class: "card body-card" },
    flatBody(mm, pick, sex),
    h("div", { class: "legend" }, ["none", "low", "mid", "high"].map((lv) => h("span", {}, h("i", { class: `lv-${lv}` }), { none: "没练", low: "1–4 组", mid: "5–9 组", high: "10 组以上" }[lv])), h("span", {}, h("i", { class: "glow" }), "闪烁：恢复中或还酸")),
    rd && (rd.level === "poor" || rd.level === "fair") && rd.reasons?.length ? h("div", { class: "notice-line" }, icon("alert", "xs"), `${rd.reasons[0]}：今天整体恢复偏慢，可以降低强度。`) : null,
    resting.length ? h("div", { class: "rest-list" }, resting.map((m) => pressable(h("span", { class: `rest-chip ${m.state}` },
      h("b", {}, m.name), h("small", {}, m.state === "sore" ? "还酸" : `${md(m.ready_on)}可练`)), () => pick(m)))) : null,
    mm.sessions === 0 ? h("p", { class: "muted" }, "最近还没有训练记录：在首页打卡，或在对话里说“今天练了……”就会记下来。") : h("div", { class: "muscle-rows" },
      top.slice(0, 6).map((m) => pressable(h("div", { class: "muscle-row" },
        h("span", { class: "mr-name" }, m.name, RECOVER_WORD[m.state] ? h("em", {}, RECOVER_WORD[m.state]) : null),
        h("span", { class: "mr-bar" }, h("i", { class: `lv-${m.level}`, style: `width:${Math.min(100, (m.sets_7d / 12) * 100)}%` })),
        h("span", { class: "mr-sets" }, `${m.sets_7d} 组`)), () => pick(m)))),
    untrained.length && mm.sessions ? h("div", { class: "notice-line" }, icon("info", "xs"), `近 7 天没练：${untrained.join("、")}`) : null,
    untrained.length && mm.sessions ? h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我最近${untrained.join("、")}没怎么练，下次训练怎么补上？`) }, icon("coach", "sm"), "让教练帮我补上") : null,
    h("details", { class: "all-muscles" }, h("summary", {}, `全部 ${mm.muscles.length} 块肌肉`), partList(mm, pick)),
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
  const items = [...ADD.slice(0, 3), ["more", "更多", "", () => { location.hash = "#me/data"; }]];
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
        h("a", { class: "btn ghost block", href: "#me/data", onclick: () => { cache.metrics = null; closeSheet(); render(); } }, "去看数据")));
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
const ME_TABS = [["data", "数据"], ["tier", "夯"], ["profile", "档案"]];
async function me(view, sub, extra) {
  const tab = ME_TABS.some(([k]) => k === sub) ? sub : "data";
  view.append(h("nav", { class: "seg", "aria-label": "我的" }, ME_TABS.map(([k, name]) =>
    h("a", { href: `#me/${k}`, class: k === tab ? "on" : "", "aria-current": k === tab ? "page" : null }, name))));
  await { data, tier: tierTab, profile: profileTab }[tab](view, extra);
}

async function profileTab(view) {
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
  view.append(goalSection());
  view.append(citySection());
  view.append(section("说明", null, h("div", { class: "card" }, h("p", { class: "muted" }, "AI 健身管家会把你的问题交给最合适的专业角色（训练教练、营养师、康复恢复师），涉及几个方面时再把他们的意见整合起来。建议仅供参考，不能代替医生；身体不适请及时就医。"))));
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
      h("div", { class: "cc-main" }, h("span", {}, c.change === "removed" ? `${c.before}（已解除）` : c.after))))) : null,
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

// ---- 路由 ---------------------------------------------------------------------------------
const PAGES = {
  home: { title: "今天", kicker: todayLabel, render: home, skeleton: [200, 300, 320] },
  moves: { title: "动作", render: moves, skeleton: [46, 40, 520] },
  chat: { title: "教练", full: true, render: chatPage },
  food: { title: "饮食", render: food, skeleton: [180, 220, 150] },
  me: { title: "我的", render: me, skeleton: [44, 320, 180] },
};
const WITH_COACH = new Set(["moves", "food", "me"]); // 右下角悬浮"教练"按钮（§59 需求 3）
let renderSeq = 0;

async function render() {
  closeSheet();
  const seq = ++renderSeq;
  const view = $("view");
  const signedIn = Boolean(store.get());
  document.body.classList.remove("chatting");
  if (!signedIn) {
    $("bar").hidden = true; $("tabs").hidden = true; $("fab").hidden = true; chat.els = null;
    view.replaceChildren(); loginView(view); return;
  }
  const [name, sub, ...rest] = (location.hash.slice(1) || "home").split("/");
  if (name === "data") { location.replace("#me/data"); return; } // 原来的数据页并进了"我的"
  const page = PAGES[name] ? name : "home";
  const cfg = PAGES[page];
  document.title = `${cfg.title} · AI 健身管家`;
  for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.tab === page);
  $("tabs").hidden = Boolean(cfg.full);
  $("bar").hidden = Boolean(cfg.full);
  $("fab").hidden = !WITH_COACH.has(page);
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
  render();
});
