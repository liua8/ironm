// 以前的对话（同网页版 historySheet，spec §36）：从下面弹出的列表，标题和时间，点开回到那段对话。
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { apiData, errorText } from "./api";
import { sessionTime } from "./text";

type Summary = { session_id: string; summary?: string; timestamp?: string };

export function HistorySheet({ visible, current, onClose, onPick }: { visible: boolean; current: string | null; onClose: () => void; onPick: (id: string) => void }) {
  const insets = useSafeAreaInsets();
  const [list, setList] = useState<Summary[] | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setList(null);
    setError("");
    try {
      setList(((await apiData<{ summaries?: Summary[] }>("/api/history")).summaries ?? []).slice(0, 50));
    } catch (err) {
      setError(errorText(err, "没读到以前的对话，请再试一次。"));
    }
  }, []);

  useEffect(() => {
    if (visible) void load();
  }, [visible, load]);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.back}>
        <Pressable style={s.dim} accessibilityRole="button" accessibilityLabel="关闭" onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: space.l + insets.bottom }]}>
          <View style={s.head}>
            <Text style={s.title}>以前的对话</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="关闭" onPress={onClose} hitSlop={10} style={s.close}>
              <Text style={s.closeText}>×</Text>
            </Pressable>
          </View>
          {error ? (
            <View style={s.state}>
              <Text style={s.error}>{error}</Text>
              <Button small kind="ghost" title="再试一次" onPress={load} />
            </View>
          ) : !list ? (
            <View style={s.state}>
              <ActivityIndicator color={color.accent} />
            </View>
          ) : !list.length ? (
            <View style={s.state}>
              <Text style={s.muted}>还没有以前的对话。</Text>
            </View>
          ) : (
            <ScrollView style={s.list} contentContainerStyle={s.listBody}>
              {list.map((x) => {
                const on = x.session_id === current;
                return (
                  <Pressable
                    key={x.session_id}
                    accessibilityRole="button"
                    onPress={() => onPick(x.session_id)}
                    style={({ pressed }) => [s.row, on && s.rowOn, pressed && s.rowDown]}
                  >
                    <View style={s.main}>
                      <Text style={s.rowTitle} numberOfLines={2}>{x.summary || "（没有标题）"}</Text>
                      <Text style={s.muted}>{sessionTime(x.timestamp)}</Text>
                    </View>
                    <Text style={on ? s.now : s.chev}>{on ? "当前" : "›"}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  back: { flex: 1, justifyContent: "flex-end" },
  dim: { ...StyleSheet.absoluteFill, backgroundColor: "rgba(40,20,5,0.45)" },
  sheet: { maxHeight: "80%", backgroundColor: color.paper, borderTopWidth: 1, borderColor: color.woodDark, paddingHorizontal: space.l, paddingTop: space.m, gap: space.m, width: "100%", maxWidth: 720, alignSelf: "center" },
  head: { flexDirection: "row", alignItems: "center" },
  title: { flex: 1, color: color.ink, fontSize: 18, fontWeight: "700" },
  close: { width: 32, height: 32, alignItems: "center", justifyContent: "center" },
  closeText: { color: color.muted, fontSize: 26, lineHeight: 28 },
  state: { paddingVertical: space.xl, alignItems: "center", gap: space.m },
  list: { flexGrow: 0 },
  listBody: { gap: space.s, paddingBottom: space.s },
  row: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, paddingHorizontal: space.m, paddingVertical: 10 },
  rowOn: { borderColor: color.accent },
  rowDown: { opacity: 0.7 },
  main: { flex: 1, minWidth: 0, gap: 2 },
  rowTitle: { color: color.ink, fontSize: 15, lineHeight: 21 },
  muted: { color: color.muted, fontSize: 12 },
  now: { color: color.accentText, fontSize: 12, fontWeight: "700" },
  chev: { color: color.muted, fontSize: 20 },
  error: { color: color.heat, fontSize: 14, textAlign: "center" },
});
