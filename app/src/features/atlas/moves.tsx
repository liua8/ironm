// 图鉴·动作库（同网页 moves / moveCard / exerciseSheet / moveImages）：自由训练入口、搜索、部位和器械筛选、
// 按部位收纳（每组先 4 个，"全部 N 个"展开）、常见动作在前；点开看配图、做法、要点，能直接开始训练。
import { useEffect, useMemo, useState } from "react";
import { Image, Linking, Pressable, StyleSheet, Text, View } from "react-native";

import { Button, Field, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { askCoach, errText, liveNow, loadExercises, startLive, useLoad } from "./data";
import { ALL_EQUIP, ALL_PARTS, coverOf, creditLine, filterMoves, GROUP_SHOW, groupMoves, imgUrl, isGrouped, type MoveFilter, partMark, plain } from "./logic";
import type { Exercise, Img } from "./types";
import { Caption, Card, Cover, Grid, H3, Loading, MarkList, Pills, Sheet, Steps, Tags, ui } from "./ui";

// 离开图鉴再回来，筛选和展开的部位还在（同网页 moveFilter、moveOpen）
const kept: { filter: MoveFilter; open: Set<string> } = { filter: { part: ALL_PARTS, equip: ALL_EQUIP, q: "" }, open: new Set() };

export function MovesSection({ onOpen }: { onOpen: (x: Exercise, note: string) => void }) {
  const { data: lib, error, reload } = useLoad(loadExercises);
  const [filter, setFilterState] = useState<MoveFilter>(kept.filter);
  const [open, setOpen] = useState<Set<string>>(kept.open);
  const setFilter = (next: MoveFilter) => { kept.filter = next; setFilterState(next); };
  const toggle = (part: string) => {
    const next = new Set(open);
    if (!next.delete(part)) next.add(part);
    kept.open = next;
    setOpen(next);
  };
  const items = useMemo(() => (lib ? filterMoves(lib.exercises, filter) : []), [lib, filter]);
  const groups = useMemo(() => (lib && isGrouped(filter) ? groupMoves(lib.parts, items) : null), [lib, filter, items]);

  if (!lib) return <Loading error={error} onRetry={reload} what="动作库" />;
  const card = (x: Exercise) => <MoveCard key={x.id} x={x} onPress={() => onOpen(x, lib.note)} />;
  return (
    <View style={s.wrap}>
      <FreeTrain />
      <Field
        value={filter.q}
        onChangeText={(q) => setFilter({ ...filter, q })}
        placeholder="搜索动作或部位，比如深蹲、肩"
        accessibilityLabel="搜索动作"
        returnKeyType="search"
        style={ui.search}
      />
      <Pills label="部位" options={[ALL_PARTS, ...lib.parts]} value={filter.part} onChange={(part) => setFilter({ ...filter, part })} />
      <Pills label="器械" options={[ALL_EQUIP, ...lib.equipment]} value={filter.equip} onChange={(equip) => setFilter({ ...filter, equip })} />
      <Text style={s.count}>{`${items.length} 个动作`}</Text>
      {!items.length ? (
        <View style={s.empty}>
          <Text style={ui.muted}>没有符合的动作，换个条件试试。</Text>
        </View>
      ) : groups ? (
        groups.map((g) => {
          const all = open.has(g.part);
          return (
            <View key={g.part} style={ui.section}>
              <View style={ui.sectionHead}>
                <Text style={ui.plankTitle}>
                  {g.part}
                  <Text style={ui.small}>{`  ${g.items.length} 个`}</Text>
                </Text>
                {g.items.length > GROUP_SHOW ? (
                  <Pressable accessibilityRole="button" accessibilityState={{ expanded: all }} onPress={() => toggle(g.part)} hitSlop={6}>
                    <Text style={ui.link}>{all ? "收起" : `全部 ${g.items.length} 个 ›`}</Text>
                  </Pressable>
                ) : null}
              </View>
              <Grid>{(all ? g.items : g.items.slice(0, GROUP_SHOW)).map(card)}</Grid>
            </View>
          );
        })
      ) : (
        <Grid>{items.map(card)}</Grid>
      )}
    </View>
  );
}

/** 自由训练：空的开始、不带计划，训练页能加动作（§133）；有进行中的写"继续训练"。 */
function FreeTrain() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [going, setGoing] = useState(false);
  useEffect(() => { liveNow().then(setGoing); }, []);
  return (
    <View style={s.free}>
      <Button
        title={going ? "训练进行中，继续记" : "自由训练"}
        disabled={busy}
        onPress={() => {
          setBusy(true);
          setMsg("");
          startLive({ free: true }).catch((err: unknown) => setMsg(errText(err))).finally(() => setBusy(false));
        }}
      />
      <Note tone="error">{msg}</Note>
    </View>
  );
}

export function MoveCard({ x, onPress }: { x: Exercise; onPress: () => void }) {
  return (
    <Card
      label={`${x.name}，点开看做法`}
      onPress={onPress}
      cover={<Cover uri={coverOf(x)} mark={partMark(x.part)} style={s.cover} contain />}
      badge={x.level}
      title={x.name}
      sub={`${x.part} · ${x.equipment.slice(0, 2).join("、")}`}
    />
  );
}

/** 动作配图：动图单张放，起止两张并排；下面署名，点了看原图页。 */
export function MoveImages({ images }: { images: Img[] }) {
  const im = images[0];
  if (!im) return null;
  const page = im.page || im.author_url || im.license_url;
  return (
    <View style={s.figure}>
      <View style={s.frames}>
        {images.map((x, i) => (
          <Image
            key={x.url}
            source={{ uri: imgUrl(x.url) }}
            style={[s.frame, images.length === 1 && s.frameOne]}
            resizeMode="contain"
            accessibilityLabel={x.made ? "动作演示" : i ? "动作结束" : "动作开始"}
          />
        ))}
      </View>
      <Text
        style={[s.credit, page ? s.creditLink : null]}
        onPress={page ? () => { Linking.openURL(page).catch(() => {}); } : undefined}
        accessibilityRole={page ? "link" : undefined}
      >
        {creditLine(im)}
      </Text>
    </View>
  );
}

/** 动作详情。 */
export function ExerciseSheet({ x, note, onClose }: { x: Exercise; note: string; onClose: () => void }) {
  const [going, setGoing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => { liveNow().then(setGoing); }, []);
  const start = () => {
    setBusy(true);
    setMsg("");
    startLive({ exercises: [x.name] })
      .then(onClose)
      .catch((err: unknown) => setMsg(errText(err)))
      .finally(() => setBusy(false));
  };
  const ask = (q: string) => { onClose(); askCoach(q); };
  return (
    <Sheet title={x.name} onClose={onClose}>
      {x.gif ? (
        <MoveImages images={[x.gif]} />
      ) : x.images?.length ? (
        <MoveImages images={x.images} />
      ) : (
        <View style={s.noPic}>
          <Text style={s.noPicMark}>{partMark(x.part)}</Text>
          <Caption>示范图还在补充，先看下面的做法和要点</Caption>
        </View>
      )}
      <Tags items={[x.part, ...x.equipment, x.level]} />
      <Text style={ui.lede}>{`主要练：${x.muscles}`}</Text>
      <H3>怎么做</H3>
      <Steps items={x.steps.map(plain)} />
      <H3>要点</H3>
      <MarkList items={x.cues.map(plain)} tone="ok" />
      <H3>常见错误</H3>
      <MarkList items={x.mistakes.map(plain)} tone="bad" />
      <H3>替代动作</H3>
      <View style={s.swap}>
        <View style={s.swapCell}>
          <Text style={s.swapHead}>更容易</Text>
          <Text style={ui.body}>{plain(x.easier)}</Text>
        </View>
        <View style={s.swapCell}>
          <Text style={s.swapHead}>更难</Text>
          <Text style={ui.body}>{plain(x.harder)}</Text>
        </View>
      </View>
      <View style={ui.callout}>
        <Text style={s.alert}>!</Text>
        <Text style={ui.calloutText}>
          <Text style={s.bold}>什么情况先别做：</Text>
          {plain(x.avoid)}
        </Text>
      </View>
      <Button title={going ? "继续训练" : "开始训练"} onPress={start} disabled={busy} />
      <Note tone="error">{msg}</Note>
      <View style={ui.btnRow}>
        <View style={s.half}>
          <Button kind="ghost" small title="没看懂？讲简单点" onPress={() => ask(`${x.name}我没看懂，请用大白话、打个比方再给我讲讲怎么做，最容易做错的地方是什么`)} />
        </View>
        <View style={s.half}>
          <Button kind="ghost" small title="换个动作" onPress={() => ask(`${x.name}有什么替代动作？按我的器械和身体情况选`)} />
        </View>
      </View>
      <Caption>{note}</Caption>
    </Sheet>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.m },
  free: { gap: 4 },
  count: { color: color.paperLight, fontSize: 14, fontWeight: "600", textShadowColor: color.woodDark, textShadowOffset: { width: 1, height: 1 }, textShadowRadius: 0 },
  empty: { backgroundColor: color.paper, borderWidth: 3, borderColor: color.wood, padding: space.l, alignItems: "center" },
  cover: { width: "100%", aspectRatio: 4 / 3 },
  figure: { gap: 4 },
  frames: { flexDirection: "row", gap: 6 },
  frame: { flex: 1, aspectRatio: 1, backgroundColor: "#fff", borderWidth: 3, borderColor: color.wood },
  frameOne: { aspectRatio: 4 / 3 },
  credit: { color: color.muted, fontSize: 12, lineHeight: 17 },
  creditLink: { textDecorationLine: "underline" },
  noPic: { alignItems: "center", gap: 6, paddingVertical: space.l, backgroundColor: "#e9c784", borderWidth: 3, borderColor: color.wood },
  noPicMark: { fontSize: 36, fontWeight: "800", color: color.woodDark },
  swap: { flexDirection: "row", gap: space.s },
  swapCell: { flex: 1, gap: 2, backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.woodLight, padding: space.s },
  swapHead: { color: color.woodDark, fontSize: 14, fontWeight: "700" },
  alert: { color: color.heat, fontSize: 15, fontWeight: "800", lineHeight: 21 },
  bold: { fontWeight: "700" },
  half: { flexGrow: 1, flexBasis: 140 },
});
