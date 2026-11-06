// 首页"今天吃"卡（spec §176，同网页 eatCard §175）：剩余热量的圆环、还能吃多少、蛋白质还差多少、碳水 / 蛋白质 / 脂肪三格、
// 拍照记、写一句两个大按钮；右上角"饮食账单"进原来的整页（/eat）。
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import Svg, { Circle } from "react-native-svg";

import { getPhoto, type Photo, photoErrText } from "@/lib/photo";
import { Icon } from "@/ui/icons";
import { Note, Panel, PixelText } from "@/ui/pixel";
import { color, radius, space } from "@/ui/theme";

import type { Day, Metric } from "./types";

const R = 34, C = 2 * Math.PI * R;

/** 卡上的几个数：剩多少、吃了百分之几、蛋白质目标（有"116–145"这样的范围取下限）。 */
export function eatNumbers(day: Day, metrics: Record<string, Metric>) {
  const t = day.target, tot = day.totals;
  if (!t) return null;
  const left = Math.round(t.kcal - tot.kcal);
  const pct = Math.min(100, Math.round((tot.kcal / t.kcal) * 100));
  const shown = metrics.protein_target?.display;
  const protein = shown ? Number(String(shown).split("–")[0]) || t.protein_g : t.protein_g;
  const state: [string, "green" | "warn" | "plain"] = !tot.kcal ? ["还没记", "plain"] : left >= 0 ? ["在目标内", "green"] : ["超了一点", "warn"];
  return { left, pct, protein, state };
}

export function EatCard({ day, metrics, onWrite, onPhoto }: { day: Day; metrics: Record<string, Metric>; onWrite: () => void; onPhoto: (p: Photo) => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const n = eatNumbers(day, metrics);
  const tot = day.totals, t = day.target;
  const shoot = async () => {
    setErr("");
    setBusy(true);
    try {
      const p = await getPhoto("拍照记一餐");
      if (p) onPhoto(p);
    } catch (e) {
      setErr(photoErrText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel style={s.card}>
      <View style={s.head}>
        <PixelText size={24} style={s.title}>今天吃</PixelText>
        {n ? <Text style={[s.tag, n.state[1] === "green" ? s.tagGreen : n.state[1] === "warn" ? s.tagWarn : null]}>{n.state[0]}</Text> : null}
        <Pressable accessibilityRole="link" onPress={() => router.push("/eat")} hitSlop={8} style={s.more}>
          <Text style={s.moreText}>饮食账单 ›</Text>
        </Pressable>
      </View>
      {n && t ? (
        <>
          <View style={s.main}>
            <View style={s.ring}>
              <Svg width={100} height={100} viewBox="0 0 84 84">
                <Circle cx={42} cy={42} r={R} stroke="#e6e3ef" strokeWidth={9} fill="none" />
                {n.pct > 0 ? (
                  <Circle cx={42} cy={42} r={R} stroke={color.accent} strokeWidth={9} fill="none" strokeLinecap="round"
                    strokeDasharray={`${(C * n.pct) / 100} ${C}`} transform="rotate(-90 42 42)" />
                ) : null}
              </Svg>
              <View style={s.ringText}>
                <Text style={s.ringNum}>{Math.abs(n.left)}</Text>
                <Text style={s.ringUnit}>{n.left >= 0 ? "剩余 kcal" : "多了 kcal"}</Text>
              </View>
            </View>
            <View style={s.text}>
              <Text style={s.big}>{n.left >= 0 ? `还能吃 ${n.left} kcal` : `多吃了 ${-n.left} kcal`}</Text>
              <Text style={s.small}>{`每日总摄入目标 ${Math.round(t.kcal)} kcal`}</Text>
              {n.protein ? <Text style={s.ok}>{tot.protein_g >= n.protein ? "✓ 蛋白质够了" : `✓ 蛋白质还差 ${Math.round(n.protein - tot.protein_g)} 克`}</Text> : null}
            </View>
          </View>
          <View style={s.macros}>
            <Macro name="碳水" have={tot.carbs_g} target={t.carbs_g || 0} tint="#2f9e68" />
            <Macro name="蛋白质" have={tot.protein_g} target={n.protein || 0} tint={color.accent} />
            <Macro name="脂肪" have={tot.fat_g} target={t.fat_g || 0} tint="#8a6fd6" />
          </View>
        </>
      ) : (
        <View style={s.mainEmpty}>
          <Text style={s.small}>在「我」里填好身高、出生日期、性别和目标，就能算出每天该吃多少。</Text>
        </View>
      )}
      <View style={s.acts}>
        <Act title="拍照记" sub="拍一下估热量" icon="camera" onPress={shoot} disabled={busy} />
        <Act title="写一句" sub="说一句就记" onPress={onWrite} />
      </View>
      {err ? <Note tone="error">{err}</Note> : null}
    </Panel>
  );
}

function Macro({ name, have, target, tint }: { name: string; have: number; target: number; tint: string }) {
  return (
    <View style={s.macro}>
      <Text style={s.mName} numberOfLines={1}>{name}</Text>
      {target ? <Text style={s.mLeft}>{`余 ${Math.max(0, Math.round(target - have))}g`}</Text> : null}
      {target ? (
        <View style={s.mTrack}><View style={[s.mFill, { width: `${Math.min(100, Math.round((have / target) * 100))}%`, backgroundColor: tint }]} /></View>
      ) : null}
      <Text style={s.mNum}>{target ? `${Math.round(have)} / ${Math.round(target)}g` : `${Math.round(have)}g`}</Text>
    </View>
  );
}

function Act({ title, sub, icon, onPress, disabled }: { title: string; sub: string; icon?: "camera"; onPress: () => void; disabled?: boolean }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={title} disabled={disabled} onPress={onPress} style={({ pressed }) => [s.act, (pressed || disabled) && s.actDown]}>
      <View style={s.actIc}>{icon ? <Icon name={icon} size={20} color={color.accentText} /> : <Text style={s.pen}>✎</Text>}</View>
      <View style={s.actText}>
        <Text style={s.actTitle}>{title}</Text>
        <Text style={s.actSub} numberOfLines={1}>{sub}</Text>
      </View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  card: { padding: 18, gap: 14 },
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  title: { fontSize: 22, lineHeight: 28 },
  tag: { fontSize: 12, fontWeight: "700", color: color.ink2, backgroundColor: color.paperLight, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4, overflow: "hidden" },
  tagGreen: { color: color.good, backgroundColor: color.goodSoft },
  tagWarn: { color: "#b45309", backgroundColor: "#fff3dc" },
  more: { marginLeft: "auto" },
  moreText: { color: color.accentText, fontSize: 13, fontWeight: "700" },
  main: { flexDirection: "row", alignItems: "center", gap: space.l, backgroundColor: color.paperLight, borderRadius: 18, padding: space.l },
  mainEmpty: { backgroundColor: color.paperLight, borderRadius: 18, padding: space.l },
  ring: { width: 100, height: 100 },
  ringText: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, alignItems: "center", justifyContent: "center" },
  ringNum: { fontSize: 19, fontWeight: "800", color: color.ink },
  ringUnit: { fontSize: 11, color: color.muted },
  text: { flex: 1, minWidth: 0, gap: 4 },
  big: { fontSize: 18, fontWeight: "800", color: color.ink },
  small: { fontSize: 13, color: color.ink2, lineHeight: 19 },
  ok: { fontSize: 13, fontWeight: "700", color: color.good },
  macros: { flexDirection: "row", gap: space.s },
  macro: { flex: 1, minWidth: 0, backgroundColor: color.paperLight, borderRadius: radius.s, padding: 10, gap: 4 },
  mName: { fontSize: 13, fontWeight: "700", color: color.ink },
  mLeft: { fontSize: 11, color: color.muted },
  mTrack: { height: 5, borderRadius: 999, backgroundColor: "#e6e3ef", overflow: "hidden" },
  mFill: { height: 5, borderRadius: 999 },
  mNum: { fontSize: 13, color: color.ink2 },
  acts: { flexDirection: "row", gap: 10 },
  act: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: 10, padding: 12, borderRadius: radius.m, backgroundColor: color.iconBg },
  actDown: { opacity: 0.75 },
  actIc: { width: 36, height: 36, borderRadius: 18, backgroundColor: color.paper, alignItems: "center", justifyContent: "center" },
  pen: { fontSize: 18, color: color.accentText },
  actText: { flex: 1, minWidth: 0 },
  actTitle: { fontSize: 15, fontWeight: "700", color: color.ink },
  actSub: { fontSize: 11, color: color.muted },
});
