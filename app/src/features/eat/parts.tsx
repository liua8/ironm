// 干饭这一块共用的小件：底部弹出页、餐次小圆片、食物色块（照网页版 openSheet / pills / foodTile），像素农场风。
import type { ReactNode } from "react";
import { Image, KeyboardAvoidingView, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { API_BASE } from "@/config";
import { LinkButton, PixelText, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { foodInitial } from "./logic";
import type { FoodImage } from "./types";

/** 底部弹出页：点外面或"关闭"收起。 */
export function Sheet({ title, visible, onClose, children }: { title: string; visible: boolean; onClose: () => void; children: ReactNode }) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={s.backdrop}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="关闭" />
        <SafeAreaView edges={["bottom"]} style={s.sheet}>
          <View style={s.head}>
            <PixelText size={24} style={s.title} numberOfLines={2}>{title}</PixelText>
            <LinkButton title="关闭" onPress={onClose} />
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.body}>{children}</ScrollView>
        </SafeAreaView>
      </KeyboardAvoidingView>
    </Modal>
  );
}

/** 一排小圆片（选哪一餐、油量）。 */
export function Pills<K extends string>({ items, value, onChange, label }: { items: readonly K[]; value: K; onChange: (k: K) => void; label?: string }) {
  return (
    <View style={s.pills} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {items.map((k) => (
        <Pressable key={k} accessibilityRole="radio" accessibilityState={{ selected: k === value }} onPress={() => onChange(k)} style={[s.pill, k === value && s.pillOn]}>
          <Text style={[s.pillText, k === value && s.pillTextOn]}>{k}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** 小标题（弹出页里分段用）。 */
export function SubTitle({ children }: { children: ReactNode }) {
  return <T style={s.sub}>{children}</T>;
}

/** 一组"结论 / 怎么算的 / 依据"。 */
export function Facts({ items }: { items: [string, string][] }) {
  return (
    <View style={s.facts}>
      {items.map(([k, v]) => (
        <View key={k} style={s.fact}>
          <T muted style={s.factKey}>{k}</T>
          <T style={s.factVal}>{v}</T>
        </View>
      ))}
    </View>
  );
}

/** 配图的完整地址：服务端给的是相对地址。 */
export function imageUri(im: FoodImage | undefined): string | null {
  if (!im?.url) return null;
  return /^https?:/.test(im.url) ? im.url : `${API_BASE}${im.url}`;
}

/** 食物的图：有配图用配图；没有的木框色块里写名字的第一个字。 */
export function FoodTile({ name, image, size = 40, dim }: { name: string; image?: FoodImage; size?: number; dim?: boolean }) {
  const uri = imageUri(image);
  return (
    <View style={[s.tile, { width: size, height: size }, dim && s.dim]} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {uri ? <Image source={{ uri }} style={s.tileImg} resizeMode="cover" /> : <Text style={[s.tileText, { fontSize: Math.round(size * 0.4) }]}>{foodInitial(name)}</Text>}
    </View>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(58,30,8,0.45)" },
  sheet: { maxHeight: "88%", backgroundColor: color.paper, borderTopWidth: 1, borderColor: color.woodDark, width: "100%", maxWidth: 720, alignSelf: "center" },
  head: { flexDirection: "row", alignItems: "center", gap: space.m, paddingHorizontal: space.l, paddingTop: space.m, paddingBottom: space.s, borderBottomWidth: 1, borderColor: color.woodLight },
  title: { flex: 1, minWidth: 0 },
  body: { padding: space.l, gap: space.m, paddingBottom: space.xl },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  pill: { paddingHorizontal: space.m, paddingVertical: 6, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight },
  pillOn: { backgroundColor: color.amber, borderColor: "#8a5a10" },
  pillText: { color: color.ink, fontSize: 14, fontWeight: "600" },
  pillTextOn: { color: color.ink2 },
  sub: { fontWeight: "700", fontSize: 16 },
  facts: { gap: space.s },
  fact: { gap: 2 },
  factKey: { fontSize: 13, lineHeight: 18 },
  factVal: { fontSize: 14, lineHeight: 21 },
  tile: { alignItems: "center", justifyContent: "center", overflow: "hidden", borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: "#e9c784" },
  tileImg: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  tileText: { color: color.ink2, fontWeight: "700" },
  dim: { opacity: 0.55 },
});
