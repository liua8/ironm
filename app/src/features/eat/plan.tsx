// 今天吃什么（照网页版 todayPlan / planEditSheet，§125）：标题旁"改计划"；下一行今天用哪套、一共多少千卡；
// 两周复盘的建议有才出现；按顿一行，逐样列吃什么、多少克、多少千卡：
// 吃过的列实际记的（点开能改份量），没吃、计划里有的淡色列计划和"照计划记"，都没有的"没排"和"＋ 记"。
import { Fragment, useEffect, useState } from "react";
import { Pressable, StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import { Button, LinkButton, Note, Panel, PixelText, Plank, Seg, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { isPicked, PLAN_GROUPS, planMeta, planOptions, reviewLine, type SlotRow, slotRows } from "./logic";
import { FoodTile } from "./parts";
import type { Day, DietPlan, DietReview, Meal, PlanOption, PlanSet, Usual } from "./types";

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "没有成功，请再试一次。");

type Line = { name: string; grams: number; kcal: number };

function FoodList({ foods, dim }: { foods: Line[]; dim?: boolean }) {
  return (
    <View>
      {foods.map((f, i) => (
        <View key={`${f.name}-${i}`} style={[s.food, i > 0 && s.foodSep]}>
          <T style={[s.foodName, dim && s.dim]} numberOfLines={1}>{f.name}</T>
          <T style={[s.num, s.numG, dim && s.dim]}>{`${Math.round(f.grams)} 克`}</T>
          <T style={[s.num, s.numK, dim && s.dim]}>{`${Math.round(f.kcal)} 千卡`}</T>
        </View>
      ))}
    </View>
  );
}

function MealRow({ row, onMeal, onLog, onAdd }: { row: SlotRow; onMeal: (m: Meal) => void; onLog: (kind: string) => Promise<void>; onAdd: (kind: string) => void }) {
  const [busy, setBusy] = useState(false);
  const planned = row.state === "planned";
  const image = row.state === "done" ? row.image : row.state === "planned" ? row.slot.image : null;
  const kcal = row.state === "unplanned" ? null : row.kcal;
  let end;
  if (row.state === "done") end = <T style={s.tag}>已吃</T>;
  else if (row.state === "planned") {
    end = (
      <Button
        title="照计划记"
        small
        disabled={busy}
        onPress={async () => {
          setBusy(true);
          await onLog(row.kind);
          setBusy(false);
        }}
      />
    );
  } else end = <LinkButton title={`＋ 记`} onPress={() => onAdd(row.kind)} />;
  return (
    <View style={s.meal}>
      <View style={s.head}>
        {image ? <FoodTile name={row.kind} image={image} size={40} dim={planned} /> : null}
        <PixelText size={24} style={planned ? s.dim : undefined}>{row.kind}</PixelText>
        {kcal != null ? (
          <View style={s.kcal}>
            <PixelText size={24} style={planned ? s.dim : undefined}>{String(Math.round(kcal))}</PixelText>
            <T muted style={s.kcalUnit}>千卡</T>
          </View>
        ) : null}
        <View style={s.end}>{end}</View>
      </View>
      {row.state === "done"
        ? row.meals.map((x) => (
            <Pressable key={x.id} accessibilityRole="button" accessibilityLabel={`${x.name}，点开改份量`} onPress={() => onMeal(x)} style={({ pressed }) => [s.eaten, pressed && s.pressed]}>
              <T muted style={s.name}>{`${x.name} ›`}</T>
              {x.foods?.length ? <FoodList foods={x.foods.map((f) => ({ name: f.name, grams: f.grams, kcal: f.macros.kcal }))} /> : null}
            </Pressable>
          ))
        : row.state === "planned" ? (
            <Fragment>
              <T muted style={s.name}>{row.slot.name}</T>
              {row.slot.foods?.length ? <FoodList foods={row.slot.foods} dim /> : null}
            </Fragment>
          ) : (
            <T muted style={s.name}>没排</T>
          )}
    </View>
  );
}

export function TodayPlan({ day, plan, review, reviewErr, flash, onEdit, onMeal, onLog, onAdd, onReview }: {
  day: Day;
  plan: DietPlan | null;
  review: DietReview | null;
  reviewErr: string;
  flash: { tone: "ok" | "error"; text: string } | null;
  onEdit: () => void;
  onMeal: (m: Meal) => void;
  onLog: (kind: string) => Promise<void>;
  onAdd: (kind: string) => void;
  onReview: (action: "confirm" | "undo") => void;
}) {
  const r = reviewLine(review);
  const meta = planMeta(plan);
  return (
    <Panel>
      <View style={s.titleRow}>
        <Plank>今天吃什么</Plank>
        <LinkButton title="改计划" onPress={onEdit} />
      </View>
      {meta ? <T muted style={s.small}>{meta}</T> : null}
      {r ? (
        <View style={s.review}>
          <View style={s.reviewText}>
            <T style={s.reviewTitle}>{r.title}</T>
            <T muted style={s.small}>{r.sub}</T>
          </View>
          {r.action === "confirm" ? <Button title="确认" small onPress={() => onReview("confirm")} /> : <LinkButton title="撤销" onPress={() => onReview("undo")} />}
        </View>
      ) : null}
      {reviewErr ? <Note tone="error">{reviewErr}</Note> : null}
      {flash ? <Note tone={flash.tone}>{flash.text}</Note> : null}
      <View>
        {slotRows(day, plan).map((row) => <MealRow key={row.kind} row={row} onMeal={onMeal} onLog={onLog} onAdd={onAdd} />)}
      </View>
    </Panel>
  );
}

type RecipeList = { recommended: { id: string; name: string; per_serving: { kcal: number } }[]; mine: { id: string; name: string; per_serving: { kcal: number } }[] };

/** 饮食计划：工作日、周末各一套；每一顿从常吃的、我的食谱、推荐食谱、减脂餐里挑，或者空着。 */
export function PlanEdit({ initial, onChanged }: { initial: DietPlan; onChanged: (p: DietPlan) => void }) {
  const [p, setP] = useState(initial);
  const [set, setSet] = useState<PlanSet>(initial.today_set);
  const [options, setOptions] = useState<PlanOption[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([
      api<RecipeList>("/iron/api/recipes").catch(() => ({ recommended: [], mine: [] }) as RecipeList),
      api<{ usual: Usual[] }>("/iron/api/meals/usual").catch(() => ({ usual: [] as Usual[] })),
      api<{ presets: { id: string; name: string; kcal: number }[] }>("/iron/api/meals/presets").catch(() => ({ presets: [] })),
    ]).then(([rec, usual, pre]) => live && setOptions(planOptions(usual.usual ?? [], { recommended: rec.recommended ?? [], mine: rec.mine ?? [] }, pre.presets ?? [])));
    return () => {
      live = false;
    };
  }, []);

  const put = async (slot: string, ref: PlanOption["ref"] | null) => {
    setBusy(true);
    setMsg("");
    try {
      const next = await api<DietPlan>("/iron/api/diet/plan", { method: "PUT", json: { set, slot, ref } });
      setP(next);
      setOpen(null);
      onChanged(next);
    } catch (e) {
      setMsg(errText(e));
    }
    setBusy(false);
  };

  const slots = p.sets[set] ?? {};
  const tot = p.totals[set];
  return (
    <View style={s.stack}>
      <Seg items={[["weekday", "工作日"], ["weekend", "周末"]] as const} value={set} onChange={(k) => { setSet(k); setOpen(null); }} />
      {p.slots.map((k) => {
        const cur = slots[k];
        return (
          <View key={k} style={s.pmRow}>
            <View style={s.pmHead}>
              <View style={s.pmName}>
                <T style={s.pmKind}>{k}</T>
                {cur?.missing ? <T style={s.err}>原来选的已经没有了</T> : <T muted style={s.small} numberOfLines={1}>{cur ? `${cur.name} · ${Math.round(cur.kcal)} 千卡` : "空着"}</T>}
              </View>
              <LinkButton title={open === k ? "收起" : "换"} onPress={() => setOpen(open === k ? null : k)} />
            </View>
            {open === k ? (
              options === null ? <Note>正在读能选的…</Note> : (
                <View style={s.opts}>
                  <Opt label="空着" on={!cur} disabled={busy} onPress={() => put(k, null)} />
                  {PLAN_GROUPS.map((g) => {
                    const os = options.filter((o) => o.group === g);
                    if (!os.length) return null;
                    return (
                      <View key={g} style={s.optGroup}>
                        <T muted style={s.groupName}>{g}</T>
                        {os.map((o) => (
                          <Opt key={`${o.ref.type}-${o.ref.id}`} label={`${o.name} · ${Math.round(o.kcal)} 千卡`} on={isPicked(cur, o)} disabled={busy} onPress={() => put(k, o.ref)} />
                        ))}
                      </View>
                    );
                  })}
                </View>
              )
            ) : null}
          </View>
        );
      })}
      {msg ? <Note tone="error">{msg}</Note> : null}
      <T muted style={s.small}>{`这一套合计 ${tot.kcal} 千卡、蛋白质 ${tot.protein_g} 克${p.target ? `；每天目标 ${p.target.kcal} 千卡、蛋白质 ${p.target.protein_g} 克` : ""}`}</T>
      <T muted style={s.small}>食谱按 1 份算；只有你自己能看到。</T>
    </View>
  );
}

function Opt({ label, on, disabled, onPress }: { label: string; on: boolean; disabled: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="radio" accessibilityState={{ selected: on, disabled }} disabled={disabled} onPress={onPress} style={({ pressed }) => [s.opt, on && s.optOn, pressed && s.pressed]}>
      <T style={s.optText}>{label}</T>
    </Pressable>
  );
}

const s = StyleSheet.create({
  stack: { gap: space.m },
  titleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.m },
  small: { fontSize: 14, lineHeight: 20 },
  review: { flexDirection: "row", alignItems: "center", gap: space.m, padding: space.m, backgroundColor: color.goodSoft, borderWidth: 2, borderColor: color.woodLight },
  reviewText: { flex: 1, minWidth: 0, gap: 2 },
  reviewTitle: { fontWeight: "700", color: color.accentText, fontSize: 14 },
  meal: { gap: 6, paddingVertical: 14, borderTopWidth: 2, borderStyle: "dashed", borderColor: color.woodLight },
  head: { flexDirection: "row", alignItems: "center", gap: 10 },
  kcal: { flexDirection: "row", alignItems: "baseline", gap: 2, flexShrink: 1 },
  kcalUnit: { fontSize: 13 },
  end: { marginLeft: "auto" },
  tag: { fontSize: 13, fontWeight: "700", color: color.woodDark, backgroundColor: color.amber, borderWidth: 2, borderColor: "#8a5a10", paddingHorizontal: space.s, letterSpacing: 1 },
  dim: { color: color.muted },
  name: { fontSize: 14, lineHeight: 20 },
  eaten: { gap: 4 },
  pressed: { opacity: 0.7 },
  food: { flexDirection: "row", gap: space.s, paddingVertical: 5 },
  foodSep: { borderTopWidth: 1, borderStyle: "dashed", borderColor: color.woodLight },
  foodName: { flex: 1, minWidth: 0, fontSize: 14 },
  num: { textAlign: "right", fontWeight: "700", fontSize: 14 },
  numG: { width: 60 },
  numK: { width: 72 },
  pmRow: { gap: space.s, paddingVertical: space.s, borderTopWidth: 2, borderStyle: "dashed", borderColor: color.woodLight },
  pmHead: { flexDirection: "row", alignItems: "center", gap: space.m },
  pmName: { flex: 1, minWidth: 0 },
  pmKind: { fontWeight: "700" },
  err: { color: color.heat, fontSize: 13 },
  opts: { gap: space.s },
  optGroup: { gap: space.xs },
  groupName: { fontSize: 12, lineHeight: 16, letterSpacing: 1 },
  opt: { paddingVertical: space.s, paddingHorizontal: space.m, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.woodLight },
  optOn: { backgroundColor: color.amber, borderColor: "#8a5a10" },
  optText: { fontSize: 14, lineHeight: 20 },
});
