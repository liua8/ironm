// 排行榜（spec §161、§164 第三期）：从首页最上面"今日热搜"进来；左上角回首页，底部标签不变。
import { RankHomeView } from "@/features/rank/home";
import { goBack } from "@/features/rank/nav";
import { RankBar } from "@/features/rank/ui";
import { Screen } from "@/ui/pixel";

export default function Rank() {
  return (
    <Screen>
      <RankBar back="首页" onBack={() => goBack("/")} title="排行榜" />
      <RankHomeView />
    </Screen>
  );
}
