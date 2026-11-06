// 训练计划（同网页 trainPlan，spec §106、§116）：一周七天一排，选中那天看动作、组次、下次目标、热身、估算消耗；
// 点动作改组次、换动作、去掉；排顺序；今天改过的能恢复原计划；今天那天能开始训练、直接打卡、记今天没练。
import { router, useFocusEffect } from "expo-router";
import { type ReactNode, useCallback, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { syncTrainingReminder } from "@/lib/notify";
import { askCoach, Fold, Thumb, useFlash } from "@/features/home/bits";
import { DoneSheet, REST_WORDS, RestSheet } from "@/features/home/checkin";
import { type EditCtx, type EditResult, ItemSheet, planEdit, type Scope, ScopeSeg } from "@/features/home/plan-edit";
import { clean, editedLine, exImg, setsText, weekdayName } from "@/features/home/train-logic";
import type { Brief, Library, PlanItem, Session, Training, Week } from "@/features/home/types";
import { LiveIcon } from "@/features/live/icons";
import type { Live } from "@/features/live/logic";
import { checkLive, startLive } from "@/features/live/start";
import { Button, LinkButton, Note, PageTitle, Panel, Screen, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

type Data = { tr: Training | null; week: Week | null; lib: Library | null; brief: Brief | null; live: Live | null };

export default function PlanPage() {
  const [d, setD] = useState<Data | null>(null);
  const [planDay, setPlanDay] = useState<string | null>(null);  // 选中的那天：改完重画时停在刚才那天（§106）
  const [ordering, setOrdering] = useState<string[] | null>(null);  // 排顺序时排到一半的动作名
  const [orderScope, setOrderScope] = useState<Scope>("today");
  const [burnOpen, setBurnOpen] = useState(false);
  const [editing, setEditing] = useState<{ ctx: EditCtx; it: PlanItem } | null>(null);
  const [done, setDone] = useState<{ name: string; version: Session | null } | null>(null);
  const [rest, setRest] = useState(false);
  const [flash, show] = useFlash();

  const load = useCallback(async () => {
    const [tr, week, lib, brief, live] = await Promise.all([
      api<Training>("/iron/api/training").catch(() => null),
      api<Week>("/iron/api/week").catch(() => null),
      api<Library>("/iron/api/exercises").catch(() => null),
      api<Brief>("/iron/api/brief").catch(() => null),
      checkLive(),
    ]);
    setD({ tr, week, lib, brief, live });
  }, []);
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  // 改完的提示：以后都改的带"撤销"（回到改之前那一版）
  const edited = (r: EditResult, scope: Scope) => {
    setEditing(null);
    setOrdering(null);
    void load();
    const said = editedLine(r);
    if (scope === "today" || !r.draft) { show(`今天改好了：${said}`); return; }
    const id = r.draft.id;
    const undo = async () => {
      try {
        await api(`/iron/api/drafts/${id}/undo`, { method: "POST" });
        void syncTrainingReminder();
        show("撤销了，回到改之前");
        void load();
      } catch (err) {
        show(err instanceof Error ? err.message : "没有成功，请再试一次。");
      }
    };
    show(<View style={s.flashRow}><Text style={s.flashText}>{`改好了：${said}`}</Text><Pressable accessibilityRole="button" onPress={undo}><Text style={s.flashLink}>撤销</Text></Pressable></View>, 8000);
  };
  const finished = (msg: string) => {
    setDone(null);
    setRest(false);
    show(msg, 3000);
    void load();
  };
  const go = async () => {
    const err = await startLive({ today_plan: true });
    if (err) show(err);
  };

  const head = (
    <View style={s.top}>
      <LinkButton title="‹ 返回" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} />
      <PageTitle>训练计划</PageTitle>
    </View>
  );
  const page = (...kids: ReactNode[]) => <Screen>{head}{flash}{kids}</Screen>;

  if (!d) return page(<Note key="l">正在读训练计划…</Note>);
  const { tr, week, lib, brief } = d;
  if (!tr || !week) {
    return page(
      <Panel key="f">
        <Note>没读到训练计划。</Note>
        <Button small kind="ghost" title="重试" onPress={load} />
      </Panel>,
    );
  }
  if (!tr.plan) {
    return page(
      <Panel key="n">
        <T>还没有训练计划</T>
        <View style={s.btnRow}>
          <Button small title="让 IronM 排一份" onPress={() => askCoach("帮我排一个每周训练计划")} />
          <Button small kind="ghost" title="从方案库挑" onPress={() => router.push({ pathname: "/atlas", params: { seg: "plans" } })} />
        </View>
      </Panel>,
    );
  }
  const targets = tr.targets || {};
  let pick = week.days.findIndex((c) => c.date === planDay);
  if (pick < 0) pick = week.days.findIndex((c) => c.today);
  if (pick < 0) pick = 0;
  const c = week.days[pick];
  const shown = c.version || c.session;
  const t = brief?.today?.training;
  const todayDate = week.days.find((x) => x.today)?.date;
  const rested = (tr.workouts || []).find((x) => x.rest && x.day === todayDate);

  const strip = (
    <View key="strip" style={s.strip}>
      {week.days.map((x, i) => (
        <Pressable
          key={x.date}
          accessibilityRole="button"
          accessibilityState={{ selected: i === pick }}
          accessibilityLabel={`${x.weekday}${x.session ? ` ${x.session.name}` : " 休息"}${x.done ? "，练过了" : ""}`}
          onPress={() => { setPlanDay(x.date); setOrdering(null); setBurnOpen(false); }}
          style={[s.day, x.session && s.dayPlan, i === pick && s.dayOn]}
        >
          <Text style={[s.dayTop, i === pick && s.dayTextOn]}>{x.today ? "今" : x.weekday.slice(1)}</Text>
          <Text style={[s.dayName, i === pick && s.dayTextOn]} numberOfLines={1}>{x.session ? x.session.name.slice(0, 3) : "休"}</Text>
          {x.done ? <View style={s.doneDot} /> : null}
        </Pressable>
      ))}
    </View>
  );
  if (!shown || !c.session) return page(strip, <Panel key="r"><Note>这天休息。</Note></Panel>);

  // 点动作就能改（§106）：按计划本身那一次改（调整出的版本只是显示），今天那天可以只改今天
  const base = c.session;
  const ed = c.edited || [];
  const ctx: EditCtx = { day: base.day, isToday: c.today, lib, items: base.items, name: weekdayName(base.day) };
  const live = c.today && !c.done && !t?.done;
  const saveOrder = async () => {
    if (!ordering) return;
    try {
      const { r, scope } = await planEdit(ctx, orderScope, { kind: "order", names: ordering });
      edited(r, scope);
    } catch (err) {
      show(err instanceof Error ? err.message : "没有成功，请再试一次。");
    }
  };
  const swapAt = (i: number, j: number) => {
    if (!ordering) return;
    const next = [...ordering];
    [next[i], next[j]] = [next[j], next[i]];
    setOrdering(next);
  };
  const resetToday = async () => {
    try {
      await api("/iron/api/plan/today", { method: "DELETE" });
      show("回到原计划了");
      void load();
    } catch (err) {
      show(err instanceof Error ? err.message : "没有成功，请再试一次。");
    }
  };

  const list = ordering ? (
    <View key="order" style={s.stack}>
      <Panel>
        {ordering.map((n, i) => (
          <View key={n} style={s.item}>
            <Thumb url={exImg(lib, n)} />
            <Text style={[s.itemName, s.flex]} numberOfLines={1}>{n}</Text>
            <IconBtn label={`${n}上移`} icon="up" disabled={i === 0} onPress={() => swapAt(i, i - 1)} />
            <IconBtn label={`${n}下移`} icon="down" disabled={i === ordering.length - 1} onPress={() => swapAt(i, i + 1)} />
          </View>
        ))}
      </Panel>
      <ScopeSeg isToday={c.today} value={orderScope} onChange={setOrderScope} />
      <View style={s.btnRow}>
        <Button title="保存顺序" onPress={saveOrder} />
        <Button kind="ghost" title="取消" onPress={() => setOrdering(null)} />
      </View>
    </View>
  ) : (
    <Panel key="list">
      {shown.items.map((it, i) => {
        const tg = targets[it.exercise];
        const mine = base.items.find((x) => x.exercise === it.exercise) || it;
        return (
          <Pressable
            key={`${it.exercise}-${i}`}
            accessibilityRole="button"
            accessibilityHint="点开改组次、换动作"
            onPress={() => setEditing({ ctx, it: mine })}
            style={({ pressed }) => [s.item, pressed && s.pressed]}
          >
            <Thumb url={exImg(lib, it.exercise)} />
            <View style={s.flex}>
              <Text style={s.itemName}>{it.exercise}</Text>
              <Text style={s.itemSub}>{`${setsText(it, lib)}${it.load ? `，${it.load}` : ""}`}</Text>
              {tg && !c.version && !ed.length ? <Text style={s.itemNext}>{`下次 ${clean(tg.text)}`}</Text> : null}
            </View>
            <LiveIcon name="edit" size={14} color={color.muted} />
          </Pressable>
        );
      })}
    </Panel>
  );

  return page(
    strip,
    <View key="head" style={s.pdHead}>
      <View style={s.flex}>
        <Text style={s.h2}>{shown.name}</Text>
        <Text style={s.itemSub}>{`${shown.minutes} 分钟 · ${shown.items.length} 个动作`}</Text>
        {c.burn ? (
          <LinkButton title={`约 ${c.burn.low}–${c.burn.high} 千卡（估算）`} onPress={() => setBurnOpen(!burnOpen)} />
        ) : (
          <Text style={s.caption}>记了体重才能估消耗</Text>
        )}
      </View>
      <View style={s.tools}>
        {base.items.length > 1 && !ordering ? (
          <Button small kind="ghost" title="排顺序" onPress={() => { setOrdering(base.items.map((x) => x.exercise)); setOrderScope("today"); }} />
        ) : null}
        <Button small kind="ghost" title="让 IronM 改" onPress={() => askCoach("帮我看看现在的训练计划，需要调整吗？")} />
      </View>
    </View>,
    c.burn && burnOpen ? <Text key="how" style={s.caption}>{clean(c.burn.how)}</Text> : null,
    c.warmup && !ordering ? (
      <Fold key="warm" title={`热身约 ${c.warmup.minutes} 分钟 · 怎么做`}>
        {c.warmup.steps.map((x, i) => <Text key={i} style={s.p}>{`${i + 1}. ${clean(x)}`}</Text>)}
        <Text style={s.caption}>{clean(c.warmup.basis)}</Text>
      </Fold>
    ) : null,
    c.today && ed.length ? (
      <View key="edited" style={s.edited}>
        <Text style={[s.p, s.flex]}>{`今天改过：${ed.map(clean).join("；")}`}</Text>
        <LinkButton title="恢复原计划" onPress={resetToday} />
      </View>
    ) : null,
    list,
    live && !ordering ? (
      <View key="go" style={s.stack}>
        <Button title={d.live ? "继续训练" : "开始训练"} onPress={go} />
        <Button kind="ghost" title="练完直接打卡" onPress={() => setDone({ name: shown.name, version: c.version || null })} />
        {rested ? <Text style={s.caption}>{`今天记了没练（${REST_WORDS[rested.rest || ""] || ""}）`}</Text> : <LinkButton title="今天没练？" onPress={() => setRest(true)} />}
      </View>
    ) : null,
    editing ? <ItemSheet key="edit" ctx={editing.ctx} it={editing.it} onClose={() => setEditing(null)} onDone={edited} /> : null,
    <DoneSheet
      key="done"
      open={done !== null}
      onClose={() => setDone(null)}
      session={done?.name || ""}
      version={done?.version || null}
      onDone={finished}
      onRest={() => { setDone(null); setRest(true); }}
    />,
    <RestSheet key="rest" open={rest} onClose={() => setRest(false)} onDone={finished} />,
  );
}

function IconBtn({ label, icon, disabled, onPress }: { label: string; icon: "up" | "down"; disabled?: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} disabled={disabled} onPress={onPress} hitSlop={6} style={[s.iconBtn, disabled && s.off]}>
      <LiveIcon name={icon} size={18} color={color.ink} />
    </Pressable>
  );
}

const s = StyleSheet.create({
  top: { gap: space.xs },
  flex: { flex: 1, minWidth: 0 },
  stack: { gap: space.m },
  btnRow: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  strip: { flexDirection: "row", gap: 4 },
  day: { flex: 1, minWidth: 0, alignItems: "center", paddingVertical: 6, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight },
  dayPlan: { backgroundColor: color.paper, borderColor: color.wood },
  dayOn: { backgroundColor: color.plank, borderColor: color.woodDark },
  dayTop: { color: color.muted, fontSize: 12 },
  dayName: { color: color.ink, fontSize: 12, fontWeight: "700" },
  dayTextOn: { color: color.accentInk },
  doneDot: { width: 6, height: 6, marginTop: 2, backgroundColor: color.accent },
  pdHead: { flexDirection: "row", flexWrap: "wrap", gap: space.m, alignItems: "flex-start", backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m },
  h2: { color: color.ink, fontSize: 20, fontWeight: "700" },
  tools: { gap: space.s, alignItems: "flex-end" },
  caption: { color: color.muted, fontSize: 13, lineHeight: 19 },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  edited: { flexDirection: "row", alignItems: "center", gap: space.s, backgroundColor: color.goodSoft, borderWidth: 1, borderRadius: 14, borderColor: color.accent, padding: space.m },
  item: { flexDirection: "row", alignItems: "center", gap: space.m, paddingVertical: 4 },
  pressed: { opacity: 0.7 },
  itemName: { color: color.ink, fontSize: 15, fontWeight: "700" },
  itemSub: { color: color.muted, fontSize: 13 },
  itemNext: { color: color.accentText, fontSize: 13, fontWeight: "600" },
  iconBtn: { width: 36, height: 36, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: color.paperLight },
  off: { opacity: 0.4 },
  flashRow: { flexDirection: "row", alignItems: "center", gap: space.m },
  flashText: { flex: 1, color: color.ink, fontSize: 14, lineHeight: 20 },
  flashLink: { color: color.accentText, fontSize: 14, fontWeight: "700", textDecorationLine: "underline" },
});
