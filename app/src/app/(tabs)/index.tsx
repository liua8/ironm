// 首页（同网页 §121、§161）：最上面今日热搜；三段 练 / 干饭 / IronM，IronM 打开对话页。
// 还没填自己的模型时，标题下面一张可以关掉的提示卡（spec §167）。
import { router } from "expo-router";
import { useState } from "react";

import { EatSection } from "@/features/eat/eat";
import { HotStrip } from "@/features/home/hot-strip";
import { TrainSection } from "@/features/home/train";
import { ModelHint } from "@/features/me/need-model";
import { PageTitle, Screen, Seg } from "@/ui/pixel";

type Part = "train" | "eat" | "chat";

export default function Home() {
  const [part, setPart] = useState<Part>("train");
  return (
    <Screen>
      <PageTitle>首页</PageTitle>
      <ModelHint />
      <HotStrip />
      <Seg
        items={[["train", "练"], ["eat", "干饭"], ["chat", "IronM"]] as const}
        value={part}
        onChange={(k) => (k === "chat" ? router.push("/chat") : setPart(k))}
      />
      {part === "eat" ? <EatSection /> : <TrainSection />}
    </Screen>
  );
}
