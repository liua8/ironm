// 战绩和"我"共用的小组件（照网页版的 openSheet、chip、row-item、buddy-say、twoStep）：
// 弹出页用 RN 的 Modal；确认删除不用系统弹窗（网页预览里 Alert 不出来），改成当场再点一次。
import { Redirect, router } from "expo-router";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useSession } from "@/auth/session";
import { Button, Note, PixelText, Plank, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

/** 读一个接口：loading / data / error，能重试。 */
export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);
  const run = useCallback(() => {
    const mine = ++seq.current;
    setLoading(true);
    setError("");
    load()
      .then((d) => {
        if (mine === seq.current) setData(d);
      })
      .catch((e: Error) => {
        if (mine === seq.current) setError(e.message || "没能加载");
      })
      .finally(() => {
        if (mine === seq.current) setLoading(false);
      });
  }, deps);
  useEffect(() => {
    run();
  }, [run]);
  return { data, error, loading, reload: run, setData };
}

/** 底部弹出页：点外面或"关闭"收起。 */
export function Sheet({ visible, title, onClose, children }: { visible: boolean; title: string; onClose: () => void; children: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <View style={k.overlay}>
        <Pressable style={k.backdrop} accessibilityRole="button" accessibilityLabel="关闭" onPress={onClose} />
        <View style={[k.sheet, { paddingBottom: Math.max(insets.bottom, space.l) }]} accessibilityViewIsModal accessibilityLabel={title}>
          <View style={k.sheetHead}>
            <PixelText size={24} style={k.sheetTitle} numberOfLines={2}>
              {title}
            </PixelText>
            <Pressable accessibilityRole="button" accessibilityLabel="关闭" hitSlop={10} onPress={onClose} style={k.close}>
              <Text style={k.closeText}>×</Text>
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={k.sheetBody} keyboardShouldPersistTaps="handled">
            {children}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** 面板顶上：木牌标题，右边一行小字或一个按钮。 */
export function PanelHead({ title, right }: { title: string; right?: ReactNode }) {
  return (
    <View style={k.head}>
      <Plank>{title}</Plank>
      {typeof right === "string" ? <T muted style={k.headRight}>{right}</T> : right}
    </View>
  );
}

/** 小标签：good 绿、attention 红、warn 黄。 */
export function Chip({ text, tone }: { text?: string | null; tone?: string }) {
  if (!text) return null;
  const t = tone === "good" ? k.chipGood : tone === "attention" || tone === "bad" ? k.chipBad : tone === "warn" ? k.chipWarn : null;
  return <Text style={[k.chip, t]}>{text}</Text>;
}

/** 一行：标题、说明、右边的字；能点的带箭头。 */
export function Row({ title, sub, end, onPress, last }: { title: ReactNode; sub?: ReactNode; end?: ReactNode; onPress?: () => void; last?: boolean }) {
  const body = (
    <>
      <View style={k.rowMain}>
        <Text style={k.rowTitle}>{title}</Text>
        {sub ? <Text style={k.rowSub}>{sub}</Text> : null}
      </View>
      {typeof end === "string" ? <Text style={k.rowEnd}>{end}</Text> : end}
      {onPress ? <Text style={k.chev}>›</Text> : null}
    </>
  );
  return onPress ? (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [k.row, last && k.rowLast, pressed && k.rowDown]}>
      {body}
    </Pressable>
  ) : (
    <View style={[k.row, last && k.rowLast]}>{body}</View>
  );
}

/** IronM 说的一段（带小标题）。 */
export function BuddySay({ head, children }: { head: string; children: ReactNode }) {
  return (
    <View style={k.say}>
      <Text style={k.sayHead}>{head}</Text>
      <T>{children}</T>
    </View>
  );
}

/** 小字说明。 */
export function Caption({ children }: { children: ReactNode }) {
  return <Text style={k.caption}>{children}</Text>;
}

/** 小标题（弹出页里分段用）。 */
export function Sub({ children }: { children: ReactNode }) {
  return <Text style={k.sub}>{children}</Text>;
}

/** 没加载出来：一句原因，一个重试。 */
export function Failed({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <View style={k.failed}>
      <T style={{ fontWeight: "700" }}>没能加载</T>
      <Note tone="error">{error}</Note>
      {retry ? <Button kind="ghost" small title="重试" onPress={retry} /> : null}
    </View>
  );
}

/** 一组可选的小按钮（单选）。 */
export function Pills<K extends string>({ options, value, onPick, label }: { options: readonly (readonly [K, string])[]; value: K | null | ((k: K) => boolean); onPick: (k: K) => void; label?: string }) {
  const on = (key: K) => (typeof value === "function" ? value(key) : value === key);
  return (
    <View style={k.pills} accessibilityLabel={label}>
      {options.map(([key, word]) => (
        <Pressable key={key} accessibilityRole="button" accessibilityState={{ selected: on(key) }} onPress={() => onPick(key)} style={[k.pill, on(key) && k.pillOn]}>
          <Text style={[k.pillText, on(key) && k.pillTextOn]}>{word}</Text>
        </Pressable>
      ))}
    </View>
  );
}

/** 要再点一次才算的按钮（删记忆、删记录用）：第一次变成"确定…"，3 秒没点就回去。 */
export function TwoStep({ label, sure, onConfirm, danger = true }: { label: string; sure: string; onConfirm: () => void; danger?: boolean }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const t = setTimeout(() => setArmed(false), 3000);
    return () => clearTimeout(t);
  }, [armed]);
  return (
    <Pressable
      accessibilityRole="button"
      hitSlop={8}
      onPress={() => {
        if (!armed) return setArmed(true);
        setArmed(false);
        onConfirm();
      }}
    >
      <Text style={[k.link, danger && k.danger, armed && k.armed]}>{armed ? sure : label}</Text>
    </Pressable>
  );
}

/** 单独一页顶上的返回：能退就退，退不了（直接打开的）就回到给定的标签页。 */
export function BackLink({ label, fallback }: { label: string; fallback: "/record" | "/me" }) {
  return (
    <Pressable accessibilityRole="link" accessibilityLabel={`返回${label}`} hitSlop={8} onPress={() => (router.canGoBack() ? router.back() : router.replace(fallback))} style={k.back}>
      <Text style={k.backText}>{`‹ ${label}`}</Text>
    </Pressable>
  );
}

/** 单独一页（不在底部标签里）也要登录：没登录回登录页。 */
export function NeedLogin({ children }: { children: ReactNode }) {
  const { ready, token } = useSession();
  if (!ready) return null;
  if (!token) return <Redirect href="/login" />;
  return <>{children}</>;
}

/** 键值一行（弹出页里的"上传时间 / 11月3日"）。 */
export function KV({ k: name, v }: { k: string; v: ReactNode }) {
  return (
    <View style={k.kv}>
      <Text style={k.kvKey}>{name}</Text>
      <Text style={k.kvVal}>{v}</Text>
    </View>
  );
}

export const kit = StyleSheet.create({
  rows: { borderTopWidth: 2, borderTopColor: color.woodLight },
  card: { backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, padding: space.m, gap: space.s },
  link: { color: color.accentText, fontSize: 14, fontWeight: "600" },
});

const k = StyleSheet.create({
  overlay: { flex: 1, justifyContent: "flex-end" },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(40, 20, 6, 0.45)" },
  sheet: { maxHeight: "90%", width: "100%", maxWidth: 720, alignSelf: "center", backgroundColor: color.paper, borderTopWidth: 4, borderLeftWidth: 4, borderRightWidth: 4, borderColor: color.woodDark },
  sheetHead: { flexDirection: "row", alignItems: "center", gap: space.s, paddingHorizontal: space.l, paddingTop: space.m, paddingBottom: space.s, borderBottomWidth: 2, borderBottomColor: color.woodLight },
  sheetTitle: { flex: 1 },
  close: { width: 36, height: 36, alignItems: "center", justifyContent: "center", backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark },
  closeText: { color: color.accentInk, fontSize: 22, fontWeight: "700", lineHeight: 24 },
  sheetBody: { padding: space.l, gap: space.m },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s, flexWrap: "wrap" },
  headRight: { fontSize: 14 },
  chip: { alignSelf: "flex-start", fontSize: 12, fontWeight: "700", color: color.ink, backgroundColor: color.paperLight, borderWidth: 1, borderColor: color.woodLight, paddingHorizontal: 6, paddingVertical: 1, overflow: "hidden" },
  chipGood: { backgroundColor: color.goodSoft, color: color.accentText, borderColor: color.accent },
  chipBad: { backgroundColor: color.heatSoft, color: color.heat, borderColor: color.heat },
  chipWarn: { backgroundColor: color.amber, color: color.woodDark, borderColor: color.wood },
  row: { flexDirection: "row", alignItems: "center", gap: space.s, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: color.woodLight },
  rowLast: { borderBottomWidth: 0 },
  rowDown: { backgroundColor: color.paperLight },
  rowMain: { flex: 1, gap: 2 },
  rowTitle: { color: color.ink, fontSize: 15, fontWeight: "600" },
  rowSub: { color: color.muted, fontSize: 13, lineHeight: 18 },
  rowEnd: { color: color.muted, fontSize: 14 },
  chev: { color: color.muted, fontSize: 20, marginLeft: 2 },
  say: { backgroundColor: color.paperLight, borderLeftWidth: 4, borderLeftColor: color.accent, padding: space.m, gap: 4 },
  sayHead: { color: color.accentText, fontSize: 13, fontWeight: "700" },
  caption: { color: color.muted, fontSize: 13, lineHeight: 19 },
  sub: { color: color.ink, fontSize: 15, fontWeight: "700", marginTop: space.xs },
  failed: { gap: space.s },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  pill: { paddingHorizontal: space.m, paddingVertical: 7, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood },
  pillOn: { backgroundColor: color.amber, borderColor: color.woodDark },
  pillText: { color: color.ink, fontSize: 14 },
  pillTextOn: { color: color.woodDark, fontWeight: "700" },
  link: { color: color.accentText, fontSize: 14, fontWeight: "600", paddingVertical: 4 },
  danger: { color: color.heat },
  armed: { backgroundColor: color.heatSoft, paddingHorizontal: 6 },
  back: { alignSelf: "flex-start", backgroundColor: color.plank, borderWidth: 2, borderColor: color.woodDark, paddingHorizontal: space.m, paddingVertical: 6 },
  backText: { color: color.accentInk, fontSize: 15, fontWeight: "700" },
  kv: { flexDirection: "row", justifyContent: "space-between", gap: space.m, paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: color.woodLight },
  kvKey: { color: color.muted, fontSize: 14 },
  kvVal: { color: color.ink, fontSize: 14, flexShrink: 1, textAlign: "right" },
});
