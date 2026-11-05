// 趋势小图（同网页 spark）：折线带浅色面积，最后一个点标出来；步数画柱。用 react-native-svg 画，横向铺满。
import { StyleSheet, Text, View } from "react-native";
import Svg, { Polygon, Polyline, Rect } from "react-native-svg";

import { md } from "@/features/record/logic";
import { color } from "@/ui/theme";

import { num, sparkPoints } from "./logic";

export function Spark({ series, bars = false, height = 54 }: { series: [string, number][]; bars?: boolean; height?: number }) {
  const vs = series.map((p) => p[1]);
  const pts = sparkPoints(vs, bars);
  if (pts.length < 2) return null;
  const last = pts[pts.length - 1];
  const line = pts.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
  const w = 100 / pts.length;
  return (
    <View style={{ height }} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none">
        {bars ? (
          pts.map((p, i) => (
            <Rect key={i} x={i * w + w * 0.18} width={w * 0.64} y={p.y} height={100 - p.y} fill={color.accent} opacity={i === pts.length - 1 ? 1 : 0.55} />
          ))
        ) : (
          <>
            <Polygon points={`0,100 ${line} 100,100`} fill={color.accent} opacity={0.16} />
            <Polyline points={line} fill="none" stroke={color.accentText} strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
          </>
        )}
      </Svg>
      {bars ? null : <View style={[s.end, { left: `${last.x}%`, top: `${last.y}%` }]} />}
    </View>
  );
}

/** 详情里的大图：上面图，下面起止日期和最高最低。 */
export function Chart({ series, bars = false }: { series: [string, number][]; bars?: boolean }) {
  if (series.length < 2) return null;
  const vs = series.map((p) => p[1]);
  return (
    <View style={s.chart}>
      <View style={s.chartBox}>
        <Spark series={series} bars={bars} height={140} />
      </View>
      <View style={s.foot}>
        <Text style={s.footText}>{`${md(series[0][0])} – ${md(series[series.length - 1][0])}`}</Text>
        <Text style={s.footText}>{`最高 ${num(Math.max(...vs))} · 最低 ${num(Math.min(...vs))}`}</Text>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  end: { position: "absolute", width: 10, height: 10, marginLeft: -5, marginTop: -5, backgroundColor: color.accentText, borderWidth: 2, borderColor: color.paperLight },
  chart: { gap: 6 },
  chartBox: { borderTopWidth: 1, borderBottomWidth: 1, borderStyle: "dashed", borderColor: color.woodLight, paddingVertical: 4 },
  foot: { flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap", gap: 6 },
  footText: { color: color.muted, fontSize: 12 },
});
