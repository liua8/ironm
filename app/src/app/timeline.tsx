// 训练时间线（同网页 timelinePage，spec §139）：从新到旧一条竖线串起每一次训练，每次一张卡片配一张图。
// 有打卡照片的配打卡照片（要带登录凭证取，见 lib/authed-image），没有的配这次练得最多的部位的训练照片。
// 每张卡下面"晒一下"，打开这次训练的分享卡（§147、§164 第四期）。
import { useState } from "react";
import { Image, Linking, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { API_BASE } from "@/config";
import { BackLink, Failed, NeedLogin, PanelHead, Sheet, useLoad } from "@/features/record/kit";
import { type Exercise, mainPart, md, REST_WORDS, timelineFacts, timelineRows, type Workout } from "@/features/record/logic";
import { WorkoutShare } from "@/features/share/share";
import { useAuthedImage } from "@/lib/authed-image";
import { LinkButton, Panel, PixelText, Screen, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

type TrainImage = { url: string; author?: string; page?: string };

async function loadAll() {
  const [tr, lib, photos] = await Promise.all([
    api<{ workouts: Workout[] }>("/iron/api/training"),
    api<{ exercises: Exercise[] }>("/iron/api/exercises").catch(() => null),
    api<{ images: Record<string, TrainImage> }>("/iron/api/train-images").catch(() => null),
  ]);
  return { rows: timelineRows(tr.workouts ?? []), lib: lib?.exercises ?? null, imgs: photos?.images ?? {} };
}

export default function Timeline() {
  return (
    <NeedLogin>
      <TimelinePage />
    </NeedLogin>
  );
}

function TimelinePage() {
  const { data, error, reload } = useLoad(loadAll);
  const [share, setShare] = useState<string | null>(null);
  return (
    <Screen>
      <BackLink label="战绩" fallback="/record" />
      <Panel>
        <PanelHead title="训练时间线" right="最近 30 天" />
        {error ? <Failed error={error} retry={reload} /> : !data ? <T muted>正在读取…</T> : !data.rows.length ? <T muted>还没有训练记录。练完打个卡，这里就会一条条排出来。</T> : null}
      </Panel>
      {data?.rows.length ? (
        <View style={s.line}>
          <View style={s.rail} />
          {data.rows.map((x) => (
            <Item key={String(x.id)} x={x} pic={data.imgs[mainPart(data.lib, x)]} onShare={() => setShare(String(x.id))} />
          ))}
        </View>
      ) : null}
      <Sheet visible={share !== null} title="晒一下" onClose={() => setShare(null)}>
        {share ? <WorkoutShare id={share} /> : null}
      </Sheet>
    </Screen>
  );
}

/** 打卡照片：取不到就不画（卡上只留字）。 */
function CheckinPhoto({ id }: { id: string }) {
  const source = useAuthedImage(`/iron/api/workouts/${encodeURIComponent(id)}/photo`);
  if (!source) return null;
  return (
    <View style={s.pic}>
      <Image source={source} style={s.img} resizeMode="cover" accessibilityLabel="打卡照片" />
    </View>
  );
}

function Item({ x, pic, onShare }: { x: Workout; pic?: TrainImage; onShare: () => void }) {
  if (x.rest) {
    return (
      <View style={s.item}>
        <View style={[s.knot, s.knotRest]} />
        <Text style={s.date}>{md(x.day)}</Text>
        <Text style={s.rest}>{`没练（${REST_WORDS[x.rest]}）`}</Text>
      </View>
    );
  }
  const facts = timelineFacts(x);
  const moves = (x.items ?? []).map((it) => it.exercise).join("、");
  return (
    <View style={s.item}>
      <View style={s.knot} />
      <Text style={s.date}>{md(x.day)}</Text>
      <View style={s.card}>
        {x.photo ? (
          <CheckinPhoto id={String(x.id)} />
        ) : pic ? (
          <View style={s.pic}>
            <Image source={{ uri: `${API_BASE}${pic.url}` }} style={s.img} resizeMode="cover" accessibilityIgnoresInvertColors alt="" />
            {pic.author ? (
              <Text style={s.credit} onPress={pic.page ? () => void Linking.openURL(pic.page as string) : undefined} accessibilityRole={pic.page ? "link" : undefined}>
                {`照片：${pic.author}`}
              </Text>
            ) : null}
          </View>
        ) : null}
        <PixelText size={24}>{x.session || "训练"}</PixelText>
        {facts ? <T>{facts}</T> : null}
        {moves ? <Text style={s.moves}>{moves}</Text> : null}
        {x.note ? <T muted>{x.note}</T> : null}
        <LinkButton title="晒一下" onPress={onShare} />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  line: { position: "relative", paddingLeft: 24, gap: space.l },
  rail: { position: "absolute", left: 7, top: 8, bottom: 8, width: 6, backgroundColor: color.wood, borderLeftWidth: 1, borderRightWidth: 1, borderColor: color.woodDark },
  item: { position: "relative", gap: 6 },
  knot: { position: "absolute", left: -24, top: 2, width: 20, height: 20, backgroundColor: color.amber, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark },
  knotRest: { backgroundColor: color.paperLight },
  date: { color: color.ink, fontSize: 15, fontWeight: "700" },
  rest: { alignSelf: "flex-start", color: color.muted, fontSize: 14, backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, paddingHorizontal: space.m, paddingVertical: 6, overflow: "hidden" },
  card: { backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m, gap: 6 },
  pic: { height: 160, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, backgroundColor: "#e9c784", overflow: "hidden" },
  img: { width: "100%", height: "100%" },
  credit: { position: "absolute", right: 0, bottom: 0, color: "#fff", fontSize: 11, backgroundColor: "rgba(0,0,0,0.45)", paddingHorizontal: 6, paddingVertical: 2 },
  moves: { color: color.muted, fontSize: 14, lineHeight: 20 },
});
