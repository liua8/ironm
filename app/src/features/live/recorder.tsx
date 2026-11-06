// 训练记录器（同网页 livePage，spec §71、§92、§104、§130、§133）：一组一组记重量、次数（计时动作记秒数、有氧记分钟），
// 当前这一组放大（动作图、一句要点、− / + 一档、一个大按钮），打勾后组间休息倒计时，最上面是总用时和进度。
// 每改一处都整份存回服务端（PUT /iron/api/live），离开这页训练不会结束，回来接着计。
// 组间休息开始时排一条手机本地通知（§164 第四期），App 在后台也到点提醒；休息跳过、改时长、换下一组、结束训练、离开这页时取消或重排。
import { router } from "expo-router";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, Vibration, View } from "react-native";

import { api } from "@/api/client";
import { Thumb, useFlash } from "@/features/home/bits";
import { exImg } from "@/features/home/train-logic";
import { prWall, type Workout } from "@/features/record/logic";
import type { Library } from "@/features/home/types";
import { cancelRestEnd, scheduleRestEnd } from "@/lib/notify";
import { Button, LinkButton, Note, PixelText } from "@/ui/pixel";
import { color, radius, space } from "@/ui/theme";

import { AddMoveSheet } from "./add-move";
import { FinishSheet } from "./finish";
import { LiveIcon, type LiveIconName } from "./icons";
import {
  addSet, bumpValue, checkKg, clampRest, clock, completeSet, curPos, e1rm, emptyMsg, type Live, type LiveItem, type LiveResp, targetPill,
  type LiveSet, minutesToSeconds, moveItem, progress, secondsToMinutes, stepOf, toNum, undoSet, type Warn,
} from "./logic";

// 提示音开关：这次打开 App 期间记住
const sound = { on: true };
// 没有通知权限时说一次怎么打开：这次打开 App 期间不再提
const told = { perm: false };

/** 休息结束的提示音：网页预览用浏览器的声音；手机上暂时只振动（没有装声音的包）。 */
function beep() {
  if (Platform.OS !== "web") return;
  try {
    const Ctx = (globalThis as unknown as { AudioContext?: new () => AudioContext }).AudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.15;
    o.connect(g);
    g.connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.3);
    setTimeout(() => void ctx.close(), 500);
  } catch {
    // 没有声音也不影响
  }
}

const goBack = () => (router.canGoBack() ? router.back() : router.replace("/"));

/** 数字输入框：自己留着打的字，外面的值变了（加减一档、改回）才跟着换。 */
function NumField({ value, onChange, onCommit, placeholder, label, decimal, done }: {
  value: number | null;
  onChange: (v: number | null) => void;
  onCommit?: (prev: number | null) => void;
  placeholder: string;
  label: string;
  decimal?: boolean;
  done?: boolean;
}) {
  const [text, setText] = useState(value == null ? "" : String(value));
  const typed = useRef(text);
  const prev = useRef(value);
  useEffect(() => {
    if (toNum(typed.current) !== value) {
      typed.current = value == null ? "" : String(value);
      setText(typed.current);
    }
  }, [value]);
  return (
    <TextInput
      value={text}
      onChangeText={(t) => { typed.current = t; setText(t); onChange(toNum(t)); }}
      onFocus={() => { prev.current = value; }}
      onBlur={() => onCommit?.(prev.current)}
      keyboardType={decimal ? "decimal-pad" : "number-pad"}
      placeholder={placeholder}
      placeholderTextColor={color.muted}
      accessibilityLabel={label}
      style={[s.in, done && s.inDone]}
    />
  );
}

function IconBtn({ icon, label, onPress, disabled, on, size = 16 }: { icon: LiveIconName; label: string; onPress: () => void; disabled?: boolean; on?: boolean; size?: number }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} accessibilityState={{ disabled, selected: on }} disabled={disabled} onPress={onPress} hitSlop={4} style={[s.iconBtn, on && s.iconOn, disabled && s.off]}>
      <LiveIcon name={icon} size={size} color={on ? color.accentInk : color.ink} />
    </Pressable>
  );
}

/** 重量、次数各一块（§176 照参照图）：上面一行名字和小标签，下面大号数字配左右圆按钮。 */
function Stepper({ label, value, unit, onDown, onUp, hot, pill, pillTone }: { label: string; value: number | null; unit: string; onDown: () => void; onUp: () => void; hot?: boolean; pill?: string; pillTone?: "green" }) {
  return (
    <View style={s.stepper}>
      <View style={s.stepHead}>
        <Text style={s.stepLabel}>{label}</Text>
        {pill ? <Text style={[s.pill, pillTone === "green" && s.pillGreen]}>{pill}</Text> : null}
      </View>
      <View style={s.stepRow}>
        <Pressable accessibilityRole="button" accessibilityLabel={`${label}减`} onPress={onDown} style={s.stepBtn}><Text style={s.stepSign}>−</Text></Pressable>
        <View style={s.stepVal}>
          <Text style={[s.stepNum, hot && s.hot]}>{value == null ? "–" : String(value)}</Text>
          <Text style={s.unit}>{unit}</Text>
        </View>
        <Pressable accessibilityRole="button" accessibilityLabel={`${label}加`} onPress={onUp} style={[s.stepBtn, s.stepUp]}><Text style={[s.stepSign, s.stepSignUp]}>+</Text></Pressable>
      </View>
    </View>
  );
}

export function Recorder({ data, onReload }: { data: LiveResp & { live: Live }; onReload: () => void }) {
  const L = useRef<Live>(data.live).current;
  const steps = data.steps;
  const [, redraw] = useReducer((x: number) => x + 1, 0);
  const [lib, setLib] = useState<Library | null>(null);
  const [warn, setWarn] = useState<Warn | null>(null);
  const [timing, setTiming] = useState<{ i: number; j: number; from: number } | null>(null);
  const [rest, setRest] = useState<{ i: number; end: number } | null>(null);
  const [status, setStatus] = useState("");
  const [now, setNow] = useState(Date.now());
  const [finishing, setFinishing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [soundOn, setSoundOn] = useState(sound.on);
  const [flash, show] = useFlash();
  const okKg = useRef<Record<number, number>>({}).current;  // 已经确认过的重量（每个动作）
  const saveT = useRef<ReturnType<typeof setTimeout> | null>(null);
  const skew = Date.now() - new Date(data.now || Date.now()).getTime();  // 手机和服务器的时钟差
  const t0 = useRef(new Date(L.started).getTime() + skew).current;

  useEffect(() => { api<Library>("/iron/api/exercises").then(setLib).catch(() => setLib(null)); }, []);
  // 重量旁的"最近最佳"：最近 30 天这个动作最好一组的重量（§176）
  const [bestKg, setBestKg] = useState<Record<string, number | null | undefined>>({});
  useEffect(() => {
    api<{ workouts?: Workout[] }>("/iron/api/training")
      .then((tr) => setBestKg(Object.fromEntries(prWall(tr.workouts ?? []).map((x) => [x.name, x.best.weight_kg]))))
      .catch(() => {});
  }, []);

  const put = useCallback(async () => {
    saveT.current = null;
    try {
      await api("/iron/api/live", { method: "PUT", json: { id: L.id, items: L.items } });
      setStatus("");
    } catch (err) {
      const m = err instanceof Error ? err.message : "没存上，请再试一次。";
      setStatus(m);
      if (m.includes("刷新")) onReload();
    }
  }, [L, onReload]);
  const save = useCallback((at = false): Promise<void> => {
    if (saveT.current) clearTimeout(saveT.current);
    if (at) return put();
    saveT.current = setTimeout(() => void put(), 500);
    return Promise.resolve();
  }, [put]);
  const flush = useCallback(() => save(true), [save]);
  // 离开这页时还没存的改动马上存
  useEffect(() => () => { if (saveT.current) { clearTimeout(saveT.current); void put(); } }, [put]);

  // 走表：总用时、正在计时的一组、组间休息
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, []);
  // 休息到点的手机通知跟着页面里的休息走：开始或改了结束时间就重排，没了（跳过、到点、换动作）就取消；
  // 铃铛开关也跟着换（关了通知不出声）。离开这页（包括结束、放弃训练）时倒计时没了，通知一起取消。
  const notified = useRef(false);  // 这次休息排上了通知
  const restEnd = rest?.end ?? null;
  useEffect(() => {
    if (restEnd == null) {
      notified.current = false;
      void cancelRestEnd();
      return;
    }
    let live = true;
    void scheduleRestEnd(restEnd, soundOn).then((p) => {
      if (!live) return;
      notified.current = p.ok;
      if (!p.ok && !told.perm && Platform.OS !== "web") {
        told.perm = true;
        show(`休息到点提醒：${p.why} App 开着时照样响铃振动。`, 8000);
      }
    });
    return () => { live = false; };
  }, [restEnd, soundOn, show]);
  useEffect(() => () => void cancelRestEnd(), []);

  useEffect(() => {
    if (rest && now >= rest.end) {
      setRest(null);
      // 在后台过了点、手机通知已经响过：回到前台不再响一遍
      if (notified.current && now - rest.end > 3000) return;
      if (sound.on) beep();
      Vibration.vibrate([0, 200, 100, 200]);
    }
  }, [now, rest]);

  const commitKg = (i: number, j: number, prev: number | null) => {
    setWarn(checkKg(L, i, j, prev, steps, okKg, warn));
    redraw();
  };
  const bump = (i: number, j: number, key: "weight_kg" | "reps", d: number) => {
    const prev = bumpValue(L.items[i].sets[j], key, d);
    if (key === "weight_kg") setWarn(checkKg(L, i, j, prev, steps, okKg, warn));
    void save();
    redraw();
  };
  const markDone = (i: number, j: number) => {
    const it = L.items[i];
    const st = it.sets[j];
    if (st.done) { undoSet(st); void save(true); redraw(); return; }
    const timingThis = Boolean(timing && timing.i === i && timing.j === j);
    const m = emptyMsg(it, st, timingThis);
    if (m) { setWarn({ i, text: m }); return; }
    if (warn && warn.i === i) setWarn(null);
    const r = completeSet(L.items, i, j, Date.now(), timingThis && timing ? timing.from : null, steps);
    if (timingThis) setTiming(null);
    setRest({ i, end: r.restEnd });
    if (r.pr) {
      Vibration.vibrate([0, 30, 60, 30]);
      show(<View style={s.flashRow}><LiveIcon name="trophy" size={18} color={color.accent} /><Text style={s.flashText}><Text style={s.bold}>新纪录 </Text>{r.pr}</Text></View>);
    } else Vibration.vibrate(15);
    if (r.next) show(r.next);  // 下一组的建议：这组次数没做够，下一组降一档
    void save(true);
    redraw();
  };
  const toggleTiming = (i: number, j: number) => setTiming(timing && timing.i === i && timing.j === j ? null : { i, j, from: Date.now() });
  const move = (i: number, d: number) => { if (moveItem(L.items, i, d)) { setRest(null); setTiming(null); setWarn(null); void save(true); redraw(); } };
  const dropItem = (i: number) => { L.items.splice(i, 1); setRest(null); setTiming(null); setWarn(null); void save(true); redraw(); };
  const plusSet = (i: number) => { if (addSet(L.items[i])) { void save(true); redraw(); } };
  const dropSet = (i: number, j: number) => { L.items[i].sets.splice(j, 1); setTiming(null); void save(true); redraw(); };
  const setVal = (st: LiveSet, key: "weight_kg" | "reps" | "seconds", v: number | null) => { st[key] = v; void save(); };

  const here = curPos(L.items);
  const prog = progress(L.items);

  const row = (it: LiveItem, i: number, st: LiveSet, j: number) => {
    const running = Boolean(timing && timing.i === i && timing.j === j);
    const pr = st.done && it.best && (e1rm(st.weight_kg, st.reps) || 0) > it.best;
    const cur = here && here.i === i && here.j === j;
    const inputs = it.cardio ? (
      <>
        <MinutesField st={st} j={j} onChange={(sec) => setVal(st, "seconds", sec)} done={st.done} />
        <Text style={s.unit}>分钟</Text>
      </>
    ) : it.timed ? (
      <>
        <NumField value={st.seconds} onChange={(v) => setVal(st, "seconds", v)} placeholder="秒" label={`第 ${j + 1} 组秒数`} done={st.done} />
        <Text style={s.unit}>秒</Text>
      </>
    ) : (
      <>
        <NumField value={st.weight_kg} decimal onChange={(v) => setVal(st, "weight_kg", v)} onCommit={(prev) => commitKg(i, j, prev)} placeholder="公斤" label={`第 ${j + 1} 组重量`} done={st.done} />
        <Text style={s.unit}>×</Text>
        <NumField value={st.reps} onChange={(v) => setVal(st, "reps", v)} placeholder="次" label={`第 ${j + 1} 组次数`} done={st.done} />
      </>
    );
    return (
      <View key={j} style={[s.setRow, st.done && s.setDone, cur && s.setCur]}>
        <Text style={s.setN}>{j + 1}</Text>
        {inputs}
        {it.timed ? null : pr ? (
          <Text style={s.prTag}>新纪录</Text>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={running ? "停止计时" : "这一组计时（可不计）"}
            disabled={st.done}
            onPress={() => toggleTiming(i, j)}
            style={[s.timeBtn, running && s.timeRun, st.done && s.off]}
          >
            <Text style={[s.timeText, running && s.timeTextRun]} numberOfLines={1}>
              {running && timing ? clock((now - timing.from) / 1000) : st.seconds ? `${st.seconds}″` : "计时"}
            </Text>
          </Pressable>
        )}
        <IconBtn icon="check" label={st.done ? "取消完成" : "完成这一组"} on={st.done} onPress={() => markDone(i, j)} size={18} />
        {!st.done && it.sets.length > 1 ? (
          <Pressable accessibilityRole="button" accessibilityLabel="删掉这一组" onPress={() => dropSet(i, j)} hitSlop={6} style={s.x}>
            <LiveIcon name="x" size={14} color={color.muted} />
          </Pressable>
        ) : <View style={s.x} />}
      </View>
    );
  };

  // 当前这一组（§104 需求 6）：动作图、一句要点、− / + 一档、一个大按钮
  const focus = (it: LiveItem, i: number) => {
    if (!here || here.i !== i) return null;
    const j = here.j;
    const st = it.sets[j];
    const mv = lib?.exercises?.find((x) => x.name === it.exercise);
    const hot = st.weight_kg != null && it.plan_kg != null && st.weight_kg > it.plan_kg;
    return (
      <View style={s.focus}>
        <Text style={s.nowTag}>{`进行中 · 第 ${j + 1}/${it.sets.length} 组`}</Text>
        <View style={s.focusTop}>
          <Thumb url={exImg(lib, it.exercise)} size={72} />
          {mv?.cues?.[0] ? <Text style={[s.cue, s.flex]}>{mv.cues[0]}</Text> : null}
        </View>
        {it.timed ? null : (
          <View style={s.steps}>
            <Stepper label="重量" value={st.weight_kg} unit="公斤" hot={hot} onDown={() => bump(i, j, "weight_kg", -stepOf(steps, it))} onUp={() => bump(i, j, "weight_kg", stepOf(steps, it))}
              pill={bestKg[it.exercise] ? `最近最佳 ${bestKg[it.exercise]} kg` : undefined} pillTone="green" />
            <Stepper label="次数" value={st.reps} unit="次" onDown={() => bump(i, j, "reps", -1)} onUp={() => bump(i, j, "reps", 1)} pill={targetPill(it.target) || undefined} />
          </View>
        )}
        {warn && warn.i === i ? (
          <View style={s.warn} accessibilityLiveRegion="polite">
            <Text style={s.warnText}>{warn.text}</Text>
            {warn.back != null ? (
              <View style={s.warnBtns}>
                <Button small title="确定" onPress={() => { if (warn.w != null) okKg[i] = warn.w; setWarn(null); }} />
                <LinkButton title={`改回 ${warn.back}`} onPress={() => { st.weight_kg = warn.back ?? null; setWarn(null); void save(); redraw(); }} />
              </View>
            ) : null}
          </View>
        ) : null}
        <Button title={`完成第 ${j + 1} 组`} onPress={() => markDone(i, j)} />
      </View>
    );
  };

  const card = (it: LiveItem, i: number) => {
    const allDone = it.sets.length > 0 && it.sets.every((x) => x.done);
    const isCur = here?.i === i;
    const timingHere = Boolean(timing && timing.i === i);
    return (
      <View key={`${it.exercise}-${i}`} style={[s.card, allDone && s.cardDone, isCur && s.cardCur]}>
        <View style={s.head}>
          <View style={s.flex}>
            <View style={s.nameRow}>
              <Text style={s.name}>{it.exercise}</Text>
              {allDone ? <View accessibilityLabel="这个动作做完了"><LiveIcon name="check" size={16} color={color.accentText} /></View> : null}
            </View>
            {it.target ? <Text style={s.sub}>{it.target}</Text> : null}
          </View>
          <IconBtn icon="up" label="上移" disabled={i === 0} onPress={() => move(i, -1)} />
          <IconBtn icon="down" label="下移" disabled={i === L.items.length - 1} onPress={() => move(i, 1)} />
          <IconBtn icon="x" label="删掉这个动作" onPress={() => dropItem(i)} />
        </View>
        {focus(it, i)}
        {warn && warn.i === i && !isCur ? <Text style={s.warnText}>{warn.text}</Text> : null}
        {it.timed ? <Text style={s.sub}>{it.cardio ? "有氧：填做了多少分钟，或点开始计时" : "计时动作：填秒数，或点计时"}</Text> : null}
        {it.timed ? (
          <View style={s.timedRow}>
            <Button
              small
              kind={timingHere ? "primary" : "ghost"}
              title={timingHere && timing ? `停，记下这组 ${clock((now - timing.from) / 1000)}` : "开始计时"}
              onPress={() => {
                const j = it.sets.findIndex((x) => !x.done);
                if (j < 0) return;
                if (timingHere && timing) markDone(i, timing.j); else toggleTiming(i, j);
              }}
            />
          </View>
        ) : null}
        <View style={s.sets}>{it.sets.map((st, j) => row(it, i, st, j))}</View>
        <Pressable accessibilityRole="button" onPress={() => plusSet(i)} style={s.addSet} hitSlop={6}>
          <LiveIcon name="plus" size={14} color={color.accentText} />
          <Text style={s.addSetText}>{it.cardio ? "再加一段" : "加一组"}</Text>
        </Pressable>
      </View>
    );
  };

  const restLeft = rest ? (rest.end - now) / 1000 : 0;
  const adjRest = (d: number) => {
    if (!rest) return;
    const it = L.items[rest.i];
    if (!it) return;
    const was = it.rest;
    it.rest = clampRest(it.rest, d);
    setRest({ ...rest, end: rest.end + (it.rest - was) * 1000 });
    void save();
  };

  return (
    <View style={s.page}>
      <View style={s.bar}>
        <IconBtn icon="back" label="返回（训练不会结束）" onPress={goBack} size={18} />
        <View style={[s.flex, s.who]}>
          <Text style={s.clock}>{clock((now - t0) / 1000)}</Text>
          <Text style={s.sub} numberOfLines={1}>{L.session ? `训练中 · ${L.session}` : "训练中"}</Text>
        </View>
        <IconBtn icon={soundOn ? "bell" : "mute"} label="提示音" onPress={() => { sound.on = !sound.on; setSoundOn(sound.on); }} size={18} />
        <Pressable accessibilityRole="button" onPress={() => setFinishing(true)} style={s.end}><Text style={s.endText}>结束训练</Text></Pressable>
      </View>
      <ScrollView style={s.flex} contentContainerStyle={s.scroll} keyboardShouldPersistTaps="handled">
        {prog.all ? (
          <View style={s.prog}>
            <View style={s.progHead}>
              <Text style={s.progK}>{`总进度：第 ${here ? here.i + 1 : L.items.length}/${L.items.length} 个动作`}</Text>
              <Text style={s.progV}>{`已做 ${prog.done}/${prog.all} 组（${prog.pct}%）`}</Text>
            </View>
            <View style={s.thin}><View style={[s.thinFill, { width: `${prog.pct}%` }]} /></View>
          </View>
        ) : null}
        {rest && restLeft > 0 ? (
          <View style={s.rest}>
            <View style={s.restHead}>
              <View style={s.restK}><View style={s.restDot} /><Text style={s.restLabel}>组间休息中</Text></View>
              <Text style={s.restNum}>{clock(restLeft)}<Text style={s.restOf}>{` / ${clock(L.items[rest.i]?.rest ?? 0)}`}</Text></Text>
            </View>
            <View style={s.restTrack}><View style={[s.restFill, { width: `${Math.max(0, Math.min(100, Math.round((1 - restLeft / Math.max(1, L.items[rest.i]?.rest ?? 1)) * 100)))}%` }]} /></View>
            <View style={s.restBtns}>
              <RestBtn title="−15 秒" onPress={() => adjRest(-15)} />
              <RestBtn title="+15 秒" onPress={() => adjRest(15)} />
              <RestBtn title="跳过休息" onPress={() => setRest(null)} />
            </View>
          </View>
        ) : null}
        {flash}
        {status ? <Note tone="error">{status}</Note> : null}
        {L.items.length ? L.items.map(card) : (
          <View style={s.card}><Note>{L.session ? "今天的计划里没有动作。" : "还没有动作，点下面的「加动作」。"}</Note></View>
        )}
        {/* 按计划的训练动作已经带好了；只有自由训练能加动作（§133） */}
        {!L.session ? <Button kind="ghost" title="＋ 加动作" onPress={() => setAdding(true)} /> : null}
      </ScrollView>
      {/* 保存结束时先停掉休息（取消到点通知），训练都结束了不该再响 */}
      <FinishSheet live={L} t0={t0} open={finishing} onClose={() => setFinishing(false)} flush={() => { setRest(null); return flush(); }} />
      <AddMoveSheet open={adding} lib={lib} onClose={() => setAdding(false)} flush={flush} onAdded={(items) => { L.items = items; redraw(); }} />
    </View>
  );
}

/** 有氧（§130）：页面填分钟，存秒。 */
function RestBtn({ title, onPress }: { title: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [s.restBtn, pressed && s.off]}>
      <Text style={s.restBtnText}>{title}</Text>
    </Pressable>
  );
}

function MinutesField({ st, j, onChange, done }: { st: LiveSet; j: number; onChange: (sec: number | null) => void; done?: boolean }) {
  const [text, setText] = useState(secondsToMinutes(st.seconds));
  return (
    <TextInput
      value={text}
      onChangeText={(t) => { setText(t); onChange(minutesToSeconds(toNum(t))); }}
      keyboardType="number-pad"
      placeholder="分钟"
      placeholderTextColor={color.muted}
      accessibilityLabel={`第 ${j + 1} 段分钟数`}
      style={[s.in, done && s.inDone]}
    />
  );
}

const s = StyleSheet.create({
  page: { flex: 1, gap: space.s },
  flex: { flex: 1, minWidth: 0 },
  bold: { fontWeight: "700" },
  bar: { flexDirection: "row", alignItems: "center", gap: space.s, paddingVertical: 6 },
  who: { alignItems: "flex-start", gap: 2 },
  scroll: { gap: space.m, paddingBottom: space.xl },
  prog: { gap: 8, backgroundColor: color.paper, borderRadius: 20, padding: space.m },
  thin: { height: 8, backgroundColor: color.wood, borderRadius: 999, overflow: "hidden" },
  thinFill: { height: "100%", backgroundColor: color.accent, borderRadius: 999 },
  card: { backgroundColor: color.paper, borderRadius: 24, padding: space.l, gap: space.s },
  cardDone: { backgroundColor: color.goodSoft },
  cardCur: { borderWidth: 2, borderColor: color.accentSoft },
  head: { flexDirection: "row", alignItems: "center", gap: 6 },
  nameRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  name: { color: color.ink, fontSize: 22, fontWeight: "800", flexShrink: 1 },
  sub: { color: color.muted, fontSize: 13, lineHeight: 18 },
  unit: { color: color.muted, fontSize: 13 },
  iconBtn: { width: 34, height: 34, alignItems: "center", justifyContent: "center", borderRadius: 17, backgroundColor: color.iconBg },
  iconOn: { backgroundColor: color.fire, borderColor: color.woodDark },
  off: { opacity: 0.4 },
  focus: { gap: space.m },
  focusTop: { flexDirection: "row", alignItems: "center", gap: space.m },
  cue: { color: color.ink, fontSize: 14, lineHeight: 20 },
  steps: { gap: space.s },
  stepper: { gap: 8, backgroundColor: color.paperLight, borderRadius: 20, paddingHorizontal: space.l, paddingVertical: space.m },
  stepBtn: { width: 52, height: 52, alignItems: "center", justifyContent: "center", borderRadius: 26, backgroundColor: color.iconBg },
  stepSign: { color: "#3b3b5c", fontSize: 26, fontWeight: "600", lineHeight: 30 },
  stepVal: { flex: 1, flexDirection: "row", alignItems: "baseline", justifyContent: "center", gap: 4 },
  hot: { color: color.heat },
  warn: { gap: space.s, backgroundColor: color.heatSoft, borderWidth: 1, borderRadius: 14, borderColor: color.heat, padding: space.s },
  warnText: { color: color.heat, fontSize: 14, lineHeight: 20 },
  warnBtns: { flexDirection: "row", alignItems: "center", gap: space.m },
  timedRow: { flexDirection: "row" },
  sets: { gap: 4 },
  setRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3, paddingHorizontal: 4 },
  setDone: { backgroundColor: color.goodSoft },
  setCur: { borderWidth: 1, borderRadius: 14, borderColor: color.accent, paddingHorizontal: 2, paddingVertical: 1 },
  setN: { width: 18, color: color.muted, fontSize: 13, textAlign: "center" },
  in: { flex: 1, minWidth: 0, height: 36, paddingHorizontal: 6, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, color: color.ink, fontSize: 15, textAlign: "center" },
  inDone: { color: color.accentText },
  timeBtn: { width: 58, height: 34, alignItems: "center", justifyContent: "center", borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, backgroundColor: color.paperLight },
  timeRun: { backgroundColor: color.fire, borderColor: color.woodDark },
  timeText: { color: color.muted, fontSize: 12 },
  timeTextRun: { color: color.accentInk, fontWeight: "700" },
  prTag: { width: 58, textAlign: "center", color: color.accentInk, backgroundColor: color.heat, fontSize: 12, paddingVertical: 6, fontWeight: "700" },
  x: { width: 20, alignItems: "center" },
  addSet: { flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start", paddingVertical: 4 },
  addSetText: { color: color.accentText, fontSize: 14, fontWeight: "600" },
  rest: { gap: 10, backgroundColor: color.iconBg, borderRadius: 22, padding: space.l },
  restNum: { color: color.good, fontSize: 28, fontWeight: "800" },
  restBtns: { flexDirection: "row", gap: 8 },
  restHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  restK: { flexDirection: "row", alignItems: "center", gap: 8 },
  restDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: color.good },
  restLabel: { color: color.ink, fontSize: 15, fontWeight: "700" },
  restOf: { color: color.muted, fontSize: 14, fontWeight: "600" },
  restTrack: { height: 6, borderRadius: 999, backgroundColor: "#dcdbe9", overflow: "hidden" },
  restFill: { height: 6, borderRadius: 999, backgroundColor: color.good },
  restBtn: { flex: 1, alignItems: "center", paddingVertical: 10, borderRadius: 14, backgroundColor: color.paper },
  restBtnText: { color: color.ink, fontSize: 14, fontWeight: "600" },
  clock: { color: color.ink, fontSize: 20, fontWeight: "800", backgroundColor: color.iconBg, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 4, overflow: "hidden" },
  end: { backgroundColor: color.accentSoft, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 9 },
  endText: { color: color.accentText, fontSize: 14, fontWeight: "700" },
  progHead: { flexDirection: "row", justifyContent: "space-between", gap: 8 },
  progK: { color: color.ink2, fontSize: 13, fontWeight: "600" },
  progV: { color: color.accentText, fontSize: 13, fontWeight: "700" },
  nowTag: { alignSelf: "flex-start", color: color.accentText, backgroundColor: color.accentSoft, fontSize: 12, fontWeight: "700", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, overflow: "hidden" },
  stepHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  stepLabel: { color: color.ink2, fontSize: 13, fontWeight: "600" },
  stepRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  stepUp: { backgroundColor: color.accent },
  stepSignUp: { color: "#ffffff" },
  stepNum: { color: color.ink, fontSize: 44, fontWeight: "800" },
  pill: { color: color.ink2, backgroundColor: color.paper, fontSize: 11, fontWeight: "700", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, overflow: "hidden" },
  pillGreen: { color: color.good, backgroundColor: color.goodSoft },
  flashRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  flashText: { flex: 1, color: color.ink, fontSize: 14, lineHeight: 20 },
});
