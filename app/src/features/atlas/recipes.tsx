// 图鉴·食谱（同网页 recipesPage / recipesCard / recipeSheet）：一排标签（推荐、减脂、增肌、早餐、带饭、我的），
// 两列卡片写每份热量和蛋白质；点开看原料、做法、每份营养，按份数记成一餐；自己的食谱能删。
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { errText, useLoad } from "./data";
import { ImageCredit } from "./foods";
import { foodMark, imgUrl, plain, RECIPE_ALL, RECIPE_MINE, recipesFor, recipeTagLabel, recipeTags, servingsText, stepServings } from "./logic";
import { KindPick } from "./meal-log";
import type { Recipe, RecipeBook } from "./types";
import { Bullets, Caption, Card, Cover, Grid, H3, Loading, Pills, Sheet, Steps, TwoStep, ui } from "./ui";

let keptTag = RECIPE_ALL; // 离开再回来，选的标签还在（同网页 recipeState）

export function RecipesSection({ onOpen }: { onOpen: (x: Recipe, reload: () => void) => void }) {
  const { data: r, error, reload } = useLoad(() => api<RecipeBook>("/iron/api/recipes"));
  const [tag, setTagState] = useState(keptTag);
  const setTag = (t: string) => { keptTag = t; setTagState(t); };
  if (!r) return <Loading error={error ? "食谱这次没读到，稍后再试。" : null} onRetry={reload} what="食谱" />;
  const tags = recipeTags(r);
  const cur = tags.includes(tag) ? tag : RECIPE_ALL;
  const list = recipesFor(r, cur);
  return (
    <View style={s.wrap}>
      <Pills label="食谱分类" scroll options={tags} value={cur} onChange={setTag} labelOf={(k) => recipeTagLabel(k, r)} />
      {list.length ? (
        <Grid>
          {list.map((x) => (
            <Card
              key={x.id}
              label={`${x.name}，点开看原料和做法`}
              onPress={() => onOpen(x, reload)}
              cover={<Cover uri={imgUrl(x.image?.url)} mark={foodMark(x.name)} style={s.cover} />}
              title={x.name}
              sub={`${Math.round(x.per_serving.kcal)} 千卡 · ${Math.round(x.per_serving.protein_g)} 克蛋白`}
            />
          ))}
        </Grid>
      ) : null}
      {cur === RECIPE_MINE && !r.mine.length ? (
        <View style={s.box}>
          <Caption>常做的菜存成食谱，以后一点就能记。</Caption>
        </View>
      ) : null}
      <View style={s.box}>
        <Caption>{r.note}</Caption>
      </View>
    </View>
  );
}

export function RecipeSheet({ x, onClose, reload }: { x: Recipe; onClose: () => void; reload: () => void }) {
  const [servings, setServings] = useState(1);
  const [msg, setMsg] = useState("");
  const macros: [string, number, string][] = [
    ["每份热量", x.per_serving.kcal, "千卡"],
    ["蛋白质", x.per_serving.protein_g, "克"],
    ["碳水", x.per_serving.carbs_g, "克"],
    ["脂肪", x.per_serving.fat_g, "克"],
  ];
  return (
    <Sheet title={x.name} onClose={onClose}>
      <Cover uri={imgUrl(x.image?.url)} mark={foodMark(x.name)} style={s.hero} />
      <ImageCredit image={x.image} />
      <View style={s.macros}>
        {macros.map(([k, v, u]) => (
          <View key={k} style={s.macro}>
            <Text style={s.macroNum}>
              {Math.round(v)}
              <Text style={s.unit}>{` ${u}`}</Text>
            </Text>
            <Text style={s.macroName}>{k}</Text>
          </View>
        ))}
      </View>
      <H3>{`原料（${x.servings} 份的量）`}</H3>
      <Bullets items={[...x.parts.map((p) => `${p.name} ${p.grams} 克`), ...(x.oil ? [`食用油 ${x.oil} 克`] : [])]} />
      {x.steps.length ? (
        <>
          <H3>做法</H3>
          <Steps items={x.steps.map(plain)} />
        </>
      ) : null}
      <View style={s.stepper}>
        <Text style={ui.body}>吃了几份</Text>
        <StepBtn label="−" a11y="少半份" onPress={() => setServings((v) => stepServings(v, -0.5))} />
        <Text style={s.servings}>{String(servings)}</Text>
        <StepBtn label="+" a11y="多半份" onPress={() => setServings((v) => stepServings(v, 0.5))} />
      </View>
      <Text style={ui.muted}>{servingsText(x, servings)}</Text>
      <KindPick
        onSave={async (kind) => {
          const r = await api<{ replaced?: string[] }>(`/iron/api/recipes/${encodeURIComponent(x.id)}/log`, { method: "POST", json: { kind, servings } });
          return r.replaced?.length ? `记下了，替换了原来的${r.replaced.join("、")}` : "记下了";
        }}
      />
      {x.mine ? (
        <View style={ui.btnRow}>
          <TwoStep
            label="删除这个食谱"
            sure="确定删除？"
            onConfirm={() => {
              api(`/iron/api/recipes/${encodeURIComponent(x.id)}`, { method: "DELETE" })
                .then(() => { onClose(); reload(); })
                .catch((err: unknown) => setMsg(errText(err)));
            }}
          />
        </View>
      ) : null}
      <Note tone="error">{msg}</Note>
    </Sheet>
  );
}

function StepBtn({ label, a11y, onPress }: { label: string; a11y: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={a11y} onPress={onPress} style={s.stepBtn}>
      <Text style={s.stepText}>{label}</Text>
    </Pressable>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  box: { alignSelf: "flex-start", backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: 10, paddingVertical: 6 },
  cover: { width: "100%", aspectRatio: 4 / 3 },
  hero: { width: "100%", aspectRatio: 16 / 9 },
  macros: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  macro: { flexGrow: 1, flexBasis: 70, alignItems: "center", gap: 2, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.woodLight, paddingVertical: space.s },
  macroNum: { color: color.ink, fontSize: 18, fontWeight: "700" },
  unit: { color: color.muted, fontSize: 12, fontWeight: "400" },
  macroName: { color: color.muted, fontSize: 12 },
  stepper: { flexDirection: "row", alignItems: "center", gap: space.m },
  stepBtn: { width: 40, height: 40, alignItems: "center", justifyContent: "center", borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight },
  stepText: { color: color.woodDark, fontSize: 20, fontWeight: "700" },
  servings: { minWidth: 32, textAlign: "center", color: color.ink, fontSize: 20, fontWeight: "700" },
});
