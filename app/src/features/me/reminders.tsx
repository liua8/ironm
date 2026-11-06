// "我 → 设置"里的提醒（spec §164 第四期细则第三条）：训练日提醒默认关，时间自己定、能关；
// 只按计划里排的训练日提醒，计划没排的那天不响，App 不自己判断"该不该练"。组间休息到点提醒在训练页里自动排，这里只说明。
// 都是手机本地通知，不经过外部推送服务；网页预览收不到通知，只写明要在手机 App 里用。
import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import type { Session, Training } from "@/features/home/types";
import { Caption, kit, Pills, Sub } from "@/features/record/kit";
import {
  DEFAULT_TRAIN_REMINDER, ensurePermission, hhmm, loadTrainReminder, notifySupported, planDaysText, saveTrainReminder, scheduleTraining,
  syncTrainingReminder, type TrainReminder, WEB_TEXT,
} from "@/lib/notify";
import { Note, PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

type Msg = { tone: "error" | "muted" | "ok"; text: string };
const quiet: Msg = { tone: "muted", text: "" };
const ONOFF = [["off", "关"], ["on", "开"]] as const;

/** 时、分各一个 − / +：不装时间选择器的包，时 1 小时一档、分 5 分钟一档，转一圈回到头。 */
function TimeStep({ label, value, onDown, onUp }: { label: string; value: string; onDown: () => void; onUp: () => void }) {
  return (
    <View style={s.step}>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label}减`} onPress={onDown} hitSlop={4} style={s.stepBtn}><Text style={s.stepSign}>−</Text></Pressable>
      <View style={s.stepVal}>
        <PixelText size={24}>{value}</PixelText>
        <Text style={s.unit}>{label}</Text>
      </View>
      <Pressable accessibilityRole="button" accessibilityLabel={`${label}加`} onPress={onUp} hitSlop={4} style={s.stepBtn}><Text style={s.stepSign}>+</Text></Pressable>
    </View>
  );
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** 提醒设置：放在"我 → 设置"的弹出页里，不用传参数；改了马上生效（存在这台设备上、重排通知）。 */
export function ReminderBox() {
  const [v, setV] = useState<TrainReminder | null>(null);
  const [sessions, setSessions] = useState<Session[] | null>(null);  // 现在计划的训练日；null 是没读到
  const [noPlan, setNoPlan] = useState(false);
  const [msg, setMsg] = useState<Msg>(quiet);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  useEffect(() => {
    if (!notifySupported()) return;
    void (async () => {
      const [saved, tr] = await Promise.all([loadTrainReminder(), api<Training>("/iron/api/training").catch(() => null)]);
      if (!mounted.current) return;
      setV(saved);
      if (tr) {
        setSessions(tr.plan?.sessions ?? []);
        setNoPlan(!tr.plan);
      }
      // 开着的：看一眼权限还在不在（不弹窗），不在就如实说
      if (saved.on) {
        const p = await ensurePermission(false);
        if (mounted.current && !p.ok) setMsg({ tone: "error", text: p.why });
      }
    })();
  }, []);

  // 改了就存、按计划重排；计划没读到（没网）时只存设置，下次回到 App 再按计划排
  const apply = useCallback(async (next: TrainReminder) => {
    setV(next);
    try {
      await saveTrainReminder(next);
    } catch {
      setMsg({ tone: "error", text: "设置没存上，请再试一次。" });
      return;
    }
    if (!sessions) {
      const p = next.on ? await syncTrainingReminder() : await scheduleTraining(next, []);
      if (mounted.current) setMsg(p && !p.ok ? { tone: "error", text: p.why } : quiet);
      return;
    }
    const p = await scheduleTraining(next, sessions);
    if (!mounted.current) return;
    setMsg(p.ok ? quiet : { tone: "error", text: p.why });
  }, [sessions]);

  if (!notifySupported()) {
    return (
      <View style={kit.card}>
        <Sub>训练日提醒、组间休息到点提醒</Sub>
        <Caption>{WEB_TEXT}</Caption>
      </View>
    );
  }
  if (!v) return <Caption>正在读取…</Caption>;

  const days = sessions ? planDaysText(sessions) : "";
  const plan = noPlan || (sessions && !sessions.length)
    ? "现在还没有训练计划：有了计划后，按计划里的训练日提醒。"
    : days
      ? `按计划在${days}的 ${hhmm(v)} 提醒。计划改了，提醒的日子跟着改。`
      : `按计划里的训练日在 ${hhmm(v)} 提醒。`;
  return (
    <>
      <View style={kit.card}>
        <Sub>训练日提醒</Sub>
        <Pills options={ONOFF} value={v.on ? "on" : "off"} onPick={(k) => void apply({ ...v, on: k === "on" })} label="训练日提醒开关" />
        {v.on ? (
          <>
            <View style={s.time}>
              <TimeStep label="时" value={pad2(v.hour)} onDown={() => void apply({ ...v, hour: (v.hour + 23) % 24 })} onUp={() => void apply({ ...v, hour: (v.hour + 1) % 24 })} />
              <TimeStep label="分" value={pad2(v.minute)} onDown={() => void apply({ ...v, minute: (Math.ceil(v.minute / 5) * 5 + 55) % 60 })} onUp={() => void apply({ ...v, minute: (Math.floor(v.minute / 5) * 5 + 5) % 60 })} />
            </View>
            <Caption>{plan}</Caption>
          </>
        ) : (
          <Caption>{`关着。打开后按计划里的训练日提醒，时间自己定（默认 ${hhmm(DEFAULT_TRAIN_REMINDER)}）。`}</Caption>
        )}
        <Note tone={msg.tone}>{msg.text}</Note>
      </View>
      <View style={kit.card}>
        <Sub>组间休息到点</Sub>
        <Caption>训练中每组打勾后开始休息倒计时，到点提醒，App 在后台也响。训练页右上角的铃铛管声音：关了只振动、通知不出声。</Caption>
      </View>
    </>
  );
}

/**
 * 回到 App 时按现在的计划重排训练日提醒（计划在别的设备或对话里改了也能跟上）。
 * 放在登录后的页面里（比如标签页的布局）用一次；提醒关着时什么也不做。
 */
export function useTrainingReminderSync(): void {
  useEffect(() => {
    if (!notifySupported()) return;
    void syncTrainingReminder();
    const sub = AppState.addEventListener("change", (st) => {
      if (st === "active") void syncTrainingReminder();
    });
    return () => sub.remove();
  }, []);
}

const s = StyleSheet.create({
  time: { flexDirection: "row", gap: space.s },
  step: { flex: 1, flexDirection: "row", alignItems: "center", gap: 4 },
  stepBtn: { width: 36, height: 40, alignItems: "center", justifyContent: "center", backgroundColor: color.plank, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark },
  stepSign: { color: color.accentInk, fontSize: 20, fontWeight: "700" },
  stepVal: { flex: 1, alignItems: "center" },
  unit: { color: color.muted, fontSize: 13 },
});
