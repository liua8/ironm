// 我（同网页 me，spec §140、§141、§146、§153）：角色卡、我的目标、设置收成一列（点了在弹出页里打开），退出登录放最下面。
// 记忆不上页面，设置里一行"IronM 记得的事"能看能删。
// 别处报"还没填模型"时带着 open=model 进来，直接打开"模型和 API"（spec §167）。
import { router, useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";

import { useSession } from "@/auth/session";
import { ABOUT } from "@/features/me/logic";
import { GoalBlock, RoleCard } from "@/features/me/role-card";
import { ReminderBox } from "@/features/me/reminders";
import { CityBox, FilesBox, GearBox, ImportBox, MemoryBox, ModelBox } from "@/features/me/settings";
import { PanelHead, Row, Sheet } from "@/features/record/kit";
import { Button, Panel, PageTitle, Screen, T } from "@/ui/pixel";

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
      <PageTitle>我</PageTitle>
      <RoleCard />
      <GoalBlock />
      <Panel>
        <PanelHead title="设置" />
        <Row title="身体数据" sub="体重、BMI、体脂率" onPress={() => router.push("/body")} />
        <Row title="IronM 记得的事" sub="记错了可以删" onPress={() => setOpen("memory")} />
        <Row title="器材和场所" sub="排计划、换动作按这个" onPress={() => setOpen("gear")} />
        <Row title="导入健康数据和化验单" onPress={() => setOpen("import")} />
        <Row title="我的文件" onPress={() => setOpen("files")} />
        <Row title="城市和天气" onPress={() => setOpen("city")} />
        <Row title="提醒" sub="训练日提醒，默认关" onPress={() => setOpen("remind")} />
        <Row title="模型和 API" sub="可以用自己的模型" onPress={() => setOpen("model")} />
        <Row title="说明" last onPress={() => setOpen("about")} />
      </Panel>
      <Button
        kind="wood"
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
