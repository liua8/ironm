// 排行榜的小组件（照网页版 rk-*）：顶上一条（返回、标题、右边按钮）、档位牌、名次、配图、名字和介绍、榜单里的一行。
import type { ReactNode } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { color, font, space } from "@/ui/theme";

import { imgUrl, lineMeta, rowNo, scoreText, trendKind } from "./logic";
import type { RankRow } from "./types";

/** 顶上一条：左边返回，中间标题，右边可放一个按钮。 */
export function RankBar({ back, onBack, title, right }: { back: string; onBack: () => void; title: string; right?: ReactNode }) {
  return (
    <View style={s.bar}>
      <Pressable accessibilityRole="button" accessibilityLabel={`返回${back}`} onPress={onBack} hitSlop={8} style={s.back}>
        <Text style={s.backText}>{`‹ ${back}`}</Text>
      </Pressable>
      <Text style={s.barTitle} numberOfLines={1} accessibilityRole="header">
        {title}
      </Text>
      {right ?? null}
    </View>
  );
}

const TIER_STYLE: Record<string, { bg: string; fg: string; border?: string }> = {
  hang: { bg: color.heat, fg: color.accentInk },
  top: { bg: color.fire, fg: color.accentInk },
  elite: { bg: color.accent, fg: color.accentInk },
  npc: { bg: "#c9d8cf", fg: color.ink },
  la: { bg: "#e1ebe5", fg: color.muted },
  wait: { bg: "transparent", fg: color.muted, border: color.woodLight },
};

export function TierTag({ tier, text, big }: { tier: string; text: string; big?: boolean }) {
  const t = TIER_STYLE[tier] ?? TIER_STYLE.wait;
  return (
    <View style={[s.tag, big && s.tagBig, { backgroundColor: t.bg, borderColor: t.border ?? t.bg }]}>
      <Text style={[s.tagText, big && s.tagTextBig, { color: t.fg }]}>{text}</Text>
    </View>
  );
}

export function tierColors(tier: string) {
  return TIER_STYLE[tier] ?? TIER_STYLE.wait;
}

/** 名次：前三名换颜色。 */
export function RankNo({ text }: { text: string }) {
  const n = Number(text);
  return <Text style={[s.no, n === 1 && s.no1, n === 2 && s.no2, n === 3 && s.no3]}>{text}</Text>;
}

/** 配图：有图用图，没有用同一种占位（不用表情符号，§104）。 */
export function RankPic({ x, small }: { x: { image: string | null; name: string }; small?: boolean }) {
  const size = small ? s.picSm : s.pic;
  if (x.image) return <Image source={{ uri: imgUrl(x.image) }} style={[size, s.picImg]} resizeMode="cover" accessibilityIgnoresInvertColors />;
  return (
    <View style={[size, s.picNone]}>
      <Text style={s.picMark}>{x.name.slice(0, 1)}</Text>
    </View>
  );
}

export function RankLabel({ x }: { x: { name: string; tag?: string; desc?: string } }) {
  return (
    <View style={s.label}>
      <Text style={s.name} numberOfLines={1}>
        {x.name}
        {x.tag ? <Text style={s.kind}>{` ${x.tag}`}</Text> : null}
      </Text>
      {x.desc ? (
        <Text style={s.desc} numberOfLines={1}>
          {x.desc}
        </Text>
      ) : null}
    </View>
  );
}

export function Trend({ t }: { t: string }) {
  if (!t) return null;
  const k = trendKind(t);
  return <Text style={[s.trend, k === "up" && s.up, k === "down" && s.down, k === "new" && s.new]}>{t}</Text>;
}

/** 榜单页的一行（同网页 rankLine）：名次、图、名字、档位、分数和趋势，下面一行几人评过、几条评论。 */
export function RankLine({ x, names, onPress }: { x: RankRow; names: Record<string, string>; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="link" accessibilityLabel={`${x.name}，第 ${x.rank ?? "–"} 名`} onPress={onPress} style={({ pressed }) => [s.line, pressed && s.pressed]}>
      <View style={s.lineTop}>
        <RankNo text={rowNo(1, x.rank)} />
        <RankPic x={x} />
        <RankLabel x={x} />
        {x.tier ? <TierTag tier={x.tier} text={names[x.tier] ?? x.tier} /> : null}
        <View style={s.right}>
          <Text style={s.score}>{scoreText(x)}</Text>
          <Trend t={x.trend} />
        </View>
      </View>
      <Text style={s.meta} numberOfLines={1}>
        {lineMeta(x)}
      </Text>
    </Pressable>
  );
}

/** 木框面板（列表、待评用）。 */
export function Box({ children, style }: { children: ReactNode; style?: object }) {
  return <View style={[s.box, style]}>{children}</View>;
}

export const rk = StyleSheet.create({
  none: { color: color.muted, fontSize: 14, lineHeight: 20, paddingVertical: 4 },
  score: { color: color.ink, fontWeight: "800", fontSize: 24, lineHeight: 28 },
});

const s = StyleSheet.create({
  bar: { flexDirection: "row", alignItems: "center", gap: space.s, minHeight: 40 },
  back: { backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, paddingHorizontal: 10, paddingVertical: 4 },
  backText: { color: color.ink2, fontSize: 15, fontWeight: "700" },
  barTitle: { flex: 1, color: color.ink, fontSize: 20, fontWeight: "800" },
  tag: { borderWidth: 1, paddingHorizontal: 6, paddingVertical: 1, alignSelf: "center" },
  tagBig: { paddingHorizontal: 10, paddingVertical: 3 },
  tagText: { fontSize: 12, fontWeight: "700" },
  tagTextBig: { fontSize: 16 },
  no: { width: 22, textAlign: "center", color: color.muted, fontWeight: "800", fontSize: 12 },
  no1: { color: color.heat },
  no2: { color: color.accentText },
  no3: { color: color.ink2 },
  pic: { width: 40, height: 40 },
  picSm: { width: 32, height: 32 },
  picImg: { borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: "#fff" },
  picNone: { borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: "#e9c784", alignItems: "center", justifyContent: "center" },
  picMark: { color: color.ink2, fontSize: 15, fontWeight: "800" },
  label: { flex: 1, minWidth: 0 },
  name: { color: color.ink, fontSize: 15, fontWeight: "600" },
  kind: { color: color.muted, fontSize: 12, fontWeight: "400" },
  desc: { color: color.muted, fontSize: 12 },
  trend: { fontSize: 12, color: color.muted },
  up: { color: color.heat },
  down: { color: color.accentText },
  new: { color: color.ink2 },
  line: { gap: 4, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: color.woodLight },
  pressed: { opacity: 0.7 },
  lineTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  right: { alignItems: "flex-end", minWidth: 36 },
  score: { color: color.ink, fontSize: 16, fontWeight: "700" },
  meta: { color: color.muted, fontSize: 12, paddingLeft: 30 },
  box: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, paddingHorizontal: space.m, paddingVertical: 10, gap: 4 },
});
