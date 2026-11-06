// 对话最新位置的两条 IronM 消息（同网页版 inboxView、weekMsgView）：
// 管家消息（§26、§85）——上次看过之后的调整、要你确认的调整，在这里"确认"或"暂不"；
// 周报消息（§147 需求 3）——每周第一次打开对话时发，点掉这周不再出。
import { router } from "expo-router";
import { useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Button } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { errorText } from "./api";
import { Mascot } from "./mascot";
import { type Draft, draftClosed, type Inbox, type InboxChange, type InboxPending, INBOX_WORD, inboxShown, TEMP_RULE, tempSpan, type WeekReport, weekSaid } from "./model";
import { closeWeek } from "./store";
import { cleanText } from "./text";

function Head({ sub, onClose }: { sub: string; onClose?: () => void }) {
  return (
    <View style={s.head}>
      <Mascot size={22} />
      <Text style={s.who}>IronM</Text>
      <Text style={[s.muted, s.flex]} numberOfLines={1}>{sub}</Text>
      {onClose ? (
        <Pressable accessibilityRole="button" accessibilityLabel="这周不再显示" onPress={onClose} hitSlop={10} style={s.close}>
          <Text style={s.closeText}>×</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

export function InboxMsg({ inbox }: { inbox: Inbox }) {
  const shown = inboxShown(inbox);
  return (
    <View style={s.box}>
      <Head sub="按你最新的数据调整了方案" />
      {shown.length ? (
        <View style={s.list}>
          {shown.map((c) => (
            <ChangeRow key={c.key} c={c} />
          ))}
        </View>
      ) : null}
      {inbox.pending.length ? (
        <View style={s.pending}>
          {inbox.pending.map((x) => (x.value?.draft ? <DraftPending key={x.key} x={x} id={x.value.draft} /> : <PendingRow key={x.key} x={x} />))}
        </View>
      ) : null}
    </View>
  );
}

function ChangeRow({ c }: { c: InboxChange }) {
  return (
    <View style={s.change}>
      <Text style={[s.tag, c.change === "removed" ? s.tagOff : c.change === "added" ? s.tagNew : null]}>{INBOX_WORD[c.change] || "调整"}</Text>
      <View style={s.flex}>
        <Text style={s.text}>{cleanText(c.change === "removed" ? `${c.before ?? ""}（已解除）` : c.after ?? "")}</Text>
        {c.kind === "review" && c.change === "added" ? <ReviewExtra c={c} /> : null}
      </View>
    </View>
  );
}

// 管家复盘的调整（§85）：写着为什么；自动生效的可以"不用这样调"（计划、热量、今天都恢复原来的）
function ReviewExtra({ c }: { c: InboxChange }) {
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const undo = async () => {
    setBusy(true);
    setError("");
    try {
      await api("/iron/api/coach/decide", { method: "POST", json: { key: c.key, decision: "undo" } });
      setDone(true);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  if (done) return <Text style={s.muted}>好的，已经恢复原来的安排。</Text>;
  return (
    <View style={s.extra}>
      {c.why ? <Text style={s.muted}>{cleanText(c.why)}</Text> : null}
      {c.status === "auto" ? (
        <View style={s.row}>
          <Button small kind="ghost" title="不用这样调" disabled={busy} onPress={undo} />
        </View>
      ) : null}
      {error ? <Text style={s.error}>{error}</Text> : null}
    </View>
  );
}

type Proposal = { status: string; draft?: PlanDraft; answer?: string; warning?: string; message?: string };
type PlanDraft = { id: string; changes?: string; plan?: { sessions?: { day: number; name: string; minutes: number; items: { exercise: string; sets: number; reps: string }[] }[] } };

function PendingRow({ x }: { x: InboxPending }) {
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"ask" | "later" | "working" | "done">("ask");
  const [why, setWhy] = useState(false);
  const [said, setSaid] = useState("");
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [error, setError] = useState("");

  const decide = async (decision: "accept" | "later") => {
    setBusy(true);
    setError("");
    try {
      await api("/iron/api/coach/decide", { method: "POST", json: { key: x.key, decision } });
      if (decision === "later") {
        setPhase("later");
        return;
      }
      setPhase("working");
      const trigger = x.kind === "alert" && x.value?.trigger ? `?trigger=${encodeURIComponent(x.value.trigger)}` : "";
      const p = await api<Proposal>(`/iron/api/review/proposal${trigger}`, { method: "POST" });
      if (p.status === "ok" && p.draft) setProposal(p);
      else setSaid(p.message || "这次没能生成方案，可以直接告诉我想怎么改。");
      setPhase("done");
    } catch (err) {
      setError(errorText(err));
      setPhase((ph) => (ph === "working" ? "ask" : ph));
    } finally {
      setBusy(false);
    }
  };

  if (phase === "later") return <Text style={s.muted}>好的，「{x.title}」今天不再提。</Text>;
  return (
    <View style={s.item}>
      {x.why ? (
        <Pressable accessibilityRole="button" accessibilityState={{ expanded: why }} onPress={() => setWhy(!why)} hitSlop={6}>
          <Text style={s.title}>
            {x.title} <Text style={s.more}>{why ? "▾" : "▸"}</Text>
          </Text>
        </Pressable>
      ) : (
        <Text style={s.title}>{x.title}</Text>
      )}
      {why && x.why ? <Text style={s.muted}>{cleanText(x.why)}</Text> : null}
      {phase === "ask" ? (
        <View style={s.row}>
          <Button small title="确认，出方案" disabled={busy} onPress={() => decide("accept")} />
          <Button small kind="ghost" title="暂不" disabled={busy} onPress={() => decide("later")} />
        </View>
      ) : null}
      {phase === "working" ? <Text style={s.muted}>IronM 在改计划，大约要半分钟…</Text> : null}
      {said ? <Text style={s.text}>{cleanText(said)}</Text> : null}
      {proposal?.draft ? <DraftView d={proposal.draft} answer={proposal.answer} warning={proposal.warning} /> : null}
      {error ? <Text style={s.error}>{error}</Text> : null}
    </View>
  );
}

/** 带预览的待确认（管家提的改计划、临时调整，§163）：列出改了什么，"好"就真正确认这份预览，再收起这条；确认后能撤销。 */
function DraftPending({ x, id }: { x: InboxPending; id: string }) {
  const [d, setD] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"ask" | "later" | "done" | "undone">("ask");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api<{ draft: Draft }>(`/iron/api/drafts/${encodeURIComponent(id)}`)
      .then((r) => live && setD(r.draft))
      .catch((err) => live && setError(errorText(err)));
    return () => {
      live = false;
    };
  }, [id]);
  const call = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const confirm = () => call(async () => {
    await api(`/iron/api/drafts/${encodeURIComponent(id)}/confirm`, { method: "POST", json: {} });
    await api("/iron/api/coach/decide", { method: "POST", json: { key: x.key, decision: "accept" } }).catch(() => {});
    setPhase("done");
  });
  const later = () => call(async () => {
    await api("/iron/api/coach/decide", { method: "POST", json: { key: x.key, decision: "later" } });
    setPhase("later");
  });
  const undo = () => call(async () => {
    await api(`/iron/api/drafts/${encodeURIComponent(id)}/undo`, { method: "POST", json: {} });
    setPhase("undone");
  });
  const temp = d?.kind === "temp" && d.temp ? d.temp : null;
  if (phase === "later") return <Text style={s.muted}>好的，「{x.title}」今天不再提。</Text>;
  return (
    <View style={s.item}>
      <Text style={s.title}>{cleanText(x.title)}</Text>
      {x.why ? <Text style={s.muted}>{cleanText(x.why)}</Text> : null}
      {!d ? (error ? null : <Text style={s.muted}>正在读取…</Text>) : draftClosed(d) && phase === "ask" ? (
        <Text style={s.muted}>{draftClosed(d)}</Text>
      ) : (
        <View style={s.draft}>
          {temp ? <Text style={s.text}>{tempSpan(temp)}</Text> : <Text style={s.muted}>改了什么：</Text>}
          {(temp?.lines ?? d.items ?? []).map((it, i) => <Text key={i} style={s.text}>{`• ${cleanText(it)}`}</Text>)}
          {temp?.why ? <Text style={s.muted}>{`为什么：${cleanText(temp.why)}`}</Text> : null}
          {phase === "ask" ? (
            <>
              {temp ? <Text style={s.caption}>{TEMP_RULE}</Text> : null}
              <View style={s.row}>
                <Button small title="好" disabled={busy} onPress={confirm} />
                <Button small kind="ghost" title="暂不" disabled={busy} onPress={later} />
              </View>
            </>
          ) : phase === "done" ? (
            <View style={s.row}>
              <Text style={s.ok}>{temp ? "已生效，到期回到原计划。" : "已保存，新的计划从今天起生效。"}</Text>
              <Button small kind="ghost" title="撤销" disabled={busy} onPress={undo} />
            </View>
          ) : (
            <Text style={s.ok}>{temp ? "已撤销，回到原计划。" : "已撤销，计划回到改之前的样子。"}</Text>
          )}
        </View>
      )}
      {error ? <Text style={s.error}>{error}</Text> : null}
    </View>
  );
}

const WEEK = ["一", "二", "三", "四", "五", "六", "日"];

/** 管家出的新计划方案（同网页版 draftView）：确认后才替换现在的计划，之后可以撤销。 */
function DraftView({ d, answer, warning }: { d: PlanDraft; answer?: string; warning?: string }) {
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"ask" | "confirmed" | "closed">("ask");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const act = async (action: "confirm" | "cancel" | "undo") => {
    setBusy(true);
    setError("");
    try {
      await api(`/iron/api/drafts/${encodeURIComponent(d.id)}/${action}`, { method: "POST" });
      if (action === "confirm") {
        setMsg("已保存，新的计划从今天起生效。");
        setPhase("confirmed");
      } else {
        setMsg(action === "undo" ? "已撤销，计划回到改之前的样子。" : "已取消，计划没有改动。");
        setPhase("closed");
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };
  const sessions = d.plan?.sessions ?? [];
  return (
    <View style={s.draft}>
      {answer ? <Text style={s.text}>{cleanText(answer)}</Text> : null}
      {d.changes ? <Text style={s.muted}>改了什么：{cleanText(d.changes)}</Text> : null}
      {warning ? <Text style={s.error}>{cleanText(warning)}</Text> : null}
      {sessions.map((x, i) => (
        <Text key={i} style={s.text}>
          {`${i + 1}. 周${WEEK[x.day - 1] ?? ""} ${x.name}（约 ${x.minutes} 分钟）：${x.items.map((it) => `${it.exercise} ${it.sets}×${it.reps}`).join("、")}`}
        </Text>
      ))}
      {phase === "ask" ? (
        <View style={s.row}>
          <Button small title="确认" disabled={busy} onPress={() => act("confirm")} />
          <Button small kind="ghost" title="取消" disabled={busy} onPress={() => act("cancel")} />
        </View>
      ) : phase === "confirmed" ? (
        <View style={s.row}>
          <Button small kind="ghost" title="撤销" disabled={busy} onPress={() => act("undo")} />
        </View>
      ) : null}
      {msg ? <Text style={s.ok}>{msg}</Text> : null}
      {error ? <Text style={s.error}>{error}</Text> : null}
      <Text style={s.caption}>确认后才会替换现在的计划，之后可以撤销；这份方案 24 小时内有效。</Text>
    </View>
  );
}

export function WeekMsg({ report }: { report: WeekReport }) {
  return (
    <View style={s.box}>
      <Head sub="上周周报" onClose={closeWeek} />
      <Text style={s.text}>{cleanText(weekSaid(report))}</Text>
      <View style={s.row}>
        <Button
          small
          title="看周报"
          onPress={() => {
            closeWeek();
            router.push("/record");
          }}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  box: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.accent, padding: space.m, gap: space.m },
  head: { flexDirection: "row", alignItems: "center", gap: space.s },
  who: { color: color.ink, fontSize: 15, fontWeight: "700" },
  flex: { flex: 1, minWidth: 0 },
  close: { width: 28, height: 28, alignItems: "center", justifyContent: "center" },
  closeText: { color: color.muted, fontSize: 22, lineHeight: 24 },
  list: { gap: 10 },
  change: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  tag: { minWidth: 40, textAlign: "center", fontSize: 12, fontWeight: "700", paddingVertical: 2, color: color.accentInk, backgroundColor: color.plank, overflow: "hidden" },
  tagNew: { backgroundColor: color.fire },
  tagOff: { backgroundColor: color.muted },
  extra: { gap: 6, marginTop: 4 },
  pending: { gap: space.m, borderTopWidth: 1, borderTopColor: color.woodLight, paddingTop: space.m },
  item: { gap: 6 },
  title: { color: color.ink, fontSize: 15, fontWeight: "700" },
  more: { color: color.muted, fontWeight: "400" },
  text: { color: color.ink, fontSize: 14, lineHeight: 22 },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
  ok: { color: color.accentText, fontSize: 13, lineHeight: 19 },
  error: { color: color.heat, fontSize: 13, lineHeight: 19 },
  caption: { color: color.muted, fontSize: 12, lineHeight: 17 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
  draft: { gap: 6 },
});
