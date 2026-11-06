// "我"和身体数据的纯计算（同网页 app.js 的 num、valueText、summary、gearLine、tokenEmail、dataPart、fileState）。

export type Tone = "good" | "attention" | "warn" | "neutral" | string;
export type Metric = {
  key: string;
  name: string;
  value?: number | null;
  unit?: string;
  text?: string;
  how?: string;
  data?: string;
  source?: string;
  missing?: string[];
  tone?: Tone;
  series?: [string, number][];
  brief?: string;
  display?: string;
};
export type MetricList = { metrics: Metric[]; as_of?: string | null; stale_days?: number | null };

export const SEX: Record<string, string> = { male: "男", female: "女" };
export const ABOUT = "IronM 一个人回答训练、饮食、恢复和身体数据的问题，会记得你的情况，按你的数据和状态安排。建议仅供参考，不能代替医生；身体不适请及时就医。";

/** 数字：≥1000 加千分位取整，其余最多两位小数；没有写"—"。 */
export function num(v: number | null | undefined): string {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString("zh-CN");
  return String(Math.round(v * 100) / 100);
}

/** 指标的数值写法：有 display 用 display；每周变化带正负号。 */
export function valueText(m: Pick<Metric, "key" | "value" | "display">): string {
  if (m.display) return m.display;
  if (m.value == null) return "—";
  if (m.key === "weight_trend") return `${m.value > 0 ? "+" : m.value < 0 ? "−" : ""}${Math.abs(m.value).toFixed(2)}`;
  return num(m.value);
}

/** 体重块上那一行"每周 −0.30 公斤 · 稳步下降"。 */
export function weeklyChange(trend: Metric | undefined): string {
  if (!trend || trend.value == null) return "";
  return `每周 ${valueText(trend)} ${String(trend.unit ?? "").replace("/周", "")}${trend.brief ? ` · ${trend.brief}` : ""}`;
}

/** 回答、说明里不给用户看依据库编号（〔K03〕、〔经验〕这类）。 */
export function stripRefs(text: string | null | undefined): string {
  return String(text ?? "")
    .replace(/\s*〔[^〕]*〕/g, "")
    .replace(/\s*[【\[]\s*(?:K\d+|m\d+|经验)[^】\]]*[】\]]/g, "")
    .trim();
}

export const IMPORTANT = ["weight", "body_fat", "waist", "resting_hr", "hrv", "sleep", "steps", "active_kcal"];
export const METRIC_ORDER = ["weight", "weight_trend", "body_fat", "waist", "lean_mass", "bmi", "resting_hr", "hrv", "blood_pressure", "vo2max",
  "steps", "active_kcal", "exercise_min", "sleep", "bmr", "tdee", "kcal_target", "protein_target"];
export const IMPORTANT_NAMES: Record<string, string> = { weight: "体重", body_fat: "体脂率", waist: "腰围", resting_hr: "静息心率", hrv: "心率变异性", sleep: "睡眠时长", steps: "步数", active_kcal: "活动消耗" };
/** 能自己记的（指标 → 记录的种类）；血压要记收缩压和舒张压两个数。 */
export const MANUAL: Record<string, string[]> = { weight: ["weight"], body_fat: ["body_fat"], waist: ["waist"], resting_hr: ["resting_hr"], sleep: ["sleep"], blood_pressure: ["systolic", "diastolic"] };
/** 计算出来的指标不能直接改：写明由什么算出、去哪里改。 */
export const CALC_FROM: Record<string, [string, string]> = {
  bmi: ["由体重和身高算出。", "体重和身高都在「我」里改。"],
  bmr: ["由体重、身高、年龄、性别算出。", "身高、出生日期、性别、体重都在「我」里改。"],
  tdee: ["基础代谢乘以日常活动水平。", "活动水平在「我」里改。"],
  kcal_target: ["每日总消耗按目标加减，再加上两周饮食复盘的调整量。", "目标在「我」里改；调整量在饮食页确认或撤销。"],
  protein_target: ["按体重和目标算出。", "目标和体重都在「我」里改。"],
};
const TOP3 = ["weight", "weight_trend", "bmi", "body_fat"];

/** 全部指标：有数的按原来的顺序，常记的还没记的接在后面。 */
export function splitMetrics(byKey: Record<string, Metric>): { have: string[]; lack: string[] } {
  const has = (k: string) => byKey[k] != null && byKey[k].value != null;
  return {
    have: METRIC_ORDER.filter((k) => !TOP3.includes(k) && has(k)),
    lack: IMPORTANT.filter((k) => !TOP3.includes(k) && !has(k)),
  };
}

export function byKey(list: MetricList | null | undefined): Record<string, Metric> {
  return Object.fromEntries((list?.metrics ?? []).map((m) => [m.key, m]));
}

/** "数据截至 11月3日（2 天前）"。 */
export function freshLine(list: MetricList, md: (iso: string) => string): string {
  if (!list.as_of) return "还没有同步到健康数据，可以先自己记一条";
  return `数据截至 ${md(list.as_of)}${list.stale_days != null && list.stale_days > 1 ? `（${list.stale_days} 天前）` : ""} · 点开看怎么算的、自己记一条`;
}

/** 趋势图的点：横轴铺满 0–100，纵轴上下各留 15%；柱状从 0 起。 */
export function sparkPoints(values: number[], bars = false): { x: number; y: number }[] {
  const n = values.length;
  if (!n) return [];
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (bars) {
    lo = 0;
    hi = hi * 1.08 || 1;
  } else {
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.15;
    lo -= pad;
    hi += pad;
  }
  return values.map((v, i) => ({ x: n === 1 ? 50 : (i / (n - 1)) * 100, y: 100 - ((v - lo) / (hi - lo)) * 100 }));
}

/** 出生日期算周岁。 */
export function ageOf(birth: string | null | undefined, now: Date): number | null {
  if (!birth) return null;
  const [y, m, d] = birth.split("-").map(Number);
  if (!y || !m || !d) return null;
  return now.getFullYear() - y - (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d) ? 1 : 0);
}

export type Profile = { height_cm?: number | null; birth?: string | null; sex?: string | null; goal?: string | null; activity?: string | null };
export type ProfileData = { profile: Profile; options: { goal: Record<string, string>; activity: Record<string, string> } };

/** 角色卡上一行：身高 · 年龄 · 性别 · 目标 · 活动。 */
export function profileLine(data: ProfileData, now: Date): string {
  const p = data.profile;
  const age = ageOf(p.birth, now);
  const parts = [
    p.height_cm ? `${num(p.height_cm)} 厘米` : "",
    age != null ? `${age} 岁` : "",
    (p.sex && SEX[p.sex]) || "",
    (p.goal && data.options.goal[p.goal]) || "",
    (p.activity && data.options.activity[p.activity]) || "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "还没填身高、出生日期、性别和目标";
}

/** 登录凭证里的邮箱（JWT 第二段，base64url）；取不到给空。 */
export function tokenEmail(token: string): string {
  try {
    const part = token.split(".")[1];
    if (!part) return "";
    const json = JSON.parse(utf8(base64url(part))) as { email?: unknown };
    return typeof json.email === "string" ? json.email : "";
  } catch {
    return "";
  }
}

const B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
function base64url(s: string): number[] {
  const clean = s.replace(/-/g, "+").replace(/_/g, "/").replace(/=+$/, "");
  const out: number[] = [];
  let buf = 0;
  let bits = 0;
  for (const ch of clean) {
    const v = B64.indexOf(ch);
    if (v < 0) throw new Error("bad base64");
    buf = (buf << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((buf >> bits) & 0xff);
    }
  }
  return out;
}
function utf8(bytes: number[]): string {
  return decodeURIComponent(bytes.map((b) => `%${b.toString(16).padStart(2, "0")}`).join(""));
}

/** 写成 2026-11-05 且是真实存在的日子；max 给了就不能晚于它。 */
export function validDay(s: string, max?: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const [y, m, d] = s.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  if (dt.getFullYear() !== y || dt.getMonth() !== m - 1 || dt.getDate() !== d) return false;
  return !max || s <= max;
}

/** 注册后完善资料（§174）：身高、出生日期、体重必填；对就返回要存的，不对返回给人看的一句。 */
export function checkWelcome(
  f: { height: string; birth: string; weight: string; sex?: string; goal?: string; activity?: string },
  today: string,
): { error: string } | { profile: Record<string, string | number>; weight: number } {
  const height = Number(f.height.trim());
  if (!f.height.trim() || !Number.isFinite(height) || height < 100 || height > 250) return { error: "身高填 100–250 厘米之间" };
  const birth = f.birth.trim();
  if (!birth) return { error: "填一下出生日期" };
  if (!validDay(birth, today)) return { error: "出生日期写成 1995-06-18 这样，不能晚于今天" };
  const weight = Number(f.weight.trim());
  if (!f.weight.trim() || !Number.isFinite(weight) || weight < 20 || weight > 300) return { error: "体重填 20–300 公斤之间" };
  const profile: Record<string, string | number> = { height_cm: height, birth };
  for (const k of ["sex", "goal", "activity"] as const) if (f[k]) profile[k] = f[k] as string;
  return { profile, weight };
}

/** 定位交给服务端前粗到两位小数（约 1 公里，§173）。 */
export function spotOf(c: { latitude: number; longitude: number }): { lat: number; lon: number } {
  return { lat: Math.round(c.latitude * 100) / 100, lon: Math.round(c.longitude * 100) / 100 };
}

/** 2026-11-05 → 2026年11月5日。 */
export function fmtDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${y}年${m}月${d}日`;
}

// ---- 器材和场所 ----
export const GEAR_PLACES = [["gym", "健身房"], ["home", "家里"], ["both", "都有"]] as const;
export const GEAR = [["哑铃", "哑铃"], ["壶铃", "壶铃"], ["弹力带", "弹力带"], ["杠铃", "杠铃"], ["单杠", "单杠"], ["器械", "健身器械"]] as const;
const GEAR_WORDS: Record<string, string> = Object.fromEntries(GEAR);
export type Gear = { known: boolean; place: "gym" | "home" | "both" | null; gear: string[]; custom?: string[]; text?: string; form?: boolean; lacking?: string[] };

export function gearLine(g: Pick<Gear, "place" | "gear" | "custom">): string {
  const have = [...g.gear.map((x) => GEAR_WORDS[x] ?? x), ...(g.custom ?? [])];
  const home = have.length ? `家里有${have.join("、")}` : "家里只有自重";
  return g.place === "gym" ? "在健身房练，器械都有" : g.place === "both" ? `健身房和家里都练，${home}` : `在家练，${home.slice(2)}`;
}

/** 自己加一样器材：去掉标点空格；写"没有"的不收；和上面同名的勾上；最多 8 样。返回新的状态或一句说明。 */
export function addGear(input: string, gear: string[], custom: string[]): { gear: string[]; custom: string[] } | string {
  const v = input.replace(/[、，,；;。\s]+/g, "");
  if (!v) return { gear, custom };
  if (/没有|无|不/.test(v)) return "写有的器材就行，没有的不用写";
  if (custom.length >= 8) return "最多加 8 样";
  const same = GEAR.find(([k, w]) => k === v || w === v);
  if (same) return { gear: gear.includes(same[0]) ? gear : [...gear, same[0]], custom };
  return { gear, custom: custom.includes(v) ? custom : [...custom, v] };
}

// ---- 记忆 ----
export type MemoryItem = { id: string; category: string; content: string; status: string; expired?: boolean };
export type Memory = { categories: Record<string, string>; items: MemoryItem[] };

/** 只列还生效的，按类别分组（类别顺序照接口给的）。 */
export function memoryGroups(r: Memory): [string, MemoryItem[]][] {
  const live = r.items.filter((x) => x.status === "active" && !x.expired);
  return Object.entries(r.categories)
    .map(([k, name]) => [name, live.filter((x) => x.category === k)] as [string, MemoryItem[]])
    .filter(([, xs]) => xs.length > 0);
}

// ---- 我的文件 ----
export type UploadedFile = {
  id?: string | number;
  file_key?: string;
  original_name?: string;
  file_name?: string;
  upload_time?: string;
  report_date?: string | null;
  date_confirmed?: boolean;
  processed?: boolean;
  indicators_count?: number;
  upload_status?: string;
  error?: string | null;
  file_type?: string;
  type?: string;
  file_size?: number;
  created_source_id?: string | number;
};

const recent = (f: UploadedFile, now: number) => now - Date.parse(f.upload_time ?? "") < 2 * 60 * 1000;
/** 刚上传 2 分钟内还是 0 项的，仍算识别中（mirobody 先标已处理、过几秒才写项数）。 */
export function fileState(f: UploadedFile, now: number): [string, Tone] {
  if (f.error || f.upload_status === "failed") return ["没识别出来", "attention"];
  if (!f.processed || (!f.indicators_count && recent(f, now))) return ["识别中", ""];
  return f.indicators_count ? [`识别出 ${f.indicators_count} 项`, "good"] : ["没有识别出指标", ""];
}

export function sizeText(n: number): string {
  const MB = 1024 * 1024;
  return n >= MB ? `${(n / MB).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

// ---- 原始记录（同网页 catalogSection） ----
export type Indicator = { code?: string; name?: string; indicator?: string; latest_value?: unknown; unit?: string; last_date?: string; first_date?: string; count?: number };
const LOINC_ZH: Record<string, string> = {
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
const DAILY_ZH: Record<string, string> = {
  dailytotalsteps: "步数", dailysteps: "步数", "dailytotalsleepanalysis_asleep(total)": "睡眠时长",
  "dailytotalsleepanalysis_asleep(core)": "核心睡眠", "dailytotalsleepanalysis_asleep(deep)": "深睡",
  "dailytotalsleepanalysis_asleep(rem)": "快速眼动睡眠", dailytotalsleepanalysis_inbed: "在床时间",
  dailytotalactiveenergyburned: "活动能量", dailytotalbasalenergyburned: "静息能量",
  dailytotaldistancewalkingrunning: "步行跑步距离", dailytotalflightsclimbed: "爬楼层数", dailyavgheartrate: "平均心率",
};
const SOURCES_ZH: Record<string, string> = { apple_health_export: "苹果健康", apple_health: "苹果健康", garmin: "Garmin", oura: "Oura", whoop: "Whoop" };

export function zhName(r: Indicator): string {
  if (r.code && LOINC_ZH[r.code]) return LOINC_ZH[r.code];
  const [base, source] = String(r.name || r.indicator || "").split(".");
  const zh = DAILY_ZH[base.toLowerCase()];
  if (zh) return source ? `${zh}（${SOURCES_ZH[source] || source}）` : zh;
  return r.indicator || r.name || "";
}

/** 值按单位换成好读的写法：毫秒的睡眠换成小时，计数取整。 */
export function readable(r: Indicator): [string, string] {
  const n = Number(r.latest_value);
  const unit = String(r.unit ?? "");
  if (unit === "ms" && Number.isFinite(n)) return [String(Math.round((n / 3_600_000) * 10) / 10), "小时"];
  if ((unit === "{#}" || unit === "count") && Number.isFinite(n)) return [num(Math.round(n)), ""];
  return [Number.isFinite(n) && /\.0+$/.test(String(r.latest_value)) ? num(n) : String(r.latest_value), unit];
}
