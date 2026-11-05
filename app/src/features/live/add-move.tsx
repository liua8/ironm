// 加动作（同网页 livePage 的 addMove）：只有自由训练能加（§133）；搜动作库，点一个加到最后。
import { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api } from "@/api/client";
import { Sheet } from "@/features/home/bits";
import type { Library } from "@/features/home/types";
import { Field, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import type { LiveItem, LiveResp } from "./logic";

export function AddMoveSheet({ open, lib, onClose, flush, onAdded }: {
  open: boolean;
  lib: Library | null;
  onClose: () => void;
  flush: () => Promise<void>;
  onAdded: (items: LiveItem[]) => void;
}) {
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const k = q.trim();
  const rows = (lib?.exercises || []).filter((x) => !k || `${x.name}${x.part}${x.muscles}`.includes(k)).slice(0, 30);
  const add = async (name: string) => {
    setMsg("");
    await flush();
    try {
      const r = await api<LiveResp>("/iron/api/live/items", { method: "POST", json: { exercise: name } });
      if (r.live) onAdded(r.live.items);
      setQ("");
      onClose();
    } catch (err) {
      setMsg(err instanceof Error ? err.message : "没有成功，请再试一次。");
    }
  };
  return (
    <Sheet title="加动作" open={open} onClose={onClose}>
      <Field value={q} onChangeText={setQ} placeholder="搜动作，比如卧推" accessibilityLabel="搜动作" returnKeyType="search" />
      <Note tone="error">{msg}</Note>
      {!lib ? <Note>动作库没读到，关掉再试一次。</Note> : null}
      {rows.map((x) => (
        <Pressable key={x.id} accessibilityRole="button" onPress={() => add(x.name)} style={({ pressed }) => [s.row, pressed && s.pressed]}>
          <Text style={s.name}>{x.name}</Text>
          <Text style={s.sub}>{`${x.part} · ${x.equipment.slice(0, 2).join("、")}`}</Text>
        </Pressable>
      ))}
      {lib && !rows.length ? <View><Note>没找到这个动作。</Note></View> : null}
    </Sheet>
  );
}

const s = StyleSheet.create({
  row: { paddingVertical: 10, paddingHorizontal: space.s, borderBottomWidth: 1, borderColor: color.woodLight },
  pressed: { backgroundColor: color.paperLight },
  name: { color: color.ink, fontSize: 15, fontWeight: "700" },
  sub: { color: color.muted, fontSize: 13 },
});
