// 隐私政策、用户协议（同网页 legalPage，spec §180）：不登录也能看（登录页注册时点开、「我」里也能进）。
import { router, useLocalSearchParams } from "expo-router";
import { StyleSheet, Text, View } from "react-native";

import { LEGAL, LEGAL_DATE } from "@/features/me/legal";
import { LinkButton, Screen } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

export default function Legal() {
  const { kind } = useLocalSearchParams<{ kind?: string }>();
  const [title, parts] = LEGAL[kind === "terms" ? "terms" : "privacy"];
  return (
    <Screen>
      <LinkButton title="‹ 返回" onPress={() => (router.canGoBack() ? router.back() : router.replace("/"))} />
      <Text style={s.h1}>{title}</Text>
      <Text style={s.draft}>{`草稿（${LEGAL_DATE}），正式对外前请负责人审核。`}</Text>
      {parts.map(([hd, text]) => (
        <View key={hd} style={s.part}>
          <Text style={s.h2}>{hd}</Text>
          <Text style={s.p}>{text}</Text>
        </View>
      ))}
      <Text style={s.muted}>{`更新日期：${LEGAL_DATE}`}</Text>
    </Screen>
  );
}

const s = StyleSheet.create({
  h1: { color: color.ink, fontSize: 26, fontWeight: "800" },
  draft: { color: color.ink, fontSize: 13, backgroundColor: color.accentSoft, borderRadius: 10, padding: space.s },
  part: { gap: 4 },
  h2: { color: color.ink, fontSize: 16, fontWeight: "700" },
  p: { color: color.ink, fontSize: 15, lineHeight: 25 },
  muted: { color: color.muted, fontSize: 13 },
});
