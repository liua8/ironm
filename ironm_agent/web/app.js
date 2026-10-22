// IronM 网页：首页、动作、教练（对话）、饮食、数据、我的，都在这一个页面里。
// 只调用 mirobody 与 iron-m 的接口，不加载外部资源；浏览器里只存登录凭证。
"use strict";

const KEY = "iron.token";
const store = {
  get() { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } },
  set(v) { try { v ? localStorage.setItem(KEY, v) : localStorage.removeItem(KEY); } catch { /* 隐私模式 */ } },
};
let cache = { metrics: null, profile: null, exercises: null };

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
};
function icon(name, cls = "") {
  const svg = s("svg", { viewBox: "0 0 24 24", class: `i ${cls}`.trim(), "aria-hidden": "true" });
  for (const [tag, attrs] of ICONS[name] || []) svg.append(s(tag, attrs));
  if (name === "stop") svg.style.fill = "currentColor";
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
function signOut() { store.set(""); cache = { metrics: null, profile: null, exercises: null }; resetChat(); render(); }

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
    h("button", { class: "btn ghost block", type: "button", onclick: () => askCoach(`我的${m.name}最近怎么样？说明什么？`) }, icon("coach", "sm"), "问问教练"));
}

// ---- 首页 ---------------------------------------------------------------------------------
const QUICK = {
  "只有 30 分钟": "今天只有 30 分钟，怎么练最有效？",
  "在家没有器械": "今天在家、没有器械，怎么练？",
  "今天想练腿": "今天想练腿，怎么安排？",
  "今天有点累": "今天有点累，还要练吗？怎么安排？",
};

function readiness(m) {
  const hrv = m.hrv_sdnn || m.hrv_rmssd || m.hrv;
  const items = [["静息心率", m.resting_hr, "heart"], ["心率变异性", hrv, "wave"], ["睡眠", m.sleep, "moon"]];
  const have = items.filter(([, x]) => x && x.value != null);
  const bad = have.filter(([, x]) => x.tone === "attention");
  let tone = "neutral", headline, text;
  if (!have.length) {
    headline = "还没有恢复数据";
    text = "连接手表或上传苹果健康数据后，这里会告诉你今天的身体状态。";
  } else if (bad.length) {
    tone = "attention";
    headline = "今天注意恢复";
    text = `${bad.map(([n, x]) => `${n}${x.brief}`).join("、")}，可以降低强度或安排轻松训练。`;
  } else {
    tone = "good";
    headline = "状态平稳，可以按计划训练";
    text = `${have.map(([n, x]) => `${n}${x.brief || "正常"}`).join("、")}。`;
  }
  return { items, tone, headline, text };
}

async function home(view) {
  const list = await metrics();
  const m = byKey(list);
  const r = readiness(m);
  const hero = h("div", { class: "hero" },
    h("div", { class: "hero-kicker" }, h("span", { class: `hero-dot ${r.tone}` }), "今天的身体状态"),
    h("div", {}, h("h2", {}, r.headline), h("p", {}, r.text)),
    h("div", { class: "hero-stats" }, r.items.map(([name, x, ic]) => {
      const have = x && x.value != null;
      return h("div", { class: "hero-stat" },
        h("span", { class: "k" }, icon(ic, "xs"), name),
        h("span", { class: "v" }, have ? valueText(x) : "—", have && x.unit ? h("small", {}, x.unit) : null),
        h("span", { class: `s ${have ? x.tone : "none"}` }, have ? x.brief || "已记录" : "暂无数据"));
    })),
    list.as_of ? h("span", { class: "caption", style: "color:var(--hero-muted)" }, `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""}`) : null);

  const plan = h("div", { class: "card plan-card" },
    h("div", { class: "plan-top" },
      h("div", { class: "plan-icon" }, icon("dumbbell")),
      h("div", {}, h("h3", {}, "今日训练"), h("p", { class: "muted" }, "教练会按你的目标、能用的器械和今天的状态，现在就排好。"))),
    h("button", { class: "btn block", type: "button", onclick: () => askCoach("给我安排今天的训练") }, "安排今天的训练"),
    h("div", { class: "asks" }, Object.entries(QUICK).map(([label, q]) => askChip(label, q))));

  const kcal = m.kcal_target, protein = m.protein_target;
  const food = kcal?.value != null || protein?.value != null
    ? h("a", { class: "card", href: "#food", style: "text-decoration:none" },
      h("div", { class: "duo" },
        h("div", { class: "stat" }, h("span", { class: "k" }, "热量目标", chip(kcal?.brief)), h("span", { class: "v" }, kcal?.value != null ? valueText(kcal) : "—", h("small", {}, "千卡"))),
        h("div", { class: "stat divider-v" }, h("span", { class: "k" }, "蛋白质"), h("span", { class: "v" }, protein?.value != null ? valueText(protein) : "—", h("small", {}, "克")))))
    : h("div", { class: "card" }, h("div", { class: "empty" }, icon("info"), "在「我的」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。"), h("a", { class: "btn ghost small", href: "#me" }, "去填写"));

  const trend = m.weight_trend;
  const body = [m.weight && tile(m.weight, { brief: trend?.value != null ? trend.brief : "", tone: "neutral" }), m.steps && tile(m.steps)].filter(Boolean);

  view.append(hero, plan,
    section("今日营养", more("饮食", "#food"), food),
    body.length ? section("身体", more("全部数据", "#data"), h("div", { class: "tiles" }, body)) : null);
}

// ---- 动作 ---------------------------------------------------------------------------------
const PART_MARK = { 腿臀: "腿", 胸: "胸", 背: "背", 肩: "肩", 手臂: "臂", 核心: "核", 全身: "全", 有氧: "氧" };
const moveFilter = { part: "全部", equip: "全部器械", q: "" };

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
  const lib = await exercises();
  const count = h("div", { class: "muted", style: "padding:0 2px" });
  const listBox = h("div", { class: "card" });
  const input = h("input", { type: "search", placeholder: "搜索动作或部位，比如深蹲、肩", value: moveFilter.q, "aria-label": "搜索动作" });
  function draw() {
    const q = moveFilter.q.trim();
    const items = lib.exercises.filter((x) =>
      (moveFilter.part === "全部" || x.part === moveFilter.part)
      && (moveFilter.equip === "全部器械" || x.equipment.includes(moveFilter.equip))
      && (!q || `${x.name}${x.muscles}${x.part}`.includes(q)));
    count.textContent = `${items.length} 个动作`;
    listBox.replaceChildren(items.length
      ? h("div", { class: "rows" }, items.map((x) => h("button", { class: "row-item", type: "button", onclick: () => exerciseSheet(x, lib.note) },
        h("div", { class: `mark p-${x.part}` }, PART_MARK[x.part] || x.part[0]),
        h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, x.muscles)),
        h("div", { class: "row-end" }, h("span", { class: "level" }, x.equipment.slice(0, 2).join(" · ")), icon("chevron", "sm")))))
      : h("div", { class: "empty" }, icon("search"), "没有符合的动作，换个条件试试，或者直接问动作教练。"));
  }
  input.addEventListener("input", () => { moveFilter.q = input.value; draw(); });
  draw();
  view.append(
    h("label", { class: "search" }, icon("search", "sm"), input),
    pills(["全部", ...lib.parts], moveFilter.part, (v) => { moveFilter.part = v; draw(); }),
    pills(["全部器械", ...lib.equipment], moveFilter.equip, (v) => { moveFilter.equip = v; draw(); }),
    count, listBox,
    h("div", { class: "card plan-card" },
      h("div", { class: "plan-top" }, h("div", { class: "plan-icon" }, icon("coach")),
        h("div", {}, h("h3", {}, "不知道练哪个？"), h("p", { class: "muted" }, "告诉动作教练你想练哪里、有什么器械、哪里不舒服。"))),
      h("div", { class: "asks" }, askChip("在家用哑铃练全身"), askChip("膝盖不好能练什么腿"), askChip("久坐圆肩怎么改善"))));
}

function exerciseSheet(x, note) {
  const list = (items, cls, ic) => h("ul", { class: `marks ${cls}` }, items.map((t) => h("li", {}, icon(ic, "xs"), h("span", {}, t))));
  openSheet(x.name,
    h("div", { class: "tags" }, chip(x.part), x.equipment.map((e) => chip(e)), chip(x.level)),
    h("p", { class: "lede" }, `主要练：${x.muscles}`),
    h("div", {}, h("h3", {}, "怎么做"), h("ol", { class: "steps-ol" }, x.steps.map((t) => h("li", {}, t)))),
    h("div", {}, h("h3", {}, "要点"), list(x.cues, "ok", "check")),
    h("div", {}, h("h3", {}, "常见错误"), list(x.mistakes, "bad", "x")),
    h("div", {}, h("h3", {}, "替代动作"), h("div", { class: "swap" }, h("div", {}, h("b", {}, "更容易"), x.easier), h("div", {}, h("b", {}, "更难"), x.harder))),
    h("div", { class: "callout" }, icon("alert", "sm"), h("div", {}, h("strong", {}, "什么情况先别做："), x.avoid)),
    h("p", { class: "caption" }, note),
    h("button", { class: "btn block", type: "button", onclick: () => askCoach(`${x.name}怎么做？我要注意什么？`) }, icon("coach", "sm"), "问动作教练"));
}

// ---- 饮食 ---------------------------------------------------------------------------------
async function food(view) {
  const m = byKey(await metrics());
  const kcal = m.kcal_target, protein = m.protein_target, bmr = m.bmr, tdee = m.tdee;
  if (kcal?.value == null && protein?.value == null) {
    view.append(h("div", { class: "card" }, h("div", { class: "empty" }, icon("info"), "先在「我的」里填好身高、出生日期、性别和目标，就能算出你每天该吃多少。"), h("a", { class: "btn block", href: "#me" }, "去填写")));
  } else {
    const [lo, hi] = String(protein?.display || "").split("–").map(Number);
    const meals = lo && hi ? `${Math.round(lo / 4)}–${Math.round(hi / 4)}` : "20–40";
    view.append(h("div", { class: "card" },
      h("div", { class: "tile-head" }, h("span", { class: "tile-name" }, "每日热量目标"), chip(kcal?.brief, "good")),
      h("div", { class: "target-big" }, h("span", { class: "v" }, kcal?.value != null ? valueText(kcal) : "—"), h("span", { class: "u" }, "千卡")),
      kcal?.how ? h("p", { class: "caption" }, kcal.how) : null,
      h("div", { class: "kv", style: "border-top:1px solid var(--line);padding-top:12px" },
        h("span", {}, "蛋白质"), h("span", {}, protein?.value != null ? `${valueText(protein)} 克` : "—")),
      h("button", { class: "link", type: "button", onclick: () => openSheet("怎么算的",
        ...[kcal, protein].filter((x) => x && x.value != null).map((x) => h("div", {}, h("h3", {}, x.name), h("dl", { class: "facts" },
          [["结论", x.text], ["怎么算的", x.how], ["依据", x.source]].filter(([, v]) => v).map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v))))))) }, "怎么算的", icon("chevron", "xs"))));
    view.append(section("蛋白质分到每一餐", null, h("div", { class: "card" },
      h("div", { class: "meals" }, ["早餐", "午餐", "晚餐", "加餐"].map((t) => h("div", { class: "meal" }, h("b", {}, meals, h("small", {}, "克")), h("span", {}, t)))),
      h("p", { class: "caption" }, "分 3–4 餐吃、每餐 20–40 克（国际运动营养学会建议）；鸡蛋、奶、豆制品、瘦肉、鱼虾都是好来源。"))));
  }
  const energy = [bmr, tdee].filter((x) => x && x.value != null);
  if (energy.length) view.append(section("能量估算", null, h("div", { class: "tiles" }, energy.map((x) => tile(x)))));
  const qs = ["早餐怎么吃够蛋白质", "练前练后吃什么", "外卖怎么点更健康", "要不要吃肌酸", "减脂期饿了怎么办"];
  view.append(section("问营养师", null, h("div", { class: "card" }, h("div", { class: "rows" },
    qs.map((q) => h("button", { class: "row-item", type: "button", onclick: () => askCoach(q) },
      h("div", { class: "row-main" }, h("span", { class: "row-title" }, q)), h("span", { class: "row-end" }, icon("chevron", "sm"))))))));
}

// ---- 数据 ---------------------------------------------------------------------------------
const GROUPS = [
  ["身体", ["weight", "weight_trend", "bmi"]],
  ["恢复", ["resting_hr", "hrv_sdnn", "hrv_rmssd", "hrv", "sleep"]],
  ["活动", ["steps"]],
  ["血压", ["blood_pressure"]],
  ["能量", ["bmr", "tdee", "kcal_target", "protein_target"]],
];

async function data(view) {
  const list = await metrics();
  const m = byKey(list);
  view.append(h("div", { class: "fresh" }, icon("info", "xs"),
    list.as_of ? `数据截至 ${md(list.as_of)}${list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开任一项看怎么算的` : "还没有同步到健康数据"));
  for (const [title, keys] of GROUPS) {
    const present = keys.map((k) => m[k]).filter(Boolean);
    const have = present.filter((x) => x.value != null);
    const miss = present.filter((x) => x.value == null);
    if (!present.length) continue;
    const wide = have.filter((x) => (x.series || []).length > 1);
    const small = have.filter((x) => (x.series || []).length <= 1);
    const tiles = [...wide.map((x) => tile(x, { wide: true })), ...small.map((x, i) => tile(x, { wide: small.length % 2 === 1 && i === small.length - 1 }))];
    view.append(section(title, null,
      tiles.length ? h("div", { class: "tiles" }, tiles) : null,
      miss.length ? h("div", { class: "card missing-list" }, h("div", { class: "rows" }, miss.map((x) => h("button", { class: "row-item", type: "button", onclick: () => metricSheet(x) },
        h("div", { class: "row-main" }, h("span", { class: "row-title" }, x.name), h("span", { class: "row-sub" }, missingHint(x))),
        h("span", { class: "row-end" }, "暂无", icon("chevron", "sm")))))) : null));
  }
}

function missingHint(m) {
  const reason = (m.missing || []).join("；");
  const how = reason.match(/（(.+)）/);
  return how ? `${how[1]}后显示` : reason || "暂无数据";
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
  view.append(section("说明", null, h("div", { class: "card" }, h("p", { class: "muted" }, "IronM 由主教练调度训练规划、动作教练、营养、恢复、数据分析几位专业角色一起回答。建议仅供参考，不能代替医生；身体不适请及时就医。"))));
  view.append(h("button", { class: "btn danger block", type: "button", onclick: signOut }, icon("logout", "sm"), "退出登录"));
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
const chat = { session: null, messages: [], busy: false, ctrl: null, loaded: false, pending: null, back: "home", els: null };
function resetChat() { chat.ctrl?.abort(); Object.assign(chat, { session: null, messages: [], busy: false, ctrl: null, loaded: false, pending: null }); }
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
  const form = h("form", { class: "composer" }, input, send);
  const fresh = h("button", { class: "icon-btn", type: "button", "aria-label": "新对话", title: "新对话", onclick: () => { resetChat(); chat.loaded = true; drawThread(); input.focus(); } }, icon("plus", "sm"));
  view.append(h("div", { class: "chat" },
    h("div", { class: "chat-bar" },
      h("a", { class: "icon-btn", href: `#${chat.back}`, "aria-label": "返回" }, icon("back", "sm")),
      h("div", { class: "who" }, h("b", {}, "教练"), h("span", {}, "训练规划 · 动作教练 · 营养 · 恢复 · 数据分析")),
      fresh),
    thread, form));
  chat.els = { thread, input, send };
  const grow = () => { input.style.height = "auto"; input.style.height = `${Math.min(input.scrollHeight, 140)}px`; syncComposer(); };
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (chat.busy) { chat.ctrl?.abort(); return; }
    const q = input.value; input.value = ""; grow(); ask(q);
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
  send.disabled = !chat.busy && !input.value.trim();
}

function drawThread() {
  if (!chat.els) return;
  const { thread } = chat.els;
  if (!chat.messages.length) {
    thread.replaceChildren(h("div", { class: "welcome" },
      h("div", { class: "mark-big" }, icon("coach")),
      h("div", {}, h("h2", {}, "你的教练团队"), h("p", { class: "muted" }, "主教练会请合适的专业角色一起回答；每条回答都能展开看依据和来源。")),
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
  if (msg.role === "user") return h("div", { class: "msg-user" }, msg.text);
  const running = !msg.done;
  const experts = msg.steps.filter((x) => x.id !== "coach");
  let head;
  if (running) {
    const busy = msg.steps.filter((x) => !x.done);
    head = msg.text ? "正在整理回答…"
      : busy.length ? `${busy.map((x) => x.name).join("、")}正在${busy.some((x) => x.id === "coach") ? "安排" : "回答"}…`
        : msg.steps.length ? "主教练正在整合…" : "正在理解你的问题…";
  } else {
    head = experts.length ? `${experts.length} 位专业角色参与` : msg.steps.length ? "主教练直接回答" : "";
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
      if (!msg.steps.some((x) => x.id === b.id)) msg.steps.push({ id: b.id, name: b.name || "", task: b.args?.["任务"] || "", result: "", done: false });
      break;
    case "tool_result": {
      if (b.tool_call_id === "sources") { msg.sources = String(b.content || ""); break; }
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

function coachMsg() { return { role: "coach", steps: [], text: "", notices: [], sources: "", id: "", error: "", done: false, open: false, srcOpen: false, rating: 0, el: null }; }

async function ask(question) {
  const q = String(question || "").trim();
  if (!q || chat.busy) return;
  const msg = coachMsg();
  chat.messages.push({ role: "user", text: q }, msg);
  chat.busy = true;
  drawThread();
  try {
    if (!chat.session) chat.session = (await apiData("/api/session", { method: "POST", body: "{}" })).session_id;
    await stream(q, msg);
    if (!msg.text && !msg.error) msg.error = "这次没有收到回答，请稍后再试。";
  } catch (err) {
    if (err.name === "AbortError") msg.notices.push("已停止。");
    else msg.error = err.message || "这次没能回答，请稍后再试。";
  } finally {
    msg.done = true; chat.busy = false; chat.ctrl = null;
    refresh(msg); syncComposer();
  }
}

async function stream(question, msg) {
  chat.ctrl = new AbortController();
  syncComposer();
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "content-type": "application/json", Authorization: `Bearer ${store.get()}` },
    body: JSON.stringify({ question, session_id: chat.session, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "" }),
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
    h("div", {}, h("div", { class: "wordmark" }, "Iron", h("b", {}, "M")), h("p", { class: "lede", style: "margin-top:10px" }, "你的健身教练团队：训练、动作、饮食、恢复和身体数据，一起帮你练。")),
    form));
}

// ---- 路由 ---------------------------------------------------------------------------------
const PAGES = {
  home: { title: "今天", kicker: todayLabel, render: home, skeleton: [250, 190, 120] },
  moves: { title: "动作", render: moves, skeleton: [46, 40, 420] },
  chat: { title: "教练", full: true, render: chatPage },
  food: { title: "饮食", render: food, skeleton: [210, 150, 120] },
  data: { title: "数据", render: data, skeleton: [180, 120, 180] },
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
  document.title = `${cfg.title} · IronM`;
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
