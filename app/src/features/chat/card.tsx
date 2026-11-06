// 回答里的预览卡片（同网页版 cardView，spec §9、§45、§151、§163）：计划、训练记录、改目标、临时调整。
// 确认才写入，写入后能撤销；状态从服务端取（重新打开对话也对）。
import { type ReactNode, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { syncTrainingReminder } from "@/lib/notify";
import { Button } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { errorText } from "./api";
import { CARD_STATE, type CardRef, cardExpired, TEMP_RULE } from "./model";
import { cleanText } from "./text";

type DraftState = { draft: { state: string } };

export function PreviewCard({ card }: { card: CardRef }) {
  const d = card.data;
  const [state, setState] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!d || !card.draft) return;
    let live = true;
    api<DraftState>(`/iron/api/drafts/${encodeURIComponent(card.draft)}`)
      .then((r) => live && setState(r.draft?.state || "pending"))
      .catch(() => live && setState("pending"));
    return () => {
      live = false;
    };
  }, [d, card.draft]);

  if (!d) return null;
  const now = state || "pending";
  const expired = cardExpired(d, now);
  const plan = card.kind === "plan";
  const temp = card.kind === "temp";  // 临时调整（§163）：这几天这样练，到期回到原计划
  const c = (t: string | undefined) => cleanText(t ?? "");

  const act = async (action: "confirm" | "cancel" | "undo") => {
    setBusy(true);
    setError("");
    try {
      const r = await api<DraftState>(`/iron/api/drafts/${encodeURIComponent(card.draft)}/${action}`, { method: "POST", json: {} });
      setState(r.draft?.state || now);
      if (plan || temp) void syncTrainingReminder(); // 确认或撤销了改计划：训练日提醒跟着计划走
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  let body: ReactNode;
  if (plan && d.rows) {
    // 按操作改的：只列变化的行（§45）
    body = (
      <>
        {d.changes ? <Text style={s.changes}>{c(d.changes)}</Text> : null}
        <View style={s.list}>
          {d.rows.map((r, i) => (
            <Text key={i} style={s.li}>
              <Text style={s.b}>{c(r.what)}</Text> {r.before ? <Text style={s.muted}>{c(r.before)} → </Text> : null}
              {c(r.after)}
            </Text>
          ))}
        </View>
        {(d.impact ?? []).map((x, i) => <Text key={`i${i}`} style={s.muted}>{c(x)}</Text>)}
        {(d.skipped ?? []).map((x, i) => <Text key={`s${i}`} style={s.note}>没改：{c(x)}</Text>)}
        {d.hint ? <Text style={s.muted}>{c(d.hint)}</Text> : null}
      </>
    );
  } else if (plan) {
    body = (
      <>
        {d.changes ? <Text style={s.changes}>{c(d.changes)}</Text> : null}
        {(d.sessions ?? []).map((x, i) => (
          <View key={i} style={s.session}>
            <View style={s.sessionHead}>
              <Text style={[s.b, x.changed && d.replaces ? s.changed : null, s.flex]}>{`${x.day} · ${x.name}`}</Text>
              <Text style={s.muted}>约 {x.minutes} 分钟</Text>
            </View>
            {(x.items ?? []).map((it, k) => <Text key={k} style={s.li}>• {c(it)}</Text>)}
          </View>
        ))}
        {(d.removed ?? []).length ? <Text style={s.muted}>去掉：{(d.removed ?? []).join("、")}</Text> : null}
      </>
    );
  } else {
    body = (
      <>
        {(d.items ?? []).length ? <View style={s.list}>{(d.items ?? []).map((it, i) => <Text key={i} style={s.li}>• {c(it)}</Text>)}</View> : null}
        {d.rpe ? <Text style={s.muted}>感受 {d.rpe} 分</Text> : null}
        {d.note ? <Text style={s.muted}>{c(d.note)}</Text> : null}
      </>
    );
  }

  let actions: ReactNode;
  if (!state) actions = <Text style={s.muted}>正在读取状态…</Text>;
  else if (now === "pending" && !expired)
    actions = (
      <>
        <Button small title={temp ? "确认，这几天这样练" : plan ? "确认，保存计划" : "确认，记下"} disabled={busy} onPress={() => act("confirm")} />
        <Button small kind="ghost" title="取消" disabled={busy} onPress={() => act("cancel")} />
      </>
    );
  else if (now === "confirmed")
    actions = (
      <>
        <Text style={[s.chip, s.chipGood]}>{temp ? "已生效，到期回到原计划" : plan ? "计划已保存" : "已记下"}</Text>
        <Button small kind="ghost" title="撤销" disabled={busy} onPress={() => act("undo")} />
      </>
    );
  else actions = <Text style={s.chip}>{expired ? (temp ? "已作废：过了开始日期还没确认" : "已过期，让 IronM 重新生成") : temp && now === "undone" ? "已撤销，回到原计划" : CARD_STATE[now] || now}</Text>;

  return (
    <View style={[s.card, now === "confirmed" && s.cardOk, (now === "cancelled" || now === "undone") && s.cardOff]}>
      <Text style={s.title}>{c(d.title)}</Text>
      {d.headline ? <Text style={s.muted}>{c(d.headline)}</Text> : null}
      {body}
      {temp && now === "pending" && !expired ? <Text style={s.muted}>{`${TEMP_RULE}没确认的过了开始日期就作废。`}</Text> : null}
      {temp && now === "confirmed" ? <Text style={s.muted}>到了结束日期自动回到原计划，也可以提前撤销。</Text> : null}
      <View style={s.actions}>{actions}</View>
      {error ? <Text style={s.note}>{error}</Text> : null}
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: color.paperLight, padding: space.m, gap: space.s },
  cardOk: { borderColor: color.accent },
  cardOff: { opacity: 0.7 },
  title: { color: color.ink, fontSize: 16, fontWeight: "700" },
  muted: { color: color.muted, fontSize: 14, lineHeight: 20 },
  changes: { color: color.ink, fontSize: 14, lineHeight: 20 },
  list: { gap: 4 },
  li: { color: color.ink, fontSize: 14, lineHeight: 21 },
  b: { fontWeight: "700", color: color.ink },
  flex: { flex: 1 },
  changed: { color: color.accentText },
  session: { borderTopWidth: 1, borderTopColor: color.woodLight, paddingTop: space.s, gap: 4 },
  sessionHead: { flexDirection: "row", gap: space.s, alignItems: "baseline" },
  note: { color: color.heat, backgroundColor: color.heatSoft, fontSize: 13, lineHeight: 19, padding: space.s },
  actions: { flexDirection: "row", flexWrap: "wrap", gap: space.s, alignItems: "center" },
  chip: { color: color.muted, backgroundColor: color.paper, borderWidth: 1, borderColor: color.woodLight, fontSize: 13, paddingHorizontal: space.s, paddingVertical: 4, overflow: "hidden" },
  chipGood: { color: color.accentText, backgroundColor: color.goodSoft, borderColor: color.accent },
});
