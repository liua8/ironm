// 身体数据（同网页 #body，spec §146）：从"我"的设置里进来，顶上能回"我"。
import { BodyData } from "@/features/me/body-data";
import { BackLink, NeedLogin } from "@/features/record/kit";
import { PageTitle, Screen } from "@/ui/pixel";

export default function Body() {
  return (
    <NeedLogin>
      <Screen>
        <BackLink label="我" fallback="/me" />
        <PageTitle>身体数据</PageTitle>
        <BodyData />
      </Screen>
    </NeedLogin>
  );
}
