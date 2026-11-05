// 榜单页（同网页 rankBoard / rankAdd，spec §161）：完整排名、动作榜按部位筛、三种排法、待评、添加。
// 整个榜没人评时只在最上面说"还没人评过，点进去打第一个分"，不写"0 人参与""待评 N 个""没人评"。
import { router } from "expo-router";
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { errText, useLoad } from "@/features/atlas/data";
import { Caption, GrassNote, Loading, Pills, ui } from "@/features/atlas/ui";
import { Button, Field, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { boardCaption, emptyText, MOVE_PARTS, pendingTitle, type SortKey, shortOf, sortOptions, sortRows, tierNames, waitingOf } from "./logic";
import { goBack, itemHref } from "./nav";
import type { Board } from "./types";
import { Box, RankBar, RankLabel, RankLine, RankPic, rk } from "./ui";

let keptParts: string[] | null = null; // 按部位看时服务端不给部位清单，用上次看全部时的

const ALL = "全部";

export function RankBoardView({ board, part }: { board: string; part: string }) {
  const { data: d, error, reload } = useLoad(
    () => api<Board>(`/iron/api/rank/board?board=${encodeURIComponent(board)}${part ? `&part=${encodeURIComponent(part)}` : ""}`),
    [board, part],
  );
  const [sort, setSort] = useState<SortKey>("综合");
  const [adding, setAdding] = useState(false);
  const back = () => goBack("/rank");
  if (!d) {
    return (
      <View style={s.wrap}>
        <RankBar back="排行榜" onBack={back} title="榜单" />
        <Loading error={error} onRetry={reload} what="榜单" />
      </View>
    );
  }
  if (d.parts.length) keptParts = d.parts;
  const names = tierNames(d.tiers);
  const rows = sortRows(d.items, sort);
  const waiting = waitingOf(d.items);
  const pending = pendingTitle(d.people, waiting.length);
  const empty = emptyText(d.people, sort);
  return (
    <View style={s.wrap}>
      <RankBar
        back="排行榜"
        onBack={back}
        title={d.name}
        right={d.can_add ? <Button title={adding ? "收起" : "＋ 添加"} kind="ghost" small onPress={() => setAdding((v) => !v)} /> : null}
      />
      {d.can_add && adding ? <RankAdd d={d} /> : null}
      {board === "move" ? (
        <Pills
          label="部位"
          options={[ALL, ...(keptParts ?? MOVE_PARTS)]}
          value={part || ALL}
          onChange={(p) => router.setParams({ part: p === ALL ? "" : p })}
        />
      ) : null}
      <GrassNote>{boardCaption(d, part)}</GrassNote>
      {d.people ? <Pills label="排法" options={sortOptions(d)} value={sort} onChange={setSort} /> : null}
      {rows.length ? (
        <Box>
          {rows.map((x) => (
            <RankLine key={x.key} x={x} names={names} onPress={() => router.push(itemHref(board, x.key))} />
          ))}
        </Box>
      ) : empty ? (
        <Box>
          <Text style={rk.none}>{empty}</Text>
        </Box>
      ) : null}
      {waiting.length ? (
        <Box>
          {pending ? <Text style={s.pendingTitle}>{pending}</Text> : null}
          {waiting.map((x) => (
            <Pressable key={x.key} accessibilityRole="link" onPress={() => router.push(itemHref(board, x.key))} style={({ pressed }) => [s.wait, pressed && s.pressed]}>
              <RankPic x={x} small />
              <RankLabel x={x} />
              {shortOf(x, d.min_votes) ? <Text style={ui.muted}>{shortOf(x, d.min_votes)}</Text> : null}
            </Pressable>
          ))}
        </Box>
      ) : null}
    </View>
  );
}

/** 添加（同网页 rankAdd）：同名的直接用已有的；有相似的先问"是不是这个"，都不是再新建；加好后进详情投票。 */
function RankAdd({ d }: { d: Board }) {
  const [name, setName] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [similar, setSimilar] = useState<{ key: string; name: string }[] | null>(null);
  const add = (force: boolean) => {
    setMsg("");
    setSimilar(null);
    setBusy(true);
    api<{ key: string | null; similar: { key: string; name: string }[] }>("/iron/api/rank/items", { method: "POST", json: { board: d.board, name, force } })
      .then((r) => {
        if (r.key) router.push(itemHref(d.board, r.key));
        else setSimilar(r.similar ?? []);
      })
      .catch((err: unknown) => setMsg(errText(err)))
      .finally(() => setBusy(false));
  };
  return (
    <Box style={s.add}>
      <View style={s.addRow}>
        <Field
          value={name}
          onChangeText={setName}
          maxLength={30}
          placeholder={`加到${d.name}，写通用名字，不写品牌`}
          accessibilityLabel="添加条目"
          onSubmitEditing={() => add(false)}
          style={s.addField}
        />
        <Button title="添加" small disabled={busy || !name.trim()} onPress={() => add(false)} />
      </View>
      <Caption>每人每天最多加 10 个。</Caption>
      <Note tone="error">{msg}</Note>
      {similar ? (
        <View style={s.similar}>
          <Caption>榜上已经有相似的，是不是这个？</Caption>
          <View style={s.asks}>
            {similar.map((x) => (
              <Pressable key={x.key} accessibilityRole="link" onPress={() => router.push(itemHref(d.board, x.key))} style={s.ask}>
                <Text style={s.askText}>{x.name}</Text>
              </Pressable>
            ))}
          </View>
          <Button title={`都不是，新建「${name.trim()}」`} kind="ghost" small disabled={busy} onPress={() => add(true)} />
        </View>
      ) : null}
    </Box>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  pendingTitle: { color: color.ink, fontSize: 15, fontWeight: "700", marginBottom: 4 },
  wait: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, borderBottomWidth: 2, borderBottomColor: color.woodLight },
  pressed: { opacity: 0.7 },
  add: { gap: space.s },
  addRow: { flexDirection: "row", alignItems: "center", gap: space.s },
  addField: { flex: 1, minWidth: 0, paddingVertical: 8 },
  similar: { gap: space.s },
  asks: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  ask: { borderWidth: 2, borderColor: color.wood, backgroundColor: color.paperLight, paddingHorizontal: 10, paddingVertical: 4 },
  askText: { color: color.woodDark, fontSize: 14, fontWeight: "600" },
});
