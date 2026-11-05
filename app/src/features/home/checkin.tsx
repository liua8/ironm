// 打卡（同网页 doneSheet、restSheet、stateBox）：练完直接打卡、今天没练、精力睡眠哪里酸。
// 网页版打卡时还能逐组填重量和次数：逐组填这里先不做（可不填的）。
// 打卡照片（§117、§164 第四期）：挂在这次记录上、不进体态对比；记录存好以后再传，传不上不影响打卡，只多说一句。
import { useState } from "react";
import { Image, Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { appendPhoto, getPhoto, type Photo, photoErrText } from "@/lib/photo";
import { Icon } from "@/ui/icons";
import { Button, Field, LinkButton, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { Chips, Fold, Sheet } from "./bits";
import type { Brief, Session } from "./types";

// 和后端 SORE_PARTS 一致
export const SORE_PARTS = ["胸", "背", "肩", "手臂", "大腿前", "大腿后", "臀", "小腿", "核心"] as const;
const FEELINGS = [["good", "好"], ["ok", "一般"], ["poor", "差"]] as const;
const REST_WHY = [["rest", "休息"], ["sick", "生病"], ["travel", "出差"], ["busy", "太忙"]] as const;
export const REST_WORDS: Record<string, string> = Object.fromEntries(REST_WHY);
const RPE = Array.from({ length: 10 }, (_, k) => [k + 1, String(k + 1)] as const);

export type StatePick = { energy: string | null; slept: string | null; sore: string[] };
export const emptyState = (): StatePick => ({ energy: null, slept: null, sore: [] });
/** 只带填了的。 */
export const stateBody = (p: StatePick) => ({
  ...(p.energy ? { energy: p.energy } : {}),
  ...(p.slept ? { slept: p.slept } : {}),
  ...(p.sore.length ? { sore: p.sore } : {}),
});

/** 打卡照片：记录存好后再传；传不上返回一句提示，不抛错（打卡已经成功了）。 */
export async function attachCheckinPhoto(workoutId: string | null | undefined, photo: Photo | null): Promise<string> {
  if (!photo || !workoutId) return "";
  const form = new FormData();
  appendPhoto(form, "photo", photo, "checkin.jpg");
  try {
    await api(`/iron/api/workouts/${encodeURIComponent(workoutId)}/photo`, { method: "POST", body: form });
    return "";
  } catch (err) {
    return `照片没传上：${err instanceof Error && err.message ? err.message : "请稍后再试。"}`;
  }
}

/** 打卡照片的格子：点了拍或从相册选，选好显示小图，可以换一张、去掉。 */
export function PhotoSlot({ photo, onChange }: { photo: Photo | null; onChange: (p: Photo | null) => void }) {
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const shoot = async () => {
    setErr("");
    setBusy(true);
    try {
      const p = await getPhoto("打卡照片");
      if (p) onChange(p);
    } catch (e) {
      setErr(photoErrText(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={s.slotWrap}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={photo ? "换一张打卡照片" : "拍打卡照片"}
        accessibilityState={{ disabled: busy }}
        disabled={busy}
        onPress={shoot}
        style={({ pressed }) => [s.slot, (pressed || busy) && s.slotDown]}
      >
        <View style={s.slotView}>
          {photo ? <Image source={{ uri: photo.uri }} style={s.slotImg} accessibilityLabel="打卡照片" /> : <Icon name="camera" size={22} color={color.ink} />}
        </View>
        <View style={s.slotMain}>
          <Text style={s.slotTitle}>打卡照片</Text>
          <Text style={s.slotSub}>{photo ? "换一张" : "随手拍一张，不用摆姿势"}</Text>
        </View>
      </Pressable>
      {photo ? <LinkButton title="不要这张" onPress={() => onChange(null)} /> : null}
      {err ? <Note tone="error">{err}</Note> : null}
    </View>
  );
}

/** 打卡多记的状态（§105）：精力、昨晚睡得怎样、哪里酸，都可不填。
 * 给了 onPhoto 才有"照片"一格（这次记录存好后由调用方传，见 attachCheckinPhoto）。 */
export function StateBox({ value, onChange, photo = null, onPhoto }: { value: StatePick; onChange: (v: StatePick) => void; photo?: Photo | null; onPhoto?: (p: Photo | null) => void }) {
  const one = (key: "energy" | "slept") => (
    <Chips items={FEELINGS} isOn={(k) => value[key] === k} onTap={(k) => onChange({ ...value, [key]: value[key] === k ? null : k })} />
  );
  return (
    <Fold title={onPhoto ? "更多：精力、睡眠、哪里酸、照片（可不填）" : "更多：精力、睡眠、哪里酸（可不填）"}>
      <Text style={s.label}>精力</Text>
      {one("energy")}
      <Text style={s.label}>昨晚睡得</Text>
      {one("slept")}
      <Text style={s.label}>哪里酸</Text>
      <Chips
        items={SORE_PARTS.map((p) => [p, p] as const)}
        isOn={(p) => value.sore.includes(p)}
        onTap={(p) => onChange({ ...value, sore: value.sore.includes(p) ? value.sore.filter((x) => x !== p) : [...value.sore, p] })}
      />
      {onPhoto ? (
        <>
          <Text style={s.label}>照片</Text>
          <PhotoSlot photo={photo} onChange={onPhoto} />
        </>
      ) : null}
    </Fold>
  );
}

/** 打卡成功的一句：写明本周第几练。 */
export async function cheerText(): Promise<string> {
  const b = await api<Brief>("/iron/api/brief").catch(() => null);
  const n = b?.week?.done || 0;
  const won = Boolean(b?.week?.planned && n >= b.week.planned);
  return `打卡成功。${n ? `本周第 ${n} 练${won ? "，本周目标达成！" : "，继续保持！"}` : "又进步了一点，继续保持！"}`;
}

/** 练完直接打卡（没用记录器）。version 是今天调整过的版本，按它记。 */
export function DoneSheet({ open, onClose, session, version, onDone, onRest }: {
  open: boolean;
  onClose: () => void;
  session: string;
  version: Session | null;
  onDone: (msg: string) => void;
  onRest: () => void;
}) {
  const [rpe, setRpe] = useState(0);
  const [st, setSt] = useState<StatePick>(emptyState);
  const [note, setNote] = useState("");
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setMsg("正在记下…");
    const items = version ? version.items.map((it) => ({ exercise: it.exercise, sets: it.sets, reps: it.reps })) : [];
    const text = (version ? [note.trim(), "按今天的版本"].filter(Boolean).join("；") : note.trim()).slice(0, 80);
    try {
      const r = await api<{ workout?: { id?: string } }>("/iron/api/workouts", {
        method: "POST",
        json: { session: session === "训练" ? "" : session, done: true, rpe: rpe || null, note: text, items, ...(version ? { minutes: version.minutes } : {}), ...stateBody(st) },
      });
      if (photo) setMsg("正在传照片…");
      const warn = await attachCheckinPhoto(r?.workout?.id, photo);
      setMsg("");
      const cheer = await cheerText();
      onDone(warn ? `${cheer}${warn}` : cheer);
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet title={`打卡：${session}${version ? "（今天的版本）" : ""}`} open={open} onClose={onClose}>
      <Note>这次感觉怎么样？1 很轻松，10 到极限（可不选）</Note>
      <Chips items={RPE} isOn={(k) => rpe === k} onTap={(k) => setRpe(k)} label="感受 1 到 10" />
      <StateBox value={st} onChange={setSt} photo={photo} onPhoto={setPhoto} />
      <Field value={note} onChangeText={setNote} maxLength={60} placeholder="备注（可不填），比如有点累、膝盖没疼" />
      <Button title="打卡" onPress={save} disabled={busy} />
      <Note>{msg}</Note>
      <LinkButton title="今天没练？" onPress={onRest} />
    </Sheet>
  );
}

/** 今天没练也能打卡（§105）：记下原因，不算练了，连续打卡照算。 */
export function RestSheet({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: (msg: string) => void }) {
  const [why, setWhy] = useState("rest");
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api("/iron/api/workouts", { method: "POST", json: { done: false, rest: why, note: note.trim() } });
      setMsg("");
      onDone("记下了，连续打卡照算");
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Sheet title="今天没练" open={open} onClose={onClose}>
      <Note>为什么没练？不算练了，连续打卡照算。</Note>
      <Chips items={REST_WHY} isOn={(k) => why === k} onTap={(k) => setWhy(k)} />
      <Field value={note} onChangeText={setNote} maxLength={60} placeholder="备注（可不填）" />
      <Button title="记下今天没练" onPress={save} disabled={busy} />
      <Note tone="error">{msg}</Note>
    </Sheet>
  );
}

const s = StyleSheet.create({
  label: { color: color.muted, fontSize: 13, fontWeight: "600", marginTop: space.xs },
  slotWrap: { gap: space.xs },
  slot: { flexDirection: "row", alignItems: "center", gap: space.m, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, padding: space.s },
  slotDown: { opacity: 0.75 },
  slotView: { width: 56, height: 56, alignItems: "center", justifyContent: "center", backgroundColor: color.paper, borderWidth: 2, borderColor: color.woodLight, overflow: "hidden" },
  slotImg: { width: "100%", height: "100%" },
  slotMain: { flex: 1, minWidth: 0, gap: 2 },
  slotTitle: { color: color.ink, fontSize: 15, fontWeight: "700" },
  slotSub: { color: color.muted, fontSize: 13 },
});
