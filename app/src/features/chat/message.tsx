// 一条消息（同网页版 msgView）：提问是右边的气泡；IronM 的回答带头像，有过程、正文、提醒、预览卡片、依据与来源、有用/没用。
import { memo, useState } from "react";
import { ActivityIndicator, Image, Pressable, StyleSheet, Text, View } from "react-native";

import { goFillModel } from "@/features/me/need-model";
import { Button } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { PreviewCard } from "./card";
import { Mascot } from "./mascot";
import { type CoachMsg, type ChatMsg, progressHead } from "./model";
import { cleanText, paragraphs, sessionTime } from "./text";

export const Message = memo(function Message({ msg, onRate }: { msg: ChatMsg; onRate: (key: string, v: 1 | -1) => void }) {
  if (msg.role === "user") {
    return (
      <View style={s.userRow}>
        <View style={s.user}>
          {msg.photos?.length ? (
            <View style={s.userPhotos}>
              {msg.photos.map((uri, i) => <Image key={i} source={{ uri }} style={s.userPhoto} accessibilityLabel="随这一问发的照片" />)}
            </View>
          ) : null}
          <Text style={s.userText} selectable>{msg.text}</Text>
          {msg.at ? <Text style={s.userTime}>{sessionTime(msg.at)}</Text> : null}
        </View>
      </View>
    );
  }
  return <CoachBubble msg={msg} onRate={onRate} />;
});

/** 服务端"没填自己的模型"那句回答的开头（ironm_agent/plugin.py NO_MODEL_CHAT）。 */
export const NO_MODEL_LEAD = "先在「我 → 模型和 API」填你自己的模型";

function CoachBubble({ msg, onRate }: { msg: CoachMsg; onRate: (key: string, v: 1 | -1) => void }) {
  const [open, setOpen] = useState(false);
  const [srcOpen, setSrcOpen] = useState(false);
  const running = !msg.done;
  const head = progressHead(msg);
  const showList = open || (running && !msg.text);
  const text = cleanText(msg.text, running);
  return (
    <View style={s.coachRow}>
      <View style={s.avatar}>
        <Mascot size={30} />
      </View>
      <View style={s.coach}>
        {msg.steps.length || running ? (
          <View style={s.prog}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ expanded: showList }}
              disabled={!msg.steps.length}
              onPress={() => setOpen(!showList)}
              style={s.progHead}
              hitSlop={6}
            >
              {running ? <ActivityIndicator size="small" color={color.accent} /> : <Text style={s.okDot}>✓</Text>}
              <Text style={s.progText}>
                {head}
                {!running && msg.steps.length ? <Text style={s.progMore}>{showList ? " · 收起" : " · 查看过程"}</Text> : null}
              </Text>
            </Pressable>
            {showList && msg.steps.length ? (
              <View style={s.progList}>
                {msg.steps.map((x) => (
                  <View key={x.id} style={s.step}>
                    <View style={s.stepWho}>
                      {x.done ? <Text style={s.okDot}>✓</Text> : <ActivityIndicator size="small" color={color.accent} />}
                      <Text style={s.stepName}>{x.id === "agent" ? "IronM" : x.name}</Text>
                    </View>
                    {x.task ? <Text style={s.muted}>{cleanText(x.task)}</Text> : null}
                    {x.done && x.result && !running ? <Text style={s.stepRes}>{cleanText(x.result)}</Text> : null}
                  </View>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        {text ? <Answer text={text} /> : running ? <Text style={s.muted} accessibilityLabel="正在回答">• • •</Text> : null}
        {/* 没填自己的模型时服务端回这一句（§167）：下面给"去填模型"，点了到「我」打开设置 */}
        {msg.done && msg.text.startsWith(NO_MODEL_LEAD) ? (
          <View style={s.fill}>
            <Button title="去填模型" small onPress={goFillModel} />
          </View>
        ) : null}

        {msg.notices.map((t, i) => (
          <Text key={i} style={s.note}>{cleanText(t)}</Text>
        ))}
        {msg.cards.map((c) => (
          <PreviewCard key={c.id} card={c} />
        ))}
        {msg.error ? <Text style={s.note}>{msg.error}</Text> : null}

        {msg.sources ? (
          <View style={s.sources}>
            <Pressable accessibilityRole="button" accessibilityState={{ expanded: srcOpen }} onPress={() => setSrcOpen(!srcOpen)} hitSlop={6}>
              <Text style={s.srcHead}>{srcOpen ? "▾" : "▸"} 依据与来源</Text>
            </Pressable>
            {srcOpen ? <Text style={s.srcText} selectable>{cleanText(msg.sources)}</Text> : null}
          </View>
        ) : null}

        {msg.done && msg.id && msg.text ? (
          <View style={s.rate}>
            <RateButton on={msg.rating === 1} label="👍 有用" onPress={() => onRate(msg.key, 1)} />
            <RateButton on={msg.rating === -1} label="👎 没用" onPress={() => onRate(msg.key, -1)} />
          </View>
        ) : null}
        {msg.done && msg.at ? <Text style={s.time}>{sessionTime(msg.at)}</Text> : null}
      </View>
    </View>
  );
}

function RateButton({ on, label, onPress }: { on: boolean; label: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityState={{ selected: on }} onPress={onPress} style={[s.rateBtn, on && s.rateOn]} hitSlop={4}>
      <Text style={[s.rateText, on && s.rateTextOn]}>{label}</Text>
    </Pressable>
  );
}

/** 回答正文：空行分段，列表一行一条，**加粗**照样加粗。 */
function Answer({ text }: { text: string }) {
  return (
    <View style={s.answer}>
      {paragraphs(text).map((p, i) => (
        <View key={i} style={s.para}>
          {p.map((line, k) =>
            line.kind === "text" || line.kind === "head" ? (
              <Text key={k} style={[s.p, line.kind === "head" && s.b]} selectable>
                {line.spans.map((sp, j) => (sp.bold ? <Text key={j} style={s.b}>{sp.text}</Text> : sp.text))}
              </Text>
            ) : (
              <View key={k} style={s.li}>
                <Text style={[s.p, s.mark]}>{line.mark}</Text>
                <Text style={[s.p, s.liText]} selectable>
                  {line.spans.map((sp, j) => (sp.bold ? <Text key={j} style={s.b}>{sp.text}</Text> : sp.text))}
                </Text>
              </View>
            ),
          )}
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  userRow: { flexDirection: "row", justifyContent: "flex-end" },
  user: { maxWidth: "85%", backgroundColor: color.fire, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, paddingHorizontal: space.m, paddingVertical: 10, gap: 4 },
  userText: { color: color.accentInk, fontSize: 15, lineHeight: 22 },
  userPhotos: { flexDirection: "row", flexWrap: "wrap", gap: space.xs },
  userPhoto: { width: 96, height: 96, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark, backgroundColor: color.paper },
  userTime: { color: color.accentInk, opacity: 0.75, fontSize: 11, alignSelf: "flex-end" },
  coachRow: { flexDirection: "row", gap: space.s, alignItems: "flex-start" },
  avatar: { paddingTop: 2 },
  coach: { flex: 1, minWidth: 0, backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: space.m, gap: 10 },
  prog: { gap: space.s },
  progHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  progText: { color: color.muted, fontSize: 13, flexShrink: 1 },
  progMore: { color: color.accentText, fontWeight: "600" },
  okDot: { color: color.accentText, fontSize: 13, fontWeight: "700" },
  progList: { borderLeftWidth: 1, borderLeftColor: color.woodLight, paddingLeft: space.m, gap: space.s },
  step: { gap: 2 },
  stepWho: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepName: { color: color.ink, fontSize: 13, fontWeight: "600" },
  stepRes: { color: color.ink, fontSize: 13, lineHeight: 19, backgroundColor: color.paperLight, padding: space.s, marginTop: 4 },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
  answer: { gap: 10 },
  para: { gap: 4 },
  p: { color: color.ink, fontSize: 15, lineHeight: 25 },
  b: { fontWeight: "700" },
  li: { flexDirection: "row", gap: 6 },
  mark: { minWidth: 14, color: color.accentText, fontWeight: "700" },
  liText: { flex: 1 },
  note: { color: color.heat, backgroundColor: color.heatSoft, fontSize: 13, lineHeight: 19, padding: space.s },
  sources: { gap: 6 },
  fill: { flexDirection: "row" },
  srcHead: { color: color.accentText, fontSize: 13, fontWeight: "600" },
  srcText: { color: color.muted, fontSize: 13, lineHeight: 20, backgroundColor: color.paperLight, padding: space.s },
  rate: { flexDirection: "row", gap: 6 },
  rateBtn: { borderWidth: 1, borderColor: color.woodLight, backgroundColor: color.paperLight, paddingHorizontal: 10, paddingVertical: 5 },
  rateOn: { backgroundColor: color.goodSoft, borderColor: color.accent },
  rateText: { color: color.muted, fontSize: 12 },
  rateTextOn: { color: color.accentText, fontWeight: "600" },
  time: { color: color.muted, fontSize: 11, alignSelf: "flex-end" },
});
