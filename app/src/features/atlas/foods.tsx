// 图鉴·食材（同网页 foodAtlas / foodSheet）：在食物库里搜，没搜时一排常搜的词；营养按每 100 克；
// 点开看热量、三大营养素，带着它记一餐（克数、油量、哪一餐）。
import { useEffect, useRef, useState } from "react";
import { Linking, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button, Field, PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { FOOD_STARTERS, foodCredit, foodMark, imgUrl, OILS } from "./logic";
import { KindPick } from "./meal-log";
import type { Food, Img } from "./types";
import { Caption, Card, Cover, Grid, H3, Pills, Sheet, ui } from "./ui";

let lastQ = ""; // 离开再回来，搜的词还在（同网页 foodAtlasQ）

type Found = { q: string; foods: Food[] | null; error: boolean };

export function FoodSection({ onOpen }: { onOpen: (f: Food) => void }) {
  const [q, setQ] = useState(lastQ);
  const [found, setFound] = useState<Found>({ q: "", foods: null, error: false });
  const seq = useRef(0);
  useEffect(() => {
    const text = q.trim();
    lastQ = text;
    const mine = ++seq.current;
    if (!text) { setFound({ q: "", foods: null, error: false }); return; }
    const timer = setTimeout(() => {
      api<{ foods: Food[] }>(`/iron/api/foods?q=${encodeURIComponent(text)}`)
        .then((r) => { if (mine === seq.current) setFound({ q: text, foods: r.foods ?? [], error: false }); })
        .catch(() => { if (mine === seq.current) setFound({ q: text, foods: null, error: true }); });
    }, 200);
    return () => clearTimeout(timer);
  }, [q]);
  return (
    <View style={s.wrap}>
      <Field value={q} onChangeText={setQ} placeholder="搜食物：米饭、鸡胸肉、番茄炒蛋…" accessibilityLabel="在食物库里搜" returnKeyType="search" style={ui.search} />
      <Pills label="常搜的" options={FOOD_STARTERS} value="" onChange={setQ} />
      {!q.trim() ? (
        <View style={s.box}>
          <Caption>在常见食物库里搜，营养按每 100 克算（内容待审定）。</Caption>
        </View>
      ) : found.error ? (
        <View style={s.box}>
          <Text style={ui.muted}>食物库这次没读到，稍后再试。</Text>
        </View>
      ) : !found.foods ? (
        <View style={s.box}>
          <Caption>正在搜…</Caption>
        </View>
      ) : found.foods.length ? (
        <Grid>
          {found.foods.map((f) => (
            <Card
              key={f.id}
              label={`${f.name}，每 100 克 ${f.per100.kcal} 千卡`}
              onPress={() => onOpen(f)}
              cover={<Cover uri={imgUrl(f.image?.url)} mark={foodMark(f.name)} style={s.cover} />}
              title={f.name}
              sub={
                <View>
                  <Text style={s.kcal}>
                    {`${f.per100.kcal} 千卡`}
                    <Text style={s.protein}>{` · 蛋白质 ${f.per100.protein_g} 克`}</Text>
                  </Text>
                  <Text style={s.per}>每 100 克</Text>
                </View>
              }
            />
          ))}
        </Grid>
      ) : (
        <View style={s.box}>
          <Text style={ui.muted}>库里没找到，换个叫法试试。</Text>
        </View>
      )}
    </View>
  );
}

/** 配图署名，点了去原图页。 */
export function ImageCredit({ image }: { image: Img | null | undefined }) {
  const text = foodCredit(image);
  if (!text) return null;
  const page = image?.page;
  return (
    <Text style={[s.credit, page ? s.link : null]} onPress={page ? () => { Linking.openURL(page).catch(() => {}); } : undefined}>
      {text}
    </Text>
  );
}

export function FoodSheet({ f, onClose }: { f: Food; onClose: () => void }) {
  const n = f.per100;
  const [logging, setLogging] = useState(false);
  const [grams, setGrams] = useState(String(Math.round(f.unit_g)));
  const [oil, setOil] = useState("正常");
  const g = Number(grams);
  return (
    <Sheet title={f.name} onClose={onClose}>
      <View style={s.head}>
        <Cover uri={imgUrl(f.image?.url)} mark={foodMark(f.name)} style={s.headPic} />
        <View style={s.headText}>
          <Text>
            <PixelText size={36}>{String(n.kcal)}</PixelText>
            <Text style={ui.muted}> 千卡 / 100 克</Text>
          </Text>
          <Text style={ui.muted}>{`一${f.unit}约 ${Math.round(f.unit_g)} 克${f.cat ? ` · ${f.cat}` : ""}`}</Text>
        </View>
      </View>
      <ImageCredit image={f.image} />
      <View style={s.macros}>
        {(
          [
            ["蛋白质", n.protein_g],
            ["碳水", n.carbs_g],
            ["脂肪", n.fat_g],
          ] as const
        ).map(([k, v]) => (
          <View key={k} style={s.macro}>
            <Text style={ui.muted}>{k}</Text>
            <Text style={s.macroNum}>{`${v} 克`}</Text>
          </View>
        ))}
      </View>
      {!logging ? (
        <Button title="带着它记一餐" onPress={() => setLogging(true)} />
      ) : (
        <View style={s.log}>
          <H3>记一餐</H3>
          <View style={s.gramRow}>
            <Text style={ui.body}>吃了</Text>
            <Field value={grams} onChangeText={setGrams} keyboardType="decimal-pad" accessibilityLabel={`${f.name}的克数`} style={s.gramField} />
            <Text style={ui.body}>克</Text>
          </View>
          {g > 0 ? <Caption>{`大约 ${Math.round((n.kcal * g) / 100)} 千卡（保存后按食物库算准）`}</Caption> : null}
          {f.dish ? <Pills label="油量" options={OILS} value={oil} onChange={setOil} /> : null}
          <KindPick
            onSave={async (kind) => {
              if (!(g > 0 && g <= 3000)) throw new Error("克数写 1 到 3000 之间");
              await api("/iron/api/meals/foods", { method: "POST", json: { kind, foods: [{ name: f.name, food_id: f.id, grams: g, oil }] } });
              return `记下了：${f.name}`;
            }}
          />
          <Caption>营养按食物库算（内容待审定），不调用模型。</Caption>
        </View>
      )}
    </Sheet>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  box: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m },
  cover: { width: "100%", aspectRatio: 4 / 3 },
  kcal: { color: color.ink, fontSize: 14, fontWeight: "700" },
  protein: { color: color.muted, fontSize: 12, fontWeight: "400" },
  per: { color: color.muted, fontSize: 12 },
  head: { flexDirection: "row", gap: space.m, alignItems: "center" },
  headPic: { width: 96, height: 96 },
  headText: { flex: 1, gap: 4 },
  credit: { color: color.muted, fontSize: 12 },
  link: { textDecorationLine: "underline" },
  macros: { flexDirection: "row", gap: space.s },
  macro: { flex: 1, alignItems: "center", gap: 2, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, paddingVertical: space.s },
  macroNum: { color: color.ink, fontSize: 16, fontWeight: "700" },
  log: { gap: space.s, borderTopWidth: 1, borderTopColor: color.woodLight, paddingTop: space.s },
  gramRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  gramField: { width: 100, paddingVertical: 8 },
});
