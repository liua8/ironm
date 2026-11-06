// 图鉴·饮食方案库（同网页 dietLibAtlas / dietLibSheet，spec §184）：每份是一整天怎么吃；点开看适合谁、热量和营养怎么分、
// 要点、工作日和周末各四顿（按他的热量目标缩放）、依据；"用这份当我的饮食计划"确认后换掉饮食计划，能撤销一次。
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { errText, useLoad } from "./data";
import { plain } from "./logic";
import type { DietLibBrief, DietLibPlan } from "./types";
import { Bullets, Caption, Chip, H3, Loading, MarkList, Pills, Row, Sheet, Tags, ui } from "./ui";

type SetKey = "weekday" | "weekend";
const SET_NAMES = { weekday: "工作日", weekend: "周末" } as const;
type SetName = (typeof SET_NAMES)[SetKey];
const SET_OF: Record<SetName, SetKey> = { 工作日: "weekday", 周末: "weekend" };
const SET_OPTIONS: readonly SetName[] = ["工作日", "周末"];

/** 一顿的名字去掉"（1.5 份）"，份数另写在右边。 */
export function slotName(name: string): string {
  return name.replace(/（[\d.]+ 份）$/, "");
}

export function servingsLine(kcal: number, servings: number): string {
  return `${Math.round(kcal)} 千卡${servings === 1 ? "" : ` · ${servings} 份`}`;
}

export function DietPlansSection({ onOpen }: { onOpen: (x: DietLibBrief) => void }) {
  const { data, error, reload } = useLoad(() => api<{ plans: DietLibBrief[]; note: string }>("/iron/api/diet/library"));
  if (!data) return <Loading error={error} onRetry={reload} what="饮食方案库" />;
  return (
    <View style={s.wrap}>
      {data.plans.map((x) => (
        <Pressable
          key={x.id}
          accessibilityRole="button"
          accessibilityLabel={`${x.name}，点开看一天吃什么`}
          onPress={() => onOpen(x)}
          style={({ pressed }) => [s.card, pressed && s.pressed]}
        >
          <Text style={s.name}>{x.name}</Text>
          <Text style={ui.muted}>{`适合：${plain(x.suits[0])}`}</Text>
          <Text style={s.kcal}>{`每天约 ${x.per_day.weekday.kcal} 千卡 · 蛋白质 ${x.per_day.weekday.protein_g} 克`}</Text>
          <View style={s.chips}>
            {x.goals.map((g) => (
              <Chip key={g}>{g}</Chip>
            ))}
          </View>
        </Pressable>
      ))}
      <View style={s.note}>
        <Caption>{data.note}</Caption>
      </View>
    </View>
  );
}

type Step = "idle" | "confirm" | "busy" | "applied" | "undone";

export function DietPlanSheet({ id, title, onClose }: { id: string; title: string; onClose: () => void }) {
  const { data: x, error, reload } = useLoad(() => api<DietLibPlan>(`/iron/api/diet/library/${encodeURIComponent(id)}`), [id]);
  const [set, setSet] = useState<SetKey>("weekday");
  const [step, setStep] = useState<Step>("idle");
  const [msg, setMsg] = useState<{ text: string; ok: boolean }>({ text: "", ok: false });
  if (!x) {
    return (
      <Sheet title={title} onClose={onClose}>
        <Loading error={error} onRetry={reload} what="这份方案" />
      </Sheet>
    );
  }
  const mine = x.scaled.target ? x.scaled : null; // 有热量目标时按目标缩放后的份数
  const day = (mine ?? x).days[set];
  const apply = async () => {
    setStep("busy");
    setMsg({ text: "", ok: false });
    try {
      await api(`/iron/api/diet/library/${encodeURIComponent(x.id)}/apply`, { method: "POST", json: {} });
      setStep("applied");
      setMsg({ text: `饮食计划换成了「${x.name}」`, ok: true });
    } catch (err) {
      setStep("idle");
      setMsg({ text: errText(err), ok: false });
    }
  };
  const undo = async () => {
    setStep("busy");
    try {
      await api("/iron/api/diet/library/undo", { method: "POST", json: {} });
      setStep("undone");
      setMsg({ text: "撤销了，饮食计划回到换之前", ok: true });
    } catch (err) {
      setStep("applied");
      setMsg({ text: errText(err), ok: false });
    }
  };
  return (
    <Sheet title={x.name} onClose={onClose}>
      <Tags items={x.goals} />
      <Text style={ui.lede}>{x.summary}</Text>
      <H3>适合</H3>
      <MarkList items={x.suits} tone="ok" />
      <H3>先问医生或营养师</H3>
      <MarkList items={x.not_for} tone="warn" />
      <H3>热量怎么定</H3>
      <Text style={ui.body}>{x.energy}</Text>
      <H3>三大营养素</H3>
      <Bullets items={[`蛋白质：${x.macros.protein}`, `碳水：${x.macros.carbs}`, `脂肪：${x.macros.fat}`]} />
      <H3>吃法要点</H3>
      <Bullets items={x.points} />
      <H3>一天吃什么</H3>
      <Pills label="工作日或周末" options={SET_OPTIONS} value={SET_NAMES[set]} onChange={(k) => setSet(SET_OF[k])} />
      <View>
        {Object.entries(day.slots).map(([k, sl]) => (
          <Row
            key={k}
            title={`${k} · ${slotName(sl.name)}`}
            sub={sl.foods.map((f) => `${f.name} ${f.grams} 克`).join("、")}
            right={<Text style={s.end}>{servingsLine(sl.kcal, sl.servings)}</Text>}
          />
        ))}
      </View>
      <Text style={s.total}>{`一天合计 ${day.total.kcal} 千卡 · 蛋白质 ${day.total.protein_g} 克 · 碳水 ${day.total.carbs_g} 克 · 脂肪 ${day.total.fat_g} 克`}</Text>
      <Caption>{mine?.target ? `按你每天 ${mine.target.kcal} 千卡的目标算了份数；${x.note}` : `按推荐份数算；${x.note}`}</Caption>
      {step === "idle" ? <Button title="用这份当我的饮食计划" onPress={() => setStep("confirm")} /> : null}
      {step === "confirm" ? (
        <View style={s.confirm}>
          <Text style={ui.body}>换掉饮食计划里工作日、周末的四顿？换之前的计划会存一份，能撤销一次。</Text>
          <View style={ui.btnRow}>
            <Button title="确认换" small onPress={apply} />
            <Button title="先不换" kind="ghost" small onPress={() => setStep("idle")} />
          </View>
        </View>
      ) : null}
      {step === "applied" ? (
        <View style={ui.btnRow}>
          <Button title="撤销" kind="ghost" small onPress={undo} />
        </View>
      ) : null}
      <Note tone={msg.ok ? "ok" : "error"}>{msg.text}</Note>
      <Caption>确认后把饮食计划的工作日、周末四顿换成这一份，之后在饮食计划里照常能改。</Caption>
      <H3>依据</H3>
      <Bullets items={x.refs} />
    </Sheet>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 10 },
  card: { gap: 4, backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: 14 },
  pressed: { opacity: 0.75 },
  name: { color: color.ink, fontSize: 17, fontWeight: "700" },
  kcal: { color: color.ink2, fontSize: 13 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 2 },
  note: { alignSelf: "flex-start", backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, paddingHorizontal: 10, paddingVertical: 6 },
  end: { color: color.muted, fontSize: 13, fontWeight: "600" },
  total: { color: color.ink, fontSize: 14, fontWeight: "700", lineHeight: 21 },
  confirm: { gap: space.s, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m },
});
