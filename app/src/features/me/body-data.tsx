// 身体数据（同网页 dataPart，spec §146）：上面只放体重（带每周变化和趋势图）、BMI、体脂率；
// 其余收进两个默认收起的折叠块——全部指标（最下面是原始记录）、这周训练（每周复盘只给建议，加肌肉恢复列表）。
// 网页版的肌肉人体图要单独一份大图形数据，先只放按恢复程度排的列表。
import { router } from "expo-router";
import { type ReactNode, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { BuddySay, Caption, Chip, Failed, kit, KV, Row, Sheet, Sub, useLoad } from "@/features/record/kit";
import { md } from "@/features/record/logic";
import { Button, Panel, PixelText, T } from "@/ui/pixel";
import { color, font, space } from "@/ui/theme";

import { apiData, askPath } from "./data";
import {
  byKey,
  CALC_FROM,
  freshLine,
  IMPORTANT_NAMES,
  type Indicator,
  MANUAL,
  type Metric,
  type MetricList,
  num,
  readable,
  splitMetrics,
  stripRefs,
  valueText,
  weeklyChange,
  zhName,
} from "./logic";
import { RecordBox } from "./record-box";
import { Chart, Spark } from "./trend-chart";

type Week = {
  planned?: number;
  done: number;
  sessions?: { day: string; name: string; done?: boolean }[];
  weight?: { brief?: string; text?: string } | null;
  sleep?: { value?: number | null; brief?: string } | null;
  resting_hr?: { value?: number | null; brief?: string } | null;
  hrv?: { name?: string; value?: number | null; brief?: string } | null;
  tips: string[];
};
type Muscle = { code?: string; name: string; part?: string; tier: string; state?: string; recovery: number; last?: string | null };
type Muscles = { muscles: Muscle[]; sessions?: number; untrained?: string[]; note?: string };

async function loadAll() {
  const [list, muscles, brief] = await Promise.all([
    api<MetricList>("/iron/api/metrics"),
    api<Muscles>("/iron/api/muscles").catch(() => null),
    api<{ week?: Week }>("/iron/api/brief").catch(() => null),
  ]);
  return { list, muscles, week: brief?.week ?? null };
}

type Open = { kind: "metric"; m: Metric } | { kind: "record"; title: string; kinds: string[] } | null;

/** top：记录页上的"身体数据指标"卡（§176）——体重、BMI、体脂率和"记录""全部身体数据"；整页在 /body。 */
export function BodyData({ top = false }: { top?: boolean } = {}) {
  const { data, error, reload } = useLoad(loadAll);
  const [open, setOpen] = useState<Open>(null);
  if (error && !data)
    return (
      <Panel>
        <Failed error={error} retry={reload} />
      </Panel>
    );
  if (!data)
    return (
      <Panel>
        <T muted>正在读取…</T>
      </Panel>
    );
  const m = byKey(data.list);
  const weight = m.weight ?? { key: "weight", name: "体重", unit: "公斤" };
  const fat = m.body_fat ?? { key: "body_fat", name: "体脂率", unit: "%" };
  const { have, lack } = splitMetrics(m);
  const week = data.week;
  const mm = data.muscles;
  const tired = (mm?.muscles ?? []).filter((x) => x.tier !== "ready" || x.state === "sore");
  const weekSub = [week?.planned ? `完成 ${week.done} / ${week.planned} 次` : "", mm?.sessions ? `${tired.length} 块肌肉恢复中` : ""].filter(Boolean).join(" · ");
  const showMetric = (x: Metric) => setOpen({ kind: "metric", m: x });
  const sheet = (
    <Sheet visible={open !== null} title={open?.kind === "metric" ? open.m.name : open ? `记录${open.title}` : ""} onClose={() => setOpen(null)}>
      {open?.kind === "metric" ? <MetricDetail m={open.m} onChanged={reload} close={() => setOpen(null)} /> : null}
      {open?.kind === "record" ? <RecordBox kinds={open.kinds} onChanged={reload} /> : null}
    </Sheet>
  );
  if (top) {
    return (
      <Panel>
        <View style={s.topHead}>
          <PixelText size={24} style={s.topTitle}>身体数据指标</PixelText>
          <Pressable accessibilityRole="button" onPress={() => setOpen({ kind: "record", title: "体重、腰围、体脂", kinds: ["weight", "waist", "body_fat"] })} style={s.topRec}>
            <Text style={s.topRecText}>记录</Text>
          </Pressable>
        </View>
        <Tile m={weight} wide extra={weeklyChange(m.weight_trend)} onPress={() => showMetric(weight)} />
        <View style={s.pair}>
          <Tile m={m.bmi ?? { key: "bmi", name: "BMI" }} brief={m.bmi ? undefined : "要先填身高体重"} onPress={() => showMetric(m.bmi ?? { key: "bmi", name: "BMI", text: "要先在「我」里填身高，再记一次体重。", missing: ["个人中心"] })} />
          <Tile m={fat} brief={fat.value != null ? undefined : "还没记录"} onPress={() => showMetric(fat)} />
        </View>
        <Pressable accessibilityRole="link" onPress={() => router.push("/body")}><Text style={s.topAll}>全部身体数据 ›</Text></Pressable>
        {sheet}
      </Panel>
    );
  }

  return (
    <>
      <Text style={s.fresh}>{freshLine(data.list, md)}</Text>
      <Tile m={weight} wide extra={weeklyChange(m.weight_trend)} onPress={() => showMetric(weight)} />
      <View style={s.pair}>
        <Tile m={m.bmi ?? { key: "bmi", name: "BMI" }} brief={m.bmi ? undefined : "要先填身高体重"} onPress={() => showMetric(m.bmi ?? { key: "bmi", name: "BMI", text: "要先在「我」里填身高，再记一次体重。", missing: ["个人中心"] })} />
        <Tile m={fat} brief={fat.value != null ? undefined : "还没记录"} onPress={() => showMetric(fat)} />
      </View>

      <Fold title="全部指标" sub={`${have.length} 项${lack.length ? ` · 还有 ${lack.length} 项没记` : ""}`}>
        <View style={kit.card}>
          {have.map((k) => (
            <Row key={k} title={m[k].name} sub={m[k].brief} end={<Text style={s.end}><Text style={s.endNum}>{valueText(m[k])}</Text> {m[k].unit ?? ""}</Text>} onPress={() => showMetric(m[k])} />
          ))}
          {lack.map((k, i) =>
            MANUAL[k] ? (
              <Row key={k} last={i === lack.length - 1} title={IMPORTANT_NAMES[k]} sub="还没记录" end="记一条" onPress={() => setOpen({ kind: "record", title: IMPORTANT_NAMES[k], kinds: MANUAL[k] })} />
            ) : (
              <Row key={k} last={i === lack.length - 1} title={IMPORTANT_NAMES[k]} sub="还没记录，要手表或苹果健康（导入放到手机版第四期）" />
            ),
          )}
        </View>
        <Fold title="看原始记录" small>
          <RawRecords />
        </Fold>
      </Fold>

      <Fold title="这周训练" sub={weekSub}>
        {week ? <WeekCard w={week} /> : null}
        {mm ? <MuscleList mm={mm} tired={tired} /> : <Failed error="肌肉恢复暂时算不出来" retry={reload} />}
      </Fold>

      <Sheet visible={open !== null} title={open?.kind === "metric" ? open.m.name : open ? `记录${open.title}` : ""} onClose={() => setOpen(null)}>
        {open?.kind === "metric" ? <MetricDetail m={open.m} onChanged={reload} close={() => setOpen(null)} /> : null}
        {open?.kind === "record" ? <RecordBox kinds={open.kinds} onChanged={reload} /> : null}
      </Sheet>
    </>
  );
}

function Tile({ m, wide, brief, extra, onPress }: { m: Metric; wide?: boolean; brief?: string; extra?: string; onPress: () => void }) {
  const shown = valueText(m);
  const series = m.series ?? [];
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${m.name}，点开看怎么算的`} onPress={onPress} style={({ pressed }) => [s.tile, !wide && s.half, pressed && s.tileDown]}>
      <View style={s.tileHead}>
        <Text style={s.tileName}>{m.name}</Text>
        <Chip text={brief ?? m.brief} tone={brief ? "" : m.tone} />
      </View>
      {extra ? <Text style={s.tileSub}>{extra}</Text> : null}
      <Text style={s.tileValue} numberOfLines={1} adjustsFontSizeToFit>
        <Text style={[s.tileNum, shown.length > 6 && s.tileNumLong]}>{shown}</Text>
        {m.unit ? <Text style={s.tileUnit}>{` ${m.unit}`}</Text> : null}
      </Text>
      {series.length > 1 ? <Spark series={series} height={wide ? 72 : 54} /> : null}
      {wide && series.length > 1 ? (
        <View style={s.tileFoot}>
          <Text style={s.footText}>{md(series[0][0])}</Text>
          <Text style={s.footText}>{md(series[series.length - 1][0])}</Text>
        </View>
      ) : null}
    </Pressable>
  );
}

/** 指标详情（同网页 metricSheet）：结论、怎么算的、趋势图；算出来的写明去哪改；能自己记的放记录框。 */
function MetricDetail({ m, onChanged, close }: { m: Metric; onChanged: () => void; close: () => void }) {
  const facts = ([["结论", m.text], ["怎么算的", m.how], ["用了哪些数据", m.data], ["依据", m.source]] as const)
    .map(([k, v]) => [k, stripRefs(v)] as const)
    .filter(([, v]) => v);
  const missing = m.missing ?? [];
  const toMe = () => {
    close();
    router.navigate("/me");
  };
  return (
    <>
      {m.value != null ? (
        <View style={s.big}>
          <PixelText size={36}>{valueText(m)}</PixelText>
          {m.unit ? <Text style={s.bigUnit}>{m.unit}</Text> : null}
          <Chip text={m.brief} tone={m.tone} />
        </View>
      ) : null}
      {(m.series ?? []).length > 1 ? <Chart series={m.series ?? []} bars={m.key === "steps"} /> : null}
      {facts.map(([k, v]) => (
        <View key={k} style={s.fact}>
          <Text style={s.factKey}>{k}</Text>
          <T>{v}</T>
        </View>
      ))}
      {missing.some((x) => x.includes("个人中心")) ? <Button title="去「我」里填写" onPress={toMe} /> : null}
      {missing.some((x) => x.includes("手表")) ? <Caption>这项要手表或苹果健康的数据；手机上导入放到第四期。</Caption> : null}
      {CALC_FROM[m.key] ? (
        <View style={s.calc}>
          <Sub>这个数不能直接改</Sub>
          <T>{CALC_FROM[m.key][0]}</T>
          <T muted>{CALC_FROM[m.key][1]}</T>
          <Button kind="ghost" title="去「我」里修改" onPress={toMe} />
        </View>
      ) : null}
      {MANUAL[m.key] ? (
        <View style={s.calc}>
          <Sub>自己记一条、改或删</Sub>
          <RecordBox kinds={MANUAL[m.key]} onChanged={onChanged} />
        </View>
      ) : null}
      <Button
        kind="ghost"
        title="问问 IronM"
        onPress={() => {
          close();
          router.push(askPath(`我的${m.name}最近怎么样？说明什么？`));
        }}
      />
    </>
  );
}

/** 每周复盘（同网页 weekCard）：只列建议，有建议时下面一行"想改计划，咨询 IronM。"（§146 需求 3）。 */
function WeekCard({ w }: { w: Week }) {
  const rows: [string, string, string][] = [];
  if (w.planned) rows.push(["训练", `完成 ${w.done} / ${w.planned} 次`, (w.sessions ?? []).map((x) => `${x.day}${x.name}${x.done ? " ✓" : ""}`).join("　")]);
  else rows.push(["训练", `本周练了 ${w.done} 次`, "还没有计划"]);
  if (w.weight) rows.push(["体重", w.weight.brief || "—", w.weight.text ?? ""]);
  if (w.sleep) rows.push(["睡眠", `平均 ${num(w.sleep.value)} 小时`, w.sleep.brief ?? ""]);
  if (w.resting_hr) rows.push(["静息心率", `${num(w.resting_hr.value)} 次/分`, w.resting_hr.brief ?? ""]);
  if (w.hrv) rows.push([w.hrv.name || "心率变异性", `${num(w.hrv.value)} 毫秒`, w.hrv.brief ?? ""]);
  return (
    <View style={kit.card}>
      {rows.map(([k, v, sub], i) => (
        <Row key={k} last={i === rows.length - 1} title={k} sub={stripRefs(sub)} end={v} />
      ))}
      {w.tips.length ? (
        w.tips.map((t) => <BuddySay key={t} head="IronM 的建议">{stripRefs(t)}</BuddySay>)
      ) : (
        <T muted>这周没有需要调整的地方，照计划来。</T>
      )}
      {w.tips.length && w.planned ? <Caption>想改计划，咨询 IronM。</Caption> : null}
    </View>
  );
}

const muscleWord = (m: Muscle) => (m.state === "sore" ? "自述酸痛" : m.tier === "high" ? "刚练过" : m.tier === "ready" ? (m.last ? "可以练" : "最近没练") : "恢复中");

/** 肌肉恢复：恢复最慢的 6 块，一条进度条（人体图先不做）。 */
function MuscleList({ mm, tired }: { mm: Muscles; tired: Muscle[] }) {
  const top = [...tired].sort((a, b) => a.recovery - b.recovery).slice(0, 6);
  const untrained = mm.untrained ?? [];
  return (
    <View style={kit.card}>
      <Sub>肌肉恢复</Sub>
      {mm.sessions === 0 ? (
        <T muted>最近还没有训练记录：在首页打卡，或在对话里说"今天练了……"就会记下来。</T>
      ) : top.length ? (
        top.map((x) => (
          <View key={x.code ?? x.name} style={s.muscle}>
            <Text style={s.muscleName} numberOfLines={1}>
              {x.name}
            </Text>
            <View style={s.bar}>
              <View style={[s.barFill, { width: `${Math.max(0, Math.min(100, x.recovery))}%` }, x.state === "sore" && s.barSore]} />
            </View>
            <Text style={[s.muscleWord, x.state === "sore" && s.sore]}>{muscleWord(x)}</Text>
          </View>
        ))
      ) : (
        <T muted>全部肌肉都已恢复，可以练。</T>
      )}
      {untrained.length && mm.sessions ? <Text style={s.notice}>{`近 7 天没练：${untrained.join("、")}`}</Text> : null}
      {mm.note ? <Caption>{stripRefs(mm.note)}</Caption> : null}
    </View>
  );
}

/** 原始记录（同网页 catalogSection）：同步和导入的每一条，包括报告里识别出的化验值；先列 8 项。 */
function RawRecords() {
  const { data, error, reload } = useLoad(async () =>
    ((await apiData<{ rows?: Indicator[] }>("/api/v1/health-indicators")).rows ?? [])
      .filter((r) => r.latest_value != null)
      .sort((a, b) => String(b.last_date).localeCompare(String(a.last_date))),
  );
  const [all, setAll] = useState(false);
  const [pick, setPick] = useState<Indicator | null>(null);
  if (error) return <Failed error={error} retry={reload} />;
  if (!data) return <Caption>正在读取…</Caption>;
  if (!data.length) return <Caption>还没有指标数据。</Caption>;
  const shown = all ? data : data.slice(0, 8);
  return (
    <View style={kit.card}>
      {shown.map((r, i) => {
        const [v, unit] = readable(r);
        return (
          <Row
            key={`${r.code ?? r.name}-${i}`}
            title={zhName(r)}
            sub={`${md(r.last_date)} · ${r.count ?? 0} 条记录`}
            end={<Text style={s.end}><Text style={s.endNum}>{v}</Text> {unit}</Text>}
            onPress={() => setPick(r)}
          />
        );
      })}
      {data.length > 8 && !all ? <Text style={kit.link} onPress={() => setAll(true)}>{`显示全部 ${data.length} 项`}</Text> : null}
      <Caption>同步和导入的每一条数据，包括从上传的报告里识别出的化验值。</Caption>
      <Sheet visible={pick !== null} title={pick ? zhName(pick) : ""} onClose={() => setPick(null)}>
        {pick ? (
          <>
            <View style={s.big}>
              <PixelText size={36}>{readable(pick)[0]}</PixelText>
              {readable(pick)[1] ? <Text style={s.bigUnit}>{readable(pick)[1]}</Text> : null}
            </View>
            <KV k="最近一次" v={md(pick.last_date)} />
            <KV k="第一次" v={md(pick.first_date)} />
            <KV k="记录数" v={`${pick.count ?? 0} 条`} />
          </>
        ) : null}
      </Sheet>
    </View>
  );
}

/** 默认收起的一块：标题下一行摘要，点开再看。 */
function Fold({ title, sub, small, children }: { title: string; sub?: string; small?: boolean; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <View style={[s.fold, small && s.foldSmall]}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={s.foldHead}>
        <View style={s.foldMain}>
          <Text style={[s.foldTitle, small && s.foldTitleSmall]}>{title}</Text>
          {sub ? <Text style={s.foldSub}>{sub}</Text> : null}
        </View>
        <Text style={s.foldChev}>{open ? "⌄" : "›"}</Text>
      </Pressable>
      {open ? <View style={s.foldBody}>{children}</View> : null}
    </View>
  );
}

const s = StyleSheet.create({
  topHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  topTitle: { fontSize: 20, lineHeight: 26 },
  topRec: { backgroundColor: color.accentSoft, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5 },
  topRecText: { color: color.accentText, fontSize: 12, fontWeight: "700" },
  topAll: { color: color.accentText, fontSize: 14, fontWeight: "700" },
  fresh: { color: color.ink, fontSize: 13 },
  pair: { flexDirection: "row", gap: space.m },
  tile: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m, gap: 6 },
  half: { flex: 1, minWidth: 0 },
  tileDown: { backgroundColor: color.paperLight },
  tileHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 6, flexWrap: "wrap" },
  tileName: { color: color.ink, fontSize: 15, fontWeight: "700" },
  tileSub: { color: color.muted, fontSize: 13 },
  tileValue: { color: color.ink },
  tileNum: { fontWeight: "800", fontSize: 36, lineHeight: 44, color: color.ink },
  tileNumLong: { fontSize: 24, lineHeight: 30 },
  tileUnit: { color: color.muted, fontSize: 14 },
  tileFoot: { flexDirection: "row", justifyContent: "space-between" },
  footText: { color: color.muted, fontSize: 12 },
  end: { color: color.muted, fontSize: 13 },
  endNum: { color: color.ink, fontSize: 15, fontWeight: "700" },
  big: { flexDirection: "row", alignItems: "baseline", gap: space.s, flexWrap: "wrap" },
  bigUnit: { color: color.muted, fontSize: 15 },
  fact: { gap: 2 },
  factKey: { color: color.muted, fontSize: 13, fontWeight: "700" },
  calc: { gap: space.s, borderTopWidth: 1, borderTopColor: color.woodLight, paddingTop: space.m },
  muscle: { flexDirection: "row", alignItems: "center", gap: space.s },
  muscleName: { width: 76, color: color.ink, fontSize: 14 },
  bar: { flex: 1, height: 10, backgroundColor: color.paper, borderWidth: 1, borderColor: color.wood },
  barFill: { height: "100%", backgroundColor: color.accent },
  barSore: { backgroundColor: color.heat },
  muscleWord: { width: 64, textAlign: "right", color: color.muted, fontSize: 13 },
  sore: { color: color.heat },
  notice: { color: color.ink2, backgroundColor: "rgba(242, 193, 78, 0.3)", borderLeftWidth: 1, borderLeftColor: "#8a5a10", padding: space.s, fontSize: 14 },
  fold: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood },
  foldSmall: { borderWidth: 1, borderRadius: 14, borderColor: color.woodLight },
  foldHead: { flexDirection: "row", alignItems: "center", gap: space.s, padding: space.m },
  foldMain: { flex: 1, gap: 2 },
  foldTitle: { color: color.ink, fontSize: 16, fontWeight: "700" },
  foldTitleSmall: { fontSize: 14 },
  foldSub: { color: color.muted, fontSize: 13 },
  foldChev: { color: color.muted, fontSize: 20 },
  foldBody: { paddingHorizontal: space.m, paddingBottom: space.m, gap: space.m },
});
