// 条目详情（spec §161）：/rank/<榜>/<条目>，打分、看评论、写评论。
import { useLocalSearchParams } from "expo-router";

import { RankItemView } from "@/features/rank/item";
import { one } from "@/features/rank/nav";
import { Screen } from "@/ui/pixel";

export default function RankItem() {
  const p = useLocalSearchParams<{ board: string; item: string }>();
  return (
    <Screen>
      <RankItemView board={one(p.board)} itemKey={one(p.item)} />
    </Screen>
  );
}
