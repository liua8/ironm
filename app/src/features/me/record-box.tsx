// 自己记一条、改值、删一条（同网页 recordBox / readingRow）：写进同一份健康记录，来源"手动记录"；
// 改和删保留原记录（mirobody 的更正与撤回）。
import { useCallback, useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Caption, Sub, TwoStep } from "@/features/record/kit";
import { isoDay } from "@/features/record/logic";
import { Button, Field, LinkButton, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { validDay } from "./logic";

type ReadingRow = { id: number; value: number; day: string; manual?: boolean };
type Readings = { kind: string; title: string; unit: string; low: number; high: number; rows: ReadingRow[] };

export function RecordBox({ kinds, onChanged }: { kinds: string[]; onChanged?: () => void }) {
  const [all, setAll] = useState<Readings[] | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [day, setDay] = useState(isoDay(new Date()));
  const [msg, setMsg] = useState<{ tone: "error" | "muted" | "ok"; text: string }>({ tone: "muted", text: "" });
  const [busy, setBusy] = useState(false);
  const key = kinds.join(",");

  const refresh = useCallback(async () => {
    const got = await Promise.all(key.split(",").map((k) => api<Readings>(`/iron/api/readings?kind=${encodeURIComponent(k)}`)));
    setAll(got);
  }, [key]);

  useEffect(() => {
    refresh().catch((e: Error) => setMsg({ tone: "error", text: e.message }));
  }, [refresh]);

  const changed = async () => {
    await refresh();
    onChanged?.();
  };

  const save = async () => {
    const today = isoDay(new Date());
    if (!validDay(day, today)) return setMsg({ tone: "error", text: "日期写成 2026-11-05 这样，不能晚于今天" });
    if (kinds.some((k) => !values[k]?.trim() || !Number.isFinite(Number(values[k])))) return setMsg({ tone: "error", text: "请填上数值" });
    setBusy(true);
    setMsg({ tone: "muted", text: "正在记下…" });
    try {
      for (const k of kinds) await api("/iron/api/readings", { method: "POST", json: { kind: k, value: Number(values[k]), day } });
      setValues({});
      setMsg({ tone: "ok", text: "已记下，指标会按新数据重新算。" });
      await changed();
    } catch (e) {
      setMsg({ tone: "error", text: (e as Error).message });
    }
    setBusy(false);
  };

  if (!all) return msg.text ? <Note tone={msg.tone}>{msg.text}</Note> : <Caption>正在读取…</Caption>;
  const rows = all.flatMap((r) => r.rows.slice(0, 6).map((row) => ({ r, row })));
  return (
    <View style={s.box}>
      {all.map((r) => (
        <View key={r.kind} style={s.field}>
          <Text style={s.label}>{`${r.title}（${r.unit}）`}</Text>
          <Field
            keyboardType="decimal-pad"
            inputMode="decimal"
            placeholder={`${r.low}–${r.high}`}
            value={values[r.kind] ?? ""}
            onChangeText={(t) => setValues((v) => ({ ...v, [r.kind]: t }))}
            accessibilityLabel={`${r.title}（${r.unit}）`}
          />
        </View>
      ))}
      <View style={s.field}>
        <Text style={s.label}>日期</Text>
        <Field value={day} onChangeText={setDay} placeholder="2026-11-05" accessibilityLabel="日期" autoCapitalize="none" />
      </View>
      <Button title="记下" onPress={save} disabled={busy} />
      <Note tone={msg.tone}>{msg.text}</Note>
      <Sub>最近的记录</Sub>
      {rows.length ? rows.map(({ r, row }) => <Reading key={`${r.kind}-${row.id}`} r={r} row={row} onChanged={changed} onError={(text) => setMsg({ tone: "error", text })} />) : <Caption>还没有记录。</Caption>}
      <Caption>改和删都会保留原来那条，可以追溯。手表、报告导入的数也能改。</Caption>
    </View>
  );
}

function Reading({ r, row, onChanged, onError }: { r: Readings; row: ReadingRow; onChanged: () => Promise<void>; onError: (t: string) => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const call = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setEdit(null);
      await onChanged();
    } catch (e) {
      onError((e as Error).message);
    }
  };
  if (edit !== null) {
    return (
      <View style={s.row}>
        <Field style={s.fix} keyboardType="decimal-pad" inputMode="decimal" value={edit} onChangeText={setEdit} accessibilityLabel="改成" autoFocus />
        <Button small title="保存" onPress={() => call(() => api(`/iron/api/readings/${r.kind}/${row.id}`, { method: "POST", json: { value: Number(edit) } }))} />
        <Button small kind="ghost" title="取消" onPress={() => setEdit(null)} />
      </View>
    );
  }
  return (
    <View style={s.row}>
      <View style={s.main}>
        <Text style={s.title}>{`${row.value} ${r.unit}`}</Text>
        <Text style={s.sub}>{`${row.day} · ${r.title} · ${row.manual ? "手动记录" : "设备或报告"}`}</Text>
      </View>
      <LinkButton title="改" onPress={() => setEdit(String(row.value))} />
      <TwoStep label="删" sure="确定删" onConfirm={() => call(() => api(`/iron/api/readings/${r.kind}/${row.id}`, { method: "DELETE" }))} />
    </View>
  );
}

const s = StyleSheet.create({
  box: { gap: space.m },
  field: { gap: 4 },
  label: { color: color.ink, fontSize: 14, fontWeight: "600" },
  row: { flexDirection: "row", alignItems: "center", gap: space.m, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: color.woodLight },
  main: { flex: 1, gap: 2 },
  title: { color: color.ink, fontSize: 15, fontWeight: "600" },
  sub: { color: color.muted, fontSize: 12 },
  fix: { flex: 1, paddingVertical: 8 },
});
