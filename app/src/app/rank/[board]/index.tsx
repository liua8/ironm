// 榜单页（spec §161）：/rank/<榜>，动作榜可带 ?part=部位。
import { useLocalSearchParams } from "expo-router";

import { RankBoardView } from "@/features/rank/board";
import { one } from "@/features/rank/nav";
import { Screen } from "@/ui/pixel";

export default function RankBoard() {
  const p = useLocalSearchParams<{ board: string; part?: string }>();
  return (
    <Screen>
      <RankBoardView board={one(p.board)} part={one(p.part)} />
    </Screen>
  );
}
