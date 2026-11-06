// 我（同网页 me，spec §140、§141、§146、§153；§176 照网页 §175）：资料卡、我的目标、设置分三组带图标（训练 / 数据 / 账号与模型），退出登录放最下面。
// 记忆不上页面，设置里一行"IronM 记得的事"能看能删。
// 别处报"还没填模型"时带着 open=model 进来，直接打开"模型和 API"（spec §167）。
import { router, useLocalSearchParams } from "expo-router";
import { type ReactNode, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { useSession } from "@/auth/session";
import { ABOUT } from "@/features/me/logic";
import { GoalBlock, RoleCard } from "@/features/me/role-card";
import { ReminderBox } from "@/features/me/reminders";
import { CityBox, FilesBox, GearBox, ImportBox, MemoryBox, ModelBox } from "@/features/me/settings";
import { Sheet } from "@/features/record/kit";
import { Icon, type IconName } from "@/ui/icons";
import { AppBar, Button, Panel, Screen, T } from "@/ui/pixel";
import { color } from "@/ui/theme";

type Open = "memory" | "gear" | "import" | "files" | "city" | "remind" | "model" | "about" | null;

const TITLES: Record<Exclude<Open, null>, string> = {
  memory: "IronM 记得的事",
  gear: "器材和场所",
  import: "导入健康数据和化验单",
  files: "我的文件",
  city: "城市和天气",
  remind: "提醒",
  model: "模型和 API",
  about: "说明",
};

export default function Me() {
  const { signOut } = useSession();
  const [open, setOpen] = useState<Open>(null);
  const close = () => setOpen(null);
  const { open: want } = useLocalSearchParams<{ open?: string }>();
  useEffect(() => {
    if (want !== "model") return;
    setOpen("model");
    // 打开后把参数清掉：下次再从别处点"去填模型"时参数又变回 model，才会再打开
    router.setParams({ open: undefined });
  }, [want]);

  return (
    <Screen>
      <AppBar title="我" />
      <RoleCard />
      <GoalBlock />
      <Group icon="home" title="训练">
        <IRow icon="home" title="器材和场所" sub="排计划、换动作按这个" onPress={() => setOpen("gear")} />
        <IRow icon="sun" title="城市和天气" onPress={() => setOpen("city")} />
        <IRow icon="bell" title="提醒" sub="训练日提醒，默认关" onPress={() => setOpen("remind")} last />
      </Group>
      <Group icon="note" title="数据">
        <IRow icon="wave" title="身体数据" sub="体重、BMI、体脂率" onPress={() => router.push("/body")} />
        <IRow icon="coach" title="IronM 记得的事" sub="记错了可以删" onPress={() => setOpen("memory")} />
        <IRow icon="upload" title="导入健康数据和化验单" onPress={() => setOpen("import")} />
        <IRow icon="note" title="我的文件" onPress={() => setOpen("files")} last />
      </Group>
      <Group icon="me" title="账号与模型">
        <IRow icon="coach" title="模型和 API" sub="可以用自己的模型" onPress={() => setOpen("model")} />
        <IRow icon="info" title="说明" onPress={() => setOpen("about")} last />
      </Group>
      <Button
        kind="ghost"
        title="退出登录"
        onPress={async () => {
          await signOut();
          router.replace("/login");
        }}
      />
      <Sheet visible={open !== null} title={open ? TITLES[open] : ""} onClose={close}>
        {open === "memory" ? <MemoryBox /> : null}
        {open === "gear" ? <GearBox close={close} /> : null}
        {open === "import" ? <ImportBox /> : null}
        {open === "files" ? <FilesBox /> : null}
        {open === "city" ? <CityBox /> : null}
        {open === "remind" ? <ReminderBox /> : null}
        {open === "model" ? <ModelBox close={close} /> : null}
        {open === "about" ? <T muted>{ABOUT}</T> : null}
      </Sheet>
    </Screen>
  );
}

/** 一组设置：组名带图标，下面一张卡。 */
function Group({ icon, title, children }: { icon: IconName; title: string; children: ReactNode }) {
  return (
    <View style={g.group}>
      <View style={g.head}><Icon name={icon} size={18} color={color.accent} /><Text style={g.headText}>{title}</Text></View>
      <Panel style={g.card}>{children}</Panel>
    </View>
  );
}

/** 一行设置：左边浅紫圆底的图标。 */
function IRow({ icon, title, sub, onPress, last }: { icon: IconName; title: string; sub?: string; onPress: () => void; last?: boolean }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={title} onPress={onPress} style={({ pressed }) => [g.row, !last && g.rowLine, pressed && g.rowDown]}>
      <View style={g.ic}><Icon name={icon} size={18} color="#3b3b5c" /></View>
      <Text style={g.title} numberOfLines={1}>{title}</Text>
      {sub ? <Text style={g.sub} numberOfLines={1}>{sub}</Text> : null}
      <Text style={g.chev}>›</Text>
    </Pressable>
  );
}

const g = StyleSheet.create({
  group: { gap: 8 },
  head: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 2 },
  headText: { color: color.ink, fontSize: 17, fontWeight: "800" },
  card: { paddingVertical: 4, gap: 0 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingVertical: 12 },
  rowLine: { borderBottomWidth: 1, borderBottomColor: color.wood },
  rowDown: { opacity: 0.7 },
  ic: { width: 40, height: 40, borderRadius: 20, backgroundColor: color.iconBg, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, minWidth: 0, color: color.ink, fontSize: 16, fontWeight: "600" },
  sub: { maxWidth: "40%", color: color.muted, fontSize: 12 },
  chev: { color: color.muted, fontSize: 20 },
});
