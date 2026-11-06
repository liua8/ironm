// 条目详情（同网页 rankItem / rankPlan / rankComments / rankNick）：平均分、档位、几人评过、名次变化；
// 五档各几票；我的一票（夯…拉，能撤回）；训练计划榜的条目带每周怎么练；评论（热门 / 最新、发、点赞、删自己的、举报）；昵称可改。
import { useState } from "react";
import { Image, Linking, Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { askCoach, errText, useLoad } from "@/features/atlas/data";
import { Bullets, Caption, GrassNote, H3, Loading, Pills, TwoStep, ui } from "@/features/atlas/ui";
import { Button, Field, Note, PixelText } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { charCount, type CommentSort, imgUrl, itemStatus, md, planDaysText, scoreText, sortComments, tierBars, tierNames, weekdayName } from "./logic";
import { boardHref, goBack } from "./nav";
import type { Comment, Item, PlanDetail } from "./types";
import { Box, RankBar, TierTag, tierColors } from "./ui";

export function RankItemView({ board, itemKey }: { board: string; itemKey: string }) {
  const path = `/iron/api/rank/item?board=${encodeURIComponent(board)}&key=${encodeURIComponent(itemKey)}`;
  const loaded = useLoad(() => api<Item>(path), [path]);
  const [fresh, setFresh] = useState<Item | null>(null);
  const d = fresh && fresh.board === board && fresh.item.key === itemKey ? fresh : loaded.data;
  const [voteMsg, setVoteMsg] = useState("");
  const [cmMsg, setCmMsg] = useState("");
  const [sort, setSort] = useState<CommentSort>("热门");
  const back = () => goBack(boardHref(board));

  // 改动之后：接口回了整条就用它，没回就重读一次（同网页 send）
  const send = async (p: string, init: RequestInit & { json?: unknown }) => {
    const r = await api<Partial<Item>>(p, init);
    if (r && r.item) setFresh(r as Item);
    else setFresh(await api<Item>(path));
  };

  if (!d) {
    return (
      <View style={s.wrap}>
        <RankBar back="榜单" onBack={back} title="条目" />
        <Loading error={loaded.error} onRetry={loaded.reload} what="条目" />
      </View>
    );
  }
  const x = d.item;
  const names = tierNames(d.tiers);
  const vote = (tier: string) => {
    setVoteMsg("");
    send("/iron/api/rank/vote", { method: "PUT", json: { board, key: itemKey, tier } }).catch((err: unknown) => setVoteMsg(errText(err)));
  };
  const credit = x.credit;
  return (
    <View style={s.wrap}>
      <RankBar back="榜单" onBack={back} title={d.name} />
      <Box style={s.hero}>
        {x.image ? <Image source={{ uri: imgUrl(x.image) }} style={s.heroPic} resizeMode="cover" accessibilityLabel={x.name} /> : null}
        <Text style={s.title}>
          {x.name}
          {x.tag ? <Text style={s.kind}>{` ${x.tag}`}</Text> : null}
        </Text>
        {x.desc ? <Text style={ui.muted}>{x.desc}</Text> : null}
        {credit ? (
          <Text
            style={[s.credit, credit.page ? s.link : null]}
            onPress={credit.page ? () => { Linking.openURL(credit.page ?? "").catch(() => {}); } : undefined}
          >
            {`图：${credit.author || "Wikimedia Commons"}${credit.license ? ` · ${credit.license}` : ""}`}
          </Text>
        ) : null}
        <View style={s.score}>
          <PixelText size={48}>{scoreText(x)}</PixelText>
          {x.tier ? <TierTag big tier={x.tier} text={names[x.tier] ?? x.tier} /> : null}
          <Text style={[ui.muted, s.status]}>{itemStatus(x, d.min_votes)}</Text>
        </View>
      </Box>
      {x.votes ? (
        <Box>
          {tierBars(x, d.tiers).map((t) => (
            <View key={t.key} style={s.distRow}>
              <Text style={s.distName}>{t.name}</Text>
              <View style={s.distBar}>
                <View style={[s.distFill, { width: `${t.frac * 100}%`, backgroundColor: tierColors(t.key).bg }]} />
              </View>
              <Text style={s.distN}>{String(t.n)}</Text>
            </View>
          ))}
        </Box>
      ) : null}
      <Box style={s.voteBox}>
        <View style={s.voteHead}>
          <Text style={s.voteTitle}>{x.mine ? `我投的：${names[x.mine] ?? x.mine}` : "我的一票"}</Text>
          {x.mine ? (
            <Pressable accessibilityRole="button" onPress={() => vote("")} hitSlop={6}>
              <Text style={s.act}>撤回</Text>
            </Pressable>
          ) : (
            <Text style={ui.muted}>夯 5 分 … 拉 1 分</Text>
          )}
        </View>
        <View style={s.tiers}>
          {d.tiers.map((t) => {
            const on = x.mine === t.key;
            const c = tierColors(t.key);
            return (
              <Pressable
                key={t.key}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
                onPress={() => vote(t.key)}
                style={({ pressed }) => [s.tierBtn, { backgroundColor: c.bg, borderColor: on ? color.woodDark : c.bg }, on && s.tierOn, pressed && s.pressed]}
              >
                <Text style={[s.tierText, { color: c.fg }]}>{t.name}</Text>
              </Pressable>
            );
          })}
        </View>
        <Note tone="error">{voteMsg}</Note>
      </Box>
      {d.plan ? <RankPlan p={d.plan} /> : null}
      <GrassNote>{d.disclaimer}</GrassNote>
      <Comments d={d} board={board} itemKey={itemKey} send={send} sort={sort} setSort={setSort} msg={cmMsg} setMsg={setCmMsg} />
      {x.custom ? (
        <View style={s.foot}>
          <ReportItem board={board} itemKey={itemKey} />
        </View>
      ) : null}
    </View>
  );
}

/** 训练计划榜的条目：每周怎么练（健身房版）、为什么、进阶、减量、来源；按我的情况用 → 进对话。 */
function RankPlan({ p }: { p: PlanDetail }) {
  return (
    <Box style={s.plan}>
      <H3>每周怎么练</H3>
      <Caption>{`${planDaysText(p)}在家、伤病、时间不够时，IronM 会按你的情况换动作。`}</Caption>
      {p.sessions.map((sn, i) => (
        <View key={`${sn.day}-${i}`} style={s.planDay}>
          <Text style={s.planDayHead}>
            {`${weekdayName(sn.day)} · ${sn.name}`}
            <Text style={ui.muted}>{`  约 ${sn.minutes} 分钟`}</Text>
          </Text>
          <Bullets items={sn.items} />
        </View>
      ))}
      <H3>为什么这样排</H3>
      <Text style={ui.body}>{p.why}</Text>
      <H3>强度和进阶</H3>
      {[p.intensity, p.progress, p.deload].filter(Boolean).map((t, i) => (
        <Text key={i} style={ui.body}>
          {t}
        </Text>
      ))}
      {p.differs.length ? (
        <>
          <H3>要注意</H3>
          <Bullets items={p.differs} />
        </>
      ) : null}
      {p.source ? (
        <Caption>
          {`参考${p.source.authors.join("、")}的公开计划（`}
          <Text style={s.link} onPress={() => { Linking.openURL(p.source?.url ?? "").catch(() => {}); }}>
            {p.source.secondhand ? "第三方整理" : "原发"}
          </Text>
          {`，${p.source.seen} 查看），不是官方计划。`}
        </Caption>
      ) : null}
      <Button title="按我的情况用这个计划" onPress={() => askCoach(p.ask)} />
    </Box>
  );
}

type Send = (p: string, init: RequestInit & { json?: unknown }) => Promise<void>;

function Comments({ d, board, itemKey, send, sort, setSort, msg, setMsg }: {
  d: Item; board: string; itemKey: string; send: Send; sort: CommentSort; setSort: (s: CommentSort) => void; msg: string; setMsg: (m: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [nick, setNick] = useState<string | null>(null);
  const [editNick, setEditNick] = useState(false);
  const list = sortComments(d.comments, sort);
  const shownNick = nick ?? d.nick;
  const post = () => {
    if (!text.trim() || busy) return;
    setMsg("");
    setBusy(true);
    send("/iron/api/rank/comments", { method: "POST", json: { board, key: itemKey, text } })
      .then(() => setText(""))
      .catch((err: unknown) => setMsg(errText(err)))
      .finally(() => setBusy(false));
  };
  const fail = (err: unknown) => setMsg(errText(err));
  return (
    <Box style={s.comments}>
      <View style={s.cmHead}>
        <Text style={s.cmTitle}>{`评论 ${d.comments.length}`}</Text>
        <Pills label="评论排序" options={["热门", "最新"] as const} value={sort} onChange={setSort} />
      </View>
      <Field
        value={text}
        onChangeText={setText}
        multiline
        maxLength={d.comment_max}
        placeholder={d.no_claims ? "说说用着怎么样（不写疗效）" : "说说你的看法"}
        accessibilityLabel="写评论"
        style={s.compose}
      />
      <View style={s.cmSub}>
        <Pressable accessibilityRole="button" onPress={() => setEditNick((v) => !v)} hitSlop={6} style={s.nickBtn}>
          <Text style={s.act}>{shownNick ? `我的昵称：${shownNick}` : "发第一条评论时给你一个随机昵称"}</Text>
        </Pressable>
        <Text style={ui.muted}>{`${charCount(text)}/${d.comment_max}`}</Text>
        <Button title="发送" small disabled={busy || !text.trim()} onPress={post} />
      </View>
      {editNick ? <NickEdit onSaved={(n) => { setNick(n); setEditNick(false); }} /> : null}
      <Note tone="error">{msg}</Note>
      {list.length ? (
        list.map((c) => <CommentRow key={c.id} c={c} send={send} fail={fail} />)
      ) : (
        <Text style={ui.muted}>还没有评论，说说你的看法。</Text>
      )}
    </Box>
  );
}

function CommentRow({ c, send, fail }: { c: Comment; send: Send; fail: (err: unknown) => void }) {
  const [reported, setReported] = useState(false);
  return (
    <View style={s.cm}>
      <View style={s.who}>
        <Text style={s.nick}>{c.nick}</Text>
        <Text style={ui.muted}>{md(c.at)}</Text>
        {c.mine ? <Text style={s.me}>我</Text> : null}
      </View>
      <Text style={ui.body}>{c.text}</Text>
      <View style={s.acts}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ selected: c.liked }}
          accessibilityLabel={c.liked ? `取消赞，现在 ${c.likes} 个赞` : `赞，现在 ${c.likes} 个赞`}
          hitSlop={6}
          onPress={() => send(`/iron/api/rank/comments/${encodeURIComponent(c.id)}/like`, { method: "POST", json: { on: !c.liked } }).catch(fail)}
        >
          <Text style={[s.act, c.liked && s.liked]}>{`${c.liked ? "已赞" : "赞"} ${c.likes}`}</Text>
        </Pressable>
        {c.mine ? (
          <TwoStep label="删除" sure="确认删除？" onConfirm={() => { send(`/iron/api/rank/comments/${encodeURIComponent(c.id)}`, { method: "DELETE" }).catch(fail); }} />
        ) : (
          <TwoStep
            label="举报"
            sure="确认举报？"
            done={reported ? "已举报" : undefined}
            onConfirm={() => { api(`/iron/api/rank/comments/${encodeURIComponent(c.id)}/report`, { method: "POST" }).then(() => setReported(true)).catch(fail); }}
          />
        )}
      </View>
    </View>
  );
}

function NickEdit({ onSaved }: { onSaved: (nick: string) => void }) {
  const [v, setV] = useState("");
  const [msg, setMsg] = useState("");
  const save = () => {
    setMsg("");
    api<{ nick: string }>("/iron/api/rank/nick", { method: "PUT", json: { nick: v } })
      .then((r) => onSaved(r.nick))
      .catch((err: unknown) => setMsg(errText(err)));
  };
  return (
    <View style={s.nickEdit}>
      <Caption>评论区只显示昵称，不显示账号。</Caption>
      <View style={s.nickRow}>
        <Field value={v} onChangeText={setV} maxLength={12} placeholder="2–12 个字" accessibilityLabel="新昵称" onSubmitEditing={save} style={s.nickField} />
        <Button title="保存" small onPress={save} />
      </View>
      <Note tone="error">{msg}</Note>
    </View>
  );
}

/** 用户加的条目能举报：3 个人举报后先隐藏。 */
function ReportItem({ board, itemKey }: { board: string; itemKey: string }) {
  const [state, setState] = useState("");
  return (
    <TwoStep
      label="举报这个条目"
      sure="确认举报？3 个人举报后先隐藏"
      done={state || undefined}
      onConfirm={() => {
        api("/iron/api/rank/report", { method: "POST", json: { board, key: itemKey } })
          .then(() => setState("已举报"))
          .catch((err: unknown) => setState(errText(err)));
      }}
    />
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  hero: { gap: space.s, paddingVertical: space.m },
  heroPic: { width: "100%", aspectRatio: 16 / 9, borderWidth: 1, borderRadius: 14, borderColor: color.wood, backgroundColor: "#fff" },
  title: { color: color.ink, fontSize: 22, fontWeight: "800" },
  kind: { color: color.muted, fontSize: 14, fontWeight: "400" },
  credit: { color: color.muted, fontSize: 12 },
  link: { textDecorationLine: "underline" },
  score: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: space.s },
  status: { flexBasis: "100%" },
  distRow: { flexDirection: "row", alignItems: "center", gap: space.s, paddingVertical: 2 },
  distName: { width: 48, color: color.ink, fontSize: 13, fontWeight: "600" },
  distBar: { flex: 1, height: 12, backgroundColor: color.paperLight, borderWidth: 1, borderColor: color.woodLight },
  distFill: { height: "100%" },
  distN: { width: 28, textAlign: "right", color: color.muted, fontSize: 13 },
  voteBox: { gap: space.s, paddingVertical: space.m },
  voteHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s },
  voteTitle: { color: color.ink, fontSize: 16, fontWeight: "700" },
  tiers: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  tierBtn: { flexGrow: 1, flexBasis: 56, alignItems: "center", paddingVertical: 10, borderWidth: 1, borderRadius: 14 },
  tierOn: { borderBottomWidth: 6 },
  tierText: { fontSize: 15, fontWeight: "800" },
  pressed: { opacity: 0.75 },
  act: { color: color.muted, fontSize: 13, fontWeight: "600" },
  liked: { color: color.heat },
  plan: { gap: space.s, paddingVertical: space.m },
  planDay: { gap: 2 },
  planDayHead: { color: color.ink, fontSize: 15, fontWeight: "700" },
  comments: { gap: space.s, paddingVertical: space.m },
  cmHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s, flexWrap: "wrap" },
  cmTitle: { color: color.ink, fontSize: 16, fontWeight: "700" },
  compose: { minHeight: 64, textAlignVertical: "top" },
  cmSub: { flexDirection: "row", alignItems: "center", gap: space.s },
  nickBtn: { flex: 1, minWidth: 0 },
  nickEdit: { gap: 6 },
  nickRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  nickField: { flex: 1, minWidth: 0, paddingVertical: 8 },
  cm: { gap: 2, paddingVertical: 8, borderTopWidth: 1, borderTopColor: color.woodLight },
  who: { flexDirection: "row", alignItems: "center", gap: space.s },
  nick: { color: color.ink, fontSize: 14, fontWeight: "700" },
  me: { color: color.accentText, fontSize: 12, fontWeight: "700", borderWidth: 1, borderColor: color.accent, paddingHorizontal: 4 },
  acts: { flexDirection: "row", gap: space.l, marginTop: 2 },
  foot: { alignItems: "flex-end" },
});
