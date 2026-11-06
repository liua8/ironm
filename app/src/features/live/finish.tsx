// 结束训练（同网页 livePage 的 finish，spec §71、§92）：小结、这次感受（RPE）、精力睡眠哪里酸、保存或放弃；
// 保存后换成练完的卡：标题、数字数上来、破纪录、本周进度环；晒一下在同一个弹出页里换成分享卡（§147、§164 第四期）。
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { StyleSheet, Text, Vibration, View } from "react-native";
import Svg, { Circle } from "react-native-svg";

import { api } from "@/api/client";
import { Chips, Sheet } from "@/features/home/bits";
import { attachCheckinPhoto, emptyState, StateBox, type StatePick, stateBody } from "@/features/home/checkin";
import type { Photo } from "@/lib/photo";
import { clean } from "@/features/home/train-logic";
import { WorkoutShare } from "@/features/share/share";
import { Button, LinkButton, Note, PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { LiveIcon } from "./icons";
import { clock, doneWords, type FinishResp, type Live, summarize } from "./logic";

const RPE = Array.from({ length: 10 }, (_, k) => [k + 1, String(k + 1)] as const);

/** 从 0 数到目标，0.9 秒。 */
function useCountUp(to: number): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    let raf = 0;
    const t0 = Date.now();
    const step = () => {
      const p = Math.min(1, (Date.now() - t0) / 900);
      setV(Math.round(to * (1 - (1 - p) ** 3)));
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return v;
}

function Cell({ label, value, unit }: { label: string; value: number; unit: string }) {
  const n = useCountUp(value);
  return (
    <View style={s.cell}>
      <Text style={s.muted}>{label}</Text>
      <Text><PixelText size={24}>{String(n)}</PixelText><Text style={s.muted}>{unit}</Text></Text>
    </View>
  );
}

/** 本周进度环：打开时停在练之前，过一下涨到现在（§93）。 */
function Ring({ before, done, planned }: { before: number; done: number; planned: number }) {
  const [n, setN] = useState(before);
  useEffect(() => { const t = setTimeout(() => setN(done), 350); return () => clearTimeout(t); }, [done]);
  const size = 96, w = 10, r = (size - w) / 2, len = 2 * Math.PI * r;
  const p = planned ? Math.min(1, n / planned) : 0;
  const full = planned > 0 && n >= planned;
  return (
    <View style={s.ring} accessibilityRole="image" accessibilityLabel={`本周完成 ${done} / ${planned} 次`}>
      <Svg width={size} height={size}>
        <Circle cx={size / 2} cy={size / 2} r={r} stroke={color.woodLight} strokeWidth={w} fill="none" />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={full ? color.good : color.accent}
          strokeWidth={w}
          fill="none"
          strokeDasharray={`${len * p} ${len}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </Svg>
      <View style={s.ringIn}>
        <PixelText size={24}>{String(n)}</PixelText>
        <Text style={s.ringSub}>{`/ ${planned} 本周`}</Text>
      </View>
    </View>
  );
}

export function FinishSheet({ live, t0, open, onClose, flush }: { live: Live; t0: number; open: boolean; onClose: () => void; flush: () => Promise<void> }) {
  const [rpe, setRpe] = useState<number | null>(null);
  const [st, setSt] = useState<StatePick>(emptyState);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [photoWarn, setPhotoWarn] = useState("");
  const [msg, setMsg] = useState("");
  const [sure, setSure] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<FinishResp | null>(null);
  const [sharing, setSharing] = useState(false);
  const sum = summarize(live.items);
  const home = () => router.replace("/");

  const save = async () => {
    setBusy(true);
    setMsg("");
    await flush();
    try {
      const r = await api<FinishResp>("/iron/api/live/finish", { method: "POST", json: { rpe, ...stateBody(st) } });
      const c = r.workout?.celebrate || {};
      Vibration.vibrate(c.week?.reached_now || c.prs?.length ? [0, 40, 60, 40] : 25);
      // 打卡照片：记录存好后再传，传不上不影响练完，只在练完的卡下面说一句
      setPhotoWarn(await attachCheckinPhoto(r.workout?.id, photo));
      setRes(r);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    } finally {
      setBusy(false);
    }
  };
  const abandon = async () => {
    try {
      await api("/iron/api/live", { method: "DELETE" });
      onClose();
      if (router.canGoBack()) router.back(); else home();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    }
  };

  if (res?.workout?.id && sharing) {
    // 分享卡就在这个弹出页里换上，不再叠一层弹出页（手机上弹出页套弹出页容易出不来）
    return (
      <Sheet title="晒一下" open={open} onClose={home}>
        <WorkoutShare id={res.workout.id} />
        <LinkButton title="‹ 返回练完的卡" onPress={() => setSharing(false)} />
      </Sheet>
    );
  }

  if (res) {
    const words = doneWords(res);
    const c = res.workout?.celebrate || {};
    const wk = c.week;
    const prs = c.prs || [];
    return (
      <Sheet title="结束训练" open={open} onClose={home}>
        <View style={s.hero}>
          <View style={s.burst}><LiveIcon name="check" size={36} color={color.accentInk} /></View>
          <PixelText size={24}>{words.title}</PixelText>
          {res.workout?.line ? <Text style={[s.muted, s.center]}>{clean(res.workout.line)}</Text> : null}
        </View>
        <View style={s.sum}>
          <Cell label="总时长" value={res.summary.minutes || 0} unit=" 分钟" />
          <Cell label="组数" value={sum.sets} unit=" 组" />
          <Cell label="总训练量" value={sum.volume} unit=" 公斤" />
        </View>
        {prs.map((p) => (
          <View key={p.exercise} style={s.pr}>
            <LiveIcon name="trophy" size={20} color={color.accent} />
            <View style={s.flex}>
              <Text style={s.prTitle}>{`${p.exercise} ${p.weight_kg}×${p.reps}`}</Text>
              <Text style={s.muted}>{`估算最大重量 ${Math.round(p.e1rm)} 公斤，以前 ${Math.round(p.before)}`}</Text>
            </View>
          </View>
        ))}
        {wk?.planned ? (
          <View style={s.week}>
            <Ring before={wk.before ?? wk.done} done={wk.done} planned={wk.planned} />
            <Text style={[s.p, s.flex]}>{words.week}</Text>
          </View>
        ) : null}
        {/* 晒一下（§147）：同网页，有这次训练的记录才能晒 */}
        {photoWarn ? <Note>{photoWarn}</Note> : null}
        {res.workout?.id ? <Button title="晒一下" onPress={() => setSharing(true)} /> : null}
        <Button kind="ghost" title="回首页" onPress={home} />
      </Sheet>
    );
  }

  const cells: [string, string][] = [
    ["总时长", clock((Date.now() - t0) / 1000)],
    ["动作", `${sum.exercises} 个`],
    ["组数", `${sum.sets} 组`],
    ["总训练量", `${sum.volume} 公斤`],
  ];
  return (
    <Sheet title="结束训练" open={open} onClose={onClose}>
      <View style={s.sum}>
        {cells.map(([k, v]) => (
          <View key={k} style={s.cell}>
            <Text style={s.muted}>{k}</Text>
            <Text style={s.cellVal}>{v}</Text>
          </View>
        ))}
      </View>
      <Text style={s.h3}>这次感受（1 很轻松 … 10 到极限，可不选）</Text>
      <Chips items={RPE} isOn={(k) => rpe === k} onTap={(k) => setRpe(rpe === k ? null : k)} label="感受 1 到 10" />
      <StateBox value={st} onChange={setSt} photo={photo} onPhoto={setPhoto} />
      <Note tone="error">{msg}</Note>
      <Button title={sum.sets ? "保存这次训练" : "还没有完成的组"} disabled={!sum.sets || busy} onPress={save} />
      <LinkButton title="放弃本次" onPress={() => setSure(true)} />
      {sure ? (
        <View style={s.sure}>
          <Text style={[s.muted, s.flex]}>放弃后这次不留记录，确定吗？</Text>
          <Button small kind="wood" title="确定放弃" onPress={abandon} />
        </View>
      ) : null}
    </Sheet>
  );
}

const s = StyleSheet.create({
  flex: { flex: 1, minWidth: 0 },
  center: { textAlign: "center" },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
  p: { color: color.ink, fontSize: 14, lineHeight: 21 },
  h3: { color: color.ink, fontSize: 15, fontWeight: "700" },
  sum: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  cell: { flexGrow: 1, flexBasis: "45%", backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.s, gap: 2 },
  cellVal: { color: color.ink, fontSize: 18, fontWeight: "700" },
  hero: { alignItems: "center", gap: space.s },
  burst: { width: 64, height: 64, alignItems: "center", justifyContent: "center", backgroundColor: color.fire, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark },
  pr: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.amber, padding: space.s },
  prTitle: { color: color.ink, fontSize: 15, fontWeight: "700" },
  week: { flexDirection: "row", alignItems: "center", gap: space.m },
  ring: { width: 96, height: 96, alignItems: "center", justifyContent: "center" },
  ringIn: { position: "absolute", alignItems: "center" },
  ringSub: { color: color.muted, fontSize: 11 },
  sure: { flexDirection: "row", alignItems: "center", gap: space.s },
});
