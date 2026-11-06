// 基本组件（spec §164 第一期；§176 照网页版 §175 换成白底圆角卡片风）：浅灰紫底、白色圆角卡片、粗体小节标题、珊瑚红圆角按钮、输入框。
// 组件名（Panel、Plank、PixelText）沿用第一期的，各页不用改调用。
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
import { router } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";

import { Mascot } from "@/features/chat/mascot";

import { Icon } from "./icons";

import { color, radius, shadow, space } from "./theme";

/** 一页：浅灰紫底，内容可以滚动。 */
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

/** 大字：大标题、小节标题、关键数字（§175 起是系统字体加粗）。 */
export function PixelText({ size = 24, style, ...rest }: TextProps & { size?: 12 | 24 | 36 | 48 }) {
  return <Text {...rest} style={[s.pixel, { fontSize: size, lineHeight: size * 1.25 }, style]} />;
}

/** 页标题（单独的页：计划、身体数据、饮食账单这类，标题写在返回链接下面）。 */
export function PageTitle({ children }: { children: ReactNode }) {
  return <PixelText size={24} style={s.pageTitle}>{children}</PixelText>;
}

/** 底栏几页的页头（§176，同网页顶栏）：左边企鹅标志和 IronM，中间页名，右边去"我"。 */
export function AppBar({ title }: { title: string }) {
  return (
    <View style={s.appBar} accessibilityRole="header">
      <View style={s.brand}>
        <View style={s.logo}><Mascot size={30} /></View>
        <Text style={s.brandText}>IronM</Text>
      </View>
      <Text style={s.appTitle}>{title}</Text>
      <View style={s.barEnd}>
        <Pressable accessibilityRole="button" accessibilityLabel="我" onPress={() => router.push("/me")} style={s.meBtn}>
          <Icon name="me" size={18} color={color.ink2} />
        </Pressable>
      </View>
    </View>
  );
}

/** 白色圆角卡片。 */
export function Panel({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  return <View style={[s.panel, style]}>{children}</View>;
}

/** 卡片里的小节标题。 */
export function Plank({ children }: { children: ReactNode }) {
  return (
    <View style={s.plank}>
      <PixelText size={24} style={s.plankText}>{children}</PixelText>
    </View>
  );
}

type ButtonKind = "primary" | "wood" | "ghost";

/** 按钮：primary 珊瑚红、wood 浅紫底、ghost 白底细边。 */
export function Button({ title, onPress, kind = "primary", disabled, small }: { title: string; onPress?: () => void; kind?: ButtonKind; disabled?: boolean; small?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [s.btn, s[`btn_${kind}`], kind === "primary" && !small && s.btnBig, small && s.btnSmall, (pressed || disabled) && s.btnDown, disabled && s.btnOff]}
    >
      <Text style={[s.btnText, kind === "primary" && !small && s.btnTextBig, kind === "ghost" ? s.btnTextGhost : kind === "wood" ? s.btnTextWood : null, small && s.btnTextSmall]}>{title}</Text>
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
  pixel: { color: color.ink, fontWeight: "800" },
  pageTitle: { color: color.ink },
  appBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  brand: { flex: 1, flexDirection: "row", alignItems: "center", gap: 8 },
  logo: { width: 36, height: 36, borderRadius: 11, backgroundColor: "#fff3c4", alignItems: "center", justifyContent: "center", ...shadow },
  brandText: { color: color.ink, fontSize: 19, fontWeight: "800" },
  appTitle: { color: color.ink2, fontSize: 16, fontWeight: "600" },
  barEnd: { flex: 1, alignItems: "flex-end" },
  meBtn: { width: 38, height: 38, borderRadius: 19, backgroundColor: color.paper, alignItems: "center", justifyContent: "center", ...shadow },
  panel: { backgroundColor: color.paper, borderRadius: radius.m, padding: space.l, gap: space.m, ...shadow },
  plank: { alignSelf: "flex-start" },
  plankText: { color: color.ink, fontSize: 20, lineHeight: 26 },
  btn: { borderRadius: radius.pill, paddingVertical: 14, paddingHorizontal: space.l, alignItems: "center" },
  btn_primary: { backgroundColor: color.fire },
  btnBig: { backgroundColor: color.accent },  // 大按钮：亮珊瑚红配 19 号粗字（大字 3:1 看得清，同网页 §175）
  btn_wood: { backgroundColor: color.iconBg },
  btn_ghost: { backgroundColor: color.paper, borderWidth: 1, borderColor: color.wood },
  btnSmall: { paddingVertical: 9, paddingHorizontal: space.m },
  btnDown: { opacity: 0.85 },
  btnOff: { opacity: 0.5 },
  btnText: { color: color.accentInk, fontSize: 16, fontWeight: "700" },
  btnTextBig: { fontSize: 19, fontWeight: "800" },
  btnTextGhost: { color: color.ink },
  btnTextWood: { color: "#2d2d4a" },
  btnTextSmall: { fontSize: 14 },
  link: { color: color.accentText, fontSize: 14, fontWeight: "600", paddingVertical: 4 },
  field: { backgroundColor: color.paper, borderWidth: 1, borderColor: color.wood, borderRadius: radius.s, paddingHorizontal: space.m, paddingVertical: 12, fontSize: 16, color: color.ink },
  seg: { flexDirection: "row", gap: 4, padding: 4, backgroundColor: color.iconBg, borderRadius: radius.pill },
  segItem: { flex: 1, alignItems: "center", paddingVertical: 9, borderRadius: radius.pill },
  segOn: { backgroundColor: color.fire },
  segText: { color: color.ink2, fontSize: 15, fontWeight: "600" },
  segTextOn: { color: color.accentInk, fontWeight: "700" },
  note: { fontSize: 14, lineHeight: 20 },
  note_error: { color: color.heat },
  note_muted: { color: color.muted },
  note_ok: { color: color.good },
});
