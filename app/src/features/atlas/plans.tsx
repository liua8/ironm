// 图鉴·方案库（同网页 plansAtlas / planLibSheet，spec §161）：适合谁、目标、每周几天、在哪练；点开看每次练什么。
// 打分在排行榜的训练计划榜，这里只放资料。
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { color } from "@/ui/theme";

import { useLoad } from "./data";
import { planFor, planItemLine, planTags, plain } from "./logic";
import type { PlanLib } from "./types";
import { Bullets, Caption, Chip, H3, Loading, Sheet, Tags, ui } from "./ui";

export function PlansSection({ onOpen }: { onOpen: (x: PlanLib) => void }) {
  const { data, error, reload } = useLoad(() => api<{ plans: PlanLib[] }>("/iron/api/plan-library"));
  if (!data) return <Loading error={error} onRetry={reload} what="方案库" />;
  return (
    <View style={s.wrap}>
      {data.plans.map((x) => (
        <Pressable
          key={x.id}
          accessibilityRole="button"
          accessibilityLabel={`${x.name}，点开看每次练什么`}
          onPress={() => onOpen(x)}
          style={({ pressed }) => [s.card, pressed && s.pressed]}
        >
          <Text style={s.name}>{x.name}</Text>
          <Text style={ui.muted}>{plain(x.blurb)}</Text>
          {x.blogger ? (
            <View style={s.chip}>
              <Chip>{`博主方案 · ${x.blogger}`}</Chip>
            </View>
          ) : null}
        </Pressable>
      ))}
      <View style={s.note}>
        <Caption>方案库由 IronM 整理，排计划时按你的器械和伤病换成合适的动作。想看大家怎么评，去首页最上面的排行榜。</Caption>
      </View>
    </View>
  );
}

export function PlanSheet({ x, onClose }: { x: PlanLib; onClose: () => void }) {
  return (
    <Sheet title={x.name} onClose={onClose}>
      <Tags items={planTags(x)} />
      <Text style={ui.lede}>{planFor(x)}</Text>
      {x.why ? <Text style={ui.body}>{plain(x.why)}</Text> : null}
      {x.sessions.map((sn, i) => (
        <View key={`${sn.name}-${i}`} style={s.session}>
          <H3>{sn.name}</H3>
          <Bullets items={sn.items.map((it) => plain(planItemLine(it)))} />
        </View>
      ))}
      {x.intensity ? (
        <View style={s.session}>
          <H3>强度</H3>
          <Text style={ui.body}>{plain(x.intensity)}</Text>
        </View>
      ) : null}
      {x.progress ? (
        <View style={s.session}>
          <H3>怎么加量</H3>
          <Text style={ui.body}>{plain(x.progress)}</Text>
        </View>
      ) : null}
      <Caption>排计划时 IronM 会按你的器械、伤病和时间调整动作；想用这个方案，跟 IronM 说一声。</Caption>
    </Sheet>
  );
}

const s = StyleSheet.create({
  wrap: { gap: 10 },
  card: { gap: 4, backgroundColor: color.paper, borderWidth: 4, borderColor: color.wood, padding: 14 },
  pressed: { opacity: 0.75 },
  name: { color: color.ink, fontSize: 17, fontWeight: "700" },
  chip: { flexDirection: "row", marginTop: 2 },
  note: { alignSelf: "flex-start", backgroundColor: color.paperLight, borderWidth: 2, borderColor: color.wood, paddingHorizontal: 10, paddingVertical: 6 },
  session: { gap: 4 },
});
