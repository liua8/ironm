// 饮食账单（§176，同网页 #home/eat）：首页"今天吃"卡右上角进来，是原来的整页饮食（今日余额、记一餐、今天的饮食计划）。
import { EatSection } from "@/features/eat/eat";
import { BackLink, NeedLogin } from "@/features/record/kit";
import { PageTitle, Screen } from "@/ui/pixel";

export default function Eat() {
  return (
    <NeedLogin>
      <Screen>
        <BackLink label="首页" fallback="/" />
        <PageTitle>饮食账单</PageTitle>
        <EatSection />
      </Screen>
    </NeedLogin>
  );
}
