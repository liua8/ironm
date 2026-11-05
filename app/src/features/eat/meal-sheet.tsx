// 记下的一餐（照网页版 mealSheet / editFoods，§118）：照片或配图、四个数、逐样改份量（按库重算、不调用模型）、删除。
import { useState } from "react";
import { Image, StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import { useAuthedImage } from "@/lib/authed-image";
import { Button, Note, PixelText, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { FoodLines } from "./food-lines";
import { type LineRow, readLines, rowsFromMeal } from "./logic";
import { FoodTile, SubTitle } from "./parts";
import type { Day, Macros, Meal } from "./types";

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "没有成功，请再试一次。");

/** 热量、蛋白质、碳水、脂肪四格。 */
export function MacroGrid({ m, first = "热量" }: { m: Macros; first?: string }) {
  const cells: [string, number, string][] = [[first, m.kcal, "千卡"], ["蛋白质", m.protein_g, "克"], ["碳水", m.carbs_g, "克"], ["脂肪", m.fat_g, "克"]];
  return (
    <View style={s.grid}>
      {cells.map(([k, v, u]) => (
        <View key={k} style={s.cell}>
          <PixelText size={24}>{String(Math.round(v))}<T muted style={s.unit}>{` ${u}`}</T></PixelText>
          <T muted style={s.cellKey}>{k}</T>
        </View>
      ))}
    </View>
  );
}

/** 拍的照片要带登录凭证取：手机上图片请求能带凭证；网页预览先取回来再显示。 */
function MealPhoto({ id }: { id: string }) {
  const source = useAuthedImage(`/iron/api/meals/${id}/photo`);
  if (!source) return null;
  return <Image source={source} style={s.photo} resizeMode="cover" accessibilityLabel="这一餐的照片" />;
}

export function MealDetail({ meal: x, done }: { meal: Meal; done: (d: Day, flash?: string) => void }) {
  const [rows, setRows] = useState<LineRow[]>(() => rowsFromMeal(x));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const hasFoods = !!x.foods?.length;

  const save = async () => {
    const foods = readLines(rows);
    if (!foods.length) {
      setMsg("至少留一样；整条不要了就点下面的删除");
      return;
    }
    setBusy(true);
    setMsg("");
    try {
      await api(`/iron/api/meals/${x.id}`, { method: "PUT", json: { day: x.day, foods } });
      done(await api<Day>("/iron/api/meals"), "改好了");
    } catch (e) {
      setMsg(errText(e));
      setBusy(false);
    }
  };
  const del = async () => {
    setBusy(true);
    setMsg("");
    try {
      await api(`/iron/api/meals/${x.id}`, { method: "DELETE" });
      done(await api<Day>("/iron/api/meals"), "删掉了");
    } catch (e) {
      setMsg(errText(e));
      setBusy(false);
    }
  };

  const caption = [hasFoods ? "营养按食物库算" : "营养是估算的", x.confidence ? `把握：${x.confidence}` : "", x.note ?? ""].filter(Boolean).join("；");
  return (
    <View style={s.stack}>
      {x.has_photo ? <MealPhoto id={x.id} /> : x.image ? (
        <View style={s.stack}>
          <View style={s.hero}><FoodTile name={x.name} image={x.image} size={120} /></View>
          {x.image.author || x.image.license ? <T muted style={s.caption}>{`图：${x.image.author || "Wikimedia Commons"}${x.image.license ? ` · ${x.image.license}` : ""}`}</T> : null}
        </View>
      ) : null}
      <MacroGrid m={x.macros} />
      {hasFoods ? (
        <View style={s.stack}>
          <SubTitle>吃了什么（可以改克数）</SubTitle>
          <FoodLines rows={rows} setRows={setRows} />
          <View style={s.row}><Button title="保存份量" small onPress={save} disabled={busy} /></View>
        </View>
      ) : x.items.length ? (
        <View style={s.stack}>
          <SubTitle>吃了什么</SubTitle>
          {x.items.map((t, i) => <T key={i}>{`· ${t}`}</T>)}
        </View>
      ) : null}
      <T muted style={s.caption}>{caption}</T>
      {msg ? <Note tone="error">{msg}</Note> : null}
      <Button title="删除这条" kind="ghost" onPress={del} disabled={busy} />
    </View>
  );
}

const s = StyleSheet.create({
  stack: { gap: space.m },
  row: { flexDirection: "row" },
  grid: { flexDirection: "row", flexWrap: "wrap", rowGap: space.s },
  cell: { width: "50%", gap: 2 },
  unit: { fontSize: 13 },
  cellKey: { fontSize: 13, lineHeight: 18 },
  caption: { fontSize: 13, lineHeight: 19 },
  hero: { alignItems: "center" },
  photo: { width: "100%", aspectRatio: 4 / 3, borderWidth: 3, borderColor: color.wood, backgroundColor: "#e9c784" },
});
