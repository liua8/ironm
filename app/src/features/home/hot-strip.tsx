// 首页最上面：今日热搜（同网页 spec §161）。露出前 3 条，整条点了进排行榜；没人搜、没人评时照实写。
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { color, font } from "@/ui/theme";

type Board = { top: { name: string; votes?: number; trend?: string }[] };
type Rank = { hot: { term: string; flag?: string }[]; boards: Board[] };
type Row = { name: string; flag?: string; people?: number };

export function rowsOf(d: Rank): Row[] {
  const hot = (d.hot ?? []).slice(0, 3).map((x) => ({ name: x.term, flag: x.flag }));
  if (hot.length) return hot;
  return d.boards
    .flatMap((b) => b.top.map((x) => ({ name: x.name, people: x.votes ?? 0, flag: x.trend === "↑" ? "升" : "" })))
    .sort((a, b) => (b.people ?? 0) - (a.people ?? 0))
    .slice(0, 3);
}

export function HotStrip() {
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => {
    api<Rank>("/iron/api/rank").then((d) => setRows(rowsOf(d))).catch(() => setRows(null));
  }, []);
  if (rows === null) return null;
  return (
    <Pressable accessibilityRole="link" accessibilityLabel="今日热搜，点开看排行榜" onPress={() => router.push("/rank")} style={s.strip}>
      <Text style={s.label}>今日热搜</Text>
      <View style={s.rows}>
        {rows.length ? (
          rows.map((x, i) => (
            <Text key={`${x.name}-${i}`} numberOfLines={1} style={s.row}>
              <Text style={s.no}>{i + 1} </Text>
              {x.name}
              {x.flag ? <Text style={s.flag}> {x.flag}</Text> : null}
            </Text>
          ))
        ) : (
          <Text style={s.muted}>排行榜刚开，去评第一个</Text>
        )}
      </View>
      <Text style={s.chev}>›</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  strip: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, paddingHorizontal: 12, paddingVertical: 10 },
  label: { fontWeight: "800", fontSize: 12, color: color.accentInk, backgroundColor: color.heat, paddingHorizontal: 6, paddingVertical: 3 },
  rows: { flex: 1, flexDirection: "row", gap: 12, overflow: "hidden" },
  row: { color: color.ink, fontSize: 14, flexShrink: 1 },
  no: { color: color.heat, fontWeight: "800" },
  flag: { color: color.heat, fontSize: 12 },
  muted: { color: color.muted, fontSize: 14 },
  chev: { color: color.muted, fontSize: 20 },
});
