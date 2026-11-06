// 记一餐（照网页版 mealEntry / logMealSheet / pickFoodsSheet / kindSheet / addMealSheet，§125）：
// 拍照记、写一句、从图鉴选一行三个；"常吃的"只在点"＋ 记"弹出来的那一页里。
// 拍照记（§164 第四期）：拍或从相册选一张、压好，先问是哪一餐再传（同网页 logMealSheet 带照片时）。
import { type ReactNode, useEffect, useState } from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import { api, isNoModel } from "@/api/client";
import { NeedModel } from "@/features/me/need-model";
import { appendPhoto, getPhoto, type Photo, photoErrText } from "@/lib/photo";
import { Button, Field, Note, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { FoodLines } from "./food-lines";
import { type LineRow, MEAL_KINDS, mealKindNow, readLines, replaceHint, rowFromFood } from "./logic";
import { FoodTile, Pills } from "./parts";
import type { Day, Food, Meal, Usual } from "./types";

type Kind = (typeof MEAL_KINDS)[number];
const asKind = (k: string | null | undefined): Kind => ((MEAL_KINDS as readonly string[]).includes(k ?? "") ? (k as Kind) : (mealKindNow() as Kind));

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "没有成功，请再试一次。");

/** 拍照记、写一句、从图鉴选一行三个小按钮。拍好、压好再交给 onPhoto 去问哪一餐。 */
export function EntryBar({ onWrite, onPick, onPhoto }: { onWrite: () => void; onPick: () => void; onPhoto: (p: Photo) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
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
    <View style={s.wrap}>
      <View style={s.bar}>
        <Chip title="拍照记" primary onPress={shoot} disabled={busy} />
        <Chip title="写一句" onPress={onWrite} />
        <Chip title="从图鉴选" onPress={onPick} />
      </View>
      {err ? <Note tone="error">{err}</Note> : null}
    </View>
  );
}

function Chip({ title, onPress, primary, disabled }: { title: string; onPress?: () => void; primary?: boolean; disabled?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [s.chip, primary && s.chipOn, (pressed || disabled) && s.chipDown, disabled && s.chipOff]}
    >
      <Text style={[s.chipText, primary && s.chipTextOn]} numberOfLines={1}>{title}</Text>
    </Pressable>
  );
}

/**
 * 选哪一餐，再记下；选到今天记过的提示会替换（每种餐每天一份）。
 * 要估热量的（拍照、写一句）还没填模型时服务端回 428：说明下面给"去填模型"，点了先 onLeave 关掉弹出页再走。
 */
export function KindPick({ meals, kind0, onPick, children, writing, goTitle = "记下", busyText, onLeave }: {
  meals: Meal[];
  kind0?: string | null;
  onPick: (kind: string) => Promise<void>;
  children?: ReactNode;
  writing?: boolean;
  goTitle?: string;
  busyText?: string;
  onLeave?: () => void;
}) {
  const [kind, setKind] = useState<Kind>(asKind(kind0));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "error" | "muted"; text: string; needModel?: boolean } | null>(null);
  const hint = replaceHint(meals, kind, writing);
  const go = async () => {
    setBusy(true);
    setMsg(busyText ? { tone: "muted", text: busyText } : null);
    try {
      await onPick(kind);
    } catch (e) {
      setMsg({ tone: "error", text: errText(e), needModel: isNoModel(e) });
      setBusy(false);
    }
  };
  return (
    <View style={s.stack}>
      {children}
      <View style={s.kindPick}>
        <T muted style={s.caption}>哪一餐</T>
        <Pills items={MEAL_KINDS} value={kind} onChange={setKind} label="哪一餐" />
        {hint ? <T muted style={s.caption}>{hint}</T> : null}
      </View>
      <Button title={goTitle} onPress={go} disabled={busy} />
      {msg?.needModel ? <NeedModel text={msg.text} before={onLeave} /> : msg ? <Note tone={msg.tone}>{msg.text}</Note> : null}
    </View>
  );
}

/** 写一句记一餐：营养师只认出吃了什么、多少克，热量按食物库算。 */
export function WriteMeal({ day, kind0, done, onLeave }: { day: Day; kind0?: string | null; done: (d: Day) => void; onLeave?: () => void }) {
  const [said, setSaid] = useState("");
  return (
    <KindPick
      meals={day.meals}
      kind0={kind0}
      onLeave={onLeave}
      writing
      goTitle="记下，估算热量"
      busyText="营养师在估算…"
      onPick={async (kind) => {
        const text = said.trim();
        if (!text) throw new Error("写一句吃了什么");
        const form = new FormData();
        form.append("said", text);
        form.append("kind", kind);
        done(await api<Day>("/iron/api/meals", { method: "POST", body: form }));
      }}
    >
      <Field
        value={said}
        onChangeText={setSaid}
        multiline
        maxLength={120}
        autoFocus
        placeholder="吃了什么、大概多少：比如一碗牛肉面，吃了一半"
        accessibilityLabel="吃了什么"
        style={s.textarea}
      />
      <T muted style={s.caption}>营养师只认出吃了什么、多少克，热量按食物库算；记下后可以逐样改克数。</T>
    </KindPick>
  );
}

/** 拍了照：先问是哪一餐，可以补一句，再传给营养师估算（照片发给模型服务商识别）。 */
export function PhotoMeal({ day, photo, kind0, done, onLeave }: { day: Day; photo: Photo; kind0?: string | null; done: (d: Day) => void; onLeave?: () => void }) {
  const [said, setSaid] = useState("");
  return (
    <KindPick
      meals={day.meals}
      kind0={kind0}
      onLeave={onLeave}
      writing
      goTitle="记下，估算热量"
      busyText="营养师在估算…"
      onPick={async (kind) => {
        const form = new FormData();
        form.append("said", said.trim());
        form.append("kind", kind);
        appendPhoto(form, "photo", photo, "meal.jpg");
        done(await api<Day>("/iron/api/meals", { method: "POST", body: form }));
      }}
    >
      <Image source={{ uri: photo.uri }} style={s.photo} resizeMode="cover" accessibilityLabel="这一餐的照片" />
      <Field
        value={said}
        onChangeText={setSaid}
        multiline
        maxLength={120}
        placeholder="补一句更准（可不填）：比如吃了一半、少油"
        accessibilityLabel="补一句"
        style={s.textareaShort}
      />
      <T muted style={s.caption}>照片估算通常偏低，油和酱最容易漏；记下后可以逐样改克数。照片会发给模型服务商识别。</T>
    </KindPick>
  );
}

/** 不拍不写，直接从食物库挑着记一餐（不调用模型）。 */
export function PickFoods({ day, kind0, initial, done }: { day: Day; kind0?: string | null; initial?: Food[]; done: (d: Day) => void }) {
  const [rows, setRows] = useState<LineRow[]>(() => (initial ?? []).map(rowFromFood));
  return (
    <KindPick
      meals={day.meals}
      kind0={kind0}
      onPick={async (kind) => {
        const foods = readLines(rows).filter((f) => f.food_id);
        if (!foods.length) throw new Error("先在上面加一样吃的");
        done(await api<Day>("/iron/api/meals/foods", { method: "POST", json: { kind, foods } }));
      }}
    >
      <FoodLines rows={rows} setRows={setRows} />
      <T muted style={s.caption}>营养按食物库算（内容待审定），不调用模型。</T>
    </KindPick>
  );
}

/** 常吃的一键记：照上次的食物和份量记成这一餐，不调用模型。 */
export function LogUsual({ day, usual, kind0, done }: { day: Day; usual: Usual; kind0?: string | null; done: (d: Day) => void }) {
  return (
    <KindPick
      meals={day.meals}
      kind0={kind0}
      onPick={async (kind) => done(await api<Day>("/iron/api/meals/usual", { method: "POST", json: { id: usual.id, kind } }))}
    />
  );
}

/** 点空着的那一顿弹出来的：拍、写、选、常吃的，都记成这一顿。 */
export function AddMeal({ onWrite, onPick, onPhoto, onUsual }: { onWrite: () => void; onPick: () => void; onPhoto: (p: Photo) => void; onUsual: (u: Usual) => void }) {
  const [usual, setUsual] = useState<Usual[]>([]);
  useEffect(() => {
    let live = true;
    api<{ usual: Usual[] }>("/iron/api/meals/usual")
      .then((r) => live && setUsual(r.usual ?? []))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return (
    <View style={s.stack}>
      <EntryBar onWrite={onWrite} onPick={onPick} onPhoto={onPhoto} />
      {usual.length ? (
        <View style={s.stack}>
          <T muted style={s.caption}>常吃的</T>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.usualRow}>
            {usual.map((u) => (
              <Pressable key={u.id} accessibilityRole="button" accessibilityLabel={`记一份${u.name}`} onPress={() => onUsual(u)} style={({ pressed }) => [s.usual, pressed && s.chipDown]}>
                <FoodTile name={u.name} image={u.image} size={40} />
                <View style={s.usualText}>
                  <T style={s.usualName} numberOfLines={1}>{u.name}</T>
                  <T muted style={s.caption}>{`${Math.round(u.kcal)} 千卡`}</T>
                </View>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.xs },
  bar: { flexDirection: "row", gap: space.s },
  chip: { flex: 1, minWidth: 0, height: 44, alignItems: "center", justifyContent: "center", paddingHorizontal: space.xs, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, borderBottomWidth: 5 },
  chipOn: { backgroundColor: color.amber, borderColor: "#8a5a10" },
  chipDown: { opacity: 0.8 },
  chipOff: { opacity: 0.5 },
  chipText: { color: color.ink, fontSize: 15, fontWeight: "600" },
  chipTextOn: { color: color.ink2 },
  stack: { gap: space.m },
  kindPick: { gap: space.s },
  caption: { fontSize: 13, lineHeight: 19 },
  textarea: { minHeight: 88, textAlignVertical: "top" },
  textareaShort: { minHeight: 60, textAlignVertical: "top" },
  photo: { width: "100%", aspectRatio: 4 / 3, borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: "#e9c784" },
  usualRow: { gap: space.s, paddingRight: space.s },
  usual: { flexDirection: "row", alignItems: "center", gap: space.s, maxWidth: 220, padding: space.s, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight },
  usualText: { flexShrink: 1, minWidth: 0 },
  usualName: { fontSize: 14, fontWeight: "600" },
});
