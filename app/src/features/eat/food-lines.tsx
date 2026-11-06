// 逐样食物（照网页版 foodLines，§118）：克数、油量（菜品）、删一样、从食物库加一样；不调用模型。
import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Field, Note, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { type LineRow, linesTotal, OILS, parseGrams, rowFromFood } from "./logic";
import { FoodTile, Pills } from "./parts";
import type { Food } from "./types";

/** 在食物库里搜。 */
export async function searchFoods(q: string): Promise<Food[]> {
  const r = await api<{ foods: Food[] }>(`/iron/api/foods?q=${encodeURIComponent(q)}`);
  return r.foods ?? [];
}

export function FoodLines({ rows, setRows, oil = true }: { rows: LineRow[]; setRows: Dispatch<SetStateAction<LineRow[]>>; oil?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Food[] | null>(null);
  const seq = useRef(0);

  // 记下过的那几样：取回食物库的数，改克数和油量时预估才准；库里没有的按原来的估值比例算
  useEffect(() => {
    for (const r of rows.filter((x) => x.food_id && !x.f)) {
      searchFoods(r.name)
        .then((foods) => {
          const f = foods.find((x) => x.id === r.food_id);
          if (f) setRows((all) => all.map((x) => (x.key === r.key ? { ...x, f } : x)));
        })
        .catch(() => {});
    }
    // 只在打开时取一次
  }, []);

  useEffect(() => {
    const s = q.trim();
    const mine = ++seq.current;
    if (!s) {
      setHits(null);
      return;
    }
    const timer = setTimeout(() => {
      searchFoods(s)
        .catch(() => [] as Food[])
        .then((foods) => {
          if (mine === seq.current) setHits(foods.slice(0, 8));
        });
    }, 200);
    return () => clearTimeout(timer);
  }, [q]);

  const patch = (key: string, p: Partial<LineRow>) => setRows((all) => all.map((x) => (x.key === key ? { ...x, ...p } : x)));

  return (
    <View style={s.wrap}>
      {rows.map((r) => (
        <View key={r.key} style={s.row}>
          <View style={s.top}>
            <View style={s.name}>
              <T style={s.nameText}>{r.name}</T>
              {r.food_id ? null : <T muted style={s.small}>库里没有，按估算</T>}
            </View>
            <Field
              value={r.grams ? String(r.grams) : ""}
              onChangeText={(t) => patch(r.key, { grams: parseGrams(t) })}
              keyboardType="decimal-pad"
              accessibilityLabel={`${r.name}的克数`}
              style={s.grams}
            />
            <T muted>克</T>
            <Pressable accessibilityRole="button" accessibilityLabel={`删掉${r.name}`} hitSlop={8} onPress={() => setRows((all) => all.filter((x) => x.key !== r.key))} style={s.del}>
              <Text style={s.delText}>×</Text>
            </Pressable>
          </View>
          {oil && r.dish ? <Pills items={OILS} value={r.oil || "正常"} onChange={(o) => patch(r.key, { oil: o })} label={`${r.name}的油量`} /> : null}
        </View>
      ))}
      <T muted style={s.total}>{linesTotal(rows)}</T>
      <Field value={q} onChangeText={setQ} placeholder="加一样：搜米饭、鸡胸肉、番茄炒蛋…" accessibilityLabel="在食物库里搜" returnKeyType="search" />
      {hits ? (
        hits.length ? (
          <View style={s.hits}>
            {hits.map((f) => (
              <Pressable
                key={f.id}
                accessibilityRole="button"
                onPress={() => {
                  setRows((all) => [...all, rowFromFood(f)]);
                  setQ("");
                }}
                style={({ pressed }) => [s.hit, pressed && s.hitDown]}
              >
                <FoodTile name={f.name} image={f.image} size={40} />
                <View style={s.hitText}>
                  <T style={s.hitName}>{f.name}</T>
                  <T muted style={s.small}>{`一${f.unit}约 ${Math.round(f.unit_g)} 克 · 每 100 克 ${f.per100.kcal} 千卡`}</T>
                </View>
              </Pressable>
            ))}
          </View>
        ) : (
          <Note>库里没找到，换个叫法试试</Note>
        )
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.s },
  row: { gap: space.xs, paddingBottom: space.s, borderBottomWidth: 1, borderStyle: "dashed", borderColor: color.woodLight },
  top: { flexDirection: "row", alignItems: "center", gap: space.s },
  name: { flex: 1, minWidth: 0 },
  nameText: { fontWeight: "600", fontSize: 14 },
  small: { fontSize: 12, lineHeight: 16 },
  grams: { width: 72, paddingVertical: 6, paddingHorizontal: space.s, textAlign: "right" },
  del: { width: 28, height: 28, alignItems: "center", justifyContent: "center" },
  delText: { color: color.muted, fontSize: 20, fontWeight: "700" },
  total: { fontSize: 13 },
  hits: { gap: space.xs },
  hit: { flexDirection: "row", alignItems: "center", gap: space.s, padding: space.xs, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, backgroundColor: color.paperLight },
  hitDown: { opacity: 0.7 },
  hitText: { flex: 1, minWidth: 0 },
  hitName: { fontSize: 14 },
});
