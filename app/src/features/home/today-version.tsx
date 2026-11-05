// 首页"更多"里今天的版本（同网页 todayVersion 的 compact 版）：今天练的动作和下次目标、"只有 30 分钟""今天有点累"、没用记录器直接打卡。
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { Chips, Fold } from "./bits";
import { clean, itemLine } from "./train-logic";
import type { Library, Session, Target, TodayVersion as TV } from "./types";

type Ok = Extract<TV, { status: "ok" }>;
const isOk = (v: TV): v is Ok => v.status === "ok";

export function TodayVersion({ lib, targets, onCheckin }: { lib: Library | null; targets: Record<string, Target>; onCheckin: (name: string, version: Session | null) => void }) {
  const [ask, setAsk] = useState<{ minutes: number | null; tired: boolean }>({ minutes: null, tired: false });
  const [v, setV] = useState<TV | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(async () => {
    const q: string[] = [];
    if (ask.minutes) q.push(`minutes=${ask.minutes}`);
    if (ask.tired) q.push("tired=true");
    setErr("");
    try {
      setV(await api<TV>(`/iron/api/today${q.length ? `?${q.join("&")}` : ""}`));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没读到今天的安排。");
    }
  }, [ask]);
  useEffect(() => { void load(); }, [load]);

  if (err) return <View style={s.box}><Note tone="error">{err}</Note><Button small kind="ghost" title="重试" onPress={load} /></View>;
  if (!v) return null;
  const toggles = (
    <Chips
      items={[["m30", "只有 30 分钟"], ["tired", "今天有点累"]] as const}
      isOn={(k) => (k === "m30" ? ask.minutes === 30 : ask.tired)}
      onTap={(k) => setAsk(k === "m30" ? { ...ask, minutes: ask.minutes === 30 ? null : 30 } : { ...ask, tired: !ask.tired })}
    />
  );
  if (!isOk(v)) {
    // 管家正在看、出错了、今天定了休息：照服务端说的写（§163）
    const say = "message" in v && v.message ? clean(v.message) : "";
    return say ? <View style={s.box}><Note>{say}</Note>{toggles}</View> : null;
  }
  const items = (v.changed ? v.today : v.original).items;
  return (
    <View style={s.box}>
      {v.changed ? (
        <Fold title="今天的版本按状态和天气调整过 · 为什么">
          <Text style={s.p}>{v.changes.map(clean).join("；")}</Text>
          <Text style={s.muted}>{`原因：${v.reasons.map(clean).join("；")}`}</Text>
          <Text style={s.muted}>{`原计划：${v.original.items.map((it) => itemLine(it, lib)).join("、")}`}</Text>
        </Fold>
      ) : null}
      {items.map((it, i) => {
        const tg = targets[it.exercise];
        return (
          <View key={`${it.exercise}-${i}`} style={s.li}>
            <Text style={s.p}>{`${i + 1}. ${itemLine(it, lib)}`}</Text>
            {tg && !v.changed ? <Text style={s.muted}>{`下次 ${clean(tg.text)}`}</Text> : null}
          </View>
        );
      })}
      {toggles}
      <Button kind="ghost" title="没用记录器，直接打卡" onPress={() => onCheckin(v.today.name, v.changed ? v.today : null)} />
    </View>
  );
}

const s = StyleSheet.create({
  box: { gap: space.s },
  li: { gap: 2 },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
});
