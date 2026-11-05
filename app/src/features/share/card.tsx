// 分享卡本身（同网页 drawCard，spec §147）：像素农场风——草地格子底、木框羊皮纸、木牌标题、三个大数、下面几行、IronM 落款。
// 网页在 canvas 上画；手机上画成一个普通的 View，再用 view-shot 把这个 View 存成图片（share.tsx）。
// 像素字只给木牌、大数和落款（§135），其余用系统字。
import type { ComponentRef, ReactNode, Ref } from "react";
import { StyleSheet, Text, View } from "react-native";
import Svg, { Defs, Pattern, Rect } from "react-native-svg";

import { PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import type { CardData } from "./logic";

/** View 挂上去的实例（RN 0.88 的 View 是函数组件，实例类型要这样取）。 */
export type CardHost = ComponentRef<typeof View>;

/** 草地格子：24 一格的浅深两色棋盘，和网页卡片、网页底色一样。 */
function Grass() {
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
      <Defs>
        <Pattern id="grass" width={24} height={24} patternUnits="userSpaceOnUse">
          <Rect x={0} y={0} width={12} height={12} fill={color.grassDark} />
          <Rect x={12} y={12} width={12} height={12} fill={color.grassDark} />
        </Pattern>
      </Defs>
      <Rect x={0} y={0} width="100%" height="100%" fill="url(#grass)" />
    </Svg>
  );
}

/** 一张分享卡；ref 交给 view-shot 截图用，所以最外层不能被安卓优化掉（collapsable）。photo：打卡照片，放在标题下面。 */
export function ShareCard({ card, photo, ref }: { card: CardData; photo?: ReactNode; ref?: Ref<CardHost> }) {
  return (
    <View ref={ref} collapsable={false} style={s.root} accessibilityRole="image" accessibilityLabel={`${card.title}，${card.date}，${card.head}`}>
      <Grass />
      <View style={s.frame}>
        <View style={s.paper}>
          <View style={s.top}>
            <View style={s.plank}>
              <PixelText size={24} style={s.plankText}>{card.title}</PixelText>
            </View>
            <Text style={s.date}>{card.date}</Text>
          </View>
          {photo ? <View style={s.photo}>{photo}</View> : null}
          <View>
            <Text style={s.head} numberOfLines={1}>{card.head}</Text>
            {card.sub ? <Text style={s.sub} numberOfLines={2}>{card.sub}</Text> : null}
          </View>
          <View style={s.stats}>
            {card.stats.map((x) => (
              <View key={x.name} style={s.stat}>
                <Text style={s.statName}>{x.name}</Text>
                <Text numberOfLines={1}>
                  <PixelText size={36}>{x.value}</PixelText>
                  {x.unit ? <Text style={s.unit}>{` ${x.unit}`}</Text> : null}
                </Text>
              </View>
            ))}
          </View>
          <View style={s.rule} />
          {card.lines.map((x) => (
            <View key={x.text} style={s.line}>
              <Text style={[s.mark, x.red && s.markRed]}>{x.mark}</Text>
              <Text style={s.lineText} numberOfLines={2}>{x.text}</Text>
            </View>
          ))}
          <View style={s.foot}>
            <PixelText size={24} style={s.brand}>IronM</PixelText>
            <Text style={s.footText}>{card.foot}</Text>
          </View>
        </View>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { width: "100%", maxWidth: 360, alignSelf: "center", backgroundColor: color.grass, padding: space.l, overflow: "hidden" },
  frame: { backgroundColor: color.woodDark, padding: 3 },
  paper: { backgroundColor: color.paper, borderWidth: 4, borderColor: color.wood, padding: space.l, gap: space.m },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s },
  plank: { backgroundColor: color.plank, borderWidth: 3, borderColor: color.woodDark, paddingHorizontal: space.m, paddingVertical: 2 },
  plankText: { color: color.accentInk },
  date: { color: color.muted, fontSize: 13 },
  photo: { height: 160, borderWidth: 3, borderColor: color.woodDark, backgroundColor: color.woodLight, overflow: "hidden" },
  head: { color: color.ink, fontSize: 20, fontWeight: "800" },
  sub: { color: color.muted, fontSize: 13, marginTop: 2 },
  stats: { flexDirection: "row", gap: space.s },
  stat: { flex: 1, minWidth: 0 },
  statName: { color: color.muted, fontSize: 12 },
  unit: { color: color.muted, fontSize: 12 },
  rule: { height: 2, backgroundColor: color.wood },
  line: { flexDirection: "row", gap: space.s },
  mark: { width: 18, color: color.fire, fontSize: 14, lineHeight: 20, fontWeight: "700" },
  markRed: { color: color.heat },
  lineText: { flex: 1, color: color.ink, fontSize: 14, lineHeight: 20 },
  foot: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s, marginTop: space.s },
  brand: { color: color.fire },
  footText: { color: color.muted, fontSize: 12 },
});
