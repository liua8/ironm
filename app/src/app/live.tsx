// 训练中（同网页 livePage，spec §71）：读进行中的训练；没有时说明（6 小时没动自动结束的，写保存了什么），可以开始训练。
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import type { Live, LiveResp } from "@/features/live/logic";
import { Recorder } from "@/features/live/recorder";
import { startLive } from "@/features/live/start";
import { clean } from "@/features/home/train-logic";
import { Button, LinkButton, Note, Panel, PixelText, Screen, T } from "@/ui/pixel";
import { space } from "@/ui/theme";

export default function LivePage() {
  const [data, setData] = useState<LiveResp | null>(null);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const load = useCallback(async () => {
    setErr("");
    try {
      setData(await api<LiveResp>("/iron/api/live"));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没读到训练。");
    }
  }, []);
  // 每次进这页都重读（训练存在服务端，回来接着计）
  useFocusEffect(useCallback(() => { void load(); }, [load]));

  const back = () => (router.canGoBack() ? router.back() : router.replace("/"));
  const start = async () => {
    const e = await startLive({ today_plan: true }, { stay: true });
    if (e) setMsg(e); else void load();
  };

  if (data?.live) {
    const live: Live = data.live;
    return (
      <Screen scroll={false}>
        <Recorder key={live.id} data={{ ...data, live }} onReload={load} />
      </Screen>
    );
  }
  return (
    <Screen>
      <View style={s.bar}>
        <LinkButton title="‹ 返回" onPress={back} />
        <PixelText size={24}>训练</PixelText>
      </View>
      {err ? (
        <Panel>
          <Note tone="error">{err}</Note>
          <Button small kind="ghost" title="重试" onPress={load} />
        </Panel>
      ) : !data ? (
        <Note>正在读…</Note>
      ) : (
        <Panel>
          <T>
            {data.expired ? `上次训练 6 小时没动，已自动结束，保存了完成的组：${clean(data.expired.line)}` : "现在没有进行中的训练。"}
          </T>
          <Button title="开始训练" onPress={start} />
          <Note tone="error">{msg}</Note>
        </Panel>
      )}
    </Screen>
  );
}

const s = StyleSheet.create({
  bar: { flexDirection: "row", alignItems: "center", gap: space.m },
});
