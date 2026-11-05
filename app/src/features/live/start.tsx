// 开练、继续训练（同网页 startLive、checkLive、liveEntry）：训练存在服务端，开始后打开训练页。
import { router } from "expo-router";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { liveMinutes } from "@/features/home/train-logic";

import { LiveIcon } from "./icons";
import type { Live } from "./logic";

export type StartBody = { today_plan?: boolean; free?: boolean; exercises?: string[] };

/** 进行中的训练；读不到当作没有。 */
export async function checkLive(): Promise<Live | null> {
  try {
    return (await api<{ live: Live | null }>("/iron/api/live")).live;
  } catch {
    return null;
  }
}

/** 开始（或接着）训练，然后打开训练页；出错时返回说明。 */
export async function startLive(body: StartBody, { stay = false }: { stay?: boolean } = {}): Promise<string> {
  try {
    await api("/iron/api/live/start", { method: "POST", json: body });
  } catch (err) {
    return err instanceof Error ? err.message : "没有成功，请再试一次。";
  }
  if (!stay) router.push("/live");
  return "";
}

/** 首页上的"训练进行中 / 继续"一行；没有进行中的训练时是"开始训练"按钮。 */
export function LiveEntry({ live, onPress, label = "开始训练" }: { live: Live | null; onPress: () => void; label?: string }) {
  if (live) {
    const mins = liveMinutes(live.started);
    return (
      <Pressable accessibilityRole="button" accessibilityLabel={`训练进行中，已开始 ${mins} 分钟，点这里继续记`} onPress={onPress} style={({ pressed }) => [s.entry, pressed && s.pressed]}>
        <LiveIcon name="timer" size={24} color={color.fire} />
        <View style={s.main}>
          <Text style={s.title}>训练进行中</Text>
          <Text style={s.sub}>{`已开始 ${mins} 分钟，点这里继续记`}</Text>
        </View>
        <Text style={s.end}>继续 ›</Text>
      </Pressable>
    );
  }
  return <Button title={label} onPress={onPress} />;
}

const s = StyleSheet.create({
  entry: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.goodSoft, borderWidth: 3, borderColor: color.fire, paddingHorizontal: space.m, paddingVertical: space.m },
  pressed: { opacity: 0.8 },
  main: { flex: 1, minWidth: 0 },
  title: { color: color.ink, fontSize: 16, fontWeight: "700" },
  sub: { color: color.muted, fontSize: 13 },
  end: { color: color.accentText, fontSize: 15, fontWeight: "700" },
});
