// 今日余额（照网页版 todayBudget，§125、§131）：左边体力条（今天还能吃的占目标多少，吃一顿掉一截），
// 右边还能吃多少（大字）、已吃和目标、进度条，下面一排蛋白质（吃了 / 目标）、碳水、脂肪；"目标怎么算的"是个小链接。
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import { Button, LinkButton, Note, Panel, PixelText, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { budgetOf, macroLine, observedFacts, stripRefs, targetFacts } from "./logic";
import { Facts, SubTitle } from "./parts";
import type { Day, DietReview, Metric } from "./types";

export function TodayBudget({ day, metrics, onHow }: { day: Day; metrics: Record<string, Metric>; onHow: () => void }) {
  const b = budgetOf(day, metrics);
  if (b.kind === "none") {
    return (
      <Panel>
        <T>在「我」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。</T>
        <View style={s.row}><Button title="去填写" kind="ghost" small onPress={() => router.push("/me")} /></View>
        {b.eaten.kcal ? <T muted>{`今天已记：${macroLine(b.eaten)}`}</T> : null}
      </Panel>
    );
  }
  const macro = (name: string, have: number, target?: number) => (
    <View style={s.macro}>
      <T muted style={s.macroName}>{name}</T>
      <PixelText size={24} numberOfLines={1}>{String(Math.round(have))}</PixelText>
      <T muted style={s.macroUnit}>{target ? `/ ${Math.round(target)} 克` : "克"}</T>
    </View>
  );
  return (
    <Panel>
      <View style={s.budget}>
        <View style={s.energy} accessibilityRole="image" accessibilityLabel={`体力还剩 ${b.energy}%`}>
          <View style={[s.energyFill, { height: `${b.energy}%` }]} />
        </View>
        <View style={s.main}>
          <T muted style={s.label}>{b.over ? "今天多吃了" : "今天还能吃"}</T>
          <PixelText size={48} numberOfLines={1}>
            {String(b.left)}
            <T style={s.bigUnit}> 千卡</T>
          </PixelText>
          <T muted style={s.small}>{`已经吃了 ${Math.round(b.eaten.kcal)}，今天的目标是 ${Math.round(b.target)} 千卡。`}</T>
          <View style={s.bar}><View style={[s.barFill, { width: `${b.pct}%` }]} /></View>
          <View style={s.macros}>
            {macro("蛋白质", b.eaten.protein_g, b.proteinTarget)}
            {macro("碳水", b.eaten.carbs_g)}
            {macro("脂肪", b.eaten.fat_g)}
          </View>
          <LinkButton title="目标怎么算的 ›" onPress={onHow} />
        </View>
      </View>
    </Panel>
  );
}

/** "今日目标怎么算的"弹出页：热量、蛋白质目标、基础代谢、每日总消耗；再加按记的吃和体重估的实际消耗。 */
export function HowTarget({ metrics }: { metrics: Record<string, Metric> }) {
  const [review, setReview] = useState<DietReview | null | "fail">(null);
  useEffect(() => {
    let live = true;
    api<DietReview>("/iron/api/diet/review")
      .then((r) => live && setReview(r))
      .catch(() => live && setReview("fail"));
    return () => {
      live = false;
    };
  }, []);
  const items = targetFacts(metrics);
  const seen = review && review !== "fail" ? observedFacts(review) : null;
  return (
    <View style={s.stack}>
      {items.length ? items.map((x) => (
        <View key={x.name} style={s.stack}>
          <SubTitle>{x.name}</SubTitle>
          <Facts items={x.facts} />
        </View>
      )) : <Note>指标这次没读到，稍后再试。</Note>}
      <SubTitle>按你记的估的实际消耗</SubTitle>
      {review === null ? <Note>正在算…</Note> : review === "fail" ? <Note>这次没算出来。</Note> : seen && "facts" in seen ? <Facts items={seen.facts} /> : <Note>{seen?.lack}</Note>}
      {review && review !== "fail" && review.proposal ? (
        <T muted style={s.small}>{`IronM 的建议：${stripRefs(review.proposal.reason)}，目标从 ${review.proposal.before} 调到 ${review.proposal.after} 千卡，在"今天吃什么"里确认。`}</T>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  row: { flexDirection: "row" },
  stack: { gap: space.s },
  budget: { flexDirection: "row", gap: 14 },
  energy: { width: 30, minHeight: 140, alignSelf: "stretch", justifyContent: "flex-end", padding: 3, backgroundColor: "#3a1e08", borderWidth: 1, borderRadius: 14, borderColor: color.wood },
  energyFill: { backgroundColor: color.accent, borderWidth: 1, borderColor: "#2e5410", borderTopColor: "#b7e86a", borderTopWidth: 1 },
  main: { flex: 1, minWidth: 0, gap: 6 },
  label: { fontSize: 13, letterSpacing: 1 },
  bigUnit: { fontSize: 16, fontWeight: "700", color: color.muted },
  small: { fontSize: 14, lineHeight: 20 },
  bar: { height: 10, backgroundColor: "#3a1e08", borderWidth: 1, borderRadius: 14, borderColor: color.wood, overflow: "hidden" },
  barFill: { height: "100%", backgroundColor: color.accent },
  macros: { flexDirection: "row", gap: space.s, marginTop: 4 },
  macro: { flex: 1, minWidth: 0, gap: 2 },
  macroName: { fontSize: 12, lineHeight: 16, letterSpacing: 1 },
  macroUnit: { fontSize: 12, lineHeight: 16, fontWeight: "600" },
});
