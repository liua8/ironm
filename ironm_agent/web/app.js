// IronM 网页：首页（练 / 干饭）、IronM（对话）、图鉴、记录、我，都在这一个页面里（§121，§175 改成五格）。
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
  download: [P("M12 15V3"), P("M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"), P("m7 10 5 5 5-5")],
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
  // 底部五格（§175）：首页哑铃、IronM 对话气泡、图鉴书本、记录柱状、我（Lucide 造型）
  bubble: [P("M7.9 20A9 9 0 1 0 4 16.1L2 22Z")],
  book: [P("M12 7v14"), P("M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z")],
  bars: [P("M3 3v16a2 2 0 0 0 2 2h16"), P("M18 17V9"), P("M13 17V5"), P("M8 17v-3")],
  // §121 的四个旧标签图标（别处还在用）
  hexhome: [["polygon", { points: "12,2 21,7 21,17 12,22 3,17 3,7" }], ["circle", { cx: "12", cy: "12", r: "3" }]],
  atlas: [["rect", { x: "4", y: "3", width: "16", height: "18", rx: "1" }], P("M8 8h8M8 12h8M8 16h5")],
  record: [P("M4 20V10M10 20V4M16 20V13M22 20H2")],
  pilot: [P("M7 4h10l2 6-7 10-7-10z"), P("M9 10h6")],
};
function icon(name, cls = "") {
  const svg = s("svg", { viewBox: "0 0 24 24", class: `i ${cls}`.trim(), "aria-hidden": "true" });
  for (const [tag, attrs] of ICONS[name] || []) svg.append(s(tag, attrs));
  if (name === "stop" || name === "play") svg.style.fill = "currentColor";
  return svg;
}

// IronM 的头像（§175 需求 3）：自己画的黄色胖企鹅——纯黄、浅黄圆肚子、头顶一滴牛奶；不仿现成角色
let mechSeq = 0;
function mech(size = 34) {
  ++mechSeq;
  const svg = s("svg", { viewBox: "0 0 64 64", width: String(size), height: String(size), class: "mech", "aria-hidden": "true" });
  svg.append(
    s("path", { d: "M19.5 37 C15.5 41 15.5 46.5 18.5 49.5 C20 50.5 21.8 49.6 21.6 47.6 Z M44.5 37 C48.5 41 48.5 46.5 45.5 49.5 C44 50.5 42.2 49.6 42.4 47.6 Z", fill: "#f4b400", stroke: "#d49600", "stroke-width": ".8" }),
    s("path", { d: "M32 12 C22.5 12 19.5 19.5 19.5 26.5 C19.5 33.5 12.5 38.5 12.5 47.5 C12.5 57.5 21.5 62.5 32 62.5 C42.5 62.5 51.5 57.5 51.5 47.5 C51.5 38.5 44.5 33.5 44.5 26.5 C44.5 19.5 41.5 12 32 12 Z", fill: "#ffd83d", stroke: "#e0a800", "stroke-width": "1" }),
    s("ellipse", { cx: "32", cy: "48", rx: "13", ry: "11.5", fill: "#ffefa6" }),
    s("ellipse", { cx: "26.5", cy: "24.5", rx: "2.2", ry: "2.6", fill: "#2a2420" }),
    s("ellipse", { cx: "37.5", cy: "24.5", rx: "2.2", ry: "2.6", fill: "#2a2420" }),
    s("circle", { cx: "27.2", cy: "23.6", r: ".8", fill: "#fff" }),
    s("circle", { cx: "38.2", cy: "23.6", r: ".8", fill: "#fff" }),
    s("ellipse", { cx: "23", cy: "29", rx: "2.4", ry: "1.3", fill: "#ffae8a", opacity: ".75" }),
    s("ellipse", { cx: "41", cy: "29", rx: "2.4", ry: "1.3", fill: "#ffae8a", opacity: ".75" }),
    s("path", { d: "M29.8 27.6 C31 26.8 33 26.8 34.2 27.6 C33.6 29.2 32.8 29.9 32 29.9 C31.2 29.9 30.4 29.2 29.8 27.6 Z", fill: "#ff9f2e", stroke: "#e07f10", "stroke-width": ".5" }),
    s("path", { d: "M32 2.5 C30.4 5.8 28.4 7.8 28.4 10.2 C28.4 12.3 30 13.8 32 13.8 C34 13.8 35.6 12.3 35.6 10.2 C35.6 7.8 33.6 5.8 32 2.5 Z", fill: "#fff", stroke: "#cbd5dd", "stroke-width": ".8" }));
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
  if (res.status === 428) throw noModelError(body);
  if (!res.ok) throw new Error(body.detail || body.msg || `请求失败（${res.status}）`);
  return body;
}
// 没填自己的模型（§167）：服务端回 428；出错的地方用 errLine 给"去填模型"的入口
const NO_MODEL = "先在「我 → 模型和 API」填你自己的模型，这个功能要用你的模型。";
function noModelError(body) { const e = new Error(body?.detail || NO_MODEL); e.noModel = true; return e; }
function errLine(err, cls = "error") {
  return h("p", { class: cls, role: "alert" }, err.message,
    err.noModel ? h("button", { class: "link", type: "button", onclick: () => modelSheet() }, " 去填模型") : null);
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
    (m.missing || []).some((x) => x.includes("个人中心")) ? h("a", { class: "btn block", href: "#me" }, "去「我」里填写") : null,
    (m.missing || []).some((x) => x.includes("手表")) ? h("button", { class: "btn block", type: "button", onclick: appleSheet }, icon("phone", "sm"), "导入苹果健康数据") : null,
    CALC_FROM[m.key] ? h("div", { class: "calc-from" }, h("h3", {}, "这个数不能直接改"), h("p", {}, CALC_FROM[m.key][0]), h("p", { class: "muted" }, CALC_FROM[m.key][1]),
      h("a", { class: "btn ghost block", href: "#me", onclick: closeSheet }, "去「我」里修改")) : null,
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

// 首页（§175 照参照图）：一页里放 今天练什么 和 今天吃；"饮食账单"进原来的干饭整页（#home/eat）
const HOME_SEGS = [["home", "练"], ["home/eat", "干饭"]];  // 旧的两段，只留给测试和旧地址参照
function homeSeg(cur) {
  return h("div", { class: "seg page-seg", role: "tablist", "aria-label": "首页" }, HOME_SEGS.map(([k, label]) =>
    h("a", { href: `#${k}`, role: "tab", class: k === cur ? "on" : "", "aria-selected": String(k === cur) }, label)));
}
async function homePage(view, sub) {
  if (sub === "eat") {
    view.append(h("a", { class: "link tl-back", href: "#home" }, icon("back", "xs"), "首页"), h("h2", { class: "page-h" }, "饮食账单"));
    return food(view);
  }
  return home(view);
}

// 首页：日期和今天练什么、IronM 入口；今日热搜；提醒；今日委托；IronM 说；今天吃；睡眠心率天气
async function home(view) {
  const [brief, training, week, lib, gear, photos, mine, meals, m] = await Promise.all([
    api("/iron/api/brief").catch(() => null),
    api("/iron/api/training").catch(() => null),
    api("/iron/api/week").catch(() => null),
    exercises().catch(() => null),
    api("/iron/api/gear").catch(() => null),
    api("/iron/api/train-images").catch(() => null),
    api("/iron/api/my-model").catch(() => null),
    api("/iron/api/meals").catch(() => null),
    metrics().then(byKey).catch(() => ({})),
    checkLive(),
  ]);
  planSessions = training?.plan?.sessions || []; planTargets = training?.targets || {};
  const today = week?.days?.find((d) => d.today);
  const what = !training?.plan ? "还没有计划" : !today?.session ? "休息日" : (today.version || today.session).name;
  const hot = await hotStrip();  // 排行榜唯一的入口（§161）
  view.append(
    h("div", { class: "home-top" },
      h("span", { class: "day-line" }, h("i", { class: "dot" }), `${today?.weekday || todayLabel().split(" ")[1] || ""} · ${what}`),
      h("a", { class: "buddy-pill", href: "#chat", "aria-label": "进 IronM 对话" }, mech(36),
        h("span", { class: "bp-text" }, h("b", {}, "IronM"), h("small", {}, "点一下进 IronM", icon("chevron", "xs"))))),
    hot || "",
    liveNow ? liveEntry({ today_plan: true }) : null,  // 继续时也补上今天计划（§123）
    modelCard(mine),
    gearCard(gear),
    alertsBox(brief),
    brief?.checkin ? h("section", { class: "card hc" }, checkinRow(brief.checkin)) : null,
    trainCard(brief, training, week, lib, photos?.images || {}),
    coachCard(),
    eatCard(meals, m),
    vitalsRow(brief, week));
}

// ---- 填自己的模型（§167）：没填时首页提示，填了就不再出现；"以后再说"这次先收起（浏览器只存登录凭证） ----
let modelLater = false;
function modelCard(mine) {
  if (!mine || mine.model || modelLater) return null;  // 读不到就不提示，免得误报
  const card = h("section", { class: "card hc model-card" });
  card.append(hcHead("填你自己的模型"),
    h("p", { class: "muted" }, "IronM 用你自己的模型回答问题、估热量、认器械。先填一个（DeepSeek、通义千问、智谱等都可以），记训练、看计划不用填也能用。"),
    h("button", { class: "btn block", type: "button", onclick: () => modelSheet() }, "去填模型"),
    h("button", { class: "link gear-later", type: "button", onclick: () => { modelLater = true; card.remove(); } }, "以后再说"));
  return card;
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
    h("button", { class: "btn small", type: "button", onclick: () => askCoach(`我的场所和器材改成了：${gearLine(r)}。计划里${r.lacking.join("、")}要用我没有的器械，帮我按现在的器械调一下计划`) }, icon("coach", "sm"), "让 IronM 按现在的器械调"));
}

function gearCard(g) {
  if (!g || g.known || gearLater) return null;
  const card = h("section", { class: "card hc gear-card" });
  card.append(hcHead("场所与器材"),
    h("p", { class: "muted" }, "填一次就好，排计划、换动作都按这个。以后在「我」里改，或者直接跟 IronM 说。"),
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
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, g.known && g.place ? gearLine(g) : g.known ? "IronM 记过，但没说在哪练" : "还没填"),
      g.text && !g.form ? h("span", { class: "row-sub" }, `IronM 记的：${g.text}`) : null,
      h("span", { class: "row-sub" }, "也可以直接跟 IronM 说，比如「搬家了，家里只有哑铃」。")),
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
      h("button", { class: "btn quiet small", type: "button", onclick: () => { location.hash = "#chat"; } }, icon("coach", "sm"), "跟 IronM 说")));
  api("/iron/api/gear").then(draw).catch(() => row.replaceChildren(h("p", { class: "muted" }, "暂时读不到，稍后再试。")));
  return section("场所与器材", null, row);
}

// ---- 首页三块（spec [2026-10-23] §104 需求 3）：看一部分，点开就地展开 ----
const exImg = (lib, name) => {
  const x = lib?.exercises?.find((e) => e.name === name);
  return (x?.gif || x?.images?.[0])?.url || "";  // 有动图先用动图（§144）
};
function thumb(lib, name, cls = "thumb") {
  const url = exImg(lib, name);
  return url ? h("img", { class: cls, src: url, alt: "", loading: "lazy" }) : h("span", { class: `${cls} none` }, icon("dumbbell", "sm"));
}
const hcHead = (label, extra) => h("div", { class: "hc-head" }, h("span", { class: "label" }, label), extra || null);
// 读不到和没有分开：读不到时说读不到，不当成"没有计划"（§104 需求 1）
const notLoaded = (label, what) => h("section", { class: "card hc" }, hcHead(label),
  h("p", { class: "muted" }, `没读到${what}。`), h("button", { class: "btn ghost small", type: "button", onclick: () => render() }, "重试"));

const partOf = (lib, name) => lib?.exercises?.find((x) => x.name === name)?.part || "";
const fig = (n, unit) => h("div", { class: "fig" }, h("b", { class: "fig-n" }, String(n)), h("span", {}, unit));
function weekDots(brief) {
  const planned = brief?.week?.planned || brief?.week?.due || 0, done = brief?.week?.done || 0;
  if (!planned) return null;
  return h("div", { class: "week-line" },
    h("div", { class: "week-dots", role: "img", "aria-label": `这周练了 ${done} 次，计划 ${planned} 次` },
      Array.from({ length: Math.max(planned, done) }, (_, i) => h("i", { class: i < done ? "on" : "" }))),
    h("span", {}, `这周练了 ${done} 次，计划 ${planned} 次`));
}
// 今日委托的照片（§131）：按今天练得最多的部位取，带署名；没下好时不放
function questPic(img) {
  if (!img?.url) return null;
  return h("div", { class: "quest-pic" }, h("img", { src: img.url, alt: "", loading: "lazy" }),
    h("a", { class: "credit", href: img.page, target: "_blank", rel: "noopener" }, `照片：${img.author}，${img.license}`));
}
// 一行组数：力量写"4 组 × 10 次"，有氧写时长（§130）
const setsLine = (it, lib) => {
  if (partOf(lib, it.exercise) === "有氧" || /分钟/.test(it.reps)) return it.reps;
  return `${it.sets} 组 × ${it.reps}${/[\d–-]$/.test(it.reps) ? " 次" : ""}`;
};
// 这周已练几次：一行字加一条进度
function weekBar(brief) {
  const planned = brief?.week?.planned || brief?.week?.due || 0, done = brief?.week?.done || 0;
  if (!planned) return null;
  return h("div", { class: "week-bar", role: "img", "aria-label": `这周练了 ${done} 次，计划 ${planned} 次` },
    h("span", {}, `这周已练 ${done}/${planned} 次`), h("i", {}, h("b", { style: `width:${Math.min(100, Math.round((done / planned) * 100))}%` })));
}
// 今日委托（§131 的说法，§175 照参照图的卡片）：标题、部位标签、本周进度、管家对今天的说法、编号的动作表、开始训练、练完直接打卡
function trainCard(brief, tr, week, lib, photos = {}) {
  if (!tr || !week) return notLoaded("训练", "今天的训练安排");
  const t = brief?.today?.training, today = week.days?.find((d) => d.today);
  const card = (title, sub, ...more) => h("section", { class: "card quest" },
    h("h2", { class: "quest-title" }, title), sub ? h("p", { class: "quest-sub" }, sub) : null, weekBar(brief), ...more);
  if (!tr.plan) {
    return card("今日委托 · 还没有计划", "让 IronM 按你的目标排一份，或者从方案里挑一套。",
      h("button", { class: "btn block go", type: "button", onclick: () => askCoach("帮我排一个每周训练计划") }, "让 IronM 排一份"),
      h("a", { class: "btn ghost block", href: "#atlas/plans" }, "从方案库挑"));
  }
  if (!today?.session) return card("今日委托 · 休息", "散散步、拉拉伸，让身体恢复。");
  if (week.sick?.mode === "rest" && !(t?.done || today.done)) return card("今日委托 · 先休息", week.sick.why);
  const v = today.version || today.session;
  if (t?.done || today.done) return card(`今日委托 · ${v.name}`, "练完了，好好恢复。", h("span", { class: "tag green" }, icon("check", "xs"), "完成，连续打卡 +1"));
  const parts = [...new Set(v.items.map((it) => partOf(lib, it.exercise)).filter(Boolean))].slice(0, 3);
  const coachNote = h("div", { class: "today-coach", role: "status", hidden: true });  // 管家对今天的说法（§163）
  const planned = Object.fromEntries(today.session.items.map((it) => [it.exercise, it.sets]));  // 被减掉的组（§121 需求 4）
  const list = h("ol", { class: "quest-list" });
  let shownVersion = today.version || null;  // 直接打卡带上的版本：管家调整过就是调整后的
  const drawList = (items) => list.replaceChildren(...items.map((it, i) => {
    const cut = (planned[it.exercise] || 0) - (it.sets || 0);
    return h("li", {}, h("span", { class: "q-no" }, String(i + 1)),
      h("span", { class: "q-name" }, it.exercise, it.load || cut > 0
        ? h("small", { class: cut > 0 ? "move-cut" : "" }, [it.load, cut > 0 ? `比计划少 ${cut} 组` : ""].filter(Boolean).join("，")) : null),
      h("span", { class: `q-sets${/自重|力竭/.test(`${it.load}${it.reps}`) ? " hot" : ""}` }, setsLine(it, lib)));
  }));
  drawList(v.items);
  // 管家定的今天（§163）：调整过就把动作表换成调整后的，和上面那一行说法一致
  const onToday = (tv, ctl) => {
    heroCoach(coachNote, tv, ctl);
    if (tv.status === "ok" && tv.changed && tv.today) { drawList(tv.today.items); shownVersion = tv.today; }
  };
  const detail = h("div", { class: "hc-detail", hidden: true },
    todayVersion(today.session, { compact: true, onStatus: onToday }),
    h("a", { class: "link hc-more", href: "#plan" }, "完整计划", icon("chevron", "xs")));
  const toggle = h("button", { class: "link hc-toggle", type: "button", "aria-expanded": "false" }, "更多");
  toggle.addEventListener("click", () => {
    detail.hidden = !detail.hidden;
    toggle.textContent = detail.hidden ? "更多" : "收起";
    toggle.setAttribute("aria-expanded", String(!detail.hidden));
  });
  return h("section", { class: "card quest" },
    h("div", { class: "quest-top" },
      h("h2", { class: "quest-title" }, `今日委托 · ${v.name}`),
      h("div", { class: "quest-tags" },
        parts.length ? h("span", { class: "tag coral" }, parts.join(" · ")) : null,
        h("span", { class: "tag green" }, "完成 +1 颗星"))),
    weekBar(brief),
    coachNote,
    list,
    h("button", { class: "btn block go", type: "button", onclick: () => startLive({ today_plan: true }) }, icon("play", "sm"), liveNow ? "继续训练" : "开始训练"),
    h("button", { class: "btn ghost block", type: "button", onclick: () => doneSheet(v.name, shownVersion) }, "已经练完了，直接打卡"),
    h("div", { class: "quest-foot" }, today.warmup ? h("span", { class: "muted" }, `先热身约 ${today.warmup.minutes} 分钟`) : h("span"), toggle),
    detail);
}

// 今天吃（§175 照参照图）：剩余热量的圆环、三大营养素小格、拍照记 / 写一句；"饮食账单"进整页
function eatCard(d, m) {
  if (!d) {  // 没读到也留着"饮食账单"入口（首页不再分段，这是进整页的路）
    return h("section", { class: "card eat" }, h("div", { class: "eat-head" }, h("h2", {}, "今天吃"),
      h("a", { class: "link eat-more", href: "#home/eat" }, "饮食账单", icon("chevron", "xs"))),
      h("p", { class: "muted" }, "今天的饮食这次没读到，点「饮食账单」再看。"));
  }
  const t = d.target, tot = d.totals;
  const redraw = () => render();
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", class: "sr-only" });
  const msg = h("p", { class: "error", role: "status" });
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    if (!/^image\/(jpeg|png|webp)$/.test(f.type)) { msg.textContent = "照片只支持 JPG、PNG、WebP"; return; }
    const photo = await shrinkPhoto(f);
    if (photo.size > 5 * MB) { msg.textContent = "照片太大了，换一张试试"; return; }
    msg.textContent = ""; logMealSheet(photo, d, redraw);
  });
  const left = t ? Math.round(t.kcal - tot.kcal) : 0, pct = t ? Math.min(100, Math.round((tot.kcal / t.kcal) * 100)) : 0;
  const state = !t ? null : !tot.kcal ? ["还没记", ""] : left >= 0 ? ["在目标内", "green"] : ["超了一点", "warn"];
  const R = 34, C = 2 * Math.PI * R;
  const ringSvg = s("svg", { viewBox: "0 0 84 84", class: "eat-ring", "aria-hidden": "true" });
  ringSvg.append(s("circle", { cx: "42", cy: "42", r: String(R), class: "er-track" }));
  if (pct > 0) ringSvg.append(s("circle", { cx: "42", cy: "42", r: String(R), class: "er-fill", "stroke-dasharray": `${(C * pct) / 100} ${C}`, transform: "rotate(-90 42 42)" }));  // 圈上是吃掉的部分；没吃不画（圆头会留一个点）
  const pt = m?.protein_target?.display ? Number(String(m.protein_target.display).split("–")[0]) : t?.protein_g;
  const macro = (name, have, target, cls) => h("div", { class: `eat-macro ${cls}` },
    h("div", { class: "em-head" }, h("b", {}, name), target ? h("span", {}, `余 ${Math.max(0, Math.round(target - have))}g`) : null),
    target ? h("i", {}, h("b", { style: `width:${Math.min(100, Math.round((have / target) * 100))}%` })) : null,
    h("span", { class: "em-num" }, target ? `${Math.round(have)} / ${Math.round(target)}g` : `${Math.round(have)}g`));
  return h("section", { class: "card eat" },
    h("div", { class: "eat-head" }, h("h2", {}, "今天吃"), state ? h("span", { class: `tag ${state[1]}` }, state[0]) : null,
      h("a", { class: "link eat-more", href: "#home/eat" }, "饮食账单", icon("chevron", "xs"))),
    t ? h("div", { class: "eat-main" },
      h("div", { class: "eat-ring-box" }, ringSvg, h("div", { class: "er-text" }, h("b", {}, String(Math.abs(left))), h("small", {}, left >= 0 ? "剩余 kcal" : "多了 kcal"))),
      h("div", { class: "eat-text" },
        h("b", {}, left >= 0 ? `还能吃 ${left} kcal` : `多吃了 ${-left} kcal`),
        h("span", {}, `每日总摄入目标 ${Math.round(t.kcal).toLocaleString()} kcal`),
        pt ? h("span", { class: "eat-ok" }, icon("check", "xs"), tot.protein_g >= pt ? "蛋白质够了" : `蛋白质还差 ${Math.round(pt - tot.protein_g)} 克`) : null))
      : h("div", { class: "eat-main empty" }, h("span", {}, "在「我」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。"), h("a", { class: "btn ghost small", href: "#me" }, "去填写")),
    t ? h("div", { class: "eat-macros" },
      macro("碳水", tot.carbs_g, t.carbs_g || null, "c"), macro("蛋白质", tot.protein_g, pt || null, "p"), macro("脂肪", tot.fat_g, t.fat_g || null, "f")) : null,
    h("div", { class: "eat-actions" },
      h("label", { class: "eat-act" }, input, h("span", { class: "ea-ic" }, icon("camera")), h("span", {}, h("b", {}, "拍照记"), h("small", {}, "拍一下估热量"))),
      h("button", { class: "eat-act", type: "button", onclick: () => logMealSheet(null, d, redraw) },
        h("span", { class: "ea-ic" }, icon("edit")), h("span", {}, h("b", {}, "写一句"), h("small", {}, "说一句就记")))),
    msg);
}

// 首页大卡片上管家对今天的说法（§163）：正在看、出错了（能重试）、调整过、定了休息；按原计划的不多说。
// 下面列的动作是原计划：管家没看完、出错时不按规则替它减量
function heroCoach(el, v, ctl) {
  const line = (cls, ...kids) => { el.className = `today-coach ${cls}`; el.replaceChildren(...kids); el.hidden = false; };
  if (v.status === "reviewing") line("wait", h("span", {}, "IronM 正在看今天的情况，下面先列原计划"), h("span", { class: "typing" }, h("i"), h("i"), h("i")));
  else if (v.status === "coach_error") {
    line("err", icon("alert", "sm"), h("span", {}, "IronM 出错了，还没看今天的情况，下面是原计划"),
      h("button", { class: "btn small", type: "button", onclick: (e) => ctl.retry(e.currentTarget) }, "重试"));
  } else if (v.status === "rest_today") line("rest", icon("coach", "sm"), h("span", {}, v.message));
  else if (v.status === "ok" && v.changed) line("adj", icon("coach", "sm"), h("span", {}, `IronM 调整了今天：${v.changes.join("；") || "点「更多」看今天的版本"}`));
  else el.hidden = true;
}

// 睡眠、静息心率、天气小格（§121 需求 4）：有数据的才显示，读不到不编
function vitalsRow(brief, week) {
  const w = brief?.week, wx = week?.days?.find((d) => d.today)?.weather;
  const cell = (cls, k, v, u, sub) => h("div", { class: `vt ${cls}` }, h("span", { class: "vt-k" }, k), h("b", { class: "num" }, v, u ? h("small", {}, ` ${u}`) : null), sub ? h("span", { class: "vt-sub" }, sub) : null);
  const cells = [
    w?.sleep?.value != null ? cell("sleep", "睡眠 · 近 7 天", String(w.sleep.value), "小时", w.sleep.brief) : null,
    w?.resting_hr?.value != null ? cell("hr", "静息心率", String(Math.round(w.resting_hr.value)), "次/分", w.resting_hr.brief) : null,
    wx ? cell("wx", "天气", `${wx.temp}°`, "", `${wx.text}${wx.name ? ` · ${wx.name}` : ""}`) : null,
  ].filter(Boolean);
  return cells.length ? h("div", { class: "vitals", style: `--n:${cells.length}` }, cells) : null;
}

// 搭子的调整（§104 需求 3、§121 需求 4）：钛金色"搭子说"条，在首页直接点"好 / 暂不 / 不用这样调"，不跳进对话
function coachCard() {
  const box = h("section", { class: "buddy-say", hidden: true });
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
      const row = h("div", { class: "hc-msg" });
      const id = x.value?.draft;
      const later = h("button", { class: "btn quiet small", type: "button", onclick: decide(x.key, "later", row, "先不调。") }, "暂不");
      const yes = h("button", { class: "btn small", type: "button", disabled: !!id }, "好");
      const detail = h("div", { class: "hc-draft" });
      row.append(h("p", {}, x.title), detail, h("div", { class: "btn-row" }, yes, later));
      if (id) {  // IronM 提的改计划、临时调整已经存成预览（§163）：列出改了什么，点"好"就确认这份预览，和对话里的卡片一样
        api(`/iron/api/drafts/${encodeURIComponent(id)}`).then(({ draft }) => {
          if (draft.state === "pending" && !draft.expired) {
            if (draft.kind === "temp") detail.replaceChildren(tempBody(draft), h("p", { class: "caption" }, `${TEMP_RULE}${tempExpire(draft.temp)}`));
            else if (draft.changes) detail.replaceChildren(h("p", { class: "muted" }, `改了什么：${draft.changes}`), h("p", { class: "caption" }, "确认后替换现在的计划，之后可以撤销。"));
            yes.disabled = false;
            yes.addEventListener("click", () => confirmPending(x, draft, row));
          } else {
            row.replaceChildren(h("p", { class: "muted" }, draft.state === "confirmed" ? `${x.title}：已经确认过了。`
              : draft.expired ? `${x.title}：没确认，已经作废了；想调可以再跟 IronM 说。` : `${x.title}：已经处理过了。`));
          }
        }).catch(() => { detail.replaceChildren(h("p", { class: "muted" }, "预览没读到，可以到对话里看看。")); });
      } else yes.addEventListener("click", () => acceptPending(x, row));
      rows.push(row);
    }
    // 今天正在看、出错了这类不是调整，大卡片上已经写了（§163）；只有自动生效的能"不用这样调"
    for (const c of r.changes.filter((c) => c.after && (c.kind !== "today" || c.status === "auto")).slice(0, 3)) {
      const row = h("div", { class: "hc-msg" });
      row.append(h("p", {}, c.after), c.status === "auto" ? h("div", { class: "btn-row" },
        h("button", { class: "btn quiet small", type: "button", onclick: decide(c.key, "undo", row, "好的，已经恢复原来的安排。") }, "不用这样调")) : null);
      rows.push(row);
    }
    if (!rows.length) return;
    if (r.changes.length) api("/iron/api/coach/seen", { method: "POST", body: JSON.stringify({ version: r.version }) }).catch(() => {});
    box.replaceChildren(h("span", { class: "buddy-say-head" }, mech(20), "IronM 说"), ...rows);
    box.hidden = false;
  }).catch(() => {});
  return box;
}

// 首页点"好"确认一份预览（§163）：先确认预览（真正生效），再把这条待确认收起；刷新首页，撤销放在提示里
async function confirmPending(x, draft, row) {
  for (const b of row.querySelectorAll("button")) b.disabled = true;
  try {
    await api(`/iron/api/drafts/${encodeURIComponent(draft.id)}/confirm`, { method: "POST", body: "{}" });
  } catch (err) {
    row.append(h("p", { class: "msg-note" }, err.message));
    for (const b of row.querySelectorAll("button")) b.disabled = false;
    return;
  }
  await api("/iron/api/coach/decide", { method: "POST", body: JSON.stringify({ key: x.key, decision: "accept" }) }).catch(() => {});  // 收不起也不影响已确认的
  cache.metrics = null;
  render();
  const undo = h("button", { class: "link", type: "button", onclick: async () => {
    undo.disabled = true;
    try { await api(`/iron/api/drafts/${encodeURIComponent(draft.id)}/undo`, { method: "POST", body: "{}" }); flash(draftUndone(draft)); render(); }
    catch (err) { flash(err.message); }
  } }, "撤销");
  flash(h("span", { class: "flash-row" }, h("span", {}, draftDone(draft)), undo), 8000);
}
// 没带预览的待确认（饮食热量、要现出方案的）：和对话里一样，点了再调热量或出方案，方案确认后才生效
async function acceptPending(x, row) {
  for (const b of row.querySelectorAll("button")) b.disabled = true;
  const out = h("div", { class: "inbox-result" });
  try {
    await api("/iron/api/coach/decide", { method: "POST", body: JSON.stringify({ key: x.key, decision: "accept" }) });
    row.replaceChildren(h("p", {}, x.title), out);
    if (x.key === "proposal:diet") {
      const d = await api("/iron/api/diet/adjust", { method: "POST" });
      cache.metrics = null;
      out.append(h("p", { class: "muted" }, `已调整：每日热量目标约 ${Math.round(d.target)} 千卡。想撤销可以在饮食页撤销。`));
      return;
    }
    if (x.kind !== "proposal" && x.kind !== "alert") { out.append(h("p", { class: "muted" }, "好的，已经按这个安排。")); return; }
    out.append(h("p", { class: "muted" }, "正在拿 IronM 的方案…"));
    const trigger = x.kind === "alert" && x.value?.trigger ? `?trigger=${encodeURIComponent(x.value.trigger)}` : "";
    const p = await api(`/iron/api/review/proposal${trigger}`, { method: "POST" });
    if (p.status === "ok") draftView(out, p.draft, p.answer, p.warning);
    else out.replaceChildren(h("p", { class: "muted" }, p.message || "这次没能生成方案，可以直接告诉 IronM 想怎么改。"));
  } catch (err) {
    row.append(h("p", { class: "msg-note" }, err.message));
    for (const b of row.querySelectorAll("button")) b.disabled = false;
  }
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
    const [wk, tr] = await Promise.all([api("/iron/api/week").catch(() => null), api("/iron/api/training").catch(() => null)]);
    if (tr) { planSessions = tr.plan?.sessions || []; planTargets = tr.targets || {}; }  // 从记录页打开时也带上每组的表（§175）
    const d = wk?.days?.find((x) => x.today);
    if (d?.session && !d.done) doneSheet((d.version || d.session).name, d.version || null);
    else if (d?.done) doneSheet("训练");  // 今天打过卡了：再记一次加练
    else restSheet(h("p", { class: "muted" }, "今天计划里没有训练。练了别的，直接跟 IronM 说一句练了什么，它会帮你记下。"));
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
// 图鉴（§121，§175 照参照图）：动作 / 器械 / 食物 / 方案
const ATLAS_SEGS = [["moves", "动作"], ["machines", "器械"], ["food", "食物"], ["plans", "方案"]];
// 图鉴去重（§161）：图鉴只放资料；打分、排名、评论都在排行榜（首页最上面"今日热搜"进去）
const ATLAS_CHIPS = {
  food: [["", "食材"], ["recipes", "食谱"]],
};
function pageSeg(base, segs, cur, label) {
  return h("div", { class: "seg page-seg", role: "tablist", "aria-label": label, style: `grid-template-columns:repeat(${segs.length},minmax(0,1fr))` }, segs.map(([k, name]) =>
    h("a", { href: `#${base}${k ? `/${k}` : ""}`, role: "tab", class: k === cur ? "on" : "", "aria-selected": String(k === cur) }, name)));
}
async function atlas(view, sub, rest) {
  const cur = ATLAS_SEGS.some(([k]) => k === sub) ? sub : "moves";
  const [chip = ""] = (rest || "").split("/");
  view.append(pageSeg("atlas", ATLAS_SEGS, cur, "图鉴"),
    ATLAS_CHIPS[cur] ? h("div", { class: "pills atlas-chips" }, ATLAS_CHIPS[cur].map(([k, name]) =>
      h("a", { class: `pill${k === chip ? " on" : ""}`, href: `#atlas/${cur}${k ? `/${k}` : ""}` }, name))) : null);
  if (cur === "plans") return plansAtlas(view);
  if (cur === "machines") return machinesPage(view);
  if (cur === "food") return chip === "recipes" ? recipesPage(view) : foodAtlas(view);
  return moves(view);
}

// 方案库（§161）：适合谁、目标、每周几天、在哪练；点开看每次练什么。打分在排行榜的训练计划榜
async function plansAtlas(view) {
  const r = await api("/iron/api/plan-library");
  view.append(h("div", { class: "plan-lib" }, r.plans.map((x) => pressable(h("div", { class: "card plan-lib-card", "aria-label": `${x.name}，点开看每次练什么` },
    h("b", {}, x.name), h("span", { class: "muted" }, x.blurb), x.blogger ? chip(`博主方案 · ${x.blogger}`) : null), () => planLibSheet(x)))),
  h("p", { class: "caption" }, "方案库由 IronM 整理，排计划时按你的器械和伤病换成合适的动作。想看大家怎么评，去首页最上面的排行榜。"));
}
function planLibSheet(x) {
  openSheet(x.name,
    h("div", { class: "tags" }, ...x.goals.map((g) => chip(g)), chip(x.place), chip(`每周 ${x.days.join("或")} 天`), chip(`每次 ${x.minutes[0]}–${x.minutes[1]} 分钟`)),
    h("p", { class: "lede" }, `适合：${x.people[0] === "成年人" ? x.levels.join("、") : x.people.join("、")}`),
    x.why ? h("p", {}, x.why) : null,
    ...x.sessions.map((s) => h("div", {}, h("h3", {}, s.name), h("ul", { class: "tips" }, s.items.map((it) => h("li", {}, `${it.move} ${it.sets} 组 × ${it.reps}${it.note ? `（${it.note}）` : ""}`))))),
    x.intensity ? h("div", {}, h("h3", {}, "强度"), h("p", {}, x.intensity)) : null,
    x.progress ? h("div", {}, h("h3", {}, "怎么加量"), h("p", {}, x.progress)) : null,
    h("p", { class: "caption" }, "排计划时 IronM 会按你的器械、伤病和时间调整动作；想用这个方案，跟 IronM 说一声。"));
}

// 排行榜（§161）：首页"今日热搜"进来；榜单首页（搜索、热搜、六个榜）、榜单页、条目详情
async function rankPage(view, sub, rest) {
  const board = sub ? decodeURIComponent(sub) : "";
  if (!board) {
    view.append(rankBar("#home", "首页", null));
    return rankHome(view);
  }
  const [part = ""] = (rest || "").split("/");
  return tierPage(view, board, part);
}

// 首页最上面：今日热搜（§161）。露出前 3 条，整条点了进排行榜；没人搜、没人评时照实写
async function hotStrip() {
  let d = null;
  try { d = cache.rank || (cache.rank = await api("/iron/api/rank")); } catch { return null; }
  setTimeout(() => { cache.rank = null; }, 60_000);
  let rows = (d.hot || []).slice(0, 3).map((x) => ({ name: x.term, flag: x.flag }));
  if (!rows.length) {
    rows = d.boards.flatMap((b) => b.top.map((x) => ({ name: x.name, people: x.votes || 0, flag: x.trend === "↑" ? "升" : "" })))
      .sort((a, b) => b.people - a.people).slice(0, 3);
  }
  return h("a", { class: "hot-strip", href: "#rank", "aria-label": "今日热搜，点开看排行榜" },
    h("span", { class: "hot-label" }, "今日热搜"),
    rows.length ? h("span", { class: "hot-rows" }, rows.map((x, i) => h("span", { class: "hot-row" }, h("b", {}, String(i + 1)), x.name,
      x.flag ? h("em", { class: `rk-flag f-${{ 热: "hot", 新: "new", 升: "up" }[x.flag]}` }, x.flag) : null)))
      : h("span", { class: "hot-rows muted" }, "排行榜刚开，去评第一个"),
    icon("chevron", "sm"));
}

// 认器械（§149）：拍一张（识别器还没有模型时如实说，引导从清单里选）；下面按三组列常见器械，点开看怎么调、能练什么
const MACHINE_GROUPS = [["gym", "健身房器械"], ["free", "自由重量和小器材"], ["cardio", "有氧器械"]];
async function machinesPage(view) {
  const [r, lib] = await Promise.all([api("/iron/api/machines"), exercises().catch(() => null)]);
  const list = r.machines || [];
  const byId = Object.fromEntries(list.map((m) => [m.id, m]));
  const groups = h("div", { class: "machine-groups" }, MACHINE_GROUPS.map(([g, name]) => {
    const mine = list.filter((m) => m.group === g);
    return mine.length ? h("section", { class: "move-group" },
      h("div", { class: "move-group-head" }, h("h2", {}, name, h("small", {}, `${mine.length} 个`))),
      h("div", { class: "move-grid" }, mine.map((m) => pressable(h("div", { class: "move-card", "aria-label": `${m.name}，点开看怎么用` },
        h("div", { class: "move-cover" }, m.picture ? h("img", { class: "move-img", src: m.picture.url, alt: "", loading: "lazy" }) : h("span", { class: "cover-mark" }, m.name[0])),
        h("div", { class: "move-info" }, h("b", {}, m.name), h("span", {}, m.trains))), () => machineSheet(m, lib))))) : null;
  }));
  const msg = h("div", { class: "machine-msg", role: "status" });
  const input = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", capture: "environment", class: "sr-only" });
  input.addEventListener("change", async () => {
    const f = input.files[0]; input.value = "";
    if (!f) return;
    msg.className = "machine-msg muted"; msg.replaceChildren("正在认…");
    try {
      const form = new FormData();
      form.append("photo", await shrinkPhoto(f), "machine.jpg");
      const got = await send("/iron/api/machines/recognize", form);
      if (got.status === "ok" || got.status === "unsure") {
        msg.className = "machine-msg";
        msg.replaceChildren(h("button", { class: "btn ghost small", type: "button", onclick: () => foundSheet(got, byId[got.match], lib) }, `${got.status === "unsure" ? "不太确定，可能是" : "认出来了："}${got.name}`));
        foundSheet(got, byId[got.match], lib);
      } else {
        msg.className = "machine-msg muted";
        msg.replaceChildren(got.status === "no_model" ? "识别还在训练中，先从下面的清单里找一下。"
          : got.status === "failed" ? (got.message || "这次没认出来，稍后再试，或者从下面的清单里找。") : "照片里没看到健身器械，换个角度再拍一张，或者从下面的清单里找。");
        groups.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "start" });
      }
    } catch (err) { msg.className = "machine-msg"; msg.replaceChildren(errLine(err)); }
  });
  view.append(
    h("label", { class: "card machine-shot" }, input, h("span", { class: "plan-icon" }, icon("camera")),
      h("div", { class: "row-main" }, h("b", {}, "拍一张认器械"), h("span", { class: "muted" }, "不知道叫什么、怎么用，拍下来看看"))),
    h("p", { class: "caption" }, "照片会发给识别服务，认完不保存。"),
    msg, groups);
}
const markList = (items, cls, ic) => h("ul", { class: `marks ${cls}` }, items.map((t) => h("li", {}, icon(ic, "xs"), h("span", {}, t))));
// 能练的动作一行：动作库里有的能点开做法，没有的只写名字
function machineMove(x, lib) {
  const ex = x.id && lib?.exercises?.find((e) => e.id === x.id);
  if (!ex) return h("div", { class: "row-item" }, h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, "图鉴里还没有")));
  return h("button", { class: "row-item", type: "button", onclick: () => exerciseSheet(ex, lib.note, new Set(), false, () => {}) },
    thumb(lib, x.name), h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, `${ex.part} · ${ex.level}`)),
    h("span", { class: "row-end" }, icon("chevron", "sm")));
}
// 拍照认出来的（模型看照片直接写的）：和清单里同一种时多一个"看图鉴里的详情"
function foundSheet(f, known, lib) {
  openSheet(f.name,
    f.status === "unsure" ? h("div", { class: "notice-line" }, icon("info", "xs"), "不太确定，看着像这个；不对的话从清单里找一下。") : null,
    h("div", { class: "tags" }, f.trains ? chip(f.trains) : null, ...(f.aka || []).map((a) => chip(`也叫${a}`))),
    f.setup.length ? h("div", {}, h("h3", {}, "怎么调、怎么用"), markList(f.setup, "ok", "check")) : null,
    f.careful.length ? h("div", {}, h("h3", {}, "要注意"), markList(f.careful, "bad", "alert")) : null,
    f.moves.length ? h("div", {}, h("h3", {}, "能练的动作"), h("div", { class: "rows" }, f.moves.map((x) => machineMove(x, lib)))) : null,
    known ? h("button", { class: "btn ghost block", type: "button", onclick: () => machineSheet(known, lib) }, `看图鉴里的${known.name}`) : null,
    h("p", { class: "caption" }, "IronM 看照片说的，可能不准，以现场说明为准。"));
}
function machineSheet(m, lib) {
  const list = markList;
  const move = (x) => machineMove(x, lib);
  openSheet(m.name,
    m.picture ? moveImages([m.picture]) : null,
    h("div", { class: "tags" }, chip(m.trains), ...(m.aka || []).map((a) => chip(`也叫${a}`))),
    h("div", {}, h("h3", {}, "怎么调"), list(m.setup, "ok", "check")),
    h("div", {}, h("h3", {}, "要注意"), list(m.careful, "bad", "alert")),
    h("div", {}, h("h3", {}, "能练的动作"), h("div", { class: "rows" }, m.moves.map(move))),
    h("p", { class: "caption" }, "器械资料由 IronM 整理，各家器械细节可能不一样，以现场说明为准。"));
}
// 战绩（§137）：不分段，一页到底——这周、打卡日历、成就、每天的记录
async function record(view, sub) { return sub === "timeline" ? timelinePage(view) : recordPage(view); }  // 训练时间线单独一页（§139）

let planDay = null;  // 计划页选中的那天（日期），离开计划页再回来回到今天
async function trainPlan(view) {
  const [tr, week, lib, brief] = await Promise.all([
    api("/iron/api/training").catch(() => null), api("/iron/api/week").catch(() => null), exercises().catch(() => null),
    api("/iron/api/brief").catch(() => null), checkLive()]);
  if (!tr || !week) { view.append(notLoaded("计划", "训练计划")); return; }
  planSessions = tr.plan?.sessions || []; planTargets = tr.targets || {};
  if (!tr.plan) {
    view.append(h("div", { class: "card" }, h("div", { class: "empty" }, icon("dumbbell"), "还没有训练计划"),
      h("div", { class: "btn-row" },
        h("button", { class: "btn small", type: "button", onclick: () => askCoach("帮我排一个每周训练计划") }, "让 IronM 排一份"),
        h("a", { class: "btn ghost small", href: "#atlas/plans" }, "从方案库挑"))));
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
            h("span", { class: "row-sub num" }, `${setsText(it, lib)}${it.load ? `，${it.load}` : ""}`),
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
          h("button", { class: "btn quiet small", type: "button", onclick: () => askCoach("帮我看看现在的训练计划，需要调整吗？") }, "让 IronM 改"))),
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
        : h("p", { class: "caption" }, `每组 ${it.reps}：这种写法用加减改不了，可以让 IronM 改`));
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
    h("button", { class: "link", type: "button", onclick: () => askCoach(`${ctx.name}的${it.exercise}想换个动作，换成什么好？`) }, "都不合适？问 IronM"));
  let r;
  try { r = await api(`/iron/api/plan/alternatives?day=${ctx.day}&exercise=${encodeURIComponent(it.exercise)}`); }
  catch (err) { box.replaceChildren(failed(err, () => swapSheet(ctx, it, st))); return; }
  if (!r.alternatives.length) {
    box.replaceChildren(h("p", { class: "muted" }, "按你的器械和身体情况，没找到合适的替代动作，可以问问 IronM。"));
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


// 战绩·本周小结（§121 需求 6）：练了几次（和上周比）、体重趋势、睡眠；每天练了几组；搭子这周的建议；PR 墙；打卡照片
const setsOf = (it) => it.done_sets?.length || it.sets || 0;
function bestSet(it) {  // 这个动作这次最好的一组：重的优先，一样重次数多的优先
  const sets = it.done_sets?.length ? it.done_sets : it.weight_kg ? [{ weight_kg: it.weight_kg, reps: parseInt(it.reps, 10) || 0 }] : [];
  return sets.filter((x) => x.weight_kg).reduce((a, x) => (!a || x.weight_kg > a.weight_kg || (x.weight_kg === a.weight_kg && x.reps > a.reps) ? x : a), null);
}
const better = (a, b) => a.weight_kg > b.weight_kg || (a.weight_kg === b.weight_kg && a.reps > b.reps);
// 最近 30 天每个动作最好的一组；比这 30 天里更早的都好的标"破 PR"（只有一次记录的不标）
function prWall(workouts) {
  const by = new Map();
  for (const w of [...workouts].filter((x) => x.done !== false && !x.rest).sort((a, b) => a.day.localeCompare(b.day))) {
    for (const it of w.items || []) {
      const b = bestSet(it);
      if (!b) continue;
      const cur = by.get(it.exercise) || { best: null, day: "", times: 0, broke: false };
      cur.broke = cur.times > 0 && better(b, cur.best);
      if (!cur.best || better(b, cur.best)) { cur.best = b; cur.day = w.day; }
      cur.times += 1;
      by.set(it.exercise, cur);
    }
  }
  return [...by.entries()].map(([name, x]) => ({ name, ...x })).sort((a, b) => Number(b.broke) - Number(a.broke) || b.day.localeCompare(a.day));
}
async function recordPage(view) {
  const [brief, cal, tr, rep] = await Promise.all([
    api("/iron/api/brief").catch(() => null), api("/iron/api/calendar").catch(() => null), api("/iron/api/training").catch(() => null),
    api("/iron/api/report/week").catch(() => null)]);
  if (!brief && !cal && !tr) { view.append(notLoaded("记录", "训练记录")); return; }
  const w = brief?.week, logs = tr?.workouts || [];
  const monday = (() => { const d = new Date(); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return isoDay(d); })();
  const lastMonday = (() => { const d = new Date(`${monday}T00:00:00`); d.setDate(d.getDate() - 7); return isoDay(d); })();
  const trained = logs.filter((x) => x.done !== false && !x.rest);
  const days = new Set(trained.filter((x) => x.day >= monday).map((x) => x.day)).size;
  const before = new Set(trained.filter((x) => x.day >= lastMonday && x.day < monday).map((x) => x.day)).size;
  const diff = days - before, planned = w?.planned || w?.due || 0;
  const rpe = cal?.week?.rpe;
  const more = [cal ? `连续打卡 ${cal.streak_days ?? 0} 天` : "", rpe != null ? `平均感受 ${rpe.toFixed(1)} 分` : "",
    w?.weight?.brief ? `体重${w.weight.brief}` : "", w?.sleep?.value != null ? `睡眠平均 ${w.sleep.value} 小时` : ""].filter(Boolean);
  // 这周表现（§137 练了几次只说一次；§175 照参照图三格加周目标进度）
  const weekLogs = trained.filter((x) => x.day >= monday);
  const mins = weekLogs.reduce((a, x) => a + (x.minutes || 0), 0), sets = weekLogs.reduce((a, x) => a + (x.items || []).reduce((b, it) => b + setsOf(it), 0), 0);
  const pct = planned ? Math.min(100, Math.round((days / planned) * 100)) : 0;
  const cell = (k, v, u, cls = "") => h("div", { class: `wp-cell ${cls}` }, h("span", {}, k), h("b", {}, v, h("small", {}, u)));
  view.append(h("section", { class: "card ws week-perf" },
    h("div", { class: "card-title" }, h("h2", {}, h("i", { class: "dot coral" }), "这周表现"), h("span", { class: "tag" }, `${md(monday)} 起`)),
    h("div", { class: "wp-cells" }, cell("已练次数", `${days}`, planned ? `/${planned}次` : "次", "hot"), cell("累计时长", mins >= 60 ? (mins / 60).toFixed(1) : `${mins}`, mins >= 60 ? "小时" : "分钟"), cell("完成组数", `${sets}`, "组")),
    planned ? h("div", { class: "wp-goal" }, h("div", { class: "wp-goal-head" }, h("span", {}, "周目标完成度"), h("b", {}, `${pct}%`)), h("i", {}, h("b", { style: `width:${pct}%` }))) : null,
    h("p", { class: "today-sub" }, [diff > 0 ? `比上周多 ${diff} 次` : diff < 0 ? `比上周少 ${-diff} 次` : before ? "和上周一样" : "上周没有记录", ...more].join("，") + "。"),
    w?.tips?.length ? h("div", { class: "buddy-say" }, h("span", { class: "buddy-say-head" }, mech(20), "IronM 这周的建议"), h("p", {}, w.tips[0])) : null));
  if (cal) view.append(calendarCard(cal));
  view.append(await bodyCard());  // 身体数据指标（§175 从"我 → 身体数据"挪到记录页）
  // 成就：最近 30 天每个动作最好的一组（原 PR 墙）
  const prs = prWall(logs).slice(0, 8);
  view.append(section("成就", h("span", { class: "caption" }, "最近 30 天"), prs.length
    ? h("div", { class: "pr-list" }, prs.map((x) => h("div", { class: `pr-row${x.broke ? " pr-new broke" : ""}` },
      h("span", { class: "pr-name" }, x.name), h("b", { class: "num" }, `${x.best.weight_kg} kg × ${x.best.reps}`),
      x.broke ? h("span", { class: "pr-badge" }, "破 PR") : h("span", { class: "pr-day num" }, md(x.day)))))
    : h("div", { class: "card" }, h("p", { class: "muted" }, "记了重量的训练，每个动作最好的一组会排在这里。"))));
  // 训练时间线：战绩页上只留入口，点了跳到时间线页（§139）
  const last = logs.find((x) => x.done !== false && !x.rest);
  view.append(h("a", { class: "card tl-entry", href: "#record/timeline" },
    h("span", { class: "plank-label" }, "训练时间线"),
    h("span", { class: "tl-entry-text" }, last ? `最近一次：${md(last.day)}，${last.session || "训练"}` : "还没有训练记录"),
    icon("chevron", "sm")));
  if (rep) view.append(weekReport(rep));  // 上周周报放最下面（§147）
}

// 记录页的身体数据指标（§175）：体重一整行（带每周变化和趋势），BMI、体脂率并排；点"全部"进身体数据整页
async function bodyCard() {
  const m = byKey(await metrics().catch(() => ({ metrics: [] })));
  const weight = m.weight || { key: "weight", name: "体重", unit: "公斤" };
  const fat = m.body_fat || { key: "body_fat", name: "体脂率", unit: "%" };
  const trend = m.weight_trend;
  const weightTile = tile(weight, { wide: true });
  if (trend && trend.value != null) {
    weightTile.querySelector(".tile-head").after(h("div", { class: "tile-sub" }, `每周 ${valueText(trend)} ${`${trend.unit || ""}`.replace("/周", "")}${trend.brief ? ` · ${trend.brief}` : ""}`));
  }
  return h("section", { class: "card body-card" },
    h("div", { class: "card-title" }, h("h2", {}, icon("wave", "sm"), "身体数据指标"),
      h("button", { class: "tag coral", type: "button", onclick: quickAdd }, icon("edit", "xs"), "记录")),  // 原悬浮"＋"的快捷记录（补打卡、记一餐、记体重、腰围体脂）挪到这里
    h("div", { class: "tiles body-three" }, weightTile,
      m.bmi ? tile(m.bmi) : tile({ key: "bmi", name: "BMI" }, { brief: "要先填身高体重", tone: "" }),
      fat.value != null ? tile(fat) : tile(fat, { brief: "还没记录", tone: "" })),
    h("a", { class: "link", href: "#body" }, "全部身体数据", icon("chevron", "xs")));
}

// 训练时间线（§139）：从新到旧一条竖线串起每一次训练；每次配一张图——打卡照片，没有就用这次练得最多的部位的训练照片
async function timelinePage(view) {
  const [tr, lib, photos] = await Promise.all([api("/iron/api/training"), exercises().catch(() => null), api("/iron/api/train-images").catch(() => null)]);
  const imgs = photos?.images || {};
  const mainPart = (x) => {
    const n = {};
    for (const it of x.items || []) { const p = partOf(lib, it.exercise); if (p) n[p] = (n[p] || 0) + Math.max(1, setsOf(it)); }
    return Object.entries(n).sort((a, b) => b[1] - a[1])[0]?.[0] || "";
  };
  const pic = (x) => {
    if (x.photo) { const box = h("div", { class: "tl-pic" }); authedImg(`/iron/api/workouts/${x.id}/photo`, box, "打卡照片"); return box; }
    const im = imgs[mainPart(x)];
    return im ? h("div", { class: "tl-pic" }, h("img", { src: im.url, alt: "", loading: "lazy" }),
      h("a", { class: "credit", href: im.page, target: "_blank", rel: "noopener" }, `照片：${im.author}`)) : null;
  };
  const rows = (tr.workouts || []).filter((x) => x.done !== false || x.rest);
  view.append(h("a", { class: "link tl-back", href: "#record" }, icon("back", "xs"), "记录"),
    h("div", { class: "tl-head" }, h("span", { class: "plank-label" }, "训练时间线"), h("span", { class: "muted" }, "最近 30 天")));
  if (!rows.length) { view.append(h("div", { class: "card" }, h("p", { class: "muted" }, "还没有训练记录。练完打个卡，这里就会一条条排出来。"))); return; }
  view.append(h("ol", { class: "timeline" }, rows.map((x) => {
    if (x.rest) return h("li", { class: "tl-item rest" }, h("span", { class: "tl-date" }, md(x.day)), h("div", { class: "tl-rest" }, `没练（${REST_WORDS[x.rest]}）`));
    const sets = (x.items || []).reduce((a, it) => a + setsOf(it), 0);
    const facts = [x.minutes ? `${x.minutes} 分钟` : "", sets ? `${sets} 组` : "", x.rpe ? `感受 ${x.rpe} 分` : "", stateText(x)].filter(Boolean).join("，");
    return h("li", { class: "tl-item" }, h("span", { class: "tl-date" }, md(x.day)),
      h("article", { class: "card tl-card" }, pic(x),
        h("b", { class: "tl-title" }, x.session || "训练"),
        facts ? h("p", { class: "today-sub" }, facts) : null,
        (x.items || []).length ? h("p", { class: "tl-moves" }, x.items.map((it) => it.exercise).join("、")) : null,
        x.note ? h("p", { class: "muted" }, x.note) : null,
        h("button", { class: "link tl-share", type: "button", onclick: () => shareSheet(x.id) }, "晒一下")));
  })));
}

// 打卡日历（§137）：月历能翻月，点那天看记录；下面一句本月练了几天、多少分钟
function calendarCard(first) {
  let cal = first;
  const box = h("section", { class: "card cal-card" });
  const load = async (month) => {
    try { cal = await api(`/iron/api/calendar?month=${month}`); draw(); }
    catch (err) { box.replaceChildren(failed(err, () => load(month))); }
  };
  const shift = (n) => {
    const [y, m] = cal.month.split("-").map(Number);
    load(isoDay(new Date(y, m - 1 + n, 1)).slice(0, 7));
  };
  const draw = () => {
    const now = cal.month === cal.today.slice(0, 7), m = Number(cal.month.slice(5));
    box.replaceChildren(h("div", { class: "quest-head" }, h("span", { class: "plank-label" }, "打卡日历")),
      monthGrid(cal, now, shift),
      h("p", { class: "today-sub" }, `${now ? "本月" : `${m}月`}练了 ${cal.done_days.length} 天，共 ${cal.month_minutes ?? 0} 分钟。`));
  };
  draw();
  return box;
}

// ---- 身体（§104 需求 2，§146 只留三项）----
async function body(view) {
  await dataPart(view);
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

// ---- 打卡分享卡和周报（§147）：在浏览器里画成一张图（§175 白底圆角卡片风），存成图片或交给系统分享；不上传 ----
const CARD = { w: 1080, h: 1350, bg: "#f6f4fa", paper: "#ffffff", soft: "#f6f5fa", line: "#ebebf2",
  ink: "#1d1d26", muted: "#757588", coral: "#f2603f", coralSoft: "#fdece7", green: "#1e8a47", red: "#d6452a" };
const SYS = '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
const kgText = (v) => (v >= 1000 ? `${(v / 1000).toFixed(1)} 吨` : `${Math.round(v)} 公斤`);
// 一行写不下就按字换行（中文没有空格），最多 max 行
function wrapText(g, text, width, max = 2) {
  const out = [];
  let line = "";
  for (const ch of String(text)) {
    if (g.measureText(line + ch).width > width && line) { out.push(line); line = ""; if (out.length === max) break; }
    line += ch;
  }
  if (out.length < max && line) out.push(line);
  return out;
}
const rrect = (g, x, y, w, h, r) => { g.beginPath(); g.roundRect ? g.roundRect(x, y, w, h, r) : g.rect(x, y, w, h); };
// c：{ title, date, head, sub, stats: [[名, 数, 单位]], lines: [..], foot }；photo：ImageBitmap（可没有）
async function drawCard(c, photo = null) {
  const cv = document.createElement("canvas");
  // 高度随内容：没照片、行少时收成方图，最高 4:5
  const H0 = Math.min(CARD.h, Math.max(CARD.w, 640 + (photo ? 468 : 0) + (c.sub ? 44 : 0) + c.lines.length * 72));
  cv.width = CARD.w; cv.height = H0;
  const g = cv.getContext("2d");
  g.fillStyle = CARD.bg; g.fillRect(0, 0, CARD.w, H0);
  const X = 60, Y = 60, W = CARD.w - 120, H = H0 - 120;  // 白色大圆角卡片
  g.save(); g.shadowColor = "rgb(40 30 60 / 8%)"; g.shadowBlur = 40; g.shadowOffsetY = 12;
  g.fillStyle = CARD.paper; rrect(g, X, Y, W, H, 56); g.fill(); g.restore();
  const L = X + 72, R = X + W - 72, inner = R - L;
  let y = Y + 72;
  // 标题：珊瑚红胶囊
  g.font = `bold 44px ${SYS}`; g.textBaseline = "middle";
  const tw = g.measureText(c.title).width + 64;
  g.fillStyle = CARD.coralSoft; rrect(g, L, y, tw, 84, 42); g.fill();
  g.fillStyle = CARD.red; g.fillText(c.title, L + 32, y + 44);
  g.font = `32px ${SYS}`; g.fillStyle = CARD.muted; g.textAlign = "right"; g.fillText(c.date, R, y + 44); g.textAlign = "left";
  y += 132;
  if (photo) {  // 打卡照片：裁成横图、圆角，放在标题下面
    const ph = 420, s = Math.max(inner / photo.width, ph / photo.height);
    const sw = inner / s, sh = ph / s;
    g.save(); rrect(g, L, y, inner, ph, 36); g.clip();
    g.drawImage(photo, (photo.width - sw) / 2, (photo.height - sh) / 2, sw, sh, L, y, inner, ph); g.restore();
    y += ph + 48;
  }
  g.fillStyle = CARD.ink; g.font = `bold 56px ${SYS}`;
  for (const t of wrapText(g, c.head, inner, 1)) { g.fillText(t, L, y + 28); y += 72; }
  if (c.sub) { g.font = `32px ${SYS}`; g.fillStyle = CARD.muted; for (const t of wrapText(g, c.sub, inner, 2)) { g.fillText(t, L, y + 16); y += 44; } }
  y += 28;
  // 三个大数：放在浅底圆角块里
  const gap = 20, cw = (inner - gap * (c.stats.length - 1)) / c.stats.length;
  c.stats.forEach(([name, v, unit], i) => {
    const x = L + i * (cw + gap);
    g.fillStyle = CARD.soft; rrect(g, x, y - 8, cw, 150, 28); g.fill();
    g.font = `28px ${SYS}`; g.fillStyle = CARD.muted; g.fillText(name, x + 24, y + 28);
    g.font = `bold 64px ${SYS}`; g.fillStyle = i === 0 ? CARD.coral : CARD.ink; g.fillText(String(v), x + 24, y + 92);
    const vw = g.measureText(String(v)).width;
    g.font = `28px ${SYS}`; g.fillStyle = CARD.muted; g.fillText(unit, x + 32 + vw, y + 100);
  });
  y += 180;
  g.fillStyle = CARD.line; g.fillRect(L, y, inner, 3); y += 44;
  // 下面几行：破纪录、连续打卡、下周重点……
  g.font = `36px ${SYS}`;
  for (const [mark, text, tone] of c.lines) {
    if (y > Y + H - 200) break;
    g.fillStyle = tone === "red" ? CARD.red : CARD.green; g.fillText(mark, L, y + 20);
    g.fillStyle = CARD.ink;
    for (const t of wrapText(g, text, inner - 64, 2)) { g.fillText(t, L + 64, y + 20); y += 52; }
    y += 12;
  }
  g.font = `bold 40px ${SYS}`; g.fillStyle = CARD.coral; g.fillText("IronM", L, Y + H - 84);
  g.font = `28px ${SYS}`; g.fillStyle = CARD.muted; g.textAlign = "right"; g.fillText(c.foot || "练完打卡，一起变强", R, Y + H - 84); g.textAlign = "left";
  return cv;
}
// 预览加"存成图片"，手机上支持系统分享的再加"分享"
function cardActions(cv, name) {
  const box = h("div", { class: "share-box" });
  const msg = h("p", { class: "muted", role: "status" });
  const img = h("img", { class: "share-img", alt: "分享卡预览" });
  cv.toBlob((blob) => {
    if (!blob) { msg.textContent = "图片没画出来，稍后再试。"; return; }
    const url = URL.createObjectURL(blob);
    img.src = url;
    const file = new File([blob], name, { type: "image/png" });
    const canShare = navigator.canShare?.({ files: [file] });
    box.append(h("div", { class: "btn-row" },
      h("a", { class: "btn", href: url, download: name }, icon("download", "sm"), "存成图片"),
      canShare ? h("button", { class: "btn ghost", type: "button", onclick: async () => {
        try { await navigator.share({ files: [file], title: "IronM" }); } catch { /* 取消了 */ }
      } }, "分享") : null), msg);
  }, "image/png");
  box.append(img);
  return box;
}
async function photoBitmap(id) {
  try {
    const res = await fetch(`/iron/api/workouts/${id}/photo`, { headers: { Authorization: `Bearer ${store.get()}` } });
    return res.ok ? await createImageBitmap(await res.blob()) : null;
  } catch { return null; }
}
function workoutCard(d) {
  const lines = [
    ...d.records.slice(0, 3).map((r) => ["★", `破纪录：${r.exercise} ${r.weight_kg} 公斤 × ${r.reps}`, "red"]),
    d.streak_days > 1 ? ["▲", `连续打卡 ${d.streak_days} 天`] : null,
    d.moves.length ? ["■", d.moves.join("、")] : null,
  ].filter(Boolean);
  return { title: "委托完成", date: md(d.day), head: d.session, sub: d.rpe ? `感受 ${d.rpe} 分` : "",
    stats: [["时长", d.minutes || "—", d.minutes ? "分钟" : ""], ["组数", d.sets || "—", d.sets ? "组" : ""],
      ["总重量", d.volume_kg >= 1000 ? (d.volume_kg / 1000).toFixed(1) : Math.round(d.volume_kg) || "—", d.volume_kg ? (d.volume_kg >= 1000 ? "吨" : "公斤") : ""]],
    lines };
}
async function shareSheet(id) {
  const box = h("div", { class: "sheet-stack" }, h("p", { class: "muted" }, "正在画分享卡…"));
  openSheet("晒一下", box);
  let d;
  try { d = await api(`/iron/api/share/workout/${encodeURIComponent(id)}`); } catch (err) { box.replaceChildren(h("p", { class: "error" }, err.message)); return; }
  const name = `ironm-${d.day}.png`;
  const slot = h("div");
  let withPhoto = Boolean(d.photo);
  const draw = async () => {
    const cv = await drawCard(workoutCard(d), withPhoto ? await photoBitmap(d.id) : null);
    slot.replaceChildren(cardActions(cv, name));
  };
  const toggle = d.photo ? h("label", { class: "check-row" }, h("input", { type: "checkbox", checked: true, onchange: (e) => { withPhoto = e.target.checked; draw(); } }), "带上打卡照片") : null;
  box.replaceChildren(toggle || "", slot, h("p", { class: "caption" }, "卡上只有训练的数，不放体重、体脂。"));
  await draw();
}
function weekImage(r) {
  const lines = [
    ...r.records.slice(0, 2).map((x) => ["★", `破纪录：${x.exercise} ${x.weight_kg} 公斤 × ${x.reps}`, "red"]),
    r.weight ? ["▲", `体重 ${r.weight.from} → ${r.weight.to} 公斤（${r.weight.change > 0 ? "+" : ""}${r.weight.change}）`] : null,
    r.diet ? ["■", `饮食 ${r.diet.on_target} / ${r.diet.logged} 天在目标热量上下`] : null,
    ["→", `下周重点：${r.focus}`],
  ].filter(Boolean);
  return { title: "上周周报", date: `${md(r.from)}–${md(r.to)}`, head: `练了 ${r.done} 次${r.planned ? `，计划 ${r.planned} 次` : ""}`,
    sub: r.rpe != null ? `平均感受 ${r.rpe} 分` : "",
    stats: [["时长", r.minutes || "—", r.minutes ? "分钟" : ""], ["组数", r.sets || "—", r.sets ? "组" : ""],
      ["总重量", r.volume_kg >= 1000 ? (r.volume_kg / 1000).toFixed(1) : Math.round(r.volume_kg) || "—", r.volume_kg ? (r.volume_kg >= 1000 ? "吨" : "公斤") : ""]],
    lines, foot: "每周一出上周的周报" };
}
async function reportSheet(r) {
  const box = h("div", { class: "sheet-stack" }, h("p", { class: "muted" }, "正在画周报…"));
  openSheet("上周周报", box);
  box.replaceChildren(cardActions(await drawCard(weekImage(r)), `ironm-week-${r.from}.png`));
}
// 战绩页最上面的周报（§147 需求 2）
function weekReport(r) {
  const facts = [r.minutes ? `${r.minutes} 分钟` : "", r.sets ? `${r.sets} 组` : "", r.volume_kg ? `总重量 ${kgText(r.volume_kg)}` : "",
    r.rpe != null ? `平均感受 ${r.rpe} 分` : ""].filter(Boolean).join("，");
  const more = [
    r.records.length ? `破纪录：${r.records.slice(0, 3).map((x) => `${x.exercise} ${x.weight_kg}×${x.reps}`).join("、")}` : "",
    r.weight ? `体重 ${r.weight.from} → ${r.weight.to} 公斤` : "",
    r.diet ? `饮食 ${r.diet.on_target} / ${r.diet.logged} 天在目标热量上下` : "",
  ].filter(Boolean);
  return h("section", { class: "card ws week-report" },
    h("div", { class: "quest-head" }, h("span", { class: "plank-label" }, "上周周报"), h("span", { class: "muted" }, `${md(r.from)}–${md(r.to)}`)),
    h("div", { class: "today-title" }, r.done ? `练了 ${r.done} 次${r.planned ? `，计划 ${r.planned} 次` : ""}` : "上周没有训练记录"),
    facts ? h("p", { class: "today-sub" }, `${facts}。`) : null,
    more.map((t) => h("p", { class: "today-sub" }, t)),
    h("div", { class: "buddy-say" }, h("span", { class: "buddy-say-head" }, mech(20), "下周重点"), h("p", {}, r.focus)),
    h("button", { class: "btn ghost block", type: "button", onclick: () => reportSheet(r) }, icon("download", "sm"), "存成图片"));
}
// 对话页：IronM 每周第一次发的周报消息（§147 需求 3），点掉这周不再出
let weekMsg = null;
async function loadWeekMsg() {
  try { const r = await api("/iron/api/report/week"); weekMsg = r.seen ? null : r; } catch { weekMsg = null; }
}
function weekMsgView(r) {
  const close = async () => { weekMsg = null; el.remove(); try { await api("/iron/api/report/week/seen", { method: "POST" }); } catch { /* 下次再点 */ } };
  const said = [r.done ? `上周练了 ${r.done} 次${r.planned ? `（计划 ${r.planned} 次）` : ""}${r.minutes ? `，一共 ${r.minutes} 分钟` : ""}。` : "上周没有训练记录。",
    r.records.length ? `破了 ${r.records.length} 个纪录，${r.records[0].exercise} 做到了 ${r.records[0].weight_kg} 公斤 × ${r.records[0].reps}。` : "",
    `下周重点：${r.focus}`].filter(Boolean).join("");
  const el = h("div", { class: "msg-coach inbox week-msg" },
    h("div", { class: "inbox-head" }, icon("coach", "sm"), h("b", {}, "IronM"), h("span", { class: "muted" }, "上周周报"),
      h("button", { class: "icon-btn", type: "button", "aria-label": "这周不再显示", onclick: close }, icon("close", "sm"))),
    h("p", {}, said),
    h("a", { class: "btn small", href: "#record", onclick: close }, "看周报"));
  return el;
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
  return section("我的目标", btn, box);
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
// 今天的版本（spec [2026-10-23] §18 需求 3；§163 起由管家定，不再按规则改），原计划不变
const setsText = (it, lib) => (partOf(lib ?? cache.exercises, it.exercise) === "有氧" || /分钟/.test(it.reps) ? it.reps : `${it.sets}×${it.reps}`);  // 有氧写时长（§130）
const itemLine = (it) => `${it.exercise} ${setsText(it)}${it.load || it.note ? `（${[it.load, it.note].filter(Boolean).join("，")}）` : ""}`;
// §163：今天怎么练只由管家定。管家还没看完 → 说"正在看"、列原计划、过几秒再取一次；出错 → 说"管家出错了"、
// 列原计划、可以重试；都不按规则替管家减量。onStatus 把状态告诉首页大卡片（那里也要看得到、能重试）
const TODAY_POLL_MS = 5000, TODAY_POLL_MAX = 24;  // 最多自动看 2 分钟，之后让他自己点刷新
const TODAY_WAIT_MAX = 9;  // 点了重试、"有点累"后最多等 45 秒管家看完（后台重看，看完前服务端还是旧的）
function todayVersion(session, { compact = false, onStatus = null } = {}) {
  const box = h("div", { class: "tv" });
  const ask = { minutes: null, tired: false, sent: {} };  // 点过的：写进今日状态、叫醒管家重看，只发一次（§163）
  let timer = 0, polls = 0, last = null;
  let wait = null;  // 刚点了重试 / "有点累"：看完之前服务端给的还是出错、原来的版本，先当作正在看
  const sig = (v) => JSON.stringify([v.status, v.today, v.changes, v.reasons, v.message]);
  const poll = () => {
    clearTimeout(timer);
    if (polls >= TODAY_POLL_MAX) return false;
    timer = setTimeout(() => { if (box.isConnected) { polls += 1; draw(); } }, TODAY_POLL_MS);
    return true;
  };
  const retry = async (btn) => {
    if (btn) btn.disabled = true;
    try {
      const r = await api("/iron/api/coach/retry", { method: "POST", body: "{}" });
      polls = 0;
      wait = r.status === "reviewing" ? { error: true, left: TODAY_WAIT_MAX } : null;
      if (wait) show({ status: "reviewing", original: last?.original });
      await draw();
    } catch (err) { flash(err.message); if (btn) btn.disabled = false; }
  };
  const ctl = { retry, refresh: () => { polls = 0; draw(); } };
  const originalList = (o) => o?.items?.length ? h("div", { class: "tv-orig" },
    h("span", { class: "label" }, `原计划 · ${o.name}`),
    h("ol", { class: "plan-items tv-list" }, o.items.map((it) => h("li", {}, itemLine(it))))) : null;
  const show = (v) => {  // IronM 正在看、出错了、定了今天休息：不按规则替它定，列原计划
    if (v.status !== "reviewing") last = v;
    onStatus?.(v, ctl);
    const err = v.status === "coach_error", waiting = v.status === "reviewing", resting = v.status === "rest_today";
    const going = waiting && poll();
    const head = h("div", { class: `tv-coach${err ? " err" : ""}`, role: "status" },
      icon(err ? "alert" : "coach", "sm"),
      h("div", {}, h("b", {}, resting ? v.message : waiting ? "IronM 正在看今天的情况" : "IronM 出错了，还没看今天的情况"),
        h("p", { class: "muted" }, resting ? "IronM 看过你今天的情况，定了今天休息。"
          : waiting ? (going ? "看完会告诉你今天怎么练，这里会自己更新。" : "看得有点久，过一会儿点刷新看看。")
          : "可以点重试，或者直接问 IronM 今天怎么练。")),
      going ? h("div", { class: "typing" }, h("i"), h("i"), h("i")) : null);
    const btns = err
      ? [h("button", { class: "btn small", type: "button", onclick: (e) => retry(e.currentTarget) }, "重试"),
        h("button", { class: "btn quiet small", type: "button", onclick: () => askCoach("今天练什么？按我的计划和今天的状态说") }, icon("coach", "sm"), "问 IronM")]
      : waiting && !going ? [h("button", { class: "btn ghost small", type: "button", onclick: () => ctl.refresh() }, "刷新")] : [];
    box.replaceChildren(head, btns.length ? h("div", { class: "btn-row" }, btns) : null, originalList(v.original));
  };
  const draw = async () => {
    clearTimeout(timer);
    const q = new URLSearchParams();
    if (ask.minutes && !ask.sent.minutes) q.set("minutes", ask.minutes);
    if (ask.tired && !ask.sent.tired) q.set("tired", "true");
    if (q.size) {  // 自动刷新时不再带：带了会一直叫醒 IronM 重看
      ask.sent = { minutes: !!ask.minutes, tired: ask.tired };
      wait = { before: last?.status === "ok" ? sig(last) : null, left: TODAY_WAIT_MAX }; polls = 0;
    }
    let v;
    try { v = await api(`/iron/api/today${q.size ? `?${q}` : ""}`); }
    catch (err) { box.replaceChildren(failed(err, draw)); return; }
    if (wait) {
      const stale = wait.error ? v.status === "coach_error" : v.status === "reviewing" || (wait.before && sig(v) === wait.before);
      if (stale && wait.left > 0) { wait.left -= 1; show({ status: "reviewing", original: v.original || last?.original }); return; }
      wait = null;
    }
    if (["reviewing", "coach_error", "rest_today"].includes(v.status)) { show(v); return; }
    last = v; onStatus?.(v, ctl);
    if (v.status !== "ok") { box.replaceChildren(); return; }
    const toggle = (label, on, flip) => h("button", { type: "button", class: `pill${on ? " on" : ""}`, "aria-pressed": String(on), disabled: on, title: on ? "说过了，IronM 会按这个重看今天" : null, onclick: () => { flip(); draw(); } }, label);
    const items = (v.changed ? v.today : v.original).items;
    box.replaceChildren(
      compact ? null : h("div", { class: "tv-head" },
        h("div", {}, h("h3", {}, `今天 · ${v.today.name}`), h("p", { class: "muted" }, `约 ${v.today.minutes || session.minutes} 分钟 · ${items.length} 个动作`)),
        h("button", { class: "icon-btn", type: "button", "aria-label": "问教练怎么练", onclick: () => askCoach("今天练什么？按我的计划和今天的状态说") }, icon("coach", "sm"))),
      v.changed ? h("details", { class: "tv-adjusted" },
        h("summary", {}, icon("alert", "xs"), h("span", {}, "IronM 按你今天的情况调整过"), h("em", {}, "为什么"), icon("chevron", "xs")),
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
      if (r.workout?.id) setTimeout(() => shareSheet(r.workout.id), 1200);  // 打卡成功后弹出分享卡（§147）
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
    w.tips.length && w.planned ? h("p", { class: "caption" }, "想改计划，咨询 IronM。") : null);  // 复盘只给建议（§146）
}

// 临时调整（§163，kind "temp"）：哪几天这样练、改了什么、为什么；确认才生效，到期回到原计划，
// 没确认的过了开始日期作废（expires）。对话里的卡片、确认弹窗、首页"IronM 说"都用这几句
const tempSpan = (t) => !t?.start ? "" : t.end && t.end !== t.start ? `${md(t.start)}到${md(t.end)}` : md(t.start);
const TEMP_RULE = "这几天这样练，到期自动回到原计划；点确认才生效，确认后也能提前撤销。";
const tempExpire = (t) => t?.start ? `没确认的过了开始日期（${md(t.start)}）就作废。` : "没确认的过了开始日期就作废。";
function tempBody(d) {
  const t = d.temp || {};
  const lines = (d.items || []).length ? d.items : t.lines || [];
  return [
    t.start ? h("p", { class: "temp-span" }, h("b", {}, `${tempSpan(t)}这样练`), "，到期回到原计划") : null,
    lines.length ? h("ul", { class: "temp-lines" }, lines.map((x) => h("li", {}, x))) : null,
    t.why ? h("p", { class: "muted" }, `为什么：${t.why}`) : null,
  ];
}
const draftDone = (d) => d.kind === "temp" ? `已确认：${tempSpan(d.temp) || "这几天"}这样练，到期回到原计划。` : "已保存，新的计划从今天起生效。";
const draftUndone = (d) => d.kind === "temp" ? "已撤销，回到原计划。" : "已撤销，计划回到改之前的样子。";

function draftView(box, d, answer, warning) {
  const temp = d.kind === "temp";
  const msg = h("p", { class: "muted", role: "status" });
  const actions = h("div", { class: "btn-row" });
  const act = async (action, done) => {
    for (const b of actions.querySelectorAll("button")) b.disabled = true;
    try { await api(`/iron/api/drafts/${d.id}/${action}`, { method: "POST" }); done(); cache.metrics = null; }
    catch (err) { msg.className = "error"; msg.textContent = err.message; for (const b of actions.querySelectorAll("button")) b.disabled = false; }
  };
  const undo = h("button", { class: "btn ghost", type: "button", onclick: () => act("undo", () => { msg.textContent = draftUndone(d); actions.replaceChildren(); }) }, "撤销");
  if (d.state === "confirmed") { actions.append(undo); msg.textContent = draftDone(d); }
  else if (d.state && d.state !== "pending") msg.textContent = CARD_STATE[d.state] || d.state;
  else if (d.expired) msg.textContent = temp ? "这份临时调整过了开始日期还没确认，已经作废；想调可以再跟 IronM 说。" : "这份方案已经过期，想调可以再跟 IronM 说。";
  else {
    actions.append(
      h("button", { class: "btn", type: "button", onclick: () => act("confirm", () => { msg.textContent = draftDone(d); actions.replaceChildren(undo); }) }, icon("check", "sm"), temp ? "确认这样练" : "确认"),
      h("button", { class: "btn ghost", type: "button", onclick: () => act("cancel", () => { msg.textContent = "已取消，计划没有改动。"; actions.replaceChildren(); }) }, "取消"));
  }
  const sessions = d.plan?.sessions || [];
  box.replaceChildren(
    answer ? h("p", { class: "lede" }, answer) : null,
    !temp && d.changes ? h("div", { class: "notice-line" }, icon("info", "xs"), `改了什么：${d.changes}`) : null,
    warning ? h("div", { class: "notice-line" }, icon("alert", "xs"), warning) : null,
    temp ? h("div", { class: "temp-box" }, tempBody(d))
      : h("ol", { class: "plan-items" }, sessions.map((x) => h("li", {}, `${weekdayName(x.day)} ${x.name}（约 ${x.minutes} 分钟）：${x.items.map((it) => `${it.exercise} ${it.sets}×${it.reps}`).join("、")}`))),
    actions, msg,
    h("p", { class: "caption" }, temp ? `${TEMP_RULE}${tempExpire(d.temp)}` : "确认后才会替换现在的计划，之后可以撤销；这份方案 24 小时内有效。"));
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
  const [lib, vids, me, tr] = await Promise.all([exercises(), api("/iron/api/videos").catch(() => ({ videos: [] })), whoami(),
    api("/iron/api/training").catch(() => null), checkLive()]);
  // 自由训练（§133）：空的开始、不带计划，训练页能加动作；照参照图做成一张横幅
  view.append(liveNow ? liveEntry({ free: true }, "自由训练") : pressable(h("div", { class: "free-banner", "aria-label": "自由训练，立即开启" },
    h("div", {}, h("b", {}, icon("dumbbell", "sm"), "自由训练"), h("span", {}, "自己加动作、加组，随心开练")),
    h("span", { class: "fb-go" }, "立即开启", icon("chevron", "xs"))), () => startLive({ free: true })));
  const best = Object.fromEntries(prWall(tr?.workouts || []).map((x) => [x.name, x.best]));  // 卡片上的历史最佳（最近 30 天）
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
    count.textContent = `${items.length} 项`;
    const card = (x) => moveCard(x, has.has(x.id), () => exerciseSheet(x, lib.note, has, me.admin, draw), best[x.name]);
    if (!items.length) {
      grid.replaceChildren(h("div", { class: "card" }, h("div", { class: "empty" }, icon("search"), "没有符合的动作，换个条件试试，或者直接问训练教练。")));
    } else if (moveFilter.part === "全部" && !q) {
      // 按部位收纳：每组先显示几个，点"全部 N 个"再展开（搜索或选了部位时平铺）
      grid.replaceChildren(...lib.parts.map((part) => {
        // 常见动作排在前面（§144），同样常见的有视频、动图或配图的在前
        const rank = (x) => (x.common === false ? 0 : 2) + (has.has(x.id) || x.gif || x.images?.length ? 1 : 0);
        const mine = items.filter((x) => x.part === part).sort((a, b) => rank(b) - rank(a));
        if (!mine.length) return null;
        const all = moveOpen.has(part);
        const toggle = () => { if (all) moveOpen.delete(part); else moveOpen.add(part); draw(); };
        return h("section", { class: "move-group" },
          h("div", { class: "move-group-head" }, h("h2", {}, part, h("small", {}, `${mine.length} 个`)),
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
    h("div", { class: "lib-head" }, h("h2", {}, "标准动作库"), count), grid);
}

function moveCard(x, video, open, best = null) {
  const cover = h("div", { class: `move-cover p-${x.part}` },
    video ? h("video", { src: `${videoUrl(x.id)}#t=0.5`, muted: true, playsinline: true, preload: "metadata", "aria-hidden": "true" })
      : x.gif || x.images?.length ? h("img", { class: "move-img", src: (x.gif || x.images[0]).url, alt: "", loading: "lazy" })
        : h("span", { class: "cover-mark" }, PART_MARK[x.part] || x.part[0]),
    video ? h("span", { class: "play" }, icon("play", "sm")) : null,
    h("span", { class: `cover-level lv-${x.level}` }, x.level));
  return pressable(h("div", { class: "move-card", "aria-label": `${x.name}，点开看做法` }, cover,
    h("div", { class: "move-info" }, h("b", {}, x.name), h("span", {}, `${x.part} · ${x.equipment.slice(0, 2).join("、")}`)),
    h("div", { class: "move-best" }, h("span", {}, "历史最佳"), h("b", {}, best ? `${best.weight_kg}kg` : "—"))), open);
}

function exerciseSheet(x, note, has, admin, redraw) {
  const list = (items, cls, ic) => h("ul", { class: `marks ${cls}` }, items.map((t) => h("li", {}, icon(ic, "xs"), h("span", {}, t))));
  const video = has.has(x.id)
    ? h("video", { class: "move-video", src: videoUrl(x.id), controls: true, playsinline: true, preload: "metadata" })
    : x.gif ? moveImages([x.gif]) : x.images?.length ? moveImages(x.images)
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

// 动作配图（来自 wger、Everkinetic，CC BY-SA）：起止两张并排，下面署名（spec [2026-10-23] §32）；合成的动图单张放，注明合成（§144）
function moveImages(images) {
  const link = (text, href) => (href ? h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text) : h("span", {}, text));
  const im = images[0];
  return h("figure", { class: "move-figure" },
    h("div", { class: `move-frames n${images.length}` }, images.map((x, i) => h("img", { src: x.url, alt: x.made ? "动作演示" : i ? "动作结束" : "动作开始", loading: "lazy" }))),
    h("figcaption", { class: "caption" }, im.made ? "动图：" : "图：", link(im.author, im.author_url), im.made ? ` · ${im.made}` : "", " · 来自 ", link(im.site || "wger", im.page), " · ", link(im.license, im.license_url)));
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

// 首页·干饭（§125）：只留今日余额、记一餐、今天的饮食计划三块
async function food(view) {
  const [day, m] = await Promise.all([api("/iron/api/meals"), metrics().then(byKey).catch(() => ({}))]);
  const budget = h("div");
  const plan = h("div");
  const meta = h("p", { class: "caption tp-meta" });
  let today = day;
  const redraw = (d) => { today = d; budget.replaceChildren(todayBudget(d, m)); plan.replaceChildren(todayPlan(d, redraw, meta)); };
  redraw(day);
  const editPlan = h("button", { class: "link", type: "button", onclick: async () => {
    const p = await api("/iron/api/diet/plan").catch(() => null);
    if (p) planEditSheet(p, () => redraw(today)); else flash("饮食计划这次没读到");
  } }, icon("edit", "xs"), "改计划");
  view.append(budget, mealEntry(() => today, redraw, null, false),
    section("今天吃什么", editPlan, plan));
}

// 图鉴·食物（§121 需求 7）：在食物库里搜；没搜时一排常搜的词；点开看营养素、带着它记一餐
const FOOD_STARTERS = ["鸡蛋", "米饭", "鸡胸", "牛奶", "燕麦", "香蕉", "豆腐", "牛肉", "西兰花", "面条"];
let foodAtlasQ = "";
async function foodAtlas(view) {
  const input = h("input", { type: "search", placeholder: "搜食物：米饭、鸡胸肉、番茄炒蛋…", value: foodAtlasQ, "aria-label": "在食物库里搜" });
  const list = h("div", { class: "fa-grid" });
  const starters = h("div", { class: "pills" }, FOOD_STARTERS.map((w) => h("button", { class: "pill", type: "button", onclick: () => { input.value = w; go(); } }, w)));
  let seq = 0, timer = 0;
  const go = async () => {
    foodAtlasQ = input.value.trim();
    const mine = ++seq;
    if (!foodAtlasQ) { list.replaceChildren(h("p", { class: "caption" }, "在常见食物库里搜，营养按每 100 克算（内容待审定）。")); return; }
    const r = await api(`/iron/api/foods?q=${encodeURIComponent(foodAtlasQ)}`).catch(() => null);
    if (mine !== seq) return;
    if (!r) { list.replaceChildren(h("p", { class: "muted" }, "食物库这次没读到，稍后再试。")); return; }
    list.replaceChildren(...(r.foods.length ? r.foods.map((f) => h("button", { class: "fa-card", type: "button", onclick: () => foodSheet(f) },
      foodTile(f.name, f.image, f.cat), h("b", {}, f.name),
      h("span", { class: "num" }, `${f.per100.kcal} 千卡`, h("small", {}, ` · 蛋白质 ${f.per100.protein_g} 克`)), h("small", { class: "muted" }, "每 100 克")))
      : [h("p", { class: "muted" }, "库里没找到，换个叫法试试。")]));
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(go, 200); });
  view.append(h("div", { class: "search" }, icon("search", "sm"), input), starters, list);
  go();
}
function foodSheet(f) {
  const n = f.per100;
  const bar = (k, v, cls) => h("div", { class: "fa-macro" }, h("span", {}, k), h("b", { class: `num ${cls}` }, `${v} 克`));
  openSheet(f.name,
    h("div", { class: "fa-head" }, foodTile(f.name, f.image, f.cat, "lg"),
      h("div", {}, h("b", { class: "num fa-kcal" }, String(n.kcal), h("small", {}, " 千卡 / 100 克")),
        h("p", { class: "muted" }, `一${f.unit}约 ${Math.round(f.unit_g)} 克${f.cat ? ` · ${f.cat}` : ""}`))),
    imageCredit(f.image),
    h("div", { class: "fa-macros" }, bar("蛋白质", n.protein_g, "p"), bar("碳水", n.carbs_g, "c"), bar("脂肪", n.fat_g, "f")),
    h("button", { class: "btn block", type: "button", onclick: async () => {
      const day = await api("/iron/api/meals").catch(() => null);
      if (!day) { flash("今天的饮食这次没读到"); return; }
      pickFoodsSheet(day, () => flash(`记下了：${f.name}`), null, [{ name: f.name, food_id: f.id, grams: f.unit_g, oil: "正常", dish: f.dish, f }]);
    } }, "带着它记一餐"));
}

// 饮食的图（§119）：有配图用配图（公开的图，<img> 直接取）；没有的用"分类颜色色块 + 名字首字"
const FOOD_HUE = { 主食: 38, 肉蛋: 8, 水产: 355, 奶豆: 48, 蔬菜: 130, 水果: 330, 坚果油: 28, 饮品: 280, 零食: 300, 家常菜: 18, 外卖: 60, 早餐: 52 };  // 不用蓝、青（§121）
function foodTile(name, image, cat = "", size = "") {
  const box = h("span", { class: `food-tile${size ? ` ${size}` : ""}` });
  if (image?.url) box.append(h("img", { src: image.url, alt: "", loading: "lazy" }));
  else {
    // 没给分类的（一餐、食谱）按名字挑一个食物色调，同一个名字每次一样
    const warm = [18, 32, 45, 95, 130, 0, 280, 340];
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
function mealEntry(today, redraw, kind = null, withUsual = true) {  // 常吃的只在"＋ 记"弹出页里（§125）
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
  if (withUsual) api("/iron/api/meals/usual").then((r) => {
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
      h("button", { class: "entry-chip", type: "button", onclick: () => pickFoodsSheet(today(), redraw, kind) }, icon("search", "sm"), "从图鉴选")),
    msg, withUsual ? h("div", { class: "usual-wrap" }, h("span", { class: "label usual-label", hidden: true }, "常吃的"), usual) : null);
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
    catch (err) { msg.className = ""; msg.replaceChildren(errLine(err)); go.disabled = false; }
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
// 今天的饮食计划（§125）：按顿逐样列吃什么、多少克、多少千卡；吃过的列实际记的，没吃的列计划，没排的能记
function todayPlan(d, redraw, meta) {
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
  const list = h("div", { class: "tp-list" });
  const lines = (foods) => h("ul", { class: "tp-foods" }, foods.map((f) => h("li", {},
    h("span", { class: "tp-food" }, f.name), h("span", { class: "num" }, `${Math.round(f.grams)} 克`), h("span", { class: "num" }, `${Math.round(f.kcal)} 千卡`))));
  const pic = (img) => (img?.url ? h("img", { class: "tp-thumb", src: img.url, alt: "", loading: "lazy" }) : null);
  const meal = (k, kcal, state, end, img, ...body) => h("div", { class: `tp-meal ${state}` },
    h("div", { class: "tp-head" }, pic(img), h("b", {}, k), kcal != null ? h("span", { class: "tp-kcal" }, h("b", { class: "fig-n" }, String(Math.round(kcal))), "千卡") : null, end), ...body);
  const draw = (plan) => {
    const set = plan?.sets?.[plan.today_set] || {};
    if (plan) meta.textContent = `按${plan.today_set === "weekend" ? "周末" : "工作日"}的计划，一共 ${plan.totals[plan.today_set].kcal} 千卡。`;
    const kinds = MEAL_KINDS.filter((k) => MAIN_KINDS.includes(k) || d.meals.some((x) => x.kind === k));
    list.replaceChildren(...kinds.map((k) => {
      const xs = d.meals.filter((x) => x.kind === k);
      if (xs.length) {
        return meal(k, xs.reduce((a, x) => a + x.macros.kcal, 0), "done", h("span", { class: "tp-tag" }, "已吃"), xs.find((x) => x.image)?.image,
          ...xs.map((x) => pressable(h("div", { class: "tp-eaten" }, h("span", { class: "tp-name" }, x.name, icon("chevron", "xs")),
            x.foods?.length ? lines(x.foods.map((f) => ({ name: f.name, grams: f.grams, kcal: f.macros.kcal }))) : null), () => mealSheet(x, redraw))));
      }
      const planned = set[k] && !set[k].missing ? set[k] : null;
      if (planned) {
        return meal(k, planned.kcal, "planned", h("button", { class: "btn small", type: "button", onclick: async (e) => {
          e.currentTarget.disabled = true;
          try { redraw(await api("/iron/api/diet/plan/log", { method: "POST", body: JSON.stringify({ slot: k }) })); flash(`记下了${k}`); } catch (err) { flash(err.message); e.currentTarget.disabled = false; }
        } }, "照计划记"), planned.image, h("span", { class: "tp-name" }, planned.name), planned.foods?.length ? lines(planned.foods) : null);
      }
      return meal(k, null, "unplanned", h("button", { class: "link", type: "button", onclick: () => addMealSheet(k, d, redraw) }, icon("plus", "xs"), "记"), null,
        h("span", { class: "tp-none" }, "没排"));
    }));
  };
  draw(null);
  api("/iron/api/diet/plan").then(draw).catch(() => {});
  return h("div", { class: "today-plan" }, meta, review, list);  // 计划说明放进面板里（草地上看不清，§131）
}

// 点空着的那一顿：拍、写、选、常吃的，都记成这一顿
function addMealSheet(kind, d, redraw) {
  openSheet(`记${kind}`, mealEntry(() => d, (r) => { closeSheet(); redraw(r); }, kind));
}

// 今日余额（§125）：还能吃多少（大字）、已吃和目标、进度条；下面一排三大营养
function todayBudget(d, m) {
  const t = d.target, tot = d.totals;
  if (!t) {
    return h("div", { class: "card" },
      h("div", { class: "empty" }, icon("info"), "在「我」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。"),
      h("a", { class: "btn ghost small", href: "#me" }, "去填写"),
      tot.kcal ? h("p", { class: "muted" }, `今天已记：${macroLine(tot)}`) : null);
  }
  const kcal = m.kcal_target, protein = m.protein_target;
  const pt = protein?.display ? Number(String(protein.display).split("–")[0]) : t.protein_g;
  const left = Math.round(t.kcal - tot.kcal), pct = Math.min(100, Math.round((tot.kcal / t.kcal) * 100));
  const macro = (name, have, target, cls) => h("div", { class: `bg-macro ${cls}` }, h("span", {}, name),
    h("b", { class: "fig-n" }, String(Math.round(have)), h("small", {}, target ? `/${Math.round(target)} 克` : "克")));
  // 体力条（§131）：今天还能吃的占目标的多少，吃一顿掉一截
  const energy = h("div", { class: "energy", role: "img", "aria-label": `体力还剩 ${Math.max(0, 100 - pct)}%` }, h("i", { style: `height:${Math.max(0, 100 - pct)}%` }));
  return h("section", { class: "budget with-energy" }, energy, h("div", { class: "budget-main" },
    h("span", { class: "label" }, left >= 0 ? "今天还能吃" : "今天多吃了"),
    h("div", { class: "bg-big fig-n" }, String(Math.abs(left)), h("small", {}, "千卡")),
    h("p", { class: "muted" }, `已经吃了 ${Math.round(tot.kcal)}，今天的目标是 ${Math.round(t.kcal)} 千卡。`),
    h("div", { class: "thin-bar" }, h("span", { style: `width:${pct}%` })),
    h("div", { class: "bg-macros" }, macro("蛋白质", tot.protein_g, pt, "p"), macro("碳水", tot.carbs_g, null, "c"), macro("脂肪", tot.fat_g, null, "f")),
    h("button", { class: "link bg-how", type: "button", onclick: () => openSheet("今日目标怎么算的",
      ...[kcal, protein, m.bmr, m.tdee].filter((x) => x && x.value != null).map((x) => h("div", {}, h("h3", {}, x.name), h("dl", { class: "facts" },
        [["结论", x.text], ["怎么算的", x.how], ["依据", x.source]].filter(([, v]) => v).map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))))),
      observedBox()) }, "目标怎么算的", icon("chevron", "xs"))));
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
      r.proposal ? h("p", { class: "caption" }, `IronM 的建议：${r.proposal.reason}，目标从 ${r.proposal.before} 调到 ${r.proposal.after} 千卡，在"吃了什么"上面确认。`) : null);
  }).catch(() => box.replaceChildren(h("p", { class: "muted" }, "这次没算出来。")));
  return box;
}

// 不拍不写，直接从食物库挑着记一餐
function pickFoodsSheet(day, redraw, kind0 = null, initial = []) {
  const lines = foodLines(initial);
  kindSheet("从食物库选", day, async (kind) => {
    const foods = lines.read().filter((f) => f.food_id);
    if (!foods.length) throw new Error("先在上面加一样吃的");
    redraw(await api("/iron/api/meals/foods", { method: "POST", body: JSON.stringify({ kind, foods }) }));
  }, h("div", {}, lines.el, h("p", { class: "caption" }, "营养按食物库算（内容待审定），不调用模型。")), kind0);
}

// 食谱（§119）：一排筛选，下面横向滑动的图片卡，最后一张是新建；点开看原料、做法、每份营养，按份数记成一餐
const recipeState = { tag: "推荐" };
// 图鉴·食谱（§125，从干饭页挪过来）：两列卡片，点开能记一餐
async function recipesPage(view) {
  let day = await api("/iron/api/meals").catch(() => null);
  if (!day) { view.append(notLoaded("食谱", "今天的饮食")); return; }
  view.append(recipesCard(() => day, (d) => { day = d; flash("记下了"); }, true));
}
function recipesCard(today, redraw, grid = false) {
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
        h("div", { class: grid ? "recipe-grid" : "hscroll recipe-row" },
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
      h("div", { class: "seg seg-2", role: "tablist" }, [["weekday", "工作日"], ["weekend", "周末"]].map(([k, n]) => h("a", { href: "#home/eat", role: "tab", class: set === k ? "on" : "", onclick: (e) => { e.preventDefault(); set = k; draw(); } }, n))),
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
    } catch (err) { out.replaceChildren(errLine(err)); }
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
  bmi: ["由体重和身高算出。", "体重和身高都在「我」里改。"],
  bmr: ["由体重、身高、年龄、性别算出。", "身高、出生日期、性别、体重都在「我」里改。"],
  tdee: ["基础代谢乘以日常活动水平。", "活动水平在「我」里改。"],
  kcal_target: ["每日总消耗按目标加减，再加上两周饮食复盘的调整量。", "目标在「我」里改；调整量在饮食页确认或撤销。"],
  protein_target: ["按体重和目标算出。", "目标和体重都在「我」里改。"],
};

// 身体数据（§146）：上面只放体重（带每周变化）、BMI、体脂率；其余收进两块，点开再看：
// "全部指标"（其余指标和还没记的合成一列，最下面是原始记录）、"这周训练"（每周复盘和肌肉恢复）
const TOP3 = ["weight", "weight_trend", "bmi", "body_fat"];
function fold(title, sub, ...body) {
  return h("details", { class: "me-more body-fold" },
    h("summary", {}, h("span", { class: "row-main" }, h("span", { class: "row-title" }, title), sub ? h("span", { class: "row-sub" }, sub) : null), icon("chevron", "xs")),
    h("div", { class: "me-more-body" }, ...body));
}
async function dataPart(view) {
  const [list, muscles, brief, mine] = await Promise.all([
    metrics(), api("/iron/api/muscles").catch(() => null), api("/iron/api/brief").catch(() => null), profile().catch(() => null)]);
  const m = byKey(list);
  const weight = m.weight || { key: "weight", name: "体重", unit: "公斤" };
  const fat = m.body_fat || { key: "body_fat", name: "体脂率", unit: "%" };
  const trend = m.weight_trend;
  const weightTile = tile(weight, { wide: true });
  if (trend && trend.value != null) {
    weightTile.querySelector(".tile-head").after(h("div", { class: "tile-sub" }, `每周 ${valueText(trend)} ${String(trend.unit || "").replace("/周", "")}${trend.brief ? ` · ${trend.brief}` : ""}`));
  }
  view.append(h("div", { class: "fresh" }, icon("info", "xs"),
    list.as_of ? `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开看怎么算的、自己记一条` : "还没有同步到健康数据，可以先自己记一条"));
  view.append(h("div", { class: "tiles body-three" },
    weightTile,
    m.bmi ? tile(m.bmi) : tile({ key: "bmi", name: "BMI" }, { brief: "要先填身高体重", tone: "" }),
    fat.value != null ? tile(fat) : tile(fat, { brief: "还没记录", tone: "" })));

  // 全部指标：有数的按原来的顺序，常记的还没记的接在后面（原来的"还缺 N 项"）
  const have = METRIC_ORDER.filter((k) => !TOP3.includes(k) && m[k] && m[k].value != null);
  const lack = IMPORTANT.filter((k) => !TOP3.includes(k) && !(m[k] && m[k].value != null));
  const metricRow = (x) => h("button", { class: "row-item", type: "button", onclick: () => metricSheet(x) },
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), x.brief ? h("span", { class: "row-sub" }, x.brief) : null),
    h("span", { class: "row-end" }, h("b", { style: "color:var(--ink)" }, valueText(x)), x.unit || "", icon("chevron", "sm")));
  const lackRow = (k) => h("button", { class: "row-item", type: "button", onclick: () => (MANUAL[k] ? recordSheet(IMPORTANT_NAMES[k], MANUAL[k]) : appleSheet()) },
    h("div", { class: "row-main" }, h("span", { class: "row-title" }, IMPORTANT_NAMES[k]), h("span", { class: "row-sub" }, MANUAL[k] ? "还没记录" : "还没记录，要手表或苹果健康")),
    h("span", { class: "row-end" }, MANUAL[k] ? "记一条" : "导入", icon("chevron", "sm")));
  const raw = h("details", { class: "raw-fold" }, h("summary", {}, "看原始记录", icon("chevron", "xs")));
  raw.addEventListener("toggle", async () => {
    if (!raw.open || raw.dataset.loaded) return;
    raw.dataset.loaded = "1";
    raw.append(await catalogSection());
  });
  view.append(fold("全部指标", `${have.length} 项${lack.length ? ` · 还有 ${lack.length} 项没记` : ""}`,
    h("div", { class: "card" }, h("div", { class: "rows" }, have.map((k) => metricRow(m[k])), lack.map(lackRow))),
    raw));

  // 这周训练：每周复盘在上，肌肉恢复在下
  const tired = (muscles?.muscles || []).filter((x) => x.tier !== "ready" || x.state === "sore").length;
  const weekSub = [brief?.week?.planned ? `完成 ${brief.week.done} / ${brief.week.planned} 次` : "",
    muscles?.sessions ? `${tired} 块肌肉恢复中` : ""].filter(Boolean).join(" · ");
  view.append(fold("这周训练", weekSub,
    brief ? weekCard(brief.week) : null,
    muscles ? bodyMap(muscles, brief, mine?.sex) : failed(new Error("肌肉恢复暂时算不出来"), () => render())));
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
const tierHref = (board, part = "") => `#rank/${encodeURIComponent(board)}${part ? `/p:${encodeURIComponent(part)}` : ""}`;
const itemHref = (board, key) => `#rank/${encodeURIComponent(board)}/i:${encodeURIComponent(key)}`;
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
        h("div", {}, h("h2", {}, b.name), b.people ? h("small", {}, `本周 · ${b.people} 人参与`) : null),
        h("a", { class: "rk-all", href: tierHref(b.board) }, "全部", icon("chevron", "xs"))),
      h("div", { class: "rk-rows" }, rows.map((x) => [
        h("a", { class: `rk-row${x.rank ? "" : " wait"}`, href: itemHref(b.board, x.key) },
          b.people ? rkNo(x.rank) : h("span", { class: "rk-no" }), rkPic(x, b.icon), rkLabel(x),  // 没人评时不写"–"（§161）
          h("span", { class: `rk-tr ${trendCls(x.trend)}` }, x.trend),
          x.rank ? tierTag(d, x) : b.people ? h("span", { class: "rk-tag t-wait" }, "待评") : null,
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
    list.replaceChildren(...(rows.length ? rows.map((x) => rankLine(d, x))
      : !d.people ? [] : [h("p", { class: "rk-none" }, sort === "新上榜" ? "还没有用户添加的条目。" : "还没有上榜的（要 3 个人评过）。下面待评的点进去投一票。")]));
  };
  draw();
  const adder = rankAdd(d);
  adder.hidden = true;
  const addBtn = h("button", { class: "btn ghost small", type: "button", onclick: () => { adder.hidden = !adder.hidden; if (!adder.hidden) adder.querySelector("input").focus(); } }, icon("plus", "xs"), "添加");
  const partHref = (p) => tierHref("move", p);
  view.append(rankBar("#rank", `${d.icon} ${d.name}`, d.can_add ? addBtn : null),
    d.can_add ? adder : null,
    board === "move" ? h("div", { class: "pills" }, h("a", { class: `pill${part ? "" : " on"}`, href: partHref("") }, "全部"),
      (rankParts || MOVE_PARTS).map((p) => h("a", { class: `pill${p === part ? " on" : ""}`, href: partHref(p) }, p))) : null,
    // 没人评时不写"0 人参与""待评 N 个""没人评"（§161）
    h("p", { class: "caption" }, `${d.people ? `${d.people} 人参与 · ` : "还没人评过，点进去打第一个分。"}${d.disclaimer}${part ? " 按部位看时名次是这个部位里的，不显示名次变化。" : ""}`),
    d.people ? sorts : null, list,
    waiting.length ? h("section", { class: "rk-pending" }, d.people ? h("h3", {}, `待评 ${waiting.length} 个 · 3 个人评过才上榜`) : null,
      waiting.map((x) => h("a", { href: itemHref(board, x.key) }, rkPic(x, d.icon, "rk-pic sm"), rkLabel(x), x.votes ? h("small", {}, `还差 ${d.min_votes - x.votes} 票`) : null))) : null);
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
    h("h3", {}, "每周怎么练"), h("p", { class: "caption" }, `${days}在家、伤病、时间不够时，IronM 会按你的情况换动作。`),
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
      if (xhr.status === 428) { reject(noModelError(body)); return; }
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
      msg.textContent = r.code === 0 ? `已上传 ${n} 个文件，正在识别，结果会出现在「我」里的「我的文件」和「原始记录」里。` : `有的文件没有上传成功：${r.msg || ""}`;
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
// 我（§140、§141）：角色卡、我的目标、设置收成一列（点了在弹出页里打开）；记忆不上页面，设置里一行能看能删
const ABOUT = "IronM 一个人回答训练、饮食、恢复和身体数据的问题，会记得你的情况，按你的数据和状态安排。建议仅供参考，不能代替医生；身体不适请及时就医。";
async function me(view) {
  const [mine, tr] = await Promise.all([profile().catch(() => null), api("/iron/api/training").catch(() => null)]);
  const row = (ic, name, sub, act) => {
    const kids = [h("span", { class: "me-ic" }, icon(ic, "sm")), h("span", { class: "me-name" }, name), sub ? h("small", {}, sub) : null, icon("chevron", "xs")];
    return typeof act === "string" ? h("a", { class: "me-row", href: act }, ...kids) : h("button", { class: "me-row", type: "button", onclick: act }, ...kids);
  };
  const group = (ic, title, ...rows) => h("section", { class: "me-group" }, h("h2", { class: "me-group-h" }, icon(ic, "sm"), title), h("nav", { class: "card me-rows", "aria-label": title }, ...rows));
  const done = (tr?.workouts || []).filter((x) => x.done !== false && !x.rest);
  const mins = done.reduce((a, x) => a + (x.minutes || 0), 0);
  view.append(meHead(mine, [["累计训练", String(done.length), "次"], ["训练总时长", mins >= 60 ? (mins / 60).toFixed(1) : String(mins), mins >= 60 ? "h" : "分钟"]]), goalBlock(),
    group("dumbbell", "训练",
      row("dumbbell", "器材和场所", "排计划、换动作按这个", () => openSheet("器材和场所", gearSection())),
      row("sun", "城市和天气", "", () => openSheet("城市和天气", citySection()))),
    group("file", "数据",
      row("wave", "身体数据", "体重、BMI、体脂率", "#body"),
      row("coach", "IronM 记得的事", "记错了可以删", memorySheet),
      row("upload", "导入健康数据和化验单", "", () => openSheet("导入健康数据和化验单", addGrid())),
      row("note", "我的文件", "", async () => { const box = h("div", {}, h("p", { class: "muted" }, "正在读取…")); openSheet("我的文件", box); box.replaceChildren(await filesSection()); })),
    group("user", "账号与模型",
      row("coach", "模型和 API", "可以用自己的模型", modelSheet),
      row("info", "说明", "", () => openSheet("说明", h("p", { class: "muted" }, ABOUT)))),
    group("file", "账号与隐私",
      row("download", "导出我的数据", "下载成文件", exportSheet),
      row("book", "隐私政策", "", "#privacy"),
      row("note", "用户协议", "", "#terms"),
      row("x", "注销账号", "删掉 IronM 里你的数据", deleteSheet)),
    h("button", { class: "btn danger block", type: "button", onclick: signOut }, icon("logout", "sm"), "退出登录"));
}


// ---- 账号与隐私（spec [2026-10-23] §180）：隐私政策、用户协议、导出我的数据、注销账号 ----
const LEGAL_DATE = "2026-11-06";
const LEGAL = {
  privacy: ["隐私政策", [
    ["这份说明管什么", "IronM（AI 健身助手）怎么收、存、用你的信息。IronM 跑在谁的电脑或服务器上，谁就保管你的数据：在你自己电脑上跑的，数据只在你自己电脑上。"],
    ["收哪些", "账号：邮箱和加密后的密码。档案：身高、出生日期、性别、目标、日常活动。训练：计划、每组记录、打卡和感受。饮食：记的餐、照片、饮食计划。身体数据：体重等读数，你导入的健康数据和化验单。你和 IronM 的对话，以及它记下的事（喜好、伤病、近期安排等）。你填的模型密钥。"],
    ["存在哪、怎么保护", "存在运行 IronM 的那台电脑或服务器的数据库里。对话、记忆、计划等内容加密存放；模型密钥加密存放，页面上只显示末四位；日志只记类别和条数，不记你说的话和具体数值。"],
    ["发给谁", "你问 IronM、拍照估热量、认器械时，内容发给你自己在「模型和 API」里填的模型服务商（如 DeepSeek、通义千问），由它按自己的隐私政策处理。查天气、用当前位置时，只把约 1 公里精度的经纬度发给 Open-Meteo 和 OpenStreetMap。动作和食物配图是从公开网站下载的，不带你的信息。除此之外不给第三方，不卖数据，不做广告。"],
    ["你能做什么", "在「我」里看和改档案、身体数据、IronM 记得的事；在「我 → 账号与隐私」导出你的数据、注销账号。注销后，IronM 里你的训练、饮食、计划、记忆等马上删除，不能恢复；体重等身体读数和其他健康记录、上传的文件、对话记录跟着账号一起关闭，不能再访问。"],
    ["未成年人", "未满 18 岁请在监护人同意下使用。"],
    ["改动", "这一页改了会更新下面的日期。"],
  ]],
  terms: ["用户协议", [
    ["IronM 是什么", "帮你安排训练和饮食、记录和解读身体数据的 AI 助手。"],
    ["不是医疗建议", "IronM 的建议仅供参考，不能代替医生、营养师或康复师。胸痛、头晕、呼吸困难、晕倒等情况请立刻停止并就医；有慢病、孕期、伤病的，开始训练前先问医生。"],
    ["你的账号", "邮箱就是登录名，密码自己保管。没配发信的服务找不回密码，请记好。"],
    ["你填的模型", "IronM 用你自己填的模型回答，费用记在你自己的账户上，请遵守服务商的规定。"],
    ["你发的内容", "排行榜里的评论、投票请真实友善，不发广告、违法或侵犯他人的内容；违规的内容会被删除。"],
    ["开源与免责", "IronM 的代码按 Apache-2.0 开源，按\"原样\"提供，不保证一定适合你的目的；因使用造成的损失，在法律允许的范围内不承担责任。"],
    ["停用", "你可以随时在「我 → 账号与隐私」注销账号；违反本协议的账号可能被停用。"],
  ]],
};
function legalPage(view, kind) {
  const [title, parts] = LEGAL[kind];
  const back = store.get() ? "#me" : "#";
  view.append(h("div", { class: "legal" },
    h("a", { class: "link", href: back }, "‹ 返回"),
    h("h1", {}, title),
    h("p", { class: "legal-draft", role: "note" }, `草稿（${LEGAL_DATE}），正式对外前请负责人审核。`),
    ...parts.flatMap(([hd, text]) => [h("h2", {}, hd), h("p", {}, text)]),
    h("p", { class: "caption" }, `更新日期：${LEGAL_DATE}`)));
}
// 下载要带登录凭证：先取回来再交给浏览器存成文件
async function download(path, name, accept) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${store.get()}`, ...(accept ? { Accept: accept } : {}) } });
  if (!res.ok) throw new Error(`没下载成（${res.status}），稍后再试`);
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function exportSheet() {
  const day = new Date().toISOString().slice(0, 10);
  const msg = h("p", { class: "muted", role: "status" });
  const go = (btn, path, name, accept) => async () => {
    btn.disabled = true; msg.className = "muted"; msg.textContent = "正在准备…";
    try { await download(path, name, accept); msg.textContent = `已下载：${name}`; }
    catch (err) { msg.className = "error"; msg.textContent = err.message; }
    btn.disabled = false;
  };
  const a = h("button", { class: "btn block", type: "button" }, icon("download", "sm"), "下载 IronM 的数据");
  const b = h("button", { class: "btn ghost block", type: "button" }, icon("download", "sm"), "下载健康记录");
  a.onclick = go(a, "/iron/api/export", `ironm-${day}.json`);
  b.onclick = go(b, "/api/user/data-export", `health-${day}.ndjson`, "application/x-ndjson");
  openSheet("导出我的数据", h("div", { class: "sheet-stack" },
    h("p", { class: "muted" }, "IronM 的数据：档案、计划、训练、饮食、目标、IronM 记得的事、器材场所、排行榜里你写的评论和投票，一个 JSON 文件。不含模型密钥、照片和内部运行记录。"),
    a,
    h("p", { class: "muted" }, "健康记录：体重等身体读数、化验、手表、导入的健康数据，另一个文件（每行一条）。"),
    b, msg));
}
function deleteSheet() {
  const email = h("input", { type: "email", autocomplete: "off", placeholder: "输入你的邮箱确认", "aria-label": "输入你的邮箱确认" });
  const msg = h("p", { class: "error", role: "status" });
  const btn = h("button", { class: "btn danger block", type: "button", disabled: true }, "注销账号");
  email.addEventListener("input", () => { btn.disabled = !email.value.includes("@"); });
  btn.addEventListener("click", async () => {
    btn.disabled = true; msg.className = "muted"; msg.textContent = "正在注销…";
    try {
      await api("/iron/api/account/delete", { method: "POST", body: JSON.stringify({ confirm: email.value.trim() }) });
      signOut(); flash(h("span", {}, "账号已注销，IronM 里你的数据已删除。"), 5000);
    } catch (err) { msg.className = "error"; msg.textContent = err.message; btn.disabled = false; }
  });
  openSheet("注销账号", h("div", { class: "sheet-stack" },
    h("p", {}, h("b", {}, "注销后：")),
    h("ul", { class: "muted legal-list" },
      h("li", {}, "马上不能再登录；"),
      h("li", {}, "IronM 里你的训练、饮食、计划、IronM 记得的事等马上删除，不能恢复；"),
      h("li", {}, "体重等身体读数和其他健康记录、上传的文件、对话记录跟着账号一起关闭，不能再访问。")),
    h("p", { class: "muted" }, "想留一份的，先在「导出我的数据」里下载。"),
    email, btn, msg));
}

// 用自己的模型（§153）：选服务商、填密钥、选模型，先测试再保存；密钥只显示末四位
async function modelSheet() {
  const box = h("div", { class: "sheet-stack model-form" }, h("p", { class: "muted" }, "正在读取…"));
  openSheet("模型和 API", box);
  let r;
  try { r = await api("/iron/api/my-model"); } catch (err) { box.replaceChildren(h("p", { class: "error" }, err.message)); return; }
  const cur = r.model, presets = r.presets;
  const opt = (v, label, on) => h("option", { value: v, selected: on }, label);
  const provider = h("select", { "aria-label": "服务商" },
    ...Object.entries(presets).map(([k, p]) => opt(k, p.name, cur?.provider === k)), opt("custom", "自定义（兼容 OpenAI 格式）", cur?.provider === "custom"));
  const url = h("input", { type: "url", placeholder: "接口地址，以 https 开头", value: cur?.provider === "custom" ? cur.base_url : "", "aria-label": "接口地址" });
  const key = h("input", { type: "password", autocomplete: "off", placeholder: cur ? `已保存，末四位 ${cur.key_tail}；不改就留空` : "API 密钥", "aria-label": "API 密钥" });
  const chatModel = h("input", { type: "text", list: "model-chat", value: cur?.chat_model || "", placeholder: "对话用的模型名", "aria-label": "对话模型" });
  const visionModel = h("input", { type: "text", list: "model-vision", value: cur?.vision_model || "", placeholder: "看图用的模型名（不填就用上面那个）", "aria-label": "看图模型" });
  const chatList = h("datalist", { id: "model-chat" }), visionList = h("datalist", { id: "model-vision" });
  const urlRow = h("label", { class: "field" }, h("span", {}, "接口地址"), url);
  const sync = () => {
    const p = presets[provider.value];
    urlRow.hidden = Boolean(p);
    chatList.replaceChildren(...(p?.chat || []).map((m) => h("option", { value: m })));
    visionList.replaceChildren(...(p?.vision || []).map((m) => h("option", { value: m })));
    if (p && !chatModel.value && p.chat[0]) chatModel.value = p.chat[0];
  };
  provider.addEventListener("change", () => { chatModel.value = ""; visionModel.value = ""; sync(); });
  sync();
  const msg = h("div", { class: "muted", role: "status" });
  const body = () => JSON.stringify({ provider: provider.value, base_url: url.value.trim(), api_key: key.value.trim(), chat_model: chatModel.value.trim(), vision_model: visionModel.value.trim() });
  const line = (name, x) => h("div", { class: "kv" }, h("span", {}, name), h("span", { class: x.ok ? "good-text" : "error" }, x.ok ? "可以" : x.why || "不行"));
  const test = h("button", { class: "btn ghost", type: "button", onclick: async () => {
    test.disabled = true; msg.className = "muted"; msg.replaceChildren("正在测试，用你的密钥发几句很短的话…");
    try {
      const x = await api("/iron/api/my-model/test", { method: "POST", body: body() });
      msg.className = ""; msg.replaceChildren(line("能不能通", x.chat), line("能不能调工具", x.tools), line("能不能看图", x.vision));
    } catch (err) { msg.className = "error"; msg.replaceChildren(err.message); }
    test.disabled = false;
  } }, "测试连接");
  const save = h("button", { class: "btn", type: "button", onclick: async () => {
    save.disabled = true;
    try { await api("/iron/api/my-model", { method: "PUT", body: body() }); msg.className = "muted"; msg.replaceChildren("已保存：以后用你自己的模型，费用记在你的账户上。"); key.value = ""; document.querySelector(".model-card")?.remove(); }
    catch (err) { msg.className = "error"; msg.replaceChildren(err.message); }
    save.disabled = false;
  } }, icon("check", "sm"), "保存");
  const drop = cur ? h("button", { class: "link danger-link", type: "button", onclick: async () => {
    try { await api("/iron/api/my-model", { method: "DELETE" }); closeSheet(); flash("已删除。要用问答、估热量这些功能，得再填一个模型。"); } catch (err) { msg.className = "error"; msg.replaceChildren(err.message); }
  } }, "删除这个模型") : null;
  box.replaceChildren(
    h("p", { class: "muted" }, cur ? `现在用的是你自己的模型：${presets[cur.provider]?.name || "自定义"} · ${cur.chat_model}` : "还没填模型。IronM 用你自己的模型回答问题、估热量、认器械、每天看你的情况，费用记在你的账户上；记训练、看计划不用填也能用。"),
    h("label", { class: "field" }, h("span", {}, "服务商"), provider), urlRow,
    h("label", { class: "field" }, h("span", {}, "API 密钥"), key),
    h("label", { class: "field" }, h("span", {}, "对话模型"), chatModel, chatList),
    h("label", { class: "field" }, h("span", {}, "看图模型"), visionModel, visionList),
    h("div", { class: "btn-row" }, test, save), msg, drop,
    h("p", { class: "caption" }, "密钥加密存在服务器上，只显示末四位。对话要能调工具的模型；拍照识别要能看图的模型。你的模型出错时会如实告诉你，不会换成别的模型。"));
}

// 搭子记得的事（§121 需求 8）：列出来，不对的删掉（删前当页再点一次确认）
async function memorySheet() {
  const box = h("div", { class: "mem-list" }, skeleton(60, 60));
  openSheet("IronM 记得的事", box);
  let r;
  try { r = await api("/iron/api/memory"); } catch (err) { box.replaceChildren(failed(err, memorySheet)); return; }
  const live = r.items.filter((x) => x.status === "active" && !x.expired);
  if (!live.length) { box.replaceChildren(h("p", { class: "muted" }, "还没记下什么。聊天里说过的伤病、器材、作息、口味，IronM 会记在这里。")); return; }
  const groups = Object.entries(r.categories).map(([k, name]) => [name, live.filter((x) => x.category === k)]).filter(([, xs]) => xs.length);
  box.replaceChildren(...groups.map(([name, xs]) => h("div", { class: "mem-group" }, h("span", { class: "label" }, name),
    xs.map((x) => {
      const row = h("div", { class: "mem-row" }, h("p", {}, x.content));
      row.append(twoStep("删掉", "确定删掉", async () => {
        try { await api(`/iron/api/memory/${encodeURIComponent(x.id)}`, { method: "DELETE" }); row.replaceWith(h("p", { class: "caption" }, "删掉了。")); }
        catch (err) { flash(err.message); }
      }, "link mem-del"));
      return row;
    }))));
}

// 头部：头像、账号，一行个人信息摘要；点"编辑"就地展开档案表单
function meHead(data, stats = []) {
  const email = tokenEmail();
  const box = h("div", { class: "me-sum" });
  const edit = h("button", { class: "link", type: "button", hidden: !data }, icon("edit", "xs"), "编辑");
  edit.addEventListener("click", () => { edit.hidden = true; profileForm(box, data, () => { edit.hidden = false; }, summary); });
  if (data) summary(box, data); else box.append(h("p", { class: "muted" }, "档案暂时读不到，稍后再试。"));
  return h("div", { class: "card me-head" },
    h("div", { class: "profile-head" },
      h("span", { class: "avatar" }, (email[0] || "我").toUpperCase()),
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, email || "已登录"), h("span", { class: "tag green" }, mech(16), "IronM 陪你练")),
      edit),
    stats.length ? h("div", { class: "me-stats" }, stats.map(([k, v, u]) => h("div", {}, h("span", {}, k), h("b", {}, v, h("small", {}, u))))) : null,
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
  // 用当前位置（spec [2026-10-23] §173）：只在他点了才取，经纬度留两位小数（约 1 公里）交给服务端认城市
  const locate = (place, msg) => {
    if (!navigator.geolocation) { msg.textContent = "这个浏览器不能定位，手填城市就行"; return; }
    msg.textContent = "正在定位…";
    navigator.geolocation.getCurrentPosition(async (pos) => {
      const spot = { lat: Number(pos.coords.latitude.toFixed(2)), lon: Number(pos.coords.longitude.toFixed(2)) };
      try { draw(await api("/iron/api/place/locate", { method: "POST", body: JSON.stringify(spot) })); }
      catch (err) { msg.textContent = err.message; }
    }, (err) => {
      msg.textContent = err && err.code === 1 ? "没有同意定位，可以手填城市" : "这次没取到位置，可以手填城市";
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 });
  };
  const draw = (place) => {
    const msg = h("div", { class: "error" });
    box.replaceChildren(h("div", { class: "kv" }, h("span", {}, "城市"),
      h("span", {}, place.label || place.city || "未设置", " ", h("button", { class: "link", type: "button", onclick: () => edit(place) }, icon("edit", "xs"), place.city ? "修改" : "设置"),
        " ", h("button", { class: "link", type: "button", onclick: () => locate(place, msg) }, "用当前位置"))), msg);
  };
  const edit = (place) => {
    const input = h("input", { type: "text", maxlength: "30", value: place.city || "", placeholder: "比如：杭州、北京朝阳" });
    const msg = h("div", { class: "error" });
    const form = h("form", {}, h("label", {}, "所在城市", input), msg,
      h("div", { class: "form-actions" },
        h("button", { class: "btn ghost", type: "button", onclick: () => draw(place) }, "取消"),
        h("button", { class: "btn ghost", type: "button", onclick: () => locate(place, msg) }, "用当前位置"),
        h("button", { class: "btn", type: "submit" }, "保存")));
    form.addEventListener("submit", async (e) => {
      e.preventDefault(); msg.textContent = "正在查找…";
      try { draw(await api("/iron/api/place", { method: "PUT", body: JSON.stringify({ city: input.value.trim() }) })); }
      catch (err) { msg.textContent = err.message; }
    });
    box.replaceChildren(form); input.focus();
  };
  api("/iron/api/place").then(draw).catch(() => draw({}));
  return section("天气", null, box, h("p", { class: "caption", style: "padding:0 2px" }, "按城市取实时天气和空气质量，首页和 IronM 安排训练、饮食时会用上；问 IronM 天气也按这里。用当前位置只在你点了才取，只留到约 1 公里。"));
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
  const uploads = [];
  for (const f of picked) {
    if (!CHAT_EXT.includes(extOf(f.name))) { chat.files.push({ name: f.name, error: "只能附图片或 PDF" }); continue; }
    if (f.size > 20 * MB) { chat.files.push({ name: f.name, error: "超过 20MB" }); continue; }
    const item = { name: f.name, progress: 0, data: null, error: "" };
    chat.files.push(item);
    const form = new FormData(); form.append("files", f);
    uploads.push(send("/files/upload", form, (x) => { item.progress = x; drawFiles(); })
      .then((body) => { const d = (body.data || [])[0]; if (d?.file_key) item.data = d; else item.error = body.msg || "上传失败"; })
      .catch((err) => { item.error = err.message; })
      .finally(() => { drawFiles(); syncComposer(); }));
  }
  drawFiles(); syncComposer();
  return Promise.all(uploads);
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
  ["深蹲时膝盖疼怎么办", "训练和恢复"],
  ["早餐怎么吃够蛋白质", "饮食"],
  ["我最近的静息心率正常吗", "身体数据"],
];

function chatPage(view) {
  const thread = h("div", { class: "thread" });
  const input = h("textarea", { rows: "1", placeholder: "问点什么，或拍一张…", "aria-label": "输入问题", enterkeyhint: "send" });
  const send = h("button", { class: "send", type: "submit", "aria-label": "发送" }, icon("send"));
  const fileInput = h("input", { type: "file", accept: CHAT_EXT.join(","), multiple: true, class: "sr-only", onchange: (e) => attachPick(e.currentTarget) });
  const clip = h("label", { class: "clip", "aria-label": "附图片或报告", title: "附图片或报告" }, fileInput, icon("plus", "sm"));
  const files = h("div", { class: "attach-row", hidden: true });
  // 拍一张（§152）：吃的、器械都行，IronM 看图自己判断；传好就发，没写字时问"帮我看看这个"
  const camInput = h("input", { type: "file", accept: "image/jpeg,image/png,image/webp", capture: "environment", class: "sr-only", onchange: async (e) => {
    await attachPick(e.currentTarget);
    if (chat.files.some((f) => f.data) && !chat.busy) form.requestSubmit();
  } });
  const cam = h("label", { class: "clip", "aria-label": "拍一张：吃的、器械都能认", title: "拍一张：吃的、器械都能认" }, camInput, icon("camera", "sm"));
  const form = h("form", { class: "composer" }, clip, cam, input, send);
  const fresh = h("button", { class: "icon-btn", type: "button", "aria-label": "新对话", title: "新对话", onclick: () => { resetChat(); chat.loaded = true; drawThread(); input.focus(); } }, icon("plus", "sm"));
  const past = h("button", { class: "icon-btn", type: "button", "aria-label": "以前的对话", title: "以前的对话", onclick: historySheet }, icon("history", "sm"));
  const facts = h("div", { class: "who-facts" });
  view.append(h("div", { class: "chat" },
    h("div", { class: "chat-bar buddy-card" },
      mech(40),
      h("div", { class: "who" }, h("b", {}, "IronM"), h("span", {}, "陪你练、帮你记"), facts),
      h("div", { class: "chat-tools" }, past, fresh)),
    thread, files, form));
  buddyFacts(facts);
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
    const inbox = Promise.all([loadInbox(), loadWeekMsg()]);
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

// 对话页顶上的企鹅卡（§175，照参照图的伴练卡，只放我们有的数）：这周练了几次、连续打卡几天、最近一次破纪录
async function buddyFacts(box) {
  const [brief, cal, tr] = await Promise.all([api("/iron/api/brief").catch(() => null), api("/iron/api/calendar").catch(() => null), api("/iron/api/training").catch(() => null)]);
  const w = brief?.week, pr = prWall(tr?.workouts || []).find((x) => x.broke);
  box.replaceChildren(...[
    w?.planned ? h("span", { class: "tag green" }, `这周 ${w.done}/${w.planned} 次`) : null,
    cal?.streak_days ? h("span", { class: "tag coral" }, `连续打卡 ${cal.streak_days} 天`) : null,
    pr ? h("span", { class: "tag" }, `${pr.name}破纪录 ${pr.best.weight_kg} kg`) : null].filter(Boolean));
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
    h("div", { class: "inbox-head" }, icon("coach", "sm"), h("b", {}, "IronM"), h("span", { class: "muted" }, "按你最新的数据调整了方案")),
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
      mech(74),
      h("div", {}, h("h2", {}, "想问点什么？"), h("p", { class: "muted" }, "练什么、吃什么、哪里不舒服，直接说就行。")),
      h("div", { class: "starters" }, STARTERS.map(([q, who]) => h("button", { class: "starter", type: "button", onclick: () => ask(q) }, q, h("span", {}, who))))));
  } else {
    thread.replaceChildren(...chat.messages.map((msg) => (msg.el = msgView(msg))));
  }
  if (coachInbox?.view) thread.append(coachInbox.view);
  if (weekMsg) thread.append(weekMsgView(weekMsg));  // IronM 发上周的周报（§147）
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
  // 只有一个搭子（§121）：过程里只说搭子在做什么，不再按专业角色计数
  let head;
  if (running) head = msg.text ? "正在整理回答…" : msg.steps.length ? "IronM 正在查资料和数据…" : "正在理解你的问题…";
  else head = msg.steps.length ? "IronM 是怎么答的" : "";
  const showList = msg.open || (running && !msg.text);
  const prog = msg.steps.length || running ? h("div", { class: "prog" },
    h("button", { class: "prog-head", type: "button", "aria-expanded": String(showList), onclick: () => { msg.open = !showList; refresh(msg); } },
      running ? h("span", { class: "spin" }) : h("span", { class: "ok-dot" }, icon("check")), head,
      !running && msg.steps.length ? h("span", { style: "color:var(--accent)" }, showList ? " · 收起" : " · 查看过程") : null),
    showList && msg.steps.length ? h("ol", { class: "prog-list" }, msg.steps.map((x) => h("li", {},
      h("span", { class: "who" }, x.done ? h("span", { class: "ok-dot" }, icon("check")) : h("span", { class: "spin" }), x.id === "agent" ? "IronM" : x.name),
      x.task ? h("span", { class: "what" }, x.task) : null,
      x.done && x.result && !running ? h("div", { class: "res" }, x.result) : null))) : null) : null;
  return h("div", { class: "msg-row" }, mech(34), h("div", { class: "msg-coach" },
    prog,
    msg.text ? h("div", { class: "answer" }, paragraphs(msg.text)) : running ? h("div", { class: "typing", "aria-label": "正在回答" }, h("i"), h("i"), h("i")) : null,
    // 没填自己的模型时服务端回这一句（§167）：下面给"去填模型"
    msg.done && (msg.text || "").startsWith(NO_MODEL.slice(0, 22)) ? h("button", { class: "btn small", type: "button", onclick: () => modelSheet() }, "去填模型") : null,
    msg.notices.map((t) => h("div", { class: "msg-note" }, t)),
    msg.cards.map((c) => cardView(msg, c)),
    msg.error ? h("div", { class: "msg-note" }, msg.error) : null,
    msg.sources ? h("details", { class: "sources", open: msg.srcOpen, ontoggle: (e) => { msg.srcOpen = e.currentTarget.open; } },
      h("summary", {}, icon("chevron", "xs"), "依据与来源"), h("div", { class: "src" }, msg.sources)) : null,
    msg.done && msg.id && msg.text ? h("div", { class: "rate" },
      h("button", { type: "button", class: msg.rating === 1 ? "on" : "", onclick: () => rate(msg, 1) }, icon("up", "xs"), "有用"),
      h("button", { type: "button", class: msg.rating === -1 ? "on" : "", onclick: () => rate(msg, -1) }, icon("down", "xs"), "没用")) : null,
    msg.done ? at : null));
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

// 预览卡片（计划、训练记录、临时调整）：确认才写入，写入后能撤销；状态从服务端取（刷新后也对）
const CARD_STATE = { pending: "", confirmed: "已保存", cancelled: "已取消", undone: "已撤销" };
function cardView(msg, card) {
  const d = card.data;
  if (!d) return null;
  if (!card.state && !card.busy) { card.busy = true; loadCard(msg, card); }
  const state = card.state || "pending";
  const expired = state === "pending" && Date.parse(d.expires) < Date.now();
  const plan = card.kind === "plan", temp = card.kind === "temp";  // temp：临时调整（§163），到期回到原计划
  const body = temp
    ? [(d.items || []).length ? h("ul", { class: "temp-lines" }, d.items.map((it) => h("li", {}, it))) : null,
      state === "pending" && !expired ? h("p", { class: "caption" }, `${TEMP_RULE}没确认的过了开始日期就作废。`)
        : state === "confirmed" ? h("p", { class: "caption" }, "到了结束日期自动回到原计划，也可以提前撤销。") : null]
    : plan && d.rows
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
    ? [h("button", { class: "btn small", type: "button", disabled: card.busy, onclick: () => act("confirm") }, plan ? "确认，保存计划" : temp ? "确认，这几天这样练" : "确认，记下"),
      h("button", { class: "btn quiet small", type: "button", disabled: card.busy, onclick: () => act("cancel") }, "取消")]
    : state === "confirmed"
      ? [h("span", { class: "chip good" }, plan ? "计划已保存" : temp ? "已生效，到期回到原计划" : "已记下"), h("button", { class: "btn quiet small", type: "button", disabled: card.busy, onclick: () => act("undo") }, "撤销")]
      : [h("span", { class: "chip" }, expired ? (temp ? "已作废：过了开始日期还没确认" : "已过期，让教练重新生成") : temp && state === "undone" ? "已撤销，回到原计划" : CARD_STATE[state] || state)];
  return h("div", { class: `preview ${state}` },
    h("div", { class: "pv-title" }, icon(plan ? "dumbbell" : temp ? "timer" : "check", "sm"), h("b", {}, d.title), h("span", { class: "muted" }, d.headline || "")),
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
// 注册和登录（§155）：邮箱验证码注册、设密码；平时用密码登录，也能用验证码登录；忘记密码用验证码重设。
// 底座回的是英文和错误码，这里按错误码换成中文
const AUTH_ERRORS = {
  "/password/register": { "-2": "邮箱格式不对", "-3": "密码至少 8 位", "-5": "先填邮箱收到的验证码", "-6": "验证码不对或已过期", "-4": "这个邮箱已经注册过，直接登录" },
  "/password/login": { "-2": "填一下邮箱和密码", "-3": "邮箱或密码不对" },
  "/password/reset": { "-2": "填一下邮箱和验证码", "-3": "密码至少 8 位", "-6": "验证码不对或已过期", "-7": "邮件服务还没配好，暂时不能找回密码" },
  "/email/verify": {},
};
// 验证码没通过时服务端写了原因（不对 / 过期 / 试错太多次）：如实说，不笼统写"不对或已过期"
function codeReason(msg) {
  if (/expired/i.test(msg)) return "验证码过期了（10 分钟内有效），重新获取一个";
  if (/too many/i.test(msg)) return "这个验证码试错太多次已经作废，重新获取一个";
  if (/code/i.test(msg)) return "验证码不对：用最新一封邮件里的 6 位数字（重新获取后，旧的就不能用了）";
  return "";
}
async function authCall(path, body) {
  let r;
  try { r = await api(path, { method: "POST", body: JSON.stringify(body) }); } catch (err) { throw new Error(err.message); }
  if (r?.code !== undefined && r.code !== 0) {
    const msg = String(r.msg || "");
    throw new Error((r.code === -6 || path === "/email/verify" ? codeReason(msg) : "") || AUTH_ERRORS[path]?.[String(r.code)] || (/SMTP|mail/i.test(msg) ? "邮件服务还没配好，暂时发不了验证码" : path === "/email/verify" ? "验证码不对或已过期" : "没有成功，稍后再试"));
  }
  return r;
}
function loginView(view) {
  let mode = "login", mail = null;  // login 密码登录 / code 验证码登录 / register 注册 / reset 忘记密码
  const msg = h("div", { class: "error", role: "status" });
  const email = h("input", { name: "email", type: "email", placeholder: "邮箱", autocomplete: "email" });
  const password = h("input", { name: "password", type: "password", placeholder: "密码", autocomplete: "current-password" });
  const again = h("input", { name: "again", type: "password", placeholder: "再输一遍密码", autocomplete: "new-password" });
  const code = h("input", { name: "code", inputmode: "numeric", placeholder: "验证码", autocomplete: "one-time-code", maxlength: "8" });
  const sendCode = h("button", { type: "button", class: "btn ghost" }, "获取验证码");
  let wait = 0;
  sendCode.addEventListener("click", async () => {
    msg.className = "error"; msg.textContent = "";
    if (!email.value.includes("@")) { msg.textContent = "先填邮箱"; return; }
    sendCode.disabled = true; sendCode.textContent = "发送中…";  // 发信要十几秒：先变灰、说一声，免得连点（每点一次发一封，新码让旧码作废）
    msg.className = "muted"; msg.textContent = "正在发送验证码，一般十几秒内到。";
    try {
      const r = await api("/email/login", { method: "POST", body: JSON.stringify({ email: email.value.trim() }) });
      if (r?.code !== undefined && r.code !== 0) throw new Error(/SMTP|mail/i.test(String(r.msg)) ? "邮件服务还没配好，暂时发不了验证码" : "验证码没发出去，稍后再试");
      msg.className = "muted"; msg.textContent = "验证码已发到邮箱，10 分钟内有效；收到几封时以最新一封为准。";
      wait = 60;
      const tick = () => { sendCode.textContent = wait > 0 ? `${wait} 秒后重发` : "获取验证码"; sendCode.disabled = wait > 0; if (wait-- > 0) setTimeout(tick, 1000); };
      tick();
    } catch (err) { msg.className = "error"; msg.textContent = err.message; sendCode.disabled = false; sendCode.textContent = "获取验证码"; }
  });
  const submit = h("button", { class: "btn block", type: "submit" }, "登录");
  const tabs = h("div", { class: "seg login-seg", role: "tablist" });
  const links = h("div", { class: "login-links" });
  const form = h("form", { class: "card login-form" });
  const codeRow = h("div", { class: "row" }, code, sendCode);
  const draw = () => {
    msg.className = "error"; msg.textContent = "";
    const tab = (k, label) => h("button", { type: "button", role: "tab", class: (mode === k || (k === "login" && mode === "code")) ? "on" : "", "aria-selected": String(mode === k), onclick: () => { mode = k; draw(); } }, label);
    tabs.replaceChildren(tab("login", "登录"), tab("register", "注册"));
    // 没配发信（§174）：注册只要邮箱和密码、不要验证码；验证码登录和找回密码先不给
    if (mail === false && (mode === "code" || mode === "reset")) mode = "login";
    const withCode = mode === "code" || mode === "reset" || (mode === "register" && mail !== false);
    password.placeholder = mode === "reset" ? "新密码（至少 8 位）" : mode === "register" ? "设密码（至少 8 位）" : "密码";
    password.autocomplete = mode === "login" ? "current-password" : "new-password";
    submit.textContent = { login: "登录", code: "登录", register: "注册", reset: "改好并登录" }[mode];
    form.replaceChildren(email,
      mode === "login" ? password : null,
      withCode ? codeRow : null,
      mode === "register" || mode === "reset" ? password : null,
      mode === "register" || mode === "reset" ? again : null,
      mode === "register" && mail === false ? h("p", { class: "muted" }, "现在不发验证码，邮箱就是登录名；暂时不能找回密码，请记好密码。") : null,
      submit, msg,
      mode === "register" ? h("p", { class: "caption legal-line" }, "注册即表示你同意", h("a", { href: "#terms" }, "《用户协议》"), "和", h("a", { href: "#privacy" }, "《隐私政策》")) : null);
    submit.disabled = false;
    links.replaceChildren(
      mode === "login" && mail !== false ? h("button", { type: "button", class: "link", onclick: () => { mode = "code"; draw(); } }, "用验证码登录") : null,
      mode === "code" ? h("button", { type: "button", class: "link", onclick: () => { mode = "login"; draw(); } }, "用密码登录") : null,
      (mode === "login" || mode === "code") && mail !== false ? h("button", { type: "button", class: "link", onclick: () => { mode = "reset"; draw(); } }, "忘记密码") : null,
      mode === "reset" ? h("button", { type: "button", class: "link", onclick: () => { mode = "login"; draw(); } }, "想起来了，去登录") : null);
  };
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); msg.className = "error"; msg.textContent = "";
    const mail_ = email.value.trim();
    if (!mail_.includes("@")) { msg.textContent = "邮箱格式不对"; return; }
    if ((mode === "register" || mode === "reset") && password.value.length < 8) { msg.textContent = "密码至少 8 位"; return; }
    if ((mode === "register" || mode === "reset") && password.value !== again.value) { msg.textContent = "两次输的密码不一样"; return; }
    submit.disabled = true;
    try {
      const r = mode === "login" ? await authCall("/password/login", { email: mail_, password: password.value })
        : mode === "code" ? await authCall("/email/verify", { email: mail_, code: code.value.trim() })
          : await authCall(mode === "register" ? "/password/register" : "/password/reset",
            { email: mail_, password: password.value, ...(mode === "register" && mail === false ? {} : { code: code.value.trim() }) });
      const token = r?.data?.access_token;
      if (!token) throw new Error("没有成功，稍后再试");
      store.set(token);
      if (mode === "register") location.hash = "#welcome";  // 新注册的先完善资料（§174 需求 4）
      render();
    } catch (err) { msg.textContent = err.message; await new Promise((ok) => setTimeout(ok, 1500)); }  // 没成功先停一下：连点会把验证码的 5 次机会用完
    submit.disabled = false;
  });
  draw();
  api("/iron/api/auth/options").then((r) => { mail = Boolean(r.mail); draw(); }).catch(() => {});
  view.append(h("div", { class: "login" },
    h("div", {}, h("div", { class: "wordmark" }, "Iron", h("b", {}, "M")), h("p", { class: "lede", style: "margin-top:10px" }, "AI 健身助手：训练、饮食、恢复和身体数据，按你的情况安排。")),
    tabs, form, links));
}

// ---- 注册后完善资料（§174 需求 4）：身高、出生日期、体重必填，性别、目标、日常活动建议填；存好再提示填模型 ----
async function welcomePage(view) {
  const box = h("div", { class: "card login-form welcome-form" }, h("p", { class: "muted" }, "正在读取…"));
  view.append(h("div", { class: "login" },
    h("div", {}, h("div", { class: "wordmark" }, "Iron", h("b", {}, "M")),
      h("p", { class: "lede", style: "margin-top:10px" }, "先填几样，IronM 才能按你的情况算热量、排训练。")),
    box));
  let data;
  try { data = await profile(true); } catch (err) { box.replaceChildren(h("p", { class: "error" }, err.message)); return; }
  const p = data.profile, today = new Date().toISOString().slice(0, 10);
  const opts = (map, value) => [h("option", { value: "" }, "请选择"), ...Object.entries(map).map(([k, v]) => h("option", { value: k, selected: k === value }, v))];
  const msg = h("div", { class: "error", role: "status" });
  const req = (text) => h("span", {}, text, h("b", { class: "req", "aria-hidden": "true" }, " *"));
  const form = h("form", {},
    h("label", {}, req("身高（厘米）"), h("input", { name: "height_cm", type: "number", inputmode: "decimal", step: "0.1", min: "100", max: "250", required: true, value: p.height_cm ?? "" })),
    h("label", {}, req("出生日期"), h("input", { name: "birth", type: "date", max: today, required: true, value: p.birth ?? "" })),
    h("label", {}, req("体重（公斤）"), h("input", { name: "weight", type: "number", inputmode: "decimal", step: "0.1", min: "20", max: "300", required: true })),
    h("label", {}, "性别", h("select", { name: "sex" }, opts(SEX, p.sex))),
    h("label", {}, "目标", h("select", { name: "goal" }, opts(data.options.goal, p.goal))),
    h("label", {}, "日常活动", h("select", { name: "activity" }, opts(data.options.activity, p.activity))),
    h("p", { class: "caption" }, "带 * 的要填；其余建议填，算每天该吃多少会更准。以后都能在「我」里改。"),
    msg, h("button", { class: "btn block", type: "submit" }, "保存"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault(); msg.className = "error"; msg.textContent = "";
    const f = Object.fromEntries(new FormData(form));
    const height = Number(f.height_cm), weight = Number(f.weight);
    if (!(height >= 100 && height <= 250)) { msg.textContent = "身高填 100–250 厘米之间"; return; }
    if (!f.birth || f.birth > today) { msg.textContent = f.birth ? "出生日期不能晚于今天" : "填一下出生日期"; return; }
    if (!(weight >= 20 && weight <= 300)) { msg.textContent = "体重填 20–300 公斤之间"; return; }
    const body = { height_cm: height, birth: f.birth };
    for (const k of ["sex", "goal", "activity"]) if (f[k]) body[k] = f[k];
    msg.className = "muted"; msg.textContent = "保存中…";
    try {
      await api("/iron/api/profile", { method: "PUT", body: JSON.stringify(body) });
      await api("/iron/api/readings", { method: "POST", body: JSON.stringify({ kind: "weight", value: weight }) });
      cache.metrics = null;
    } catch (err) { msg.className = "error"; msg.textContent = err.message; return; }
    box.replaceChildren(
      h("p", {}, h("b", {}, "资料存好了。")),
      h("p", { class: "muted" }, "再填一个自己的模型（DeepSeek、通义千问、智谱等都可以）就能问 IronM、拍照估热量；记训练、看计划不填也能用。"),
      h("button", { class: "btn block", type: "button", onclick: () => modelSheet() }, "去填模型"),
      h("button", { class: "link", type: "button", onclick: () => { location.hash = "#home"; } }, "以后再说，先进首页"));
  });
  box.replaceChildren(form);
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

// 训练中自己填的数（§178）：重量 0–500、最多一位小数，次数 0–100 的整数；空的、不是数、超范围的返回 null（不改原来的值）
function typedNum(text, { min = 0, max, dec = false }) {
  const t = String(text ?? "").trim().replace(/[，。]/g, ".").replace(/[０-９]/g, (c) => String.fromCharCode(c.charCodeAt(0) - 0xfee0));
  if (!/^\d+(\.\d+)?$/.test(t)) return null;
  const v = dec ? Math.round(Number(t) * 10) / 10 : Math.round(Number(t));
  return v >= min && v <= max ? v : null;
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
  const [lib, tr] = await Promise.all([exercises().catch(() => null), api("/iron/api/training").catch(() => null)]);
  const bestKg = Object.fromEntries(prWall(tr?.workouts || []).map((x) => [x.name, x.best.weight_kg]));  // 最近 30 天最好的一组的重量（§175 照参照图）
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
  // 有氧（§130）：页面填分钟，存秒
  const minutes = (s, j) => {
    const el = h("input", { type: "number", class: "live-in", value: s.seconds ? String(Math.round(s.seconds / 60)) : "", inputmode: "numeric", min: "1", max: "600", placeholder: "分钟", "aria-label": `第 ${j + 1} 段分钟数` });
    el.addEventListener("input", () => { const m = num(el.value); s.seconds = m ? Math.round(m * 60) : null; save(); });
    return el;
  };
  const setVal = (i, j, key, v) => {
    const s = L.items[i].sets[j], prev = s[key];
    s[key] = v;
    if (key === "weight_kg") checkKg(i, j, prev);
    save(); draw();
  };
  const bump = (i, j, key, d) => setVal(i, j, key, Math.max(0, Math.round(((L.items[i].sets[j][key] || 0) + d) * 100) / 100));
  const markDone = (i, j) => {
    const it = L.items[i], s = it.sets[j];
    if (s.done) { s.done = false; s.at = null; save(true); draw(); return; }
    const timingThis = timing && timing.i === i && timing.j === j;
    if (it.timed ? !(s.seconds > 0) && !timingThis : !(s.reps > 0)) {  // 空的一组不能打勾（§104 需求 1）
      warn = { i, text: it.cardio ? "先填做了多少分钟，或点计时。" : it.timed ? "先填秒数，或点计时。" : "先填这一组做了几次（和重量），再打勾。" };
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
    const inputs = it.cardio
      ? [minutes(s, j), h("span", { class: "unit" }, "分钟")]
      : it.timed
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
  // 中间的大数字点一下就能自己填（§178）：回车或点别处存，填得不对就还原
  const bigNum = (label, value, hot, range, onSet) => {
    const el = h("input", { type: "text", inputmode: range.dec ? "decimal" : "numeric", enterkeyhint: "done", autocomplete: "off",
      class: `step-in num${hot ? " hot" : ""}`, value: value == null ? "" : String(value), placeholder: "–", "aria-label": `${label}，点一下直接填` });
    el.addEventListener("focus", () => el.select());
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.blur(); });
    el.addEventListener("change", () => {
      const v = typedNum(el.value, range);
      if (v == null || v === value) { el.value = value == null ? "" : String(value); return; }
      onSet(v);
    });
    return el;
  };
  // 当前这一组（§104 需求 6）：动作图、一句要点、− / + 一档、一个大按钮
  const stepper = (label, value, unit, onDown, onUp, hot, pill = null, edit = null) => h("div", { class: "stepper" },
    h("div", { class: "step-label" }, h("span", {}, label), pill),
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}减`, onclick: onDown }, "−"),
    h("span", { class: "step-val" }, edit ? bigNum(label, value, hot, edit.range, edit.set) : h("b", { class: `num${hot ? " hot" : ""}` }, value == null ? "–" : String(value)), h("small", {}, unit)),
    h("button", { class: "step-btn", type: "button", "aria-label": `${label}加`, onclick: onUp }, "+"));
  const focus = (it, i) => {
    const here = curPos();
    if (!here || here.i !== i) return null;
    const j = here.j, s = it.sets[j], move = lib?.exercises?.find((x) => x.name === it.exercise);
    const hot = s.weight_kg != null && it.plan_kg != null && s.weight_kg > it.plan_kg;
    // 次数旁的小标签：服务端给的是"目标 …""上次 …"或"计划 N 组 × 次数"（live.py），计划的只取次数
    const plan = /^计划/.test(it.target || "") ? String(it.target).match(/×\s*([^，,、）)]+)/)?.[1] : null;
    const target = plan ? `目标 ${plan}${/\d$/.test(plan) ? " 次" : ""}` : it.target || "";
    return h("div", { class: "live-focus" },
      h("span", { class: "tag coral lf-now" }, icon("timer", "xs"), `进行中 · 第 ${j + 1}/${it.sets.length} 组`),
      h("div", { class: "lf-top" }, thumb(lib, it.exercise, "lf-img"),
        h("div", { class: "row-main" }, move?.cues?.[0] ? h("span", { class: "lf-cue" }, icon("info", "xs"), move.cues[0]) : null)),
      it.timed ? null : h("div", { class: "lf-steps" },
        stepper("重量", s.weight_kg, "公斤", () => bump(i, j, "weight_kg", -stepOf(it)), () => bump(i, j, "weight_kg", stepOf(it)), hot,
          bestKg[it.exercise] ? h("span", { class: "tag green" }, `最近最佳 ${bestKg[it.exercise]} kg`) : null,
          { range: { max: 500, dec: true }, set: (v) => setVal(i, j, "weight_kg", v) }),
        stepper("次数", s.reps, "次", () => bump(i, j, "reps", -1), () => bump(i, j, "reps", 1), false,
          target ? h("span", { class: "tag" }, target) : null,
          { range: { max: 100 }, set: (v) => setVal(i, j, "reps", v) })),
      warn && warn.i === i ? h("div", { class: "lf-warn", role: "status" }, h("span", {}, warn.text),
        warn.back != null ? h("button", { class: "btn small warn-ok", type: "button", onclick: () => { okKg[i] = warn.w; warn = null; draw(); } }, "确定") : null,
        warn.back != null ? h("button", { class: "link warn-back", type: "button", onclick: () => { s.weight_kg = warn.back; warn = null; save(); draw(); } }, `改回 ${warn.back}`) : null) : null,
      h("button", { class: "btn block lf-done", type: "button", onclick: () => markDone(i, j) }, icon("check", "sm"), `完成第 ${j + 1} 组`));
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
    it.timed ? h("p", { class: "caption" }, it.cardio ? "有氧：填做了多少分钟，或点开始计时" : "计时动作：填秒数，或点计时") : null,
    it.timed ? h("div", { class: "live-timed" }, h("button", { class: `btn small${timing && timing.i === i ? "" : " ghost"}`, type: "button", onclick: () => { const j = it.sets.findIndex((s) => !s.done); if (j >= 0) (timing && timing.i === i ? markDone(i, timing.j) : toggleTiming(i, j)); } }, icon("timer", "sm"), timing && timing.i === i ? "停，记下这组" : "开始计时")) : null,
    h("div", { class: "set-list" }, it.sets.map((s, j) => row(it, i, s, j))),
    h("button", { class: "link", type: "button", onclick: () => addSet(i) }, icon("plus", "xs"), it.cardio ? "再加一段" : "加一组"));
  const draw = () => {
    const all = L.items.reduce((a, it) => a + it.sets.length, 0), done = L.items.reduce((a, it) => a + it.sets.filter((s) => s.done).length, 0);
    prog.hidden = !all;
    const at = curPos(), pct = all ? Math.round((done / all) * 100) : 0;
    prog.replaceChildren(h("div", { class: "lp-head" }, h("span", {}, `总进度：第 ${at ? at.i + 1 : L.items.length}/${L.items.length} 个动作`), h("b", {}, `已做 ${done}/${all} 组（${pct}%）`)),
      h("div", { class: "thin-bar" }, h("span", { style: `width:${pct}%` })));
    list.replaceChildren(...(L.items.length ? L.items.map(card) : [h("div", { class: "card live-none" }, h("p", { class: "muted" }, L.session ? "今天的计划里没有动作。" : "还没有动作，点下面的「加动作」。"))]));
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
      restBar.replaceChildren(h("div", { class: "lr-head" }, h("span", {}, h("i", { class: "dot green" }), "组间休息中"), h("b", {}, clock(left), h("small", {}, ` / ${clock(it.rest)}`))),
        h("div", { class: "lr-bar" }, h("b", { style: `width:${Math.max(0, Math.min(100, Math.round((1 - left / it.rest) * 100)))}%` })),
        h("div", { class: "live-rest-btns" },
          h("button", { class: "btn ghost small", type: "button", onclick: () => adj(-15) }, "−15 秒"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => adj(15) }, "+15 秒"),
          h("button", { class: "btn ghost small", type: "button", onclick: () => { rest = null; restBar.hidden = true; } }, "跳过休息")));
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
            r.workout?.id ? h("button", { class: "btn block", type: "button", onclick: () => shareSheet(r.workout.id) }, "晒一下") : null,  // §147
            h("a", { class: "btn ghost block", href: "#home", onclick: closeSheet }, "回首页"));
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
      h("div", { class: "who" }, h("span", { class: "live-clock" }, icon("timer", "sm"), total), h("span", {}, L.session ? `训练中 · ${L.session}` : "训练中")),
      sound, h("button", { class: "btn quiet small live-end", type: "button", onclick: finish }, icon("stop", "xs"), "结束训练")),
    prog, restBar, status, list,
    // 按计划的训练动作已经带好了；只有自由训练能加动作（§133）
    !L.session ? h("button", { class: "btn ghost", type: "button", onclick: addMove }, icon("plus", "sm"), "加动作") : null));
  draw(); tick();
  liveTick = setInterval(tick, 500);
}

// ---- 路由 ---------------------------------------------------------------------------------
const PAGES = {
  home: { title: "首页", render: homePage, skeleton: [44, 300, 260] },  // 日期写在页里那一行（§175）
  plan: { title: "训练计划", tab: "home", render: trainPlan, skeleton: [60, 420] },
  atlas: { title: "图鉴", render: atlas, skeleton: [44, 60, 420] },
  rank: { title: "排行榜", tab: "home", render: rankPage, skeleton: [44, 60, 420] },
  record: { title: "记录", render: record, skeleton: [44, 260, 200] },
  me: { title: "我", render: me, skeleton: [120, 200, 320] },
  body: { title: "身体数据", tab: "me", render: body, skeleton: [120, 320, 320] },
  chat: { title: "IronM", full: true, tabs: true, render: chatPage },  // 底栏一直在（§175）
  live: { title: "训练中", full: true, render: livePage },
  welcome: { title: "完善资料", full: true, render: welcomePage },  // 新注册的先到这里（§174）
  privacy: { title: "隐私政策", full: true, render: (v) => legalPage(v, "privacy") },  // §180
  terms: { title: "用户协议", full: true, render: (v) => legalPage(v, "terms") },
};
// 旧地址跳到新位置（§121 需求 1）
function moved(name, sub, rest) {
  const tail = (xs) => (xs.length ? `/${xs.join("/")}` : "");
  if (name === "data") return "#body";
  if (name === "moves") return "#atlas";
  if (name === "food") return "#home/eat";
  if (name === "train") return sub === "log" ? "#record/timeline" : sub === "moves" ? "#atlas" : "#plan";
  if (name === "record" && sub === "log") return "#record/timeline";  // 原训练轨迹 → 训练时间线（§139）
  // 榜单都搬进排行榜（§161）：原来夯榜、图鉴里各个榜单标签和条目详情的地址跳过去
  const rk = (xs) => `#rank${tail(xs.filter((x) => x != null && x !== ""))}`;
  if (name === "tier") return rk([sub, ...rest]);
  if ((name === "me" || name === "record") && sub === "tier") return rk(rest);
  if (name === "atlas" && sub === "recipes") return "#atlas/food/recipes";
  if (name === "atlas" && sub === "tier") return rk(rest);
  if (name === "atlas" && sub === "moves" && rest[0] === "rank") return rk(["move", rest[1] ? `p:${rest[1]}` : ""]);
  if (name === "atlas" && sub === "moves" && rest[0] === "gear") return "#rank/gear";
  if (name === "atlas" && sub === "moves" && rest[0] === "machines") return "#atlas/machines";  // 器械成了大标签（§175）
  if (name === "atlas" && sub === "food" && ["meal", "supplement", "protein"].includes(rest[0])) return `#rank/${rest[0]}`;
  if (name === "me" && sub) return "#me";
  return "";
}
let renderSeq = 0;
let shownRoute = "";  // 上一次画出来的是哪一页：同一页重画不跳回顶部、不出骨架（§130）

async function render() {
  closeSheet();
  if (rankTimer) { clearInterval(rankTimer); rankTimer = null; }
  if (liveTick) { clearInterval(liveTick); liveTick = null; }  // 离开训练页：停掉计时（训练本身存在服务端，回来接着计）
  if (location.hash !== "#plan") planDay = null;
  const seq = ++renderSeq;
  const view = $("view");
  const signedIn = Boolean(store.get());
  document.body.classList.remove("chatting");
  if (!signedIn) {
    $("bar").hidden = true; $("tabs").hidden = true; $("fab").hidden = true; chat.els = null;
    const legal = { "#privacy": "privacy", "#terms": "terms" }[location.hash];  // 隐私政策、用户协议不登录也能看（§180）
    view.replaceChildren(); if (legal) legalPage(view, legal); else loginView(view); return;
  }
  const [name, sub, ...rest] = (location.hash.slice(1) || "home").split("/");
  const to = moved(name, sub, rest);
  if (to) { location.replace(to); return; }
  const page = PAGES[name] ? name : "home";
  const cfg = PAGES[page];
  document.title = `${cfg.title} · IronM`;
  for (const a of document.querySelectorAll(".tabs a")) a.classList.toggle("on", a.dataset.tab === (cfg.tab || page));
  $("tabs").hidden = Boolean(cfg.full) && !cfg.tabs;
  document.body.classList.toggle("with-tabs", Boolean(cfg.tabs));
  $("bar").hidden = Boolean(cfg.full);
  $("fab").hidden = true;  // 参照图没有悬浮的"＋"：记一餐、打卡都在首页卡片里（§175）
  if (cfg.full) {
    document.body.classList.add("chatting"); shownRoute = location.hash;
    view.replaceChildren(); cfg.render(view); return;
  }
  chat.els = null;
  const route = location.hash || "#home", samePage = route === shownRoute;
  shownRoute = route;
  const head = () => { $("title").textContent = cfg.title; $("kicker").textContent = cfg.kicker ? cfg.kicker() : ""; };
  // 切页不闪（§130）：先留着原来的内容，新内容读到了再换；读得慢（0.25 秒）才出骨架
  const slow = samePage ? 0 : setTimeout(() => {
    if (seq !== renderSeq) return;
    head(); view.replaceChildren(...skeleton(...(cfg.skeleton || [200]))); window.scrollTo(0, 0);
  }, 250);
  const box = document.createDocumentFragment();
  const holder = h("div");
  const show = (...kids) => {
    clearTimeout(slow); head();
    view.replaceChildren(...kids);
    if (samePage) return;
    window.scrollTo(0, 0);
    view.classList.remove("enter"); void view.offsetWidth; view.classList.add("enter");  // 新页淡入一下
  };
  try {
    await cfg.render(holder, sub, decodeURIComponent(rest.join("/")));
    if (seq !== renderSeq) return;
    box.append(...holder.childNodes);
    show(box);
  } catch (err) {
    if (seq !== renderSeq) return;
    show(failed(err, () => { cache.metrics = null; cache.profile = null; render(); }));
  }
}

window.addEventListener("hashchange", render);
document.addEventListener("DOMContentLoaded", () => {
  for (const el of document.querySelectorAll(".ti[data-icon]")) el.append(icon(el.dataset.icon));
  $("logo").append(mech(30)); $("me-avatar").append(icon("user", "sm"));  // 顶栏左边企鹅标志、右边"我"（§175）
  $("fab").addEventListener("click", quickAdd);
  render();
});
