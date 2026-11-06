// 角色卡和我的目标（同网页 meHead / profileForm / goalBlock，spec §140、§65）。
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { useSession } from "@/auth/session";
import { Caption, Pills, useLoad } from "@/features/record/kit";
import { isoDay } from "@/features/record/logic";
import { Button, Field, LinkButton, Note, Panel, PixelText, Plank, T } from "@/ui/pixel";
import { color, font, space } from "@/ui/theme";

import { fmtDay, num, type ProfileData, profileLine, SEX, stripRefs, tokenEmail, validDay } from "./logic";

/** 角色卡：头像、账号、一行档案摘要；点"编辑"就地展开档案表单。 */
export function RoleCard() {
  const { token } = useSession();
  const email = tokenEmail(token);
  const { data, error, setData } = useLoad(() => api<ProfileData>("/iron/api/profile"));
  const [editing, setEditing] = useState(false);
  return (
    <Panel>
      <View style={s.head}>
        <View style={s.avatar}>
          <PixelText size={24} style={s.avatarText}>
            {(email[0] || "我").toUpperCase()}
          </PixelText>
        </View>
        <View style={s.main}>
          <Text style={s.email} numberOfLines={1}>
            {email || "已登录"}
          </Text>
          <Text style={s.sub}>IronM 账号</Text>
        </View>
        {data && !editing ? <LinkButton title="编辑" onPress={() => setEditing(true)} /> : null}
      </View>
      {!data ? (
        <T muted>{error ? "档案暂时读不到，稍后再试。" : "正在读取…"}</T>
      ) : editing ? (
        <ProfileForm
          data={data}
          done={(fresh) => {
            if (fresh) setData(fresh);
            setEditing(false);
          }}
        />
      ) : (
        <>
          <T style={s.line}>{profileLine(data, new Date())}</T>
          <Caption>用来计算 BMI、基础代谢、每日热量和蛋白质目标。</Caption>
        </>
      )}
    </Panel>
  );
}

function ProfileForm({ data, done }: { data: ProfileData; done: (fresh?: ProfileData) => void }) {
  const p = data.profile;
  const [height, setHeight] = useState(p.height_cm != null ? String(p.height_cm) : "");
  const [birth, setBirth] = useState(p.birth ?? "");
  const [sex, setSex] = useState(p.sex ?? "");
  const [goal, setGoal] = useState(p.goal ?? "");
  const [activity, setActivity] = useState(p.activity ?? "");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    const body: Record<string, string | number> = {};
    if (height.trim()) {
      const h = Number(height);
      if (!Number.isFinite(h) || h < 100 || h > 250) return setMsg("身高填 100 到 250 厘米之间");
      body.height_cm = h;
    }
    if (birth.trim()) {
      if (!validDay(birth.trim(), isoDay(new Date()))) return setMsg("出生日期写成 1995-06-18 这样，不能晚于今天");
      body.birth = birth.trim();
    }
    if (sex) body.sex = sex;
    if (goal) body.goal = goal;
    if (activity) body.activity = activity;
    setBusy(true);
    setMsg("保存中…");
    try {
      await api("/iron/api/profile", { method: "PUT", json: body });
      done(await api<ProfileData>("/iron/api/profile"));
    } catch (e) {
      setMsg((e as Error).message);
      setBusy(false);
    }
  };

  return (
    <View style={s.form}>
      <Text style={s.label}>身高（厘米）</Text>
      <Field keyboardType="decimal-pad" inputMode="decimal" value={height} onChangeText={setHeight} placeholder="比如 172" accessibilityLabel="身高（厘米）" />
      <Text style={s.label}>出生日期</Text>
      <Field value={birth} onChangeText={setBirth} placeholder="比如 1995-06-18" accessibilityLabel="出生日期" autoCapitalize="none" />
      <Text style={s.label}>性别</Text>
      <Pills options={Object.entries(SEX) as [string, string][]} value={sex} onPick={setSex} label="性别" />
      <Text style={s.label}>目标</Text>
      <Pills options={Object.entries(data.options.goal)} value={goal} onPick={setGoal} label="目标" />
      <Text style={s.label}>日常活动</Text>
      <Pills options={Object.entries(data.options.activity)} value={activity} onPick={setActivity} label="日常活动" />
      <Note tone="error">{msg === "保存中…" ? "" : msg}</Note>
      {msg === "保存中…" ? <Note>{msg}</Note> : null}
      <View style={s.actions}>
        <View style={s.flex}>
          <Button kind="ghost" title="取消" onPress={() => done()} />
        </View>
        <View style={s.flex}>
          <Button title="保存" onPress={save} disabled={busy} />
        </View>
      </View>
    </View>
  );
}

type Progress = {
  status?: string;
  start?: number | null;
  current?: number | null;
  target?: number | null;
  changed?: number | null;
  percent?: number | null;
  predicted?: string | null;
  message?: string;
  missing?: string;
  pace?: string;
  retest?: { due?: boolean; text?: string };
  celebrate?: boolean;
};
type GoalState = { goal: { value: number; by: string; set_day?: string } | null; progress?: Progress };

const TONE: Record<string, "good" | "warn"> = { reached: "good", on_track: "good", ahead: "good", behind: "warn", wrong_way: "warn" };

/** 我的目标（同网页 goalBlock）：起点、当前、目标、进度条、预计达成；能设、改、清除；到了换成"目标达成"。 */
export function GoalBlock() {
  const { data, setData } = useLoad(() => api<GoalState>("/iron/api/goal").catch(() => ({ goal: null }) as GoalState));
  const [editing, setEditing] = useState(false);
  const st = data ?? { goal: null };
  const g = st.goal;
  const p = st.progress ?? {};
  const kg = (v: number | null | undefined) => (v == null ? "—" : num(v));
  // 到了目标（§93）：第一次看到时告诉服务端记下，下次不再庆祝；手机上的彩带、振动放到第四期
  const celebrate = p.status === "reached" && p.celebrate;
  useEffect(() => {
    if (celebrate) api("/iron/api/goal/celebrated", { method: "POST" }).catch(() => {});
  }, [celebrate]);

  let body;
  if (editing) {
    body = (
      <GoalForm
        goal={g}
        done={(next) => {
          if (next) setData(next);
          setEditing(false);
        }}
      />
    );
  } else if (!data) {
    body = <T muted>正在读取…</T>;
  } else if (!g) {
    body = <T muted>还没有设目标体重和日期。设好后这里显示起点、当前、目标和按体重趋势预计达成的日期，每 4 周提醒复测一次。</T>;
  } else if (p.status === "reached") {
    const days = g.set_day ? Math.max(0, Math.floor((Date.now() - new Date(`${g.set_day}T00:00:00`).getTime()) / 86400000)) : null;
    const moved = p.changed != null ? `${p.changed < 0 ? "减了" : "增了"} ${num(Math.abs(p.changed))} 公斤` : "";
    body = (
      <>
        <PixelText size={36} style={s.won}>
          目标达成
        </PixelText>
        <T>{p.start != null ? `从 ${kg(p.start)} 到 ${kg(p.current)} 公斤，${moved}${days != null ? `，用了 ${days} 天` : ""}` : `现在 ${kg(p.current)} 公斤，到目标了`}</T>
        <Button title="定下一个目标" onPress={() => setEditing(true)} />
        <Caption>也可以转为保持：体重在目标上下波动就算保持住了。</Caption>
      </>
    );
  } else {
    const pct = p.percent;
    const tone = TONE[p.status ?? ""];
    body = (
      <>
        <View style={s.goalHead}>
          <Text style={s.goalTitle}>{`目标体重 ${kg(g.value)} 公斤`}</Text>
          <Text style={s.sub}>{`${fmtDay(g.by)}前`}</Text>
        </View>
        <View style={s.nums}>
          {(
            [
              ["起点", p.start],
              ["当前", p.current],
              ["目标", p.target],
            ] as const
          ).map(([k, v]) => (
            <View key={k} style={[s.numBox, k === "当前" && s.numNow]}>
              <Text style={s.sub}>{k}</Text>
              <Text style={s.num}>{kg(v)}</Text>
              <Text style={s.sub}>公斤</Text>
            </View>
          ))}
        </View>
        {pct != null ? (
          <View style={s.progress}>
            <View style={s.bar} accessibilityRole="progressbar" accessibilityLabel={`完成 ${pct}%`}>
              <View style={[s.fill, { width: `${Math.max(0, Math.min(100, pct))}%` }]} />
            </View>
            <T>{`${p.changed ? `已${p.changed < 0 ? "减" : "增"} ${num(Math.abs(p.changed))} 公斤 · ` : ""}完成 ${pct}%`}</T>
          </View>
        ) : null}
        {p.predicted ? <T>{`预计达成：${fmtDay(p.predicted)}`}</T> : null}
        {p.message ? <T style={tone === "good" ? s.good : tone === "warn" ? s.warn : undefined}>{stripRefs(p.message)}</T> : null}
        {p.missing ? <T muted>{stripRefs(p.missing)}</T> : null}
        {p.pace ? <Text style={s.notice}>{stripRefs(p.pace)}</Text> : null}
        {p.retest?.due ? (
          <View style={s.notice}>
            <T>{stripRefs(p.retest.text)}</T>
            <LinkButton title="已复测" onPress={async () => setData(await api<GoalState>("/iron/api/goal/retest", { method: "POST" }))} />
          </View>
        ) : null}
      </>
    );
  }

  return (
    <Panel>
      <View style={s.panelHead}>
        <Plank>我的目标</Plank>
        {data && !editing && p.status !== "reached" ? <LinkButton title={g ? "修改" : "设置"} onPress={() => setEditing(true)} /> : null}
      </View>
      {body}
    </Panel>
  );
}

function GoalForm({ goal, done }: { goal: GoalState["goal"]; done: (next?: GoalState) => void }) {
  const [value, setValue] = useState(goal ? String(goal.value) : "");
  const [by, setBy] = useState(goal?.by ?? "");
  const [msg, setMsg] = useState("");
  const save = async () => {
    if (!value.trim() || !by.trim()) return setMsg("目标体重和日期都要填");
    const v = Number(value);
    if (!Number.isFinite(v) || v < 30 || v > 250) return setMsg("目标体重填 30 到 250 公斤之间");
    if (!validDay(by.trim())) return setMsg("日期写成 2026-12-31 这样");
    setMsg("正在保存…");
    try {
      done(await api<GoalState>("/iron/api/goal", { method: "PUT", json: { value: v, by: by.trim() } }));
    } catch (e) {
      setMsg((e as Error).message);
    }
  };
  return (
    <View style={s.form}>
      <Text style={s.label}>目标体重（公斤）</Text>
      <Field keyboardType="decimal-pad" inputMode="decimal" value={value} onChangeText={setValue} placeholder="比如 65" accessibilityLabel="目标体重（公斤）" />
      <Text style={s.label}>目标日期</Text>
      <Field value={by} onChangeText={setBy} placeholder="比如 2026-12-31" accessibilityLabel="目标日期" autoCapitalize="none" />
      <Note tone={msg === "正在保存…" ? "muted" : "error"}>{msg}</Note>
      <View style={s.actions}>
        {goal ? (
          <View style={s.flex}>
            <Button
              kind="ghost"
              title="清除"
              onPress={async () => {
                try {
                  done(await api<GoalState>("/iron/api/goal", { method: "DELETE" }));
                } catch (e) {
                  setMsg((e as Error).message);
                }
              }}
            />
          </View>
        ) : null}
        <View style={s.flex}>
          <Button kind="ghost" title="取消" onPress={() => done()} />
        </View>
        <View style={s.flex}>
          <Button title="保存" onPress={save} />
        </View>
      </View>
    </View>
  );
}


const s = StyleSheet.create({
  head: { flexDirection: "row", alignItems: "center", gap: space.m },
  avatar: { width: 52, height: 52, alignItems: "center", justifyContent: "center", backgroundColor: color.amber, borderWidth: 1, borderRadius: 14, borderColor: color.woodDark },
  avatarText: { color: color.ink2 },
  main: { flex: 1, gap: 2, minWidth: 0 },
  email: { color: color.ink, fontSize: 16, fontWeight: "700" },
  sub: { color: color.muted, fontSize: 13 },
  line: { fontWeight: "600" },
  form: { gap: space.s },
  label: { color: color.ink, fontSize: 14, fontWeight: "600", marginTop: 4 },
  actions: { flexDirection: "row", gap: space.s, marginTop: space.xs },
  flex: { flex: 1 },
  panelHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  won: { color: color.accentText },
  goalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: space.s },
  goalTitle: { color: color.ink, fontSize: 16, fontWeight: "700" },
  nums: { flexDirection: "row", gap: space.s },
  numBox: { flex: 1, alignItems: "center", gap: 2, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.woodLight, paddingVertical: space.s },
  numNow: { borderColor: color.accent, backgroundColor: color.goodSoft },
  num: { fontWeight: "800", fontSize: 24, lineHeight: 30, color: color.ink },
  progress: { gap: 6 },
  bar: { height: 14, backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood },
  fill: { height: "100%", backgroundColor: color.accent },
  good: { color: color.accentText },
  warn: { color: "#8a5a10" },
  notice: { color: color.ink2, backgroundColor: "rgba(242, 193, 78, 0.3)", borderLeftWidth: 1, borderLeftColor: "#8a5a10", padding: space.s, fontSize: 14, gap: 4 },
});
