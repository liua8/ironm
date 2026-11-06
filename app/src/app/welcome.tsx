// 注册后完善资料（同网页 welcomePage，spec §174 需求 4）：身高、出生日期、体重必填，性别、目标、日常活动建议填；
// 存进档案和体重记录，再提示填自己的模型（去填 / 以后再说），然后进首页。只有刚注册时进这里。
import { router } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { checkWelcome, type ProfileData, SEX } from "@/features/me/logic";
import { ModelBox } from "@/features/me/settings";
import { Pills, useLoad } from "@/features/record/kit";
import { isoDay } from "@/features/record/logic";
import { Button, Field, LinkButton, Note, Panel, PixelText, Screen, T } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

export default function Welcome() {
  const { data, error } = useLoad<ProfileData>(() => api<ProfileData>("/iron/api/profile"));
  const [f, setF] = useState({ height: "", birth: "", weight: "", sex: "", goal: "", activity: "" });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [model, setModel] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  const home = () => router.replace("/");

  const save = async () => {
    const r = checkWelcome(f, isoDay(new Date()));
    if ("error" in r) return setMsg(r.error);
    setBusy(true);
    setMsg("保存中…");
    try {
      await api("/iron/api/profile", { method: "PUT", json: r.profile });
      await api("/iron/api/readings", { method: "POST", json: { kind: "weight", value: r.weight } });
      setSaved(true);
      setMsg("");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <View style={s.head}>
        <PixelText size={48} style={s.word}>IronM</PixelText>
        <T style={s.lede}>先填几样，IronM 才能按你的情况算热量、排训练。</T>
      </View>
      <Panel>
        {saved ? (
          model ? (
            <>
              <ModelBox close={home} />
              <LinkButton title="先进首页" onPress={home} />
            </>
          ) : (
            <>
              <T style={s.bold}>资料存好了。</T>
              <Text style={s.muted}>再填一个自己的模型（DeepSeek、通义千问、智谱等都可以）就能问 IronM、拍照估热量；记训练、看计划不填也能用。</Text>
              <Button title="去填模型" onPress={() => setModel(true)} />
              <LinkButton title="以后再说，先进首页" onPress={home} />
            </>
          )
        ) : (
          <>
            <Text style={s.label}>身高（厘米）*</Text>
            <Field keyboardType="decimal-pad" inputMode="decimal" value={f.height} onChangeText={set("height")} placeholder="比如 172" accessibilityLabel="身高（厘米）" />
            <Text style={s.label}>出生日期 *</Text>
            <Field value={f.birth} onChangeText={set("birth")} placeholder="比如 1995-06-18" accessibilityLabel="出生日期" autoCapitalize="none" />
            <Text style={s.label}>体重（公斤）*</Text>
            <Field keyboardType="decimal-pad" inputMode="decimal" value={f.weight} onChangeText={set("weight")} placeholder="比如 65" accessibilityLabel="体重（公斤）" />
            <Text style={s.label}>性别</Text>
            <Pills options={Object.entries(SEX) as [string, string][]} value={f.sex} onPick={set("sex")} label="性别" />
            {data ? (
              <>
                <Text style={s.label}>目标</Text>
                <Pills options={Object.entries(data.options.goal)} value={f.goal} onPick={set("goal")} label="目标" />
                <Text style={s.label}>日常活动</Text>
                <Pills options={Object.entries(data.options.activity)} value={f.activity} onPick={set("activity")} label="日常活动" />
              </>
            ) : null}
            {error ? <Note tone="error">{error}</Note> : null}
            <Text style={s.muted}>带 * 的要填；其余建议填，算每天该吃多少会更准。以后都能在「我」里改。</Text>
            <Note tone={msg === "保存中…" ? "muted" : "error"}>{msg}</Note>
            <Button title="保存" onPress={save} disabled={busy} />
          </>
        )}
      </Panel>
    </Screen>
  );
}

const s = StyleSheet.create({
  head: { marginTop: 32, gap: 8 },
  word: { color: color.ink },
  lede: { color: color.ink },
  bold: { color: color.ink, fontWeight: "700" },
  label: { color: color.ink, fontSize: 14, fontWeight: "600", marginTop: space.s },
  muted: { color: color.muted, fontSize: 13, lineHeight: 19 },
});
