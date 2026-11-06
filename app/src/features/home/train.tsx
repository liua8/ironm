// 首页·练（同网页 home、trainCard，spec §121 需求 4；§176 照网页 §175 的今日委托卡）：训练进行中的入口、安全提醒、
// 今日委托卡（标题、部位标签、"完成 +1 颗星"、这周已练几次的进度、编号的动作表、开始训练、已经练完了直接打卡、热身时长、更多）。
// 网页上的场所与器材卡、睡眠心率天气小格、IronM 说、生病追问、右下角快捷记录不在这里（场所器材放"我"，快捷记录按 §133 不要悬浮按钮）。
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { Image, Linking, Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button, LinkButton, Note, Panel, PixelText, Plank, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { LiveIcon } from "@/features/live/icons";
import type { Live } from "@/features/live/logic";
import { checkLive, LiveEntry, startLive } from "@/features/live/start";

import { askCoach, Fig, Fold, Thumb, useFlash, WeekDots } from "./bits";
import { DoneSheet, RestSheet } from "./checkin";
import { heroLine, withCoach } from "./today-logic";
import { TodayVersion, useToday } from "./today-version";
import { clean, type TodayCard, todayCard, weekDots } from "./train-logic";
import type { Brief, Library, Session, TrainImages, Training, Week } from "./types";

type Data = { brief: Brief | null; tr: Training | null; week: Week | null; lib: Library | null; photos: TrainImages | null; live: Live | null };

export function TrainSection() {
  const [d, setD] = useState<Data | null>(null);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ name: string; version: Session | null } | null>(null);
  const [rest, setRest] = useState(false);
  const [flash, show] = useFlash();
  const today = useToday();  // 管家定的今天（§163）：大卡片上一行提示和"更多"里共用

  const load = useCallback(async () => {
    const [brief, tr, week, lib, photos, live] = await Promise.all([
      api<Brief>("/iron/api/brief").catch(() => null),
      api<Training>("/iron/api/training").catch(() => null),
      api<Week>("/iron/api/week").catch(() => null),
      api<Library>("/iron/api/exercises").catch(() => null),
      api<TrainImages>("/iron/api/train-images").catch(() => null),
      checkLive(),
    ]);
    setD({ brief, tr, week, lib, photos, live });
  }, []);
  // 每次回到首页都重读：从训练页回来时"训练进行中""练完了"要跟着变
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const go = async () => {
    setBusy(true);
    const err = await startLive({ today_plan: true });  // 继续时也补上今天计划（§123）
    setBusy(false);
    if (err) show(err);
  };
  const finished = (msg: string) => {
    setDone(null);
    setRest(false);
    show(msg, 3000);
    void load();
  };

  if (!d) return <Note>正在读今天的训练…</Note>;
  const card = todayCard(d.brief, d.tr, withCoach(d.week, today.shown), d.lib, d.photos?.images || {});  // 管家调整过就列调整后的
  const dots = weekDots(d.brief);
  const alerts = d.brief?.alerts || [];
  return (
    <View style={s.wrap}>
      {flash}
      {d.live ? <LiveEntry live={d.live} onPress={go} /> : null}
      {alerts.length ? (
        <View style={s.alerts}>
          {alerts.map((a) => (
            <Fold key={a.key} title={clean(a.title)} lead={<LiveIcon name="alert" size={16} color={color.heat} />}>
              <Text style={s.p}>{clean(a.text)}</Text>
            </Fold>
          ))}
        </View>
      ) : null}
      {card.kind === "session" ? (
        <Panel style={s.quest}>
          <View style={s.questTop}>
            <PixelText size={24} style={s.questTitle}>{`今日委托 · ${card.title}`}</PixelText>
            <View style={s.tags}>
              {card.parts.length ? <Text style={[s.tag, s.tagCoral]}>{card.parts.join(" · ")}</Text> : null}
              <Text style={[s.tag, s.tagGreen]}>完成 +1 颗星</Text>
            </View>
          </View>
          <WeekBar w={dots} />
          <CoachLine today={today} />
          <View style={s.list}>
            {card.rows.map((it, i) => (
              <View key={`${it.exercise}-${i}`} style={[s.row, i > 0 && s.rowLine]}>
                <Text style={s.no}>{i + 1}</Text>
                <View style={s.moveText}>
                  <Text style={s.moveName} numberOfLines={1}>{it.exercise}</Text>
                  {it.note ? <Text style={[s.moveNote, it.cut && s.cut]}>{it.note}</Text> : null}
                </View>
                <Text style={s.moveSets}>{it.sets}</Text>
              </View>
            ))}
          </View>
          <Button title={d.live ? "继续训练" : "开始训练"} onPress={go} disabled={busy} />
          <Button kind="wood" title="已经练完了，直接打卡" onPress={() => setDone({ name: card.title, version: card.version })} />
          <View style={s.foot}>
            <Text style={s.mutedText}>{card.warmup ? `先热身约 ${card.warmup.minutes} 分钟` : ""}</Text>
            <LinkButton title={more ? "收起" : "更多"} onPress={() => setMore(!more)} />
          </View>
          {more ? (
            <View style={s.more}>
              {card.warmup ? (
                <Fold title={`先热身，约 ${card.warmup.minutes} 分钟`}>
                  {card.warmup.steps.map((x, i) => <Text key={i} style={s.p}>{`${i + 1}. ${clean(x)}`}</Text>)}
                </Fold>
              ) : null}
              <TodayVersion today={today} lib={d.lib} targets={d.tr?.targets || {}} onCheckin={(name, version) => setDone({ name, version })} />
              <LinkButton title="完整计划 ›" onPress={() => router.push("/plan")} />
            </View>
          ) : null}
        </Panel>
      ) : (
        <Hero card={card} dots={dots} onRetry={load} />
      )}
      <DoneSheet
        open={done !== null}
        onClose={() => setDone(null)}
        session={done?.name || ""}
        version={done?.version || null}
        onDone={finished}
        onRest={() => { setDone(null); setRest(true); }}
      />
      <RestSheet open={rest} onClose={() => setRest(false)} onDone={finished} />
    </View>
  );
}

/** 大卡片上一行（同网页 heroCoach，§163）：IronM 正在看 / 出错了（带重试）/ 调整了今天 / 今天休息。 */
function CoachLine({ today }: { today: ReturnType<typeof useToday> }) {
  const line = heroLine(today.shown);
  if (!line) return null;
  return (
    <View style={[s.coach, line.tone === "error" && s.coachErr]} accessibilityLiveRegion="polite">
      <Text style={[s.coachText, line.tone === "error" && s.coachTextErr]}>{clean(line.text)}</Text>
      {line.tone === "error" ? <Button small title="重试" onPress={() => void today.retry()} /> : null}
    </View>
  );
}

/** 这周已练几次：一行字加一条进度（§176）。 */
function WeekBar({ w }: { w: ReturnType<typeof weekDots> }) {
  if (!w) return null;
  const pct = Math.min(100, Math.round((w.done / w.planned) * 100));
  return (
    <View style={s.weekBar} accessibilityLabel={w.label}>
      <Text style={s.weekText}>{`这周已练 ${w.done}/${w.planned} 次`}</Text>
      <View style={s.track}><View style={[s.fill, { width: `${pct}%` }]} /></View>
    </View>
  );
}

/** 没有今天的训练时（还没计划、休息、练完了、读不到）那张卡。 */
function Hero({ card, dots, onRetry }: { card: TodayCard; dots: ReturnType<typeof weekDots>; onRetry: () => void }) {
  if (card.kind === "failed") {
    return (
      <Panel>
        <Plank>训练</Plank>
        <Note>没读到今天的训练安排。</Note>
        <Button small kind="ghost" title="重试" onPress={onRetry} />
      </Panel>
    );
  }
  if (card.kind === "noPlan") {
    return (
      <Panel>
        <PixelText size={24}>还没有训练计划</PixelText>
        <T muted>让 IronM 按你的目标排一份，或者从方案里挑一套。</T>
        <View style={s.btnRow}>
          <Button small title="让 IronM 排一份" onPress={() => askCoach("帮我排一个每周训练计划")} />
          <Button small kind="ghost" title="从方案库挑" onPress={() => router.push({ pathname: "/atlas", params: { seg: "plans" } })} />
        </View>
        <WeekDots w={dots} />
      </Panel>
    );
  }
  if (card.kind === "plain") {
    return (
      <Panel>
        <PixelText size={24}>{card.title}</PixelText>
        {card.sub ? <T muted>{card.sub}</T> : null}
        <WeekDots w={dots} />
      </Panel>
    );
  }
  return (
    <Panel>
      <View style={s.questHead}>
        <Plank>今日委托</Plank>
        <Text style={s.mutedText}>{card.weekday}</Text>
      </View>
      {card.photo ? (
        <View>
          <Image source={{ uri: card.photo.url }} style={s.pic} resizeMode="cover" accessibilityIgnoresInvertColors />
          {card.photo.author ? (
            <Pressable accessibilityRole="link" onPress={() => card.photo?.page && Linking.openURL(card.photo.page)}>
              <Text style={s.credit}>{`照片：${card.photo.author}，${card.photo.license || ""}`}</Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
      <PixelText size={24}>{card.title}</PixelText>
      <T muted>{card.sub}</T>
      <View style={s.figs}>
        <Fig n={card.minutes} unit="分钟" />
        <Fig n={card.moves} unit="个动作" />
        {card.burn ? <Fig n={card.burn} unit="千卡" /> : null}
      </View>
      <View style={s.reward}>
        <LiveIcon name="trophy" size={16} color={color.accent} />
        <Text style={s.rewardText}>完成奖励：一颗星，连续打卡 +1</Text>
      </View>
      <WeekDots w={dots} />
    </Panel>
  );
}

const s = StyleSheet.create({
  coach: { flexDirection: "row", alignItems: "center", gap: space.s, backgroundColor: color.paperLight, borderRadius: 12, padding: space.s },
  coachErr: { backgroundColor: color.heatSoft },
  coachText: { flex: 1, color: color.ink, fontSize: 13, lineHeight: 19 },
  coachTextErr: { color: color.heat },
  quest: { padding: 18, gap: 14 },
  questTop: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between", gap: space.s },
  questTitle: { flex: 1, fontSize: 22, lineHeight: 28 },
  tags: { alignItems: "flex-end", gap: 6 },
  tag: { fontSize: 12, fontWeight: "700", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, overflow: "hidden" },
  tagCoral: { color: color.accentText, backgroundColor: color.accentSoft },
  tagGreen: { color: color.good, backgroundColor: color.goodSoft },
  weekBar: { flexDirection: "row", alignItems: "center", gap: 10 },
  weekText: { color: color.ink, fontSize: 13, fontWeight: "700" },
  track: { width: 100, height: 6, borderRadius: 999, backgroundColor: color.wood, overflow: "hidden" },
  fill: { height: 6, borderRadius: 999, backgroundColor: color.accent },
  list: { backgroundColor: color.paperLight, borderRadius: 18, paddingHorizontal: 14, paddingVertical: 4 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12 },
  rowLine: { borderTopWidth: 1, borderTopColor: color.wood },
  no: { width: 26, height: 26, borderRadius: 13, overflow: "hidden", backgroundColor: color.paper, textAlign: "center", lineHeight: 26, fontSize: 13, fontWeight: "700", color: color.ink },
  foot: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  wrap: { gap: space.l },
  alerts: { gap: space.s },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  h3: { color: color.ink, fontSize: 16, fontWeight: "700" },
  questHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.m },
  mutedText: { color: color.muted, fontSize: 14 },
  pic: { width: "100%", aspectRatio: 16 / 9, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, backgroundColor: color.paperLight },
  credit: { color: color.muted, fontSize: 11, marginTop: 2, textDecorationLine: "underline" },
  figs: { flexDirection: "row", flexWrap: "wrap", gap: space.l },
  reward: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, paddingHorizontal: space.s, paddingVertical: 6 },
  rewardText: { color: color.ink2, fontSize: 13, fontWeight: "600" },
  btnRow: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  move: { flexDirection: "row", alignItems: "center", gap: space.m, paddingVertical: 4 },
  moveText: { flex: 1, minWidth: 0 },
  moveName: { color: color.ink, fontSize: 15, fontWeight: "700" },
  moveNote: { color: color.muted, fontSize: 12 },
  cut: { color: color.heat },
  moveSets: { color: color.ink, fontSize: 15, fontWeight: "700" },
  more: { gap: space.m, borderTopWidth: 1, borderColor: color.woodLight, paddingTop: space.m },
});
