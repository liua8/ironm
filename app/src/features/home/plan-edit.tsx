// 计划页直接改（同网页 §106 的 itemSheet、swapSheet、scopeSeg、planEdit）：改组次、换动作、去掉动作、排顺序；
// 今天那天可以选"只改今天 / 以后都改"，别的天改的就是每周这一天的计划。
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { syncTrainingReminder } from "@/lib/notify";
import { Button, LinkButton, Note, Seg } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { askCoach, Sheet, Thumb } from "./bits";
import { exImg, parseReps, repsText } from "./train-logic";
import type { Library, PlanItem } from "./types";

export type Scope = "today" | "always";
export type EditCtx = { day: number; isToday: boolean; lib: Library | null; items: PlanItem[]; name: string };
export type Edit =
  | { kind: "edit"; exercise: string; sets: number; reps?: string }
  | { kind: "remove"; exercise: string }
  | { kind: "swap"; exercise: string; to: string }
  | { kind: "order"; names: string[] };
export type EditResult = { status: string; lines: string[]; notes: string[]; warnings: string[]; draft?: { id: string } | null };

/** 改计划：今天那天才能选只改今天。 */
export async function planEdit(ctx: EditCtx, scope: Scope, edit: Edit): Promise<{ r: EditResult; scope: Scope }> {
  const sc: Scope = ctx.isToday ? scope : "always";
  const r = await api<EditResult>("/iron/api/plan/edit", { method: "POST", json: { day: ctx.day, scope: sc, edit } });
  void syncTrainingReminder(); // 训练日提醒跟着计划走
  return { r, scope: sc };
}

/** 只改今天 / 以后都改。 */
export function ScopeSeg({ isToday, value, onChange }: { isToday: boolean; value: Scope; onChange: (v: Scope) => void }) {
  if (!isToday) return <Text style={s.caption}>改的是每周这一天的计划</Text>;
  return <Seg items={[["today", "只改今天"], ["always", "以后都改"]] as const} value={value} onChange={onChange} />;
}

function Stepper({ label, value, unit, onDown, onUp }: { label: string; value: string; unit: string; onDown: () => void; onUp: () => void }) {
  return (
    <View style={s.stepper}>
      <Button small kind="wood" title="−" onPress={onDown} />
      <View style={s.stepVal} accessibilityLabel={`${label} ${value} ${unit}`}>
        <Text style={s.stepNum}>{value}</Text>
        <Text style={s.stepUnit}>{unit}</Text>
      </View>
      <Button small kind="wood" title="+" onPress={onUp} />
    </View>
  );
}

type Done = (r: EditResult, scope: Scope) => void;

/** 点一个动作：改组次、换动作、去掉。 */
export function ItemSheet({ ctx, it, onClose, onDone }: { ctx: EditCtx; it: PlanItem; onClose: () => void; onDone: Done }) {
  const [scope, setScope] = useState<Scope>("today");
  const [sets, setSets] = useState(it.sets);
  const [reps, setReps] = useState(parseReps(it.reps));
  const [msg, setMsg] = useState("");
  const [sure, setSure] = useState(false);
  const [swap, setSwap] = useState(false);
  const was0 = parseReps(it.reps);
  const was = was0 ? repsText(was0) : it.reps;
  const changed = sets !== it.sets || (reps !== null && repsText(reps) !== was);
  const only = ctx.items.length <= 1;
  const send = async (edit: Edit) => {
    setMsg("");
    try {
      const { r, scope: sc } = await planEdit(ctx, scope, edit);
      onDone(r, sc);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    }
  };
  if (swap) return <SwapSheet ctx={ctx} it={it} scope={scope} setScope={setScope} onClose={onClose} onDone={onDone} />;
  return (
    <Sheet title={it.exercise} open onClose={onClose}>
      <View style={s.head}>
        <Thumb url={exImg(ctx.lib, it.exercise)} />
        <Text style={s.muted}>{`${ctx.name} · 现在 ${it.sets} 组 × ${it.reps}`}</Text>
      </View>
      <ScopeSeg isToday={ctx.isToday} value={scope} onChange={setScope} />
      <Stepper label="组数" value={String(sets)} unit="组" onDown={() => setSets(Math.max(1, sets - 1))} onUp={() => setSets(Math.min(10, sets + 1))} />
      {reps ? (
        <Stepper
          label="每组次数"
          value={repsText(reps)}
          unit="次"
          onDown={() => { if (reps.every((x) => x - 1 >= 1)) setReps(reps.map((x) => x - 1)); }}
          onUp={() => { if (reps.every((x) => x + 1 <= 50)) setReps(reps.map((x) => x + 1)); }}
        />
      ) : (
        <Text style={s.caption}>{`每组 ${it.reps}：这种写法用加减改不了，可以让 IronM 改`}</Text>
      )}
      <Button
        title="保存组次"
        disabled={!changed}
        onPress={() => send({ kind: "edit", exercise: it.exercise, sets, ...(reps && repsText(reps) !== was ? { reps: repsText(reps) } : {}) })}
      />
      <Button kind="ghost" title="换动作" onPress={() => setSwap(true)} />
      {only ? (
        <Text style={s.caption}>这天只剩这一个动作，不能去掉</Text>
      ) : (
        <LinkButton
          title={sure ? "再点一次，确认去掉" : "去掉这个动作"}
          onPress={() => (sure ? send({ kind: "remove", exercise: it.exercise }) : setSure(true))}
        />
      )}
      <Note tone="error">{msg}</Note>
    </Sheet>
  );
}

type Alt = { name: string; same: boolean; equipment: string[]; level: string; last?: string };

function SwapSheet({ ctx, it, scope, setScope, onClose, onDone }: { ctx: EditCtx; it: PlanItem; scope: Scope; setScope: (v: Scope) => void; onClose: () => void; onDone: Done }) {
  const [alts, setAlts] = useState<Alt[] | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");
  const day = ctx.day;
  const name = it.exercise;
  const load = useCallback(async () => {
    setErr("");
    try {
      const r = await api<{ alternatives: Alt[] }>(`/iron/api/plan/alternatives?day=${day}&exercise=${encodeURIComponent(name)}`);
      setAlts(r.alternatives);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没读到替代动作。");
    }
  }, [day, name]);
  useEffect(() => { void load(); }, [load]);
  const pick = async (to: string) => {
    setBusy(to);
    setMsg("");
    try {
      const { r, scope: sc } = await planEdit(ctx, scope, { kind: "swap", exercise: it.exercise, to });
      onDone(r, sc);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "没有成功，请再试一次。");
      setBusy("");
    }
  };
  return (
    <Sheet title={`换掉 ${it.exercise}`} open onClose={onClose}>
      <ScopeSeg isToday={ctx.isToday} value={scope} onChange={setScope} />
      {err ? <><Note tone="error">{err}</Note><Button small kind="ghost" title="重试" onPress={load} /></> : null}
      {!err && alts === null ? <Note>正在找…</Note> : null}
      {alts && !alts.length ? <Note>按你的器械和身体情况，没找到合适的替代动作，可以问问 IronM。</Note> : null}
      {alts?.map((a) => (
        <View key={a.name} style={s.alt}>
          <Thumb url={exImg(ctx.lib, a.name)} />
          <View style={s.altMain}>
            <Text style={s.altName}>{a.name}</Text>
            <Text style={s.muted}>{[a.same ? "同一类" : "相近", a.equipment.join("、"), a.level].join(" · ")}</Text>
            {a.last ? <Text style={s.muted}>{a.last}</Text> : null}
          </View>
          <Button small kind="ghost" title="换" disabled={busy !== ""} onPress={() => pick(a.name)} />
        </View>
      ))}
      <Note tone="error">{msg}</Note>
      <LinkButton title="都不合适？问 IronM" onPress={() => { onClose(); askCoach(`${ctx.name}的${it.exercise}想换个动作，换成什么好？`); }} />
    </Sheet>
  );
}

const s = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: space.m },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19, flexShrink: 1 },
  caption: { color: color.muted, fontSize: 13, lineHeight: 19 },
  stepper: { flexDirection: "row", alignItems: "center", gap: space.m },
  stepVal: { flex: 1, flexDirection: "row", alignItems: "baseline", justifyContent: "center", gap: 4 },
  stepNum: { color: color.ink, fontSize: 24, fontWeight: "700" },
  stepUnit: { color: color.muted, fontSize: 13 },
  alt: { flexDirection: "row", alignItems: "center", gap: space.m, paddingVertical: 4 },
  altMain: { flex: 1, minWidth: 0 },
  altName: { color: color.ink, fontSize: 15, fontWeight: "700" },
});
