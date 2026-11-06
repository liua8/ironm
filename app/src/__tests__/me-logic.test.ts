// "我"和身体数据（spec §140、§141、§146、§153）：数值写法、趋势图的点、档案摘要、器材、记忆分组、文件状态、不露依据编号。
import {
  addGear,
  ageOf,
  checkWelcome,
  fileState,
  freshLine,
  gearLine,
  memoryGroups,
  num,
  profileLine,
  readable,
  sizeText,
  sparkPoints,
  splitMetrics,
  stripRefs,
  tokenEmail,
  validDay,
  valueText,
  weeklyChange,
  zhName,
} from "@/features/me/logic";
import { md } from "@/features/record/logic";

describe("metric formatting", () => {
  it("formats numbers and the weekly change", () => {
    expect(num(null)).toBe("—");
    expect(num(72.456)).toBe("72.46");
    expect(num(12345.6)).toBe("12,346");
    expect(valueText({ key: "weight_trend", value: -0.3 })).toBe("−0.30");
    expect(valueText({ key: "weight_trend", value: 0.25 })).toBe("+0.25");
    expect(valueText({ key: "blood_pressure", value: 112, display: "112/71" })).toBe("112/71");
    expect(weeklyChange({ key: "weight_trend", name: "每周变化", value: -0.3, unit: "公斤/周", brief: "稳步下降" })).toBe("每周 −0.30 公斤 · 稳步下降");
    expect(weeklyChange(undefined)).toBe("");
  });

  it("splits the other metrics into have and lack", () => {
    const m = {
      weight: { key: "weight", name: "体重", value: 70 },
      waist: { key: "waist", name: "腰围", value: 80 },
      bmr: { key: "bmr", name: "基础代谢", value: 1600 },
      sleep: { key: "sleep", name: "睡眠", value: null },
    };
    const { have, lack } = splitMetrics(m);
    expect(have).toEqual(["waist", "bmr"]);
    expect(lack).toEqual(["resting_hr", "hrv", "sleep", "steps", "active_kcal"]);
  });

  it("writes the data freshness line", () => {
    expect(freshLine({ metrics: [], as_of: "2026-11-03", stale_days: 2 }, md)).toBe("数据截至 11月3日（2 天前） · 点开看怎么算的、自己记一条");
    expect(freshLine({ metrics: [] }, md)).toBe("还没有同步到健康数据，可以先自己记一条");
  });

  it("never shows reference codes", () => {
    expect(stripRefs("每周减 0.5 公斤〔K03〕更容易保持〔经验〕")).toBe("每周减 0.5 公斤更容易保持");
    expect(stripRefs("看这里 [K12]")).toBe("看这里");
  });
});

describe("sparkPoints", () => {
  it("spreads x over 0–100 and pads y", () => {
    const pts = sparkPoints([70, 71, 72]);
    expect(pts.map((p) => p.x)).toEqual([0, 50, 100]);
    expect(pts[0].y).toBeCloseTo(100 - (0.15 / 1.3) * 100);
    expect(pts[2].y).toBeCloseTo((0.15 / 1.3) * 100);
  });
  it("starts bars from zero and handles flat lines", () => {
    expect(sparkPoints([0, 10], true)[0].y).toBe(100);
    expect(sparkPoints([5, 5]).every((p) => p.y === 50)).toBe(true);
    expect(sparkPoints([])).toEqual([]);
  });
});

describe("profile", () => {
  const data = {
    profile: { height_cm: 175, birth: "1995-11-06", sex: "male", goal: "gain", activity: "light" },
    options: { goal: { gain: "增肌" }, activity: { light: "轻度活动" } },
  };
  it("computes age before and after the birthday", () => {
    expect(ageOf("1995-11-06", new Date(2026, 10, 5))).toBe(30);
    expect(ageOf("1995-11-05", new Date(2026, 10, 5))).toBe(31);
    expect(ageOf(null, new Date())).toBeNull();
  });
  it("writes the role card line", () => {
    expect(profileLine(data, new Date(2026, 10, 5))).toBe("175 厘米 · 30 岁 · 男 · 增肌 · 轻度活动");
    expect(profileLine({ ...data, profile: {} }, new Date())).toBe("还没填身高、出生日期、性别和目标");
  });
  it("reads the email from the token", () => {
    const payload = "eyJlbWFpbCI6ICLlsI_njotAZXhhbXBsZS5jb20ifQ"; // {"email":"小王@example.com"} 的 base64url
    expect(tokenEmail(`h.${payload}.s`)).toBe("小王@example.com");
    expect(tokenEmail("garbage")).toBe("");
    expect(tokenEmail("")).toBe("");
  });
  it("validates days", () => {
    expect(validDay("2026-02-28")).toBe(true);
    expect(validDay("2026-02-30")).toBe(false);
    expect(validDay("2026-2-3")).toBe(false);
    expect(validDay("2026-11-06", "2026-11-05")).toBe(false);
  });
});

describe("gear", () => {
  it("writes where and what", () => {
    expect(gearLine({ place: "gym", gear: [] })).toBe("在健身房练，器械都有");
    expect(gearLine({ place: "home", gear: ["哑铃", "器械"], custom: ["跳绳"] })).toBe("在家练，有哑铃、健身器械、跳绳");
    expect(gearLine({ place: "home", gear: [] })).toBe("在家练，只有自重");
    expect(gearLine({ place: "both", gear: ["壶铃"] })).toBe("健身房和家里都练，家里有壶铃");
  });
  it("adds custom gear with the same rules as the web", () => {
    expect(addGear(" 跳绳，", [], [])).toEqual({ gear: [], custom: ["跳绳"] });
    expect(addGear("健身器械", [], [])).toEqual({ gear: ["器械"], custom: [] });
    expect(addGear("没有杠铃", [], [])).toBe("写有的器材就行，没有的不用写");
    expect(addGear("TRX", [], ["1", "2", "3", "4", "5", "6", "7", "8"])).toBe("最多加 8 样");
  });
});

describe("memory and files", () => {
  it("groups only live memories in category order", () => {
    const groups = memoryGroups({
      categories: { injury: "伤病与身体状况", equipment: "器械与场地", diet: "饮食限制与习惯" },
      items: [
        { id: "a", category: "equipment", content: "家里有哑铃", status: "active" },
        { id: "b", category: "injury", content: "左膝旧伤", status: "active" },
        { id: "c", category: "injury", content: "以前的", status: "superseded" },
        { id: "d", category: "diet", content: "过期的", status: "active", expired: true },
      ],
    });
    expect(groups.map(([name, xs]) => [name, xs.map((x) => x.id)])).toEqual([
      ["伤病与身体状况", ["b"]],
      ["器械与场地", ["a"]],
    ]);
  });

  it("tells the file state", () => {
    const now = Date.parse("2026-11-05T10:00:00Z");
    expect(fileState({ error: "坏了" }, now)).toEqual(["没识别出来", "attention"]);
    expect(fileState({ processed: true, indicators_count: 0, upload_time: "2026-11-05T09:59:00Z" }, now)).toEqual(["识别中", ""]);
    expect(fileState({ processed: true, indicators_count: 0, upload_time: "2026-11-05T09:00:00Z" }, now)).toEqual(["没有识别出指标", ""]);
    expect(fileState({ processed: true, indicators_count: 12, upload_time: "2026-11-05T09:00:00Z" }, now)).toEqual(["识别出 12 项", "good"]);
    expect(sizeText(2.5 * 1024 * 1024)).toBe("2.5 MB");
    expect(sizeText(100)).toBe("1 KB");
  });

  it("names raw records in Chinese and makes values readable", () => {
    expect(zhName({ code: "29463-7", name: "weight" })).toBe("体重");
    expect(zhName({ name: "dailyTotalSteps.apple_health_export" })).toBe("步数（苹果健康）");
    expect(readable({ latest_value: 25200000, unit: "ms" })).toEqual(["7", "小时"]);
    expect(readable({ latest_value: 8123.4, unit: "count" })).toEqual(["8,123", ""]);
    expect(readable({ latest_value: "72.0", unit: "kg" })).toEqual(["72", "kg"]);
  });
});


describe("checkWelcome (§174)", () => {
  const ok = { height: "172", birth: "1995-06-18", weight: "65.5", sex: "male", goal: "", activity: "" };
  it("height, birth and weight are required and checked", () => {
    expect(checkWelcome({ ...ok, height: "" }, "2026-11-06")).toEqual({ error: "身高填 100–250 厘米之间" });
    expect(checkWelcome({ ...ok, birth: "" }, "2026-11-06")).toEqual({ error: "填一下出生日期" });
    expect(checkWelcome({ ...ok, birth: "2027-01-01" }, "2026-11-06")).toEqual({ error: "出生日期写成 1995-06-18 这样，不能晚于今天" });
    expect(checkWelcome({ ...ok, birth: "1995-02-30" }, "2026-11-06")).toEqual({ error: "出生日期写成 1995-06-18 这样，不能晚于今天" });
    expect(checkWelcome({ ...ok, weight: "abc" }, "2026-11-06")).toEqual({ error: "体重填 20–300 公斤之间" });
  });
  it("returns what to save; empty optional fields are left out", () => {
    expect(checkWelcome(ok, "2026-11-06")).toEqual({ profile: { height_cm: 172, birth: "1995-06-18", sex: "male" }, weight: 65.5 });
  });
});
