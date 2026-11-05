// 还没填自己的模型（spec §167 每个人用自己的模型）：服务端没有默认模型，要用模型的功能回 428。
// - NeedModel：哪个功能报了 no_model，就在那条说明下面多一个"去填模型"，点了到「我」打开"模型和 API"；
// - ModelHint：首页一张可以关掉的提示卡，没填模型的人看到一次；关掉记在这台设备上，填了模型就不再出现。
import { router, useFocusEffect } from "expo-router";
import { useCallback, useState } from "react";
import { StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import { readLocal, writeLocal } from "@/lib/local-store";
import { Button, Note, Panel, T } from "@/ui/pixel";
import { space } from "@/ui/theme";

/** 到「我」并打开"模型和 API"（me.tsx 读 open=model）。 */
export function goFillModel(): void {
  router.navigate({ pathname: "/me", params: { open: "model" } });
}

/**
 * 报了 no_model 时的说明 + "去填模型"。
 * before：在弹出页里时先关掉它再走，不然弹出页会盖在「我」上面。
 */
export function NeedModel({ text, before }: { text: string; before?: () => void }) {
  return (
    <View style={s.need}>
      <Note tone="error">{text}</Note>
      <View style={s.row}>
        <Button
          title="去填模型"
          small
          onPress={() => {
            before?.();
            goFillModel();
          }}
        />
      </View>
    </View>
  );
}

export const HINT_KEY = "iron.hint.model";
export const HINT_TEXT = "IronM 用你自己的模型回答问题、估热量、认器械。先填一个模型（DeepSeek、通义千问、智谱等都可以）。";

/**
 * 首页提示卡：GET /iron/api/my-model 回 {model: null} 才出现；点"以后再说"这台设备上不再出现。
 * 每次回到首页重读一次：刚在「我」里填好模型，回来卡片就没了。读不到（没网）不出现，不吓人。
 */
export function ModelHint() {
  const [show, setShow] = useState(false);
  useFocusEffect(
    useCallback(() => {
      let live = true;
      (async () => {
        if ((await readLocal(HINT_KEY)) === "1") return live && setShow(false);
        const r = await api<{ model: unknown }>("/iron/api/my-model").catch(() => null);
        if (live) setShow(!!r && r.model == null);
      })();
      return () => {
        live = false;
      };
    }, []),
  );
  if (!show) return null;
  return (
    <Panel>
      <T>{HINT_TEXT}</T>
      <View style={s.buttons}>
        <Button title="去填模型" small onPress={goFillModel} />
        <Button
          title="以后再说"
          kind="ghost"
          small
          onPress={() => {
            setShow(false);
            void writeLocal(HINT_KEY, "1");
          }}
        />
      </View>
    </Panel>
  );
}

const s = StyleSheet.create({
  need: { gap: space.s },
  row: { flexDirection: "row" },
  buttons: { flexDirection: "row", flexWrap: "wrap", gap: space.s },
});
