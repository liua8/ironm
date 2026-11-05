// 图鉴和排行榜共用的小组件（像素农场风，照网页版 style.css）：小标签、一排可选的牌子、底部弹出的详情、
// 要点和错误的列表、封面图、读不到时的提示、两步确认的按钮。
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Image, Modal, Pressable, ScrollView, StyleSheet, Text, View, type ViewStyle } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { Button } from "@/ui/pixel";
import { color, font, space } from "@/ui/theme";

/** 小标签（方框）。 */
export function Chip({ children, tone }: { children: ReactNode; tone?: "hot" | "good" }) {
  if (!children) return null;
  return (
    <View style={[s.chip, tone === "hot" && s.chipHot, tone === "good" && s.chipGood]}>
      <Text style={[s.chipText, tone === "hot" && s.chipTextHot]}>{children}</Text>
    </View>
  );
}

export function Tags({ items }: { items: (string | null | undefined | false)[] }) {
  const shown = items.filter(Boolean) as string[];
  if (!shown.length) return null;
  return (
    <View style={s.tags}>
      {shown.map((t, i) => (
        <Chip key={`${t}-${i}`}>{t}</Chip>
      ))}
    </View>
  );
}

/** 一排可选的牌子；scroll 时横着滑（食谱标签），不然折行。 */
export function Pills<K extends string>({
  options,
  value,
  onChange,
  label,
  scroll,
  labelOf,
}: {
  options: readonly K[];
  value: K;
  onChange: (k: K) => void;
  label?: string;
  scroll?: boolean;
  labelOf?: (k: K) => string;
}) {
  const items = options.map((k) => (
    <Pressable
      key={k}
      accessibilityRole="button"
      accessibilityState={{ selected: k === value }}
      onPress={() => onChange(k)}
      style={[s.pill, k === value && s.pillOn]}
    >
      <Text style={[s.pillText, k === value && s.pillTextOn]}>{labelOf ? labelOf(k) : k}</Text>
    </Pressable>
  ));
  if (scroll) {
    return (
      <ScrollView horizontal showsHorizontalScrollIndicator={false} accessibilityLabel={label} contentContainerStyle={s.pillsRow}>
        {items}
      </ScrollView>
    );
  }
  return (
    <View style={s.pills} accessibilityLabel={label}>
      {items}
    </View>
  );
}

/** 详情：从底部弹出，内容可以滚动，右上角关闭。 */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={s.overlay}>
        <Pressable style={StyleSheet.absoluteFill} accessibilityLabel="关闭" onPress={onClose} />
        <View style={[s.sheet, { paddingBottom: Math.max(insets.bottom, space.m) }]} accessibilityViewIsModal>
          <View style={s.sheetHead}>
            <Text style={s.sheetTitle} accessibilityRole="header" numberOfLines={2}>
              {title}
            </Text>
            <Pressable accessibilityRole="button" accessibilityLabel="关闭" onPress={onClose} hitSlop={8} style={s.close}>
              <Text style={s.closeText}>✕</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={s.sheetBody} keyboardShouldPersistTaps="handled">
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** 详情里的小标题。 */
export function H3({ children }: { children: ReactNode }) {
  return <Text style={s.h3}>{children}</Text>;
}

/** 说明小字。 */
export function Caption({ children, style }: { children: ReactNode; style?: object }) {
  if (!children) return null;
  return <Text style={[s.caption, style]}>{children}</Text>;
}

/** 要点（✓ 绿）、常见错误和要注意（✕ / ! 红）。 */
export function MarkList({ items, tone }: { items: string[]; tone: "ok" | "bad" | "warn" }) {
  const mark = tone === "ok" ? "✓" : tone === "bad" ? "✕" : "!";
  return (
    <View style={s.marks}>
      {items.map((t, i) => (
        <View key={i} style={s.markRow}>
          <Text style={[s.mark, tone === "ok" ? s.markOk : s.markBad]}>{mark}</Text>
          <Text style={s.markText}>{t}</Text>
        </View>
      ))}
    </View>
  );
}

/** 编号列表（怎么做、做法）。 */
export function Steps({ items }: { items: string[] }) {
  return (
    <View style={s.marks}>
      {items.map((t, i) => (
        <View key={i} style={s.markRow}>
          <Text style={s.stepNo}>{i + 1}.</Text>
          <Text style={s.markText}>{t}</Text>
        </View>
      ))}
    </View>
  );
}

/** 小圆点列表。 */
export function Bullets({ items }: { items: string[] }) {
  return (
    <View style={s.marks}>
      {items.map((t, i) => (
        <View key={i} style={s.markRow}>
          <Text style={s.stepNo}>·</Text>
          <Text style={s.markText}>{t}</Text>
        </View>
      ))}
    </View>
  );
}

/** 封面：有图放图，没有写一个字。 */
export function Cover({ uri, mark, style, contain }: { uri: string; mark: string; style?: ViewStyle; contain?: boolean }) {
  return (
    <View style={[s.cover, style]}>
      {uri ? (
        <Image source={{ uri }} style={s.coverImg} resizeMode={contain ? "contain" : "cover"} accessibilityIgnoresInvertColors />
      ) : (
        <Text style={s.coverMark}>{mark}</Text>
      )}
    </View>
  );
}

/** 卡片：一张封面 + 两行字，两列排。 */
export function Card({ cover, title, sub, badge, onPress, label }: { cover: ReactNode; title: string; sub?: ReactNode; badge?: string; onPress: () => void; label: string }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={({ pressed }) => [s.card, pressed && s.pressed]}>
      <View>
        {cover}
        {badge ? <Text style={s.badge}>{badge}</Text> : null}
      </View>
      <View style={s.cardInfo}>
        <Text style={s.cardTitle} numberOfLines={2}>
          {title}
        </Text>
        {typeof sub === "string" ? (
          <Text style={s.cardSub} numberOfLines={2}>
            {sub}
          </Text>
        ) : (
          sub
        )}
      </View>
    </Pressable>
  );
}

export function Grid({ children }: { children: ReactNode }) {
  return <View style={s.grid}>{children}</View>;
}

/** 一行：可选的缩略图、标题、小字，右边一个 ›。 */
export function Row({ thumb, title, sub, onPress, right }: { thumb?: ReactNode; title: string; sub?: string; onPress?: () => void; right?: ReactNode }) {
  const body = (
    <>
      {thumb}
      <View style={s.rowMain}>
        <Text style={s.rowTitle}>{title}</Text>
        {sub ? <Text style={s.rowSub}>{sub}</Text> : null}
      </View>
      {right ?? (onPress ? <Text style={s.chev}>›</Text> : null)}
    </>
  );
  if (!onPress) return <View style={s.row}>{body}</View>;
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [s.row, pressed && s.pressed]}>
      {body}
    </Pressable>
  );
}

/** 读的时候、读不到时：读不到时说读不到，给一个重试（不当成"没有"）。 */
export function Loading({ error, onRetry, what = "" }: { error?: string | null; onRetry?: () => void; what?: string }) {
  if (!error) return <Text style={s.caption}>{`正在读${what}…`}</Text>;
  return (
    <View style={s.failed}>
      <Text style={s.failedTitle}>没能加载</Text>
      <Text style={s.caption}>{error}</Text>
      {onRetry ? <Button title="重试" kind="ghost" small onPress={onRetry} /> : null}
    </View>
  );
}

/** 两步确认（不弹框）：第一次点变成确认的说法，3 秒内再点才执行。 */
export function TwoStep({ label, sure, onConfirm, done }: { label: string; sure: string; onConfirm: () => void; done?: string }) {
  const [armed, setArmed] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  if (done) return <Text style={s.act}>{done}</Text>;
  return (
    <Pressable
      accessibilityRole="button"
      hitSlop={6}
      onPress={() => {
        if (timer.current) clearTimeout(timer.current);
        if (!armed) {
          setArmed(true);
          timer.current = setTimeout(() => setArmed(false), 3000);
          return;
        }
        setArmed(false);
        onConfirm();
      }}
    >
      <Text style={[s.act, armed && s.actArmed]}>{armed ? sure : label}</Text>
    </Pressable>
  );
}

/** 写在草地上的说明：配羊皮纸底，看得清。 */
export function GrassNote({ children }: { children: ReactNode }) {
  if (!children) return null;
  return (
    <View style={s.grassNote}>
      <Text style={s.caption}>{children}</Text>
    </View>
  );
}

export const ui = StyleSheet.create({
  section: { gap: space.s },
  sectionHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s },
  plankTitle: { alignSelf: "flex-start", fontFamily: font.pixel, fontSize: 24, lineHeight: 28, color: color.accentInk, backgroundColor: color.plank, borderWidth: 3, borderColor: color.woodDark, paddingHorizontal: 10, paddingVertical: 4 },
  small: { fontSize: 13, color: color.paperLight },
  link: { color: color.woodDark, fontSize: 14, fontWeight: "600", backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: 8, paddingVertical: 2 },
  lede: { color: color.ink, fontSize: 16, lineHeight: 24, fontWeight: "600" },
  body: { color: color.ink, fontSize: 15, lineHeight: 24 },
  muted: { color: color.muted, fontSize: 14, lineHeight: 20 },
  error: { color: color.heat, fontSize: 14, lineHeight: 20 },
  ok: { color: color.accentText, fontSize: 14, lineHeight: 20 },
  callout: { flexDirection: "row", gap: 8, backgroundColor: color.heatSoft, borderLeftWidth: 3, borderLeftColor: color.heat, padding: space.m },
  calloutText: { flex: 1, color: color.ink, fontSize: 14, lineHeight: 21 },
  btnRow: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  search: { backgroundColor: color.paperLight, borderWidth: 3, borderColor: color.wood, paddingHorizontal: space.m, paddingVertical: 10, fontSize: 16, color: color.ink },
});

const s = StyleSheet.create({
  chip: { borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight, paddingHorizontal: 8, paddingVertical: 2 },
  chipHot: { borderColor: color.heat, backgroundColor: color.heatSoft },
  chipGood: { borderColor: color.accent, backgroundColor: color.goodSoft },
  chipText: { color: color.woodDark, fontSize: 13, fontWeight: "600" },
  chipTextHot: { color: color.heat },
  tags: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pillsRow: { flexDirection: "row", gap: 6, paddingRight: space.s },
  pill: { borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight, paddingHorizontal: 12, paddingVertical: 6 },
  pillOn: { backgroundColor: color.amber, borderColor: "#8a5a10" },
  pillText: { color: color.woodDark, fontSize: 14, fontWeight: "600" },
  pillTextOn: { color: color.woodDark },
  overlay: { flex: 1, justifyContent: "flex-end", backgroundColor: "rgba(40,20,5,0.45)" },
  sheet: { maxHeight: "90%", width: "100%", maxWidth: 720, alignSelf: "center", backgroundColor: color.paper, borderTopWidth: 4, borderColor: color.wood, borderLeftWidth: 4, borderRightWidth: 4 },
  sheetHead: { flexDirection: "row", alignItems: "center", gap: space.s, paddingHorizontal: space.l, paddingTop: space.m, paddingBottom: space.s, borderBottomWidth: 2, borderBottomColor: color.woodLight },
  sheetTitle: { flex: 1, color: color.ink, fontSize: 20, fontWeight: "700" },
  close: { width: 36, height: 36, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight },
  closeText: { color: color.woodDark, fontSize: 16, fontWeight: "700" },
  sheetBody: { padding: space.l, gap: space.m },
  h3: { color: color.ink, fontSize: 16, fontWeight: "700", marginTop: 2 },
  caption: { color: color.muted, fontSize: 13, lineHeight: 19 },
  marks: { gap: 6 },
  markRow: { flexDirection: "row", gap: 8, alignItems: "flex-start" },
  mark: { width: 16, fontSize: 14, lineHeight: 22, fontWeight: "700", textAlign: "center" },
  markOk: { color: color.accentText },
  markBad: { color: color.heat },
  stepNo: { minWidth: 18, color: color.muted, fontSize: 15, lineHeight: 22, fontWeight: "700" },
  markText: { flex: 1, color: color.ink, fontSize: 15, lineHeight: 22 },
  cover: { backgroundColor: "#e9c784", borderWidth: 3, borderColor: color.wood, alignItems: "center", justifyContent: "center", overflow: "hidden" },
  coverImg: { width: "100%", height: "100%", backgroundColor: "#fff" },
  coverMark: { fontSize: 30, fontWeight: "800", color: color.woodDark, opacity: 0.8 },
  card: { width: "47.5%", flexGrow: 0, backgroundColor: color.paper, borderWidth: 3, borderColor: color.wood, padding: 6, gap: 6 },
  pressed: { opacity: 0.75 },
  badge: { position: "absolute", left: 4, top: 4, fontSize: 11, color: color.woodDark, backgroundColor: color.paperLight, borderWidth: 1, borderColor: color.wood, paddingHorizontal: 4 },
  cardInfo: { gap: 2 },
  cardTitle: { color: color.ink, fontSize: 15, fontWeight: "700" },
  cardSub: { color: color.muted, fontSize: 12, lineHeight: 17 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10, justifyContent: "space-between" },
  row: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderBottomWidth: 2, borderBottomColor: color.woodLight, borderStyle: "dashed" },
  rowMain: { flex: 1, minWidth: 0, gap: 2 },
  rowTitle: { color: color.ink, fontSize: 15, fontWeight: "600" },
  rowSub: { color: color.muted, fontSize: 13 },
  chev: { color: color.muted, fontSize: 20 },
  failed: { gap: space.s, backgroundColor: color.paper, borderWidth: 3, borderColor: color.wood, padding: space.m },
  failedTitle: { color: color.heat, fontSize: 15, fontWeight: "700" },
  act: { color: color.muted, fontSize: 13, fontWeight: "600", paddingVertical: 2 },
  actArmed: { color: color.heat },
  grassNote: { alignSelf: "flex-start", backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: 10, paddingVertical: 4 },
});
