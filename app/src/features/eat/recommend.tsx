// 推荐这一餐（同网页 recommendBox / recCard，spec §118）：按目标、今天还差多少、天气和状态挑一餐；
// "就吃这个，记下来"把推荐记成这一餐（营养是推荐里估算的）。要用自己的模型，没填时给"去填模型"（§167）。
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api, isNoModel } from "@/api/client";
import { NeedModel } from "@/features/me/need-model";
import { Button, Note, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { mealKindNow } from "./logic";
import { Pills } from "./parts";
import type { Day } from "./types";

const APPETITES = ["清淡", "正常", "很饿"] as const;
type Macros = { kcal: number; protein_g: number; carbs_g: number; fat_g: number };
type Dish = { name: string; amount?: string; kcal: number; protein_g: number };
export type Rec = {
  recommendation: { title: string; why?: string; tips?: string; dishes: Dish[] };
  total: Macros;
  remaining: Macros | null;
  warning?: string | null;
  considered: string[];
};

export function RecommendMeal({ done }: { done: (d: Day) => void }) {
  const [appetite, setAppetite] = useState<(typeof APPETITES)[number]>("正常");
  const [rec, setRec] = useState<Rec | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; needModel?: boolean } | null>(null);
  const kind = mealKindNow();

  const go = async () => {
    setBusy(true);
    setMsg({ text: "营养师在按你的目标、今天还差多少、天气和状态挑…" });
    setRec(null);
    try {
      setRec(await api<Rec>("/iron/api/meals/recommend", { method: "POST", json: { kind, appetite } }));
      setMsg(null);
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "这次没推荐出来，稍后再试", needModel: isNoModel(e) });
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (!rec) return;
    setBusy(true);
    try {
      const r = rec.recommendation;
      done(await api<Day>("/iron/api/meals/record", { method: "POST", json: { kind, name: r.title, items: r.dishes.map((x) => `${x.name}${x.amount ? ` ${x.amount}` : ""}`), macros: rec.total } }));
    } catch (e) {
      setMsg({ text: e instanceof Error ? e.message : "没记下，稍后再试" });
      setBusy(false);
    }
  };

  return (
    <View style={s.box}>
      <T muted>{`给${kind}推荐 · 胃口`}</T>
      <Pills items={APPETITES} value={appetite} onChange={setAppetite} label="胃口" />
      <Button title="推荐这一餐" onPress={go} disabled={busy} />
      {msg?.needModel ? <NeedModel text={msg.text} /> : msg ? <Note tone={busy ? "muted" : "error"}>{msg.text}</Note> : null}
      {rec ? (
        <View style={s.rec}>
          <Text style={s.title}>{rec.recommendation.title}</Text>
          {rec.recommendation.why ? <Text style={s.p}>{rec.recommendation.why}</Text> : null}
          {rec.considered.length ? <Text style={s.muted}>{`考虑了：${rec.considered.join("、")}`}</Text> : null}
          {rec.recommendation.dishes.map((x, i) => (
            <View key={`${x.name}-${i}`} style={s.dish}>
              <Text style={[s.p, s.flex]}>{[x.name, x.amount].filter(Boolean).join(" ")}</Text>
              <Text style={s.muted}>{`${Math.round(x.kcal)} 千卡 · 蛋白质 ${Math.round(x.protein_g)} 克`}</Text>
            </View>
          ))}
          <Text style={s.total}>{`合计 ${Math.round(rec.total.kcal)} 千卡 · 蛋白质 ${Math.round(rec.total.protein_g)} 克 · 碳水 ${Math.round(rec.total.carbs_g)} 克 · 脂肪 ${Math.round(rec.total.fat_g)} 克`}</Text>
          {rec.remaining ? <Text style={s.muted}>{`今天还剩约 ${Math.round(rec.remaining.kcal)} 千卡、蛋白质约 ${Math.round(rec.remaining.protein_g)} 克`}</Text> : null}
          {rec.warning ? <Note tone="error">{rec.warning}</Note> : null}
          {rec.recommendation.tips ? <Text style={s.muted}>{rec.recommendation.tips}</Text> : null}
          <Button kind="ghost" title="就吃这个，记下来" onPress={save} disabled={busy} />
          <Text style={s.muted}>营养是估算的。</Text>
        </View>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  box: { gap: space.s },
  rec: { gap: 6, borderTopWidth: 1, borderTopColor: color.woodLight, paddingTop: space.s },
  title: { color: color.ink, fontSize: 16, fontWeight: "700" },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
  total: { color: color.ink, fontSize: 13, fontWeight: "600", lineHeight: 19 },
  dish: { flexDirection: "row", gap: space.s, alignItems: "baseline" },
  flex: { flex: 1 },
});
