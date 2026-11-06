// 图鉴（spec §136、§161、§164 第三期；§176 照网页 §175 四段）：只放资料，动作 / 器械 / 食物 / 方案；
// 食物段有 食材 / 食谱，方案段有 训练 / 饮食 两个方案库（饮食方案库 §184）。打分、排名、评论都在排行榜（首页最上面"今日热搜"进去）。
import { useLocalSearchParams } from "expo-router";
import { useState } from "react";

import { FoodSection, FoodSheet } from "@/features/atlas/foods";
import { MachineSheet, MachinesSection } from "@/features/atlas/machines";
import { ExerciseSheet, MovesSection } from "@/features/atlas/moves";
import { DietPlanSheet, DietPlansSection } from "@/features/atlas/diet-plans";
import { PlanSheet, PlansSection } from "@/features/atlas/plans";
import { RecipeSheet, RecipesSection } from "@/features/atlas/recipes";
import type { DietLibBrief, Exercise, ExerciseLib, Food, Machine, PlanLib, Recipe } from "@/features/atlas/types";
import { Pills } from "@/features/atlas/ui";
import { AppBar, Screen, Seg } from "@/ui/pixel";

type SegKey = "moves" | "machines" | "food" | "plans";
const SEGS: readonly (readonly [SegKey, string])[] = [
  ["moves", "动作"],
  ["machines", "器械"],
  ["food", "食物"],
  ["plans", "方案"],
];
// 每段里的小标签
const CHIPS: Record<SegKey, readonly (readonly [string, string])[]> = {
  moves: [],
  machines: [],
  food: [["", "食材"], ["recipes", "食谱"]],
  plans: [["", "训练"], ["diet", "饮食"]],
};

// 同一时间只开一个详情；器械详情里点动作换成动作详情（同网页 openSheet）
type Open =
  | { kind: "move"; x: Exercise; note: string }
  | { kind: "machine"; m: Machine; lib: ExerciseLib | null }
  | { kind: "food"; f: Food }
  | { kind: "recipe"; x: Recipe; reload: () => void }
  | { kind: "plan"; x: PlanLib }
  | { kind: "diet"; x: DietLibBrief }
  | null;

const isSeg = (v: unknown): v is SegKey => v === "moves" || v === "machines" || v === "food" || v === "plans";
const kept: { seg: SegKey; chip: Record<SegKey, string> } = { seg: "moves", chip: { moves: "", machines: "", food: "", plans: "" } };

export default function Atlas() {
  // 能从别处带着段和小标签进来：/atlas?seg=food&chip=recipes
  const params = useLocalSearchParams<{ seg?: string; chip?: string }>();
  const asked = params.seg === "moves" && params.chip === "machines" ? "machines" : params.seg;  // 旧的 seg=moves&chip=machines 进器械
  const [seg, setSegState] = useState<SegKey>(isSeg(asked) ? asked : kept.seg);
  const [chips, setChips] = useState<Record<SegKey, string>>(() => {
    const start = { ...kept.chip };
    if (isSeg(params.seg) && CHIPS[params.seg].some(([k]) => k === params.chip)) start[params.seg] = params.chip ?? "";
    return start;
  });
  const [open, setOpen] = useState<Open>(null);
  const setSeg = (k: SegKey) => { kept.seg = k; setSegState(k); };
  const chip = chips[seg];
  const setChip = (label: string) => {
    const k = CHIPS[seg].find(([, name]) => name === label)?.[0] ?? "";
    const next = { ...chips, [seg]: k };
    kept.chip = next;
    setChips(next);
  };
  const close = () => setOpen(null);
  const openMove = (x: Exercise, note: string) => setOpen({ kind: "move", x, note });

  return (
    <Screen>
      <AppBar title="图鉴" />
      <Seg items={SEGS} value={seg} onChange={setSeg} />
      {CHIPS[seg].length ? (
        <Pills
          label="小标签"
          options={CHIPS[seg].map(([, name]) => name)}
          value={CHIPS[seg].find(([k]) => k === chip)?.[1] ?? CHIPS[seg][0][1]}
          onChange={setChip}
        />
      ) : null}
      {seg === "machines" ? (
        <MachinesSection onOpen={(m, lib) => setOpen({ kind: "machine", m, lib })} onMove={openMove} />
      ) : seg === "moves" ? (
        <MovesSection onOpen={openMove} />
      ) : seg === "food" && chip === "recipes" ? (
        <RecipesSection onOpen={(x, reload) => setOpen({ kind: "recipe", x, reload })} />
      ) : seg === "food" ? (
        <FoodSection onOpen={(f) => setOpen({ kind: "food", f })} />
      ) : seg === "plans" && chip === "diet" ? (
        <DietPlansSection onOpen={(x) => setOpen({ kind: "diet", x })} />
      ) : (
        <PlansSection onOpen={(x) => setOpen({ kind: "plan", x })} />
      )}

      {open?.kind === "move" ? <ExerciseSheet key={open.x.id} x={open.x} note={open.note} onClose={close} /> : null}
      {open?.kind === "machine" ? <MachineSheet m={open.m} lib={open.lib} onClose={close} onMove={openMove} /> : null}
      {open?.kind === "food" ? <FoodSheet f={open.f} onClose={close} /> : null}
      {open?.kind === "recipe" ? <RecipeSheet x={open.x} reload={open.reload} onClose={close} /> : null}
      {open?.kind === "plan" ? <PlanSheet x={open.x} onClose={close} /> : null}
      {open?.kind === "diet" ? <DietPlanSheet key={open.x.id} id={open.x.id} title={open.x.name} onClose={close} /> : null}
    </Screen>
  );
}
