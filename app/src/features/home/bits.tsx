// 首页·练、训练计划、训练记录器共用的小件：弹出页、动作小图、选项片、可展开的一段、一句短提示、本周的点。
import { router } from "expo-router";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import type { weekDots } from "./train-logic";

/** 弹出页（网页版的 sheet）：从下面滑上来，木框羊皮纸，右上角关闭。 */
export function Sheet({ title, open, onClose, children }: { title: string; open: boolean; onClose: () => void; children: ReactNode }) {
  return (
    <Modal visible={open} transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.backdrop}>
        <Pressable style={s.backdropTap} accessibilityLabel="关闭" onPress={onClose} />
        <SafeAreaView edges={["bottom"]} style={s.sheet}>
          <View style={s.sheetHead}>
            <Text style={s.sheetTitle} numberOfLines={2}>{title}</Text>
            <Pressable accessibilityRole="button" accessibilityLabel="关闭" hitSlop={10} onPress={onClose}>
              <Text style={s.close}>×</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={s.sheetBody} keyboardShouldPersistTaps="handled">{children}</ScrollView>
        </SafeAreaView>
      </View>
    </Modal>
  );
}

/** 动作小图：没有图时放一个空格子。 */
export function Thumb({ url, size = 48 }: { url: string; size?: number }) {
  if (!url) return <View style={[s.thumb, s.thumbNone, { width: size, height: size }]}><Text style={s.thumbIcon}>◆</Text></View>;
  return <Image source={{ uri: url }} resizeMode="contain" style={[s.thumb, { width: size, height: size }]} accessibilityIgnoresInvertColors />;
}

/** 一排可选的小片（精力、哪里酸、RPE 这类）。 */
export function Chips<K extends string | number>({ items, isOn, onTap, label }: { items: readonly (readonly [K, string])[]; isOn: (k: K) => boolean; onTap: (k: K) => void; label?: string }) {
  return (
    <View style={s.chips} accessibilityLabel={label}>
      {items.map(([k, w]) => {
        const on = isOn(k);
        return (
          <Pressable key={String(k)} accessibilityRole="button" accessibilityState={{ selected: on }} onPress={() => onTap(k)} style={[s.chip, on && s.chipOn]}>
            <Text style={[s.chipText, on && s.chipTextOn]}>{w}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

/** 可展开的一段（网页版的 details）。 */
export function Fold({ title, children, open: open0 = false, lead }: { title: string; children: ReactNode; open?: boolean; lead?: ReactNode }) {
  const [open, setOpen] = useState(open0);
  return (
    <View style={s.fold}>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={s.foldHead}>
        {lead}
        <Text style={s.foldTitle}>{title}</Text>
        <Text style={s.foldChev}>{open ? "▾" : "▸"}</Text>
      </Pressable>
      {open ? <View style={s.foldBody}>{children}</View> : null}
    </View>
  );
}

/** 一句短提示：过几秒自己消失（网页版的 flash；放在页面里，不浮在上面）。 */
export function useFlash(): [ReactNode, (text: ReactNode, ms?: number) => void] {
  const [msg, setMsg] = useState<ReactNode>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  const show = useCallback((text: ReactNode, ms = 2400) => {
    if (timer.current) clearTimeout(timer.current);
    setMsg(text);
    timer.current = setTimeout(() => setMsg(null), ms);
  }, []);
  const node = msg ? <View accessibilityLiveRegion="polite" style={s.flash}>{typeof msg === "string" ? <Text style={s.flashText}>{msg}</Text> : msg}</View> : null;
  return [node, show];
}

/** 本周的点：练过的点亮。 */
export function WeekDots({ w }: { w: ReturnType<typeof weekDots> }) {
  if (!w) return null;
  return (
    <View style={s.weekLine} accessibilityRole="image" accessibilityLabel={w.label}>
      <View style={s.dots}>
        {w.dots.map((on, i) => <View key={i} style={[s.dot, on && s.dotOn]} />)}
      </View>
      <Text style={s.weekText}>{w.label}</Text>
    </View>
  );
}

/** 一个大数字和单位（今日委托的分钟、动作数、千卡）。 */
export function Fig({ n, unit }: { n: string | number; unit: string }) {
  return (
    <View style={s.fig}>
      <PixelText size={24}>{String(n)}</PixelText>
      <Text style={s.figUnit}>{unit}</Text>
    </View>
  );
}

/** 问 IronM：带着一句话打开对话页（同网页 askCoach）。 */
export function askCoach(question: string) {
  router.push({ pathname: "/chat", params: { q: question } });
}

const s = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(40,20,5,0.45)", justifyContent: "flex-end" },
  backdropTap: { flex: 1 },
  sheet: { maxHeight: "88%", backgroundColor: color.paper, borderTopWidth: 4, borderColor: color.woodDark, borderLeftWidth: 4, borderRightWidth: 4, width: "100%", maxWidth: 720, alignSelf: "center" },
  sheetHead: { flexDirection: "row", alignItems: "center", gap: space.m, paddingHorizontal: space.l, paddingTop: space.m, paddingBottom: space.s, borderBottomWidth: 2, borderColor: color.wood },
  sheetTitle: { flex: 1, color: color.ink, fontSize: 17, fontWeight: "700" },
  close: { color: color.muted, fontSize: 28, lineHeight: 30 },
  sheetBody: { padding: space.l, gap: space.m, paddingBottom: space.xl },
  thumb: { backgroundColor: "#fff", borderWidth: 2, borderColor: color.wood },
  thumbNone: { alignItems: "center", justifyContent: "center", backgroundColor: color.paperLight },
  thumbIcon: { color: color.woodLight, fontSize: 18 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  chip: { paddingHorizontal: space.m, paddingVertical: 6, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood },
  chipOn: { backgroundColor: color.fire, borderColor: color.woodDark },
  chipText: { color: color.ink, fontSize: 14 },
  chipTextOn: { color: color.accentInk, fontWeight: "700" },
  fold: { borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight },
  foldHead: { flexDirection: "row", alignItems: "center", paddingHorizontal: space.m, paddingVertical: 10, gap: space.s },
  foldTitle: { flex: 1, color: color.ink, fontSize: 14, fontWeight: "600" },
  foldChev: { color: color.muted, fontSize: 14 },
  foldBody: { paddingHorizontal: space.m, paddingBottom: space.m, gap: space.s },
  flash: { backgroundColor: color.woodDark, paddingHorizontal: space.m, paddingVertical: 10, borderWidth: 2, borderColor: color.plank },
  flashText: { color: color.accentInk, fontSize: 14, lineHeight: 20 },
  weekLine: { flexDirection: "row", alignItems: "center", gap: space.s, flexWrap: "wrap" },
  dots: { flexDirection: "row", gap: 4 },
  dot: { width: 12, height: 12, borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight },
  dotOn: { backgroundColor: color.accent, borderColor: color.fire },
  weekText: { color: color.muted, fontSize: 13 },
  fig: { flexDirection: "row", alignItems: "baseline", gap: 4 },
  figUnit: { color: color.muted, fontSize: 13 },
});
