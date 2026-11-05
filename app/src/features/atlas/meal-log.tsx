// 记成哪一餐（同网页 kindSheet）：一排餐次，今天已记过这一餐时提示会替换，点"记下"。
import { useEffect, useState } from "react";
import { View } from "react-native";

import { api } from "@/api/client";
import { Button, Note } from "@/ui/pixel";

import { errText } from "./data";
import { MEAL_KINDS, mealKindNow, replaceHint } from "./logic";
import type { MealDay } from "./types";
import { Caption, Pills } from "./ui";

export function KindPick({ onSave, done }: { onSave: (kind: string) => Promise<string>; done?: () => void }) {
  const [kind, setKind] = useState(mealKindNow());
  const [day, setDay] = useState<MealDay | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "error" | "ok"; text: string } | null>(null);
  useEffect(() => {
    api<MealDay>("/iron/api/meals").then(setDay).catch(() => setDay(null));
  }, []);
  const hint = replaceHint(day?.meals, kind);
  return (
    <View style={{ gap: 8 }}>
      <Caption>哪一餐</Caption>
      <Pills label="哪一餐" options={MEAL_KINDS} value={kind} onChange={setKind} />
      {hint ? <Caption>{hint}</Caption> : null}
      <Button
        title="记下"
        disabled={busy}
        onPress={() => {
          setBusy(true);
          setMsg(null);
          onSave(kind)
            .then((text) => {
              setMsg({ tone: "ok", text });
              api<MealDay>("/iron/api/meals").then(setDay).catch(() => {});
              done?.();
            })
            .catch((err: unknown) => setMsg({ tone: "error", text: errText(err) }))
            .finally(() => setBusy(false));
        }}
      />
      {msg ? <Note tone={msg.tone}>{msg.text}</Note> : null}
    </View>
  );
}
