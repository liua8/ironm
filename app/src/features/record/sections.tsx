// 战绩页的几块（同网页 recordPage §137、§139、§147）：这周、打卡日历、成就、训练时间线入口、上周周报。
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { stripRefs } from "@/features/me/logic";
import { WeekShare } from "@/features/share/share";
import { Button, PixelText, Panel, T } from "@/ui/pixel";
import { color, font, space } from "@/ui/theme";

import { BuddySay, Failed, PanelHead, Row, Sheet } from "./kit";
import {
  type Calendar,
  type CalCell,
  compareLine,
  lastLine,
  md,
  monthCells,
  monthLine,
  type PrRow,
  shiftMonth,
  WEEK,
  weekCount,
  weekMoreLine,
  type WeekReport as Report,
  weekReportText,
  type Workout,
} from "./logic";

export type BriefWeek = {
  planned?: number;
  due?: number;
  done?: number;
  tips?: string[];
  weight?: { brief?: string; text?: string } | null;
  sleep?: { value?: number | null; brief?: string } | null;
};

/** 这周：练了几次只说一次（§137）。 */
export function WeekPanel({ logs, cal, week }: { logs: Workout[]; cal: Calendar | null; week: BriefWeek | null }) {
  const { monday, days, before, diff } = weekCount(logs, new Date());
  const planned = week?.planned || week?.due || 0;
  const more = weekMoreLine(cal, week);
  return (
    <Panel>
      <PanelHead title="这周" right={`${md(monday)} 起`} />
      <PixelText size={24}>{`练了 ${days} 次${planned ? `，计划 ${planned} 次` : ""}`}</PixelText>
      <T>{compareLine(diff, before)}</T>
      {more ? <T>{more}</T> : null}
      {week?.tips?.length ? <BuddySay head="IronM 这周的建议">{stripRefs(week.tips[0])}</BuddySay> : null}
    </Panel>
  );
}

/** 打卡日历（§137）：能翻月，点有记录的那天看当天记了什么；下面一句本月练了几天、多少分钟。 */
export function CalendarCard({ first }: { first: Calendar }) {
  const [cal, setCal] = useState(first);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<CalCell>(null);
  const [y, m] = cal.month.split("-").map(Number);
  const isNow = cal.today.slice(0, 7) === cal.month;

  const load = async (month: string) => {
    setBusy(true);
    setError("");
    try {
      setCal(await api<Calendar>(`/iron/api/calendar?month=${month}`));
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
  };

  const cells = monthCells(cal);
  const weeks: CalCell[][] = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));

  return (
    <Panel>
      <PanelHead title="打卡日历" />
      <View style={s.calHead}>
        <Pressable accessibilityRole="button" accessibilityLabel="上个月" disabled={busy} onPress={() => load(shiftMonth(cal.month, -1))} style={s.calBtn}>
          <Text style={s.calBtnText}>‹</Text>
        </Pressable>
        <Text style={s.calTitle}>{`${y}年${m}月`}</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="下个月"
          accessibilityState={{ disabled: isNow || busy }}
          disabled={isNow || busy}
          onPress={() => load(shiftMonth(cal.month, 1))}
          style={[s.calBtn, isNow && s.calBtnOff]}
        >
          <Text style={s.calBtnText}>›</Text>
        </Pressable>
      </View>
      {error ? <Failed error={error} retry={() => load(cal.month)} /> : null}
      <View style={s.calRow}>
        {WEEK.map((w) => (
          <Text key={w} style={[s.cell, s.weekday]}>
            {w}
          </Text>
        ))}
      </View>
      {weeks.map((row, i) => (
        <View key={i} style={s.calRow}>
          {row.map((c, j) => (c ? <DayCell key={c.iso} c={c} m={m} onOpen={setOpen} /> : <View key={`b${j}`} style={s.cell} />))}
        </View>
      ))}
      <T>{monthLine(cal)}</T>
      <Sheet visible={open !== null} title={open ? `${m}月${open.day}日` : ""} onClose={() => setOpen(null)}>
        {(open?.entries ?? []).map((e, i, all) => (
          <Row key={String(e.id)} last={i === all.length - 1} title={e.line} end={<View style={[s.dot, e.done && s.dotOn]} />} />
        ))}
      </Sheet>
    </Panel>
  );
}

function DayCell({ c, m, onOpen }: { c: NonNullable<CalCell>; m: number; onOpen: (c: CalCell) => void }) {
  const label = `${m}月${c.day}日${c.lit ? `，练过${c.sets ? ` ${c.sets} 组` : ""}` : c.rest ? "，记了没练" : ""}`;
  const style = [s.cell, s.day, c.lit && s[`lv${c.level}`], !c.lit && c.rest && s.rest, !c.lit && !c.rest && c.entries.length > 0 && s.has, c.today && s.today];
  const text = <Text style={[s.dayText, c.lit && c.level === 3 && s.dayTextOn, !c.lit && c.rest && s.dayTextMuted]}>{c.day}</Text>;
  if (!c.entries.length)
    return (
      <View style={style} accessibilityLabel={label}>
        {text}
      </View>
    );
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={`${label}，点开看记录`} onPress={() => onOpen(c)} style={style}>
      {text}
    </Pressable>
  );
}

/** 成就：最近 30 天每个动作最好的一组（原 PR 墙）。 */
export function PrPanel({ rows }: { rows: PrRow[] }) {
  return (
    <Panel>
      <PanelHead title="成就" right="最近 30 天" />
      {rows.length ? (
        rows.map((x, i) => (
          <View key={x.name} style={[s.pr, i === rows.length - 1 && s.prLast]}>
            <Text style={s.prName} numberOfLines={2}>
              {x.name}
            </Text>
            <Text style={[s.prNum, x.broke && s.prNumNew]}>{`${x.best.weight_kg} kg × ${x.best.reps}`}</Text>
            {x.broke ? <Text style={s.badge}>破 PR</Text> : <Text style={s.prDay}>{md(x.day)}</Text>}
          </View>
        ))
      ) : (
        <T muted>记了重量的训练，每个动作最好的一组会排在这里。</T>
      )}
    </Panel>
  );
}

/** 训练时间线：战绩页上只留入口，点了跳到时间线页（§139）。 */
export function TimelineEntry({ logs }: { logs: Workout[] }) {
  return (
    <Pressable accessibilityRole="link" accessibilityLabel="训练时间线，点开看每一次训练" onPress={() => router.push("/timeline")} style={({ pressed }) => [s.entry, pressed && s.entryDown]}>
      <View style={s.entryPlank}>
        <PixelText size={12} style={s.entryPlankText}>
          训练时间线
        </PixelText>
      </View>
      <Text style={s.entryText} numberOfLines={2}>
        {lastLine(logs)}
      </Text>
      <Text style={s.entryChev}>›</Text>
    </Pressable>
  );
}

/** 上周周报（§147），放战绩页最下面；"存成图片"弹出周报卡，手机上存图后走系统分享（§164 第四期）。 */
export function WeekReportPanel({ r }: { r: Report }) {
  const t = weekReportText(r);
  const [open, setOpen] = useState(false);
  return (
    <Panel>
      <PanelHead title="上周周报" right={t.date} />
      <PixelText size={24}>{t.head}</PixelText>
      {t.facts ? <T>{t.facts}</T> : null}
      {t.more.map((line) => (
        <T key={line}>{line}</T>
      ))}
      <BuddySay head="下周重点">{stripRefs(r.focus)}</BuddySay>
      <Button kind="ghost" title="存成图片" onPress={() => setOpen(true)} />
      <Sheet visible={open} title="上周周报" onClose={() => setOpen(false)}>
        {open ? <WeekShare r={r} /> : null}
      </Sheet>
    </Panel>
  );
}

const CELL = { flex: 1, aspectRatio: 1, maxWidth: 48, alignItems: "center", justifyContent: "center" } as const;

const s = StyleSheet.create({
  calHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  calBtn: { width: 40, height: 36, alignItems: "center", justifyContent: "center", backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark },
  calBtnOff: { opacity: 0.4 },
  calBtnText: { color: color.accentInk, fontSize: 22, fontWeight: "700", lineHeight: 24 },
  calTitle: { color: color.ink, fontSize: 17, fontWeight: "700" },
  calRow: { flexDirection: "row", justifyContent: "space-between", gap: 4 },
  cell: { ...CELL, textAlign: "center" },
  weekday: { aspectRatio: undefined, color: color.muted, fontSize: 13, paddingVertical: 2 },
  day: { borderWidth: 2, borderColor: "transparent" },
  dayText: { color: color.ink, fontSize: 14, fontVariant: ["tabular-nums"] },
  dayTextOn: { color: color.accentInk, fontWeight: "700" },
  dayTextMuted: { color: color.muted },
  lv1: { backgroundColor: "#c9e4a8" },
  lv2: { backgroundColor: "#9fd06f" },
  lv3: { backgroundColor: color.accent },
  rest: { backgroundColor: "rgba(74, 42, 16, 0.08)", borderColor: "rgba(74, 42, 16, 0.15)" },
  has: { backgroundColor: color.paperLight },
  today: { borderColor: color.woodDark },
  dot: { width: 12, height: 12, borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight },
  dotOn: { backgroundColor: color.accent, borderColor: color.accentText },
  pr: { flexDirection: "row", alignItems: "center", gap: space.s, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: color.woodLight },
  prLast: { borderBottomWidth: 0 },
  prName: { flex: 1, color: color.ink, fontSize: 15 },
  prNum: { fontFamily: font.pixel, fontSize: 24, lineHeight: 30, color: color.ink },
  prNumNew: { color: color.accentText },
  prDay: { color: color.muted, fontSize: 13, minWidth: 48, textAlign: "right" },
  badge: { fontSize: 12, fontWeight: "800", color: color.woodDark, backgroundColor: color.amber, borderWidth: 2, borderColor: "#8a5a10", paddingHorizontal: 6, paddingVertical: 1, overflow: "hidden" },
  entry: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.paper, borderWidth: 4, borderColor: color.wood, padding: space.m },
  entryDown: { backgroundColor: color.paperLight },
  entryPlank: { backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark, paddingHorizontal: 8, paddingVertical: 2 },
  entryPlankText: { color: color.accentInk },
  entryText: { flex: 1, color: color.ink, fontSize: 14 },
  entryChev: { color: color.muted, fontSize: 22 },
});
