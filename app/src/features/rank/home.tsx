// 排行榜首页（同网页 rankHome / rankRing，spec §161）：搜索框和结果、热搜、六个榜左右滑着看（一张一个榜，
// 露出下一张的边），每个榜点"全部"进榜单页，条目点进去打分、看评论。
import { router } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { type LayoutChangeEvent, type NativeScrollEvent, type NativeSyntheticEvent, Pressable, ScrollView, type ScrollViewInstance, StyleSheet, Text, useWindowDimensions, View } from "react-native";

import { api } from "@/api/client";
import { errText, useLoad } from "@/features/atlas/data";
import { GrassNote, Loading, ui } from "@/features/atlas/ui";
import { Field } from "@/ui/pixel";
import { color, font, space } from "@/ui/theme";

import { boardHref, itemHref } from "./nav";
import { cardRows, flagKind, peopleLine, rowNo, rowTag, scoreText, tierNames } from "./logic";
import type { BoardCard, Hit, RankHome } from "./types";
import { Box, RankLabel, RankNo, RankPic, TierTag, Trend } from "./ui";

export function RankHomeView() {
  const { data: d, error, reload } = useLoad(() => api<RankHome>("/iron/api/rank"));
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ q: string; items: Hit[] | null; error: string }>({ q: "", items: null, error: "" });
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  // 边打字边搜时不记热搜；按回车、点热搜才记（同网页 record）
  const search = (text: string, record: boolean) => {
    const t = text.trim();
    const mine = ++seq.current;
    if (!t) { setHits({ q: "", items: null, error: "" }); return; }
    api<{ items: Hit[] }>(`/iron/api/rank/search?q=${encodeURIComponent(t)}&record=${record}`)
      .then((r) => { if (mine === seq.current) setHits({ q: t, items: r.items ?? [], error: "" }); })
      .catch((err: unknown) => { if (mine === seq.current) setHits({ q: t, items: null, error: errText(err) }); });
  };
  const type = (text: string) => {
    setQ(text);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => search(text, false), 250);
  };
  const submit = (text: string) => {
    setQ(text);
    if (timer.current) clearTimeout(timer.current);
    search(text, true);
  };

  if (!d) return <Loading error={error} onRetry={reload} what="排行榜" />;
  const names = tierNames(d.tiers);
  const searching = Boolean(q.trim());
  return (
    <View style={s.wrap}>
      <Field
        value={q}
        onChangeText={type}
        onSubmitEditing={() => submit(q)}
        placeholder="搜动作、训练计划、健身餐、补剂、器材…"
        accessibilityLabel="搜榜单里的条目"
        returnKeyType="search"
        autoCorrect={false}
        style={ui.search}
      />
      {d.hot.length ? (
        <View style={s.hot}>
          <Text style={s.hotLabel}>热搜</Text>
          {d.hot.map((x, i) => (
            <Pressable key={x.term} accessibilityRole="button" onPress={() => submit(x.term)} style={s.hotChip}>
              <Text style={s.hotText}>
                <Text style={[s.hotNo, i < 4 && s.hotNoHi]}>{`${i + 1} `}</Text>
                {x.term}
                {x.flag ? <Text style={[s.flag, s[`flag_${flagKind(x.flag) || "hot"}`]]}>{` ${x.flag}`}</Text> : null}
              </Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {searching ? (
        <Box>
          {hits.error ? (
            <Text style={ui.error}>{hits.error}</Text>
          ) : !hits.items || hits.q !== q.trim() ? (
            <Text style={ui.muted}>正在搜…</Text>
          ) : hits.items.length ? (
            hits.items.map((x) => (
              <Pressable key={`${x.board}-${x.key}`} accessibilityRole="link" onPress={() => router.push(itemHref(x.board, x.key))} style={s.hit}>
                <Text style={s.hitName} numberOfLines={1}>
                  {x.name}
                </Text>
                {x.tier ? <TierTag tier={x.tier} text={names[x.tier] ?? x.tier} /> : null}
                <Text style={s.hitBoard}>{x.board_name}</Text>
              </Pressable>
            ))
          ) : (
            <Text style={ui.muted}>{`没有找到「${hits.q}」。可以进对应的榜单，点右上角「添加」。`}</Text>
          )}
        </Box>
      ) : (
        <Ring boards={d.boards} names={names} />
      )}
      <GrassNote>用户评分，不代表平台观点。每人一票（夯 5 分 … 拉 1 分），不到 3 票的在待评。</GrassNote>
    </View>
  );
}

const GAP = 10;

/** 六个榜：横着滑，一次停在一个榜上；下面一排点，点了转到那个榜。 */
function Ring({ boards, names }: { boards: BoardCard[]; names: Record<string, string> }) {
  const [measured, setW] = useState(0);
  const { width: win } = useWindowDimensions();
  const w = measured || Math.min(win, 720) - 32; // 量到之前先按屏幕宽估（页面左右各留 16）
  const [cur, setCur] = useState(0);
  const ref = useRef<ScrollViewInstance>(null);
  const cardW = Math.max(0, Math.round(w * 0.9));
  const onLayout = (e: LayoutChangeEvent) => setW(e.nativeEvent.layout.width);
  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    if (!cardW) return;
    const i = Math.round(e.nativeEvent.contentOffset.x / (cardW + GAP));
    setCur(Math.max(0, Math.min(boards.length - 1, i)));
  };
  const go = (i: number) => {
    setCur(i);
    ref.current?.scrollTo({ x: i * (cardW + GAP), animated: true });
  };
  return (
    <View onLayout={onLayout} style={s.ringWrap}>
      {cardW ? (
        <ScrollView
          ref={ref}
          horizontal
          showsHorizontalScrollIndicator={false}
          snapToInterval={cardW + GAP}
          snapToAlignment="start"
          decelerationRate="fast"
          disableIntervalMomentum
          onScroll={onScroll}
          scrollEventThrottle={32}
          accessibilityLabel="各类榜单，左右滑动切换"
          contentContainerStyle={{ gap: GAP, paddingRight: w - cardW }}
        >
          {boards.map((b) => (
            <BoardCardView key={b.board} b={b} names={names} width={cardW} />
          ))}
        </ScrollView>
      ) : null}
      <View style={s.ctl}>
        <View style={s.dots}>
          {boards.map((b, i) => (
            <Pressable key={b.board} accessibilityRole="button" accessibilityLabel={b.name} accessibilityState={{ selected: i === cur }} onPress={() => go(i)} hitSlop={6} style={[s.dot, i === cur && s.dotOn]} />
          ))}
        </View>
        <Text style={s.ctlText}>左右滑，一次换一个榜</Text>
      </View>
    </View>
  );
}

function BoardCardView({ b, names, width }: { b: BoardCard; names: Record<string, string>; width: number }) {
  const rows = cardRows(b);
  const first = b.top[0];
  return (
    <View style={[s.card, { width }]} accessibilityLabel={b.name}>
      <View style={s.cardHead}>
        <View style={s.cardTitle}>
          <Text style={s.cardName}>{b.name}</Text>
          {peopleLine(b.people) ? <Text style={ui.muted}>{peopleLine(b.people)}</Text> : null}
        </View>
        <Pressable accessibilityRole="link" accessibilityLabel={`${b.name}全部`} onPress={() => router.push(boardHref(b.board))} hitSlop={6}>
          <Text style={ui.link}>全部 ›</Text>
        </Pressable>
      </View>
      {rows.map((x) => {
        const tag = rowTag(b.people, x, names);
        return (
          <View key={x.key}>
            <Pressable accessibilityRole="link" onPress={() => router.push(itemHref(b.board, x.key))} style={({ pressed }) => [s.row, pressed && s.pressed]}>
              <RankNo text={rowNo(b.people, x.rank)} />
              <RankPic x={x} />
              <RankLabel x={x} />
              <Trend t={x.trend} />
              {tag ? <TierTag tier={tag.tier} text={tag.text} /> : null}
              <Text style={s.sc}>{x.rank ? scoreText(x) : ""}</Text>
            </Pressable>
            {x === first && x.top_comment ? (
              <Text style={s.quote} numberOfLines={2}>
                {`“${x.top_comment.text}”`}
                <Text style={s.likes}>{`  赞 ${x.top_comment.likes}`}</Text>
              </Text>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  hot: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 6 },
  hotLabel: { fontFamily: font.pixel, fontSize: 12, color: color.accentInk, backgroundColor: color.heat, paddingHorizontal: 6, paddingVertical: 3 },
  hotChip: { backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: 8, paddingVertical: 4 },
  hotText: { color: color.ink, fontSize: 14 },
  hotNo: { color: color.muted, fontWeight: "700" },
  hotNoHi: { color: color.heat },
  flag: { fontSize: 12, fontWeight: "700" },
  flag_hot: { color: color.heat },
  flag_new: { color: color.accentText },
  flag_up: { color: color.wood },
  hit: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8, borderBottomWidth: 2, borderBottomColor: color.woodLight },
  hitName: { flex: 1, color: color.ink, fontSize: 15, fontWeight: "600" },
  hitBoard: { color: color.muted, fontSize: 12 },
  ringWrap: { gap: space.s },
  card: { backgroundColor: color.paper, borderWidth: 4, borderColor: color.wood, padding: space.m, gap: 2 },
  cardHead: { flexDirection: "row", alignItems: "center", gap: space.s, marginBottom: 4 },
  cardTitle: { flex: 1, minWidth: 0 },
  cardName: { color: color.ink, fontSize: 18, fontWeight: "800" },
  row: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6 },
  pressed: { opacity: 0.7 },
  sc: { minWidth: 26, textAlign: "right", color: color.ink, fontSize: 14, fontWeight: "700" },
  quote: { color: color.muted, fontSize: 13, lineHeight: 19, paddingLeft: 30, paddingBottom: 4 },
  likes: { color: color.wood, fontWeight: "700" },
  ctl: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: space.s },
  dots: { flexDirection: "row", gap: 8 },
  dot: { width: 12, height: 12, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood },
  dotOn: { backgroundColor: color.amber, borderColor: color.woodDark },
  ctlText: { color: color.paperLight, fontSize: 12, textShadowColor: color.woodDark, textShadowOffset: { width: 1, height: 1 }, textShadowRadius: 0 },
});
