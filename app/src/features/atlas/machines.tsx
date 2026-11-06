// 图鉴·器械（同网页 machinesPage / machineSheet / foundSheet，spec §149、§161）：拍一张认器械（§164 第四期接上相机）；
// 下面按三组列常见器械，点开看怎么调、要注意、能练的动作（动作库里有的能点开做法）。
import { useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { api, isNoModel, NO_MODEL } from "@/api/client";
import { appendPhoto, getPhoto, photoErrText } from "@/lib/photo";
import { Icon } from "@/ui/icons";
import { Button, Note } from "@/ui/pixel";
import { color, space } from "@/ui/theme";

import { NeedModel } from "@/features/me/need-model";

import { loadExercises, useLoad } from "./data";
import { coverOf, imgUrl, machineGroups } from "./logic";
import { MoveImages } from "./moves";
import type { Exercise, ExerciseLib, Machine, MachineFound } from "./types";
import { Caption, Card, Cover, Grid, H3, Loading, MarkList, Row, Sheet, Tags, ui } from "./ui";

type Loaded = { machines: Machine[]; lib: ExerciseLib | null };

async function loadMachines(): Promise<Loaded> {
  const [r, lib] = await Promise.all([api<{ machines: Machine[] }>("/iron/api/machines"), loadExercises().catch(() => null)]);
  return { machines: r.machines ?? [], lib };
}

/** 没认出来时说的话（同网页版）。 */
export function foundText(got: MachineFound): string {
  // §167 起没有默认模型：服务端没填模型回 428；万一回的是 no_model 状态，意思一样
  if (got.status === "no_model") return NO_MODEL;
  if (got.status === "failed") return got.message || "这次没认出来，稍后再试，或者从下面的清单里找。";
  return "照片里没看到健身器械，换个角度再拍一张，或者从下面的清单里找。";
}

// needModel：还没填自己的模型（428），说明下面给"去填模型"
type Msg = { tone: "muted" | "error"; text: string } | { found: MachineFound } | { needModel: string };

export function MachinesSection({ onOpen, onMove }: { onOpen: (m: Machine, lib: ExerciseLib | null) => void; onMove: (x: Exercise, note: string) => void }) {
  const { data, error, reload } = useLoad(loadMachines);
  const groups = useMemo(() => machineGroups(data?.machines ?? []), [data]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<Msg | null>(null);
  const [found, setFound] = useState<MachineFound | null>(null);
  const lib = data?.lib ?? null;
  const known = (f: MachineFound) => (f.match ? data?.machines.find((m) => m.id === f.match) : undefined);

  const shoot = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const photo = await getPhoto("拍一张认器械");
      if (!photo) return;
      setMsg({ tone: "muted", text: "正在认…" });
      const form = new FormData();
      appendPhoto(form, "photo", photo, "machine.jpg");
      const got = await api<MachineFound>("/iron/api/machines/recognize", { method: "POST", body: form });
      if ((got.status === "ok" || got.status === "unsure") && got.name) {
        setMsg({ found: got });
        setFound(got);
      } else if (got.status === "no_model") setMsg({ needModel: foundText(got) });
      else setMsg({ tone: "muted", text: foundText(got) });
    } catch (e) {
      setMsg(isNoModel(e) ? { needModel: e.message } : { tone: "error", text: photoErrText(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.wrap}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="拍一张认器械"
        accessibilityState={{ disabled: busy }}
        disabled={busy}
        onPress={shoot}
        style={({ pressed }) => [s.shot, (pressed || busy) && s.shotDown]}
      >
        <View style={s.shotIcon}>
          <Icon name="camera" size={26} color={color.ink} />
        </View>
        <View style={s.shotMain}>
          <Text style={s.shotTitle}>拍一张认器械</Text>
          <Text style={ui.muted}>不知道叫什么、怎么用，拍下来看看</Text>
        </View>
      </Pressable>
      <Caption>照片会发给识别服务，认完不保存。</Caption>
      {msg && "found" in msg ? (
        <View style={s.row}>
          <Button
            title={`${msg.found.status === "unsure" ? "不太确定，可能是" : "认出来了："}${msg.found.name}`}
            kind="ghost"
            small
            onPress={() => setFound(msg.found)}
          />
        </View>
      ) : msg && "needModel" in msg ? (
        <NeedModel text={msg.needModel} />
      ) : msg ? (
        <Note tone={msg.tone}>{msg.text}</Note>
      ) : null}
      {!data ? (
        <Loading error={error} onRetry={reload} what="器械清单" />
      ) : (
        groups.map((g) => (
          <View key={g.key} style={ui.section}>
            <Text style={ui.plankTitle}>
              {g.name}
              <Text style={ui.small}>{`  ${g.items.length} 个`}</Text>
            </Text>
            <Grid>
              {g.items.map((m) => (
                <Card
                  key={m.id}
                  label={`${m.name}，点开看怎么用`}
                  onPress={() => onOpen(m, data.lib)}
                  cover={<Cover uri={imgUrl(m.picture?.url)} mark={m.name.slice(0, 1)} style={s.cover} contain />}
                  title={m.name}
                  sub={m.trains}
                />
              ))}
            </Grid>
          </View>
        ))
      )}
      {found ? (
        <FoundSheet
          f={found}
          known={known(found)}
          lib={lib}
          onClose={() => setFound(null)}
          onKnown={(m) => {
            setFound(null);
            onOpen(m, lib);
          }}
          onMove={(x, note) => {
            setFound(null);
            onMove(x, note);
          }}
        />
      ) : null}
    </View>
  );
}

/** 拍照认出来的（模型看照片直接写的）：和清单里同一种时多一个"看图鉴里的详情"。 */
export function FoundSheet({ f, known, lib, onClose, onKnown, onMove }: {
  f: MachineFound;
  known: Machine | undefined;
  lib: ExerciseLib | null;
  onClose: () => void;
  onKnown: (m: Machine) => void;
  onMove: (x: Exercise, note: string) => void;
}) {
  const setup = f.setup ?? [];
  const careful = f.careful ?? [];
  const moves = f.moves ?? [];
  return (
    <Sheet title={f.name ?? ""} onClose={onClose}>
      {f.status === "unsure" ? <Note>不太确定，看着像这个；不对的话从清单里找一下。</Note> : null}
      <Tags items={[f.trains, ...(f.aka ?? []).map((a) => `也叫${a}`)]} />
      {setup.length ? (
        <>
          <H3>怎么调、怎么用</H3>
          <MarkList items={setup} tone="ok" />
        </>
      ) : null}
      {careful.length ? (
        <>
          <H3>要注意</H3>
          <MarkList items={careful} tone="warn" />
        </>
      ) : null}
      {moves.length ? (
        <>
          <H3>能练的动作</H3>
          <View>
            {moves.map((mv, i) => {
              const ex = mv.id ? lib?.exercises.find((e) => e.id === mv.id) : undefined;
              if (!ex || !lib) return <Row key={`${mv.name}-${i}`} title={mv.name} sub="图鉴里还没有" />;
              return (
                <Row
                  key={`${mv.name}-${i}`}
                  thumb={<Cover uri={coverOf(ex)} mark={ex.name.slice(0, 1)} style={s.thumb} contain />}
                  title={mv.name}
                  sub={`${ex.part} · ${ex.level}`}
                  onPress={() => onMove(ex, lib.note)}
                />
              );
            })}
          </View>
        </>
      ) : null}
      {known ? <Button title={`看图鉴里的${known.name}`} kind="ghost" onPress={() => onKnown(known)} /> : null}
      <Caption>IronM 看照片说的，可能不准，以现场说明为准。</Caption>
    </Sheet>
  );
}

/** 器械详情：能练的动作点了打开那个动作的做法。 */
export function MachineSheet({ m, lib, onClose, onMove }: { m: Machine; lib: ExerciseLib | null; onClose: () => void; onMove: (x: Exercise, note: string) => void }) {
  return (
    <Sheet title={m.name} onClose={onClose}>
      {m.picture ? <MoveImages images={[m.picture]} /> : null}
      <Tags items={[m.trains, ...(m.aka ?? []).map((a) => `也叫${a}`)]} />
      <H3>怎么调</H3>
      <MarkList items={m.setup} tone="ok" />
      <H3>要注意</H3>
      <MarkList items={m.careful} tone="warn" />
      <H3>能练的动作</H3>
      <View>
        {m.moves.map((mv) => {
          const ex = lib?.exercises.find((e) => e.id === mv.id);
          if (!ex || !lib) return <Row key={mv.id} title={mv.name} sub="图鉴里还没有" />;
          return (
            <Row
              key={mv.id}
              thumb={<Cover uri={coverOf(ex)} mark={ex.name.slice(0, 1)} style={s.thumb} contain />}
              title={mv.name}
              sub={`${ex.part} · ${ex.level}`}
              onPress={() => onMove(ex, lib.note)}
            />
          );
        })}
      </View>
      <Caption>器械资料由 IronM 整理，各家器械细节可能不一样，以现场说明为准。</Caption>
    </Sheet>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.l },
  shot: { flexDirection: "row", alignItems: "center", gap: 14, backgroundColor: color.paper, borderWidth: 1, borderRadius: 14, borderColor: color.wood, padding: 14 },
  shotDown: { opacity: 0.75 },
  shotIcon: { width: 48, height: 48, alignItems: "center", justifyContent: "center", backgroundColor: color.paperLight, borderWidth: 1, borderRadius: 14, borderColor: color.wood },
  shotMain: { flex: 1, minWidth: 0, gap: 2 },
  shotTitle: { color: color.ink, fontSize: 16, fontWeight: "700" },
  row: { flexDirection: "row" },
  cover: { width: "100%", aspectRatio: 4 / 3 },
  thumb: { width: 48, height: 48, borderWidth: 1, borderRadius: 14 },
});
