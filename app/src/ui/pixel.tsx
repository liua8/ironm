// 像素农场风的基本组件（spec §164 第一期，照网页版 §131）：草地底、木框羊皮纸面板、木牌标题、木板按钮、输入框。
import type { ReactNode } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  type TextInputProps,
  TextInput,
  type TextProps,
  View,
  type ViewStyle,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { color, font, space } from "./theme";

/** 一页：草地底，内容可以滚动。 */
export function Screen({ children, scroll = true }: { children: ReactNode; scroll?: boolean }) {
  const body = <View style={s.screenBody}>{children}</View>;
  return (
    <SafeAreaView style={s.screen} edges={["top", "left", "right"]}>
      {scroll ? <ScrollView contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">{body}</ScrollView> : body}
    </SafeAreaView>
  );
}

/** 正文（系统字体）。 */
export function T({ style, muted, ...rest }: TextProps & { muted?: boolean }) {
  return <Text {...rest} style={[s.text, muted && s.muted, style]} />;
}

/** 像素字：只给大标题、木牌、关键数字，字号用 12 的整数倍。 */
export function PixelText({ size = 24, style, ...rest }: TextProps & { size?: 12 | 24 | 36 | 48 }) {
  return <Text {...rest} style={[s.pixel, { fontSize: size, lineHeight: size * 1.25 }, style]} />;
}

/** 页标题：大号像素字，带一道木色投影。 */
export function PageTitle({ children }: { children: ReactNode }) {
  return <PixelText size={36} style={s.pageTitle}>{children}</PixelText>;
}

/** 木框羊皮纸面板。 */
export function Panel({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return (
    <View style={[s.panelOuter, style]}>
      <View style={s.panelInner}>{children}</View>
    </View>
  );
}

/** 木牌标题（面板左上角那块）。 */
export function Plank({ children }: { children: ReactNode }) {
  return (
    <View style={s.plank}>
      <PixelText size={24} style={s.plankText}>{children}</PixelText>
    </View>
  );
}

type ButtonKind = "primary" | "wood" | "ghost";

/** 木板按钮。 */
export function Button({ title, onPress, kind = "primary", disabled, small }: { title: string; onPress?: () => void; kind?: ButtonKind; disabled?: boolean; small?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [s.btn, s[`btn_${kind}`], small && s.btnSmall, (pressed || disabled) && s.btnDown, disabled && s.btnOff]}
    >
      <Text style={[s.btnText, kind === "ghost" ? s.btnTextGhost : null, small && s.btnTextSmall]}>{title}</Text>
    </Pressable>
  );
}

/** 文字链接样的按钮。 */
export function LinkButton({ title, onPress }: { title: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} hitSlop={8}>
      <Text style={s.link}>{title}</Text>
    </Pressable>
  );
}

/** 输入框。 */
export function Field(props: TextInputProps) {
  return <TextInput placeholderTextColor={color.muted} {...props} style={[s.field, props.style]} />;
}

/** 两三段的切换条（登录 / 注册这类）。 */
export function Seg<K extends string>({ items, value, onChange }: { items: readonly (readonly [K, string])[]; value: K; onChange: (k: K) => void }) {
  return (
    <View style={s.seg} accessibilityRole="tablist">
      {items.map(([k, label]) => (
        <Pressable key={k} accessibilityRole="tab" accessibilityState={{ selected: k === value }} onPress={() => onChange(k)} style={[s.segItem, k === value && s.segOn]}>
          <Text style={[s.segText, k === value && s.segTextOn]}>{label}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** 一句提示：error 红、muted 灰、ok 绿。 */
export function Note({ tone = "muted", children }: { tone?: "error" | "muted" | "ok"; children: ReactNode }) {
  if (!children) return null;
  return <Text accessibilityLiveRegion="polite" style={[s.note, s[`note_${tone}`]]}>{children}</Text>;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: color.grass },
  scroll: { flexGrow: 1 },
  screenBody: { flexGrow: 1, width: "100%", maxWidth: 720, alignSelf: "center", paddingHorizontal: space.l, paddingTop: space.m, paddingBottom: space.xl, gap: space.l },
  text: { color: color.ink, fontSize: 15, lineHeight: 24 },
  muted: { color: color.muted },
  pixel: { fontFamily: font.pixel, color: color.ink },
  pageTitle: { color: color.paperLight, textShadowColor: color.woodDark, textShadowOffset: { width: 3, height: 3 }, textShadowRadius: 0 },
  panelOuter: { backgroundColor: color.woodDark, padding: 3 },
  panelInner: { backgroundColor: color.paper, borderWidth: 4, borderColor: color.wood, padding: space.l, gap: space.m },
  plank: { alignSelf: "flex-start", backgroundColor: color.plank, borderWidth: 3, borderColor: color.woodDark, paddingHorizontal: space.m, paddingVertical: 2 },
  plankText: { color: color.accentInk },
  btn: { borderWidth: 3, borderColor: color.woodDark, paddingVertical: 12, paddingHorizontal: space.l, alignItems: "center", borderBottomWidth: 6 },
  btn_primary: { backgroundColor: color.fire },
  btn_wood: { backgroundColor: color.plank },
  btn_ghost: { backgroundColor: color.paperLight, borderColor: color.wood },
  btnSmall: { paddingVertical: 8, paddingHorizontal: space.m },
  btnDown: { borderBottomWidth: 3, marginTop: 3 },
  btnOff: { opacity: 0.55 },
  btnText: { color: color.accentInk, fontSize: 16, fontWeight: "700" },
  btnTextGhost: { color: color.ink },
  btnTextSmall: { fontSize: 14 },
  link: { color: color.accentText, fontSize: 14, fontWeight: "600", paddingVertical: 4 },
  field: { backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: space.m, paddingVertical: 12, fontSize: 16, color: color.ink },
  seg: { flexDirection: "row", gap: space.s },
  segItem: { flex: 1, alignItems: "center", paddingVertical: 10, backgroundColor: color.paper, borderWidth: 2, borderColor: color.wood },
  segOn: { backgroundColor: color.plank, borderColor: color.woodDark },
  segText: { color: color.muted, fontSize: 15, fontWeight: "600" },
  segTextOn: { color: color.accentInk },
  note: { fontSize: 14, lineHeight: 20 },
  note_error: { color: color.heat },
  note_muted: { color: color.muted },
  note_ok: { color: color.accentText },
});
