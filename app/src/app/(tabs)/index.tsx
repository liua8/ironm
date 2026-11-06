// 首页（同网页 §175，spec §176）：一页里放练和吃——日期和今天练什么、IronM 入口；今日热搜；没填模型时的提示（§167）；
// 今日委托卡；今天吃卡（"饮食账单"进整页）。
import { router, useFocusEffect } from "expo-router";
import { useCallback, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { Mascot } from "@/features/chat/mascot";
import { EatSection } from "@/features/eat/eat";
import { HotStrip } from "@/features/home/hot-strip";
import { TrainSection } from "@/features/home/train";
import { ModelHint } from "@/features/me/need-model";
import { AppBar, Screen } from "@/ui/pixel";
import { color, radius, shadow } from "@/ui/theme";

const WEEKDAY = "日一二三四五六";

export default function Home() {
  // 回到首页时让"今天吃"重读（第一次进来不用，它自己会读）
  const [refresh, setRefresh] = useState(0);
  const seen = useRef(false);
  useFocusEffect(useCallback(() => {
    if (seen.current) setRefresh((n) => n + 1);
    seen.current = true;
  }, []));
  return (
    <Screen>
      <AppBar title="首页" />
      <View style={s.top}>
        <View style={s.day}>
          <View style={s.dot} />
          <Text style={s.dayText}>{`周${WEEKDAY[new Date().getDay()]} · 今天`}</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel="进 IronM 对话" onPress={() => router.push("/chat")} style={s.pill}>
          <View style={s.pillFace}><Mascot size={32} /></View>
          <View>
            <Text style={s.pillName}>IronM</Text>
            <Text style={s.pillGo}>点一下进 IronM ›</Text>
          </View>
        </Pressable>
      </View>
      <HotStrip />
      <ModelHint />
      <TrainSection />
      <EatSection compact refresh={refresh} />
    </Screen>
  );
}

const s = StyleSheet.create({
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 10 },
  day: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.good },
  dayText: { color: color.ink, fontSize: 15, fontWeight: "700" },
  pill: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, paddingLeft: 6, paddingRight: 14, borderRadius: radius.pill, backgroundColor: color.paper, ...shadow },
  pillFace: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#fff3c4", alignItems: "center", justifyContent: "center" },
  pillName: { color: color.ink, fontSize: 14, fontWeight: "700" },
  pillGo: { color: color.accentText, fontSize: 12, fontWeight: "600" },
});
