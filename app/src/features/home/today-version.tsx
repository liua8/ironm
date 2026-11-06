// 首页的"今天"（同网页 todayVersion，spec §163）：今天怎么练只由管家定。
// useToday 管取数：正在看时每 5 秒再问（最多 2 分钟，之后给"刷新"）；出错了能重试；"只有 30 分钟""今天有点累"只发一次，
// 之后不带参数地问（带着会一直叫醒管家重看），后台重看完之前服务端给的旧结果先当作正在看（today-logic）。
// 不按规则替管家减量：正在看、出错了时列原计划。
import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { Chips, Fold } from "./bits";
import { settle, TODAY_POLL_MAX, TODAY_POLL_MS, TODAY_WAIT_MAX, todaySig, type Wait } from "./today-logic";
import { clean, itemLine } from "./train-logic";
import type { Library, Session, Target, TodayVersion as TV } from "./types";

export type Today = ReturnType<typeof useToday>;

export function useToday() {
  const [shown, setShown] = useState<TV | null>(null);
  const [err, setErr] = useState("");
  const [stuck, setStuck] = useState(false);
  const [said, setSaid] = useState<{ m30: boolean; tired: boolean }>({ m30: false, tired: false });
  const wait = useRef<Wait>(null);
  const last = useRef<TV | null>(null);
  const polls = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);

  const ask = useCallback(async (q: string[] = []): Promise<void> => {
    if (timer.current) clearTimeout(timer.current);
    try {
      const v = await api<TV>(`/iron/api/today${q.length ? `?${q.join("&")}` : ""}`);
      if (!alive.current) return;
      const r = settle(v, wait.current, last.current);
      wait.current = r.wait;
      last.current = v;
      setShown(r.shown);
      setErr("");
      if (!r.poll) {
        polls.current = 0;
        setStuck(false);
      } else if (polls.current < TODAY_POLL_MAX) {
        polls.current += 1;
        timer.current = setTimeout(() => void ask(), TODAY_POLL_MS);
      } else setStuck(true);
    } catch (e) {
      if (alive.current) setErr(e instanceof Error ? e.message : "没读到今天的安排。");
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void ask();
    return () => {
      alive.current = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [ask]);

  /** 说一句今天的情况：每样只发一次。 */
  const say = (k: "m30" | "tired") => {
    if (said[k]) return;
    setSaid({ ...said, [k]: true });
    wait.current = { before: last.current ? todaySig(last.current) : undefined, left: TODAY_WAIT_MAX };
    polls.current = 0;
    void ask([k === "m30" ? "minutes=30" : "tired=true"]);
  };
  const retry = async () => {
    try {
      const r = await api<{ status: string }>("/iron/api/coach/retry", { method: "POST" });
      polls.current = 0;
      if (r.status === "reviewing") {
        wait.current = { error: true, left: TODAY_WAIT_MAX };
        const original = last.current?.original;
        setShown({ status: "reviewing", ...(original ? { original } : {}) });
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => void ask(), TODAY_POLL_MS);
      } else void ask();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没重试成功，稍后再点一次。");
    }
  };
  const refresh = () => {
    polls.current = 0;
    setStuck(false);
    void ask();
  };
  return { shown, err, stuck, said, say, retry, refresh };
}

type Ok = Extract<TV, { status: "ok" }>;
const isOk = (v: TV): v is Ok => v.status === "ok" && "today" in v;

export function TodayVersion({ today, lib, targets, onCheckin }: { today: Today; lib: Library | null; targets: Record<string, Target>; onCheckin: (name: string, version: Session | null) => void }) {
  const { shown: v, err, stuck, said, say, retry, refresh } = today;
  if (err && !v) return <View style={s.box}><Note tone="error">{err}</Note><Button small kind="ghost" title="重试" onPress={refresh} /></View>;
  if (!v) return null;
  const toggles = (
    <Chips
      items={[["m30", "只有 30 分钟"], ["tired", "今天有点累"]] as const}
      isOn={(k) => said[k]}
      onTap={(k) => say(k)}
    />
  );
  if (!isOk(v)) {
    // 正在看、出错了、今天定了休息：照服务端说的写，正在看和出错了列原计划（§163）
    const busy = v.status === "reviewing", broken = v.status === "coach_error";
    const say_ = busy ? "IronM 正在看今天的情况" : broken ? "IronM 出错了，还没看今天的情况" : ("message" in v && v.message ? clean(v.message) : "");
    const orig = (busy || broken) && v.original ? v.original : null;
    return (
      <View style={s.box}>
        {say_ ? <Note tone={broken ? "error" : "muted"}>{say_}</Note> : null}
        {broken ? <Button small title="重试" onPress={() => void retry()} /> : null}
        {busy && stuck ? <Button small kind="ghost" title="刷新" onPress={refresh} /> : null}
        {orig ? (
          <>
            <Text style={s.muted}>{`原计划 · ${orig.name}`}</Text>
            {orig.items.map((it, i) => <Text key={`${it.exercise}-${i}`} style={s.p}>{`${i + 1}. ${itemLine(it, lib)}`}</Text>)}
          </>
        ) : null}
        {v.status === "rest_today" ? null : toggles}
      </View>
    );
  }
  const items = (v.changed ? v.today : v.original).items;
  return (
    <View style={s.box}>
      {v.changed ? (
        <Fold title="IronM 按你今天的情况调整过 · 为什么">
          <Text style={s.p}>{v.changes.map(clean).join("；")}</Text>
          <Text style={s.muted}>{`原因：${v.reasons.map(clean).join("；")}`}</Text>
          <Text style={s.muted}>{`原计划：${v.original.items.map((it) => itemLine(it, lib)).join("、")}`}</Text>
        </Fold>
      ) : null}
      {items.map((it, i) => {
        const tg = targets[it.exercise];
        return (
          <View key={`${it.exercise}-${i}`} style={s.li}>
            <Text style={s.p}>{`${i + 1}. ${itemLine(it, lib)}`}</Text>
            {tg && !v.changed ? <Text style={s.muted}>{`下次 ${clean(tg.text)}`}</Text> : null}
          </View>
        );
      })}
      {toggles}
      <Button kind="ghost" title="没用记录器，直接打卡" onPress={() => onCheckin(v.today.name, v.changed ? v.today : null)} />
    </View>
  );
}

const s = StyleSheet.create({
  box: { gap: space.s },
  li: { gap: 2 },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
});
