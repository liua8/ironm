// 记录（同网页 recordPage，spec §137、§139、§147；§176 原"战绩"）：一页到底——这周表现、打卡日历、身体数据指标、成就、训练时间线入口、上周周报（放最下面）。
import { useFocusEffect } from "expo-router";
import { useCallback, useRef } from "react";

import { api } from "@/api/client";
import { BodyData } from "@/features/me/body-data";
import { Failed, useLoad } from "@/features/record/kit";
import { type Calendar, prWall, type WeekReport, type Workout } from "@/features/record/logic";
import { type BriefWeek, CalendarCard, PrPanel, TimelineEntry, WeekPanel, WeekReportPanel } from "@/features/record/sections";
import { Panel, AppBar, Screen, T } from "@/ui/pixel";

type Data = { week: BriefWeek | null; cal: Calendar | null; logs: Workout[] | null; rep: WeekReport | null };

async function loadAll(): Promise<Data> {
  const [brief, cal, tr, rep] = await Promise.all([
    api<{ week?: BriefWeek }>("/iron/api/brief").catch(() => null),
    api<Calendar>("/iron/api/calendar").catch(() => null),
    api<{ workouts: Workout[] }>("/iron/api/training").catch(() => null),
    api<WeekReport>("/iron/api/report/week").catch(() => null),
  ]);
  if (!brief && !cal && !tr) throw new Error("记录页暂时读不到训练记录，稍后再试。");
  return { week: brief?.week ?? null, cal, logs: tr?.workouts ?? null, rep };
}

export default function Record() {
  const { data, error, reload } = useLoad(loadAll);
  // 从别的页回来（打完卡、记了训练）时重新取
  const shown = useRef(false);
  useFocusEffect(
    useCallback(() => {
      if (shown.current) reload();
      shown.current = true;
    }, [reload]),
  );
  const logs = data?.logs ?? [];
  return (
    <Screen>
      <AppBar title="记录" />
      {error && !data ? (
        <Panel>
          <Failed error={error} retry={reload} />
        </Panel>
      ) : !data ? (
        <Panel>
          <T muted>正在读取…</T>
        </Panel>
      ) : (
        <>
          <WeekPanel logs={logs} cal={data.cal} week={data.week} />
          {data.cal ? <CalendarCard key={data.cal.today + data.cal.done_days.length} first={data.cal} /> : null}
          <BodyData top />
          <PrPanel rows={prWall(logs).slice(0, 8)} />
          <TimelineEntry logs={logs} />
          {data.rep ? <WeekReportPanel r={data.rep} /> : null}
        </>
      )}
    </Screen>
  );
}
