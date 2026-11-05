// 晒一下、周报存图（spec §147、§164 第四期）：卡片画成 View，view-shot 存成 PNG，交给系统分享（系统分享里能存到相册、发给朋友）。
// 网页预览（react-native-web）里不截图、不分享，只显示卡片并写明要在手机 App 里分享，免得按钮点了没反应。
// 图只在手机上生成、直接交给系统，不上传。
import * as Sharing from "expo-sharing";
import { type RefObject, useEffect, useRef, useState } from "react";
import { Image, Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { captureRef } from "react-native-view-shot";

import { api } from "@/api/client";
import type { WeekReport } from "@/features/record/logic";
import { useAuthedImage } from "@/lib/authed-image";
import { Button, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { type CardHost, ShareCard } from "./card";
import { weekCard, workoutCard, type WorkoutShare as Share } from "./logic";

const WEB_ONLY = "网页预览里不能存图和分享，在手机 App 里打开这里就能存成图片、发给朋友。";
const NO_SHARE = "这台手机不支持系统分享，可以截屏保存这张卡。";

/** 能不能走系统分享：网页预览一律不能；手机上问 expo-sharing。null = 还在问。 */
function useCanShare(): boolean | null {
  const [ok, setOk] = useState<boolean | null>(Platform.OS === "web" ? false : null);
  useEffect(() => {
    if (Platform.OS === "web") return;
    let live = true;
    Sharing.isAvailableAsync()
      .then((v) => live && setOk(v))
      .catch(() => live && setOk(false));
    return () => {
      live = false;
    };
  }, []);
  return ok;
}

/** 卡片下面：能分享的给一个"存成图片 / 分享"，不能的只写一句为什么。 */
function Actions({ target }: { target: RefObject<CardHost | null> }) {
  const can = useCanShare();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  if (can === null) return null;
  if (!can) return <Text style={s.caption}>{Platform.OS === "web" ? WEB_ONLY : NO_SHARE}</Text>;
  const share = async () => {
    setBusy(true);
    setMsg("");
    try {
      const uri = await captureRef(target, { format: "png", quality: 1, result: "tmpfile" });
      await Sharing.shareAsync(uri, { mimeType: "image/png", UTI: "public.png", dialogTitle: "晒一下" });
    } catch {
      setMsg("图片没画出来，稍后再试。"); // 用户在系统分享里取消不算失败（shareAsync 正常返回）
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={s.actions}>
      <Button title={busy ? "正在存图…" : "存成图片 / 分享"} disabled={busy} onPress={share} />
      <Text style={s.caption}>系统分享里可以存到相册，或者直接发给朋友。</Text>
      <Note tone="error">{msg}</Note>
    </View>
  );
}

/** 打卡照片要带登录凭证取：手机上图片请求能带凭证；网页预览先取回来再显示（同"记一餐"的照片）。 */
function CardPhoto({ id }: { id: string }) {
  const source = useAuthedImage(`/iron/api/workouts/${encodeURIComponent(id)}/photo`);
  if (!source) return null;
  return <Image source={source} style={s.photo} resizeMode="cover" accessibilityLabel="打卡照片" />;
}

/** 一个勾选框：带不带打卡照片。 */
function Check({ on, label, onChange }: { on: boolean; label: string; onChange: (v: boolean) => void }) {
  return (
    <Pressable accessibilityRole="checkbox" accessibilityState={{ checked: on }} onPress={() => onChange(!on)} style={s.check} hitSlop={6}>
      <View style={[s.box, on && s.boxOn]}>{on ? <Text style={s.tick}>✓</Text> : null}</View>
      <Text style={s.checkText}>{label}</Text>
    </Pressable>
  );
}

/** 晒一下：取这次训练的分享卡数据，有打卡照片的默认带上、可以去掉（同网页 shareSheet）。 */
export function WorkoutShare({ id }: { id: string }) {
  const [d, setD] = useState<Share | null>(null);
  const [error, setError] = useState("");
  const [withPhoto, setWithPhoto] = useState(true);
  const ref = useRef<CardHost>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    setError("");
    api<Share>(`/iron/api/share/workout/${encodeURIComponent(id)}`)
      .then((x) => live && setD(x))
      .catch((e: Error) => live && setError(e.message || "没能取到这次训练"));
    return () => {
      live = false;
    };
  }, [id]);
  if (error) return <Note tone="error">{error}</Note>;
  if (!d) return <Text style={s.caption}>正在画分享卡…</Text>;
  return (
    <View style={s.stack}>
      {d.photo ? <Check on={withPhoto} label="带上打卡照片" onChange={setWithPhoto} /> : null}
      <ShareCard ref={ref} card={workoutCard(d)} photo={d.photo && withPhoto ? <CardPhoto id={d.id} /> : undefined} />
      <Actions target={ref} />
      <Text style={s.caption}>卡上只有训练的数，不放体重、体脂。</Text>
    </View>
  );
}

/** 上周周报存成图片（同网页 reportSheet）：数据就是战绩页已经取到的那份。 */
export function WeekShare({ r }: { r: WeekReport }) {
  const ref = useRef<CardHost>(null);
  return (
    <View style={s.stack}>
      <ShareCard ref={ref} card={weekCard(r)} />
      <Actions target={ref} />
    </View>
  );
}

const s = StyleSheet.create({
  stack: { gap: space.m },
  actions: { gap: space.s },
  caption: { color: color.muted, fontSize: 13, lineHeight: 19 },
  photo: { width: "100%", height: "100%" },
  check: { flexDirection: "row", alignItems: "center", gap: space.s },
  box: { width: 22, height: 22, borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight, alignItems: "center", justifyContent: "center" },
  boxOn: { backgroundColor: color.accent, borderColor: color.accentText },
  tick: { color: color.accentInk, fontSize: 14, fontWeight: "800", lineHeight: 16 },
  checkText: { color: color.ink, fontSize: 15 },
});
