// 饮食（spec §164 第二期，照网页版 food，§125）：今日余额、记一餐（带"推荐这一餐"，§118）、今天的饮食计划三块（"饮食账单"整页 /eat）。
// compact（§176 首页）：只放"今天吃"卡（圆环、三格、拍照记、写一句），弹出页照旧在这里开。
// 弹出页一次只开一个：从"＋ 记"那页点写一句、从图鉴选、常吃的，是换掉弹出页里的内容，不叠第二层。
import { useCallback, useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";

import { api } from "@/api/client";
import type { Photo } from "@/lib/photo";
import { Button, Note, Panel, T } from "@/ui/pixel";
import { space } from "@/ui/theme";

import { HowTarget, TodayBudget } from "./budget";
import { EatCard } from "./eat-card";
import { AddMeal, EntryBar, LogUsual, PhotoMeal, PickFoods, WriteMeal } from "./entry";
import { MealDetail } from "./meal-sheet";
import { Sheet } from "./parts";
import { PlanEdit, TodayPlan } from "./plan";
import { RecommendMeal } from "./recommend";
import type { Day, DietPlan, DietReview, Meal, Metric, Usual } from "./types";

type SheetState =
  | { type: "write"; kind: string | null }
  | { type: "photo"; kind: string | null; photo: Photo }
  | { type: "pick"; kind: string | null }
  | { type: "usual"; kind: string | null; usual: Usual }
  | { type: "add"; kind: string }
  | { type: "meal"; meal: Meal }
  | { type: "how" }
  | { type: "plan"; plan: DietPlan }
  | { type: "rec" };

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : "没有成功，请再试一次。");

function sheetTitle(x: SheetState): string {
  switch (x.type) {
    case "write": return "填一餐";
    case "photo": return "这是哪一餐？";
    case "pick": return "从食物库选";
    case "usual": return `记一份「${x.usual.name}」`;
    case "add": return `记${x.kind}`;
    case "meal": return `${x.meal.kind} · ${x.meal.name}`;
    case "how": return "今日目标怎么算的";
    case "plan": return "饮食计划";
    case "rec": return "推荐这一餐";
  }
}

export function EatSection({ compact = false, refresh = 0 }: { compact?: boolean; refresh?: number } = {}) {
  const [day, setDay] = useState<Day | null>(null);
  const [loadErr, setLoadErr] = useState("");
  const [metrics, setMetrics] = useState<Record<string, Metric>>({});
  const [plan, setPlan] = useState<DietPlan | null>(null);
  const [review, setReview] = useState<DietReview | null>(null);
  const [reviewErr, setReviewErr] = useState("");
  const [sheet, setSheet] = useState<SheetState | null>(null);
  const [sheetSeq, setSheetSeq] = useState(0);
  const [flash, setFlash] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const say = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    setFlash({ tone, text });
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 3000);
  }, []);
  useEffect(() => () => {
    if (flashTimer.current) clearTimeout(flashTimer.current);
  }, []);

  // 计划和复盘：每次记完一餐跟着重读（复盘建议会随记录变）
  const loadSide = useCallback(() => {
    api<DietPlan>("/iron/api/diet/plan").then(setPlan).catch(() => {});
    api<DietReview>("/iron/api/diet/review").then(setReview).catch(() => {});
  }, []);

  const loadAll = useCallback(async () => {
    setLoadErr("");
    const [d, m] = await Promise.all([
      api<Day>("/iron/api/meals").catch((e: unknown) => {
        setLoadErr(errText(e));
        return null;
      }),
      api<{ metrics: Metric[] }>("/iron/api/metrics")
        .then((r) => Object.fromEntries(r.metrics.map((x) => [x.key, x])) as Record<string, Metric>)
        .catch(() => ({}) as Record<string, Metric>),
    ]);
    setMetrics(m);
    if (d) setDay(d);
    loadSide();
  }, [loadSide]);

  // refresh 变了就重读（§176：首页一直挂着，回到首页时首页把它加一，去饮食账单或对话里记的一餐跟着显示）
  useEffect(() => {
    loadAll();
  }, [loadAll, refresh]);

  const open = (x: SheetState) => {
    setSheet(x);
    setSheetSeq((n) => n + 1);
  };
  const close = () => setSheet(null);
  /** 记下、改了、删了之后：关掉弹出页，换成服务端给的今天。 */
  const done = (d: Day, text?: string) => {
    close();
    setDay(d);
    loadSide();
    if (text) say(text);
  };

  const logPlan = async (kind: string) => {
    try {
      const d = await api<Day>("/iron/api/diet/plan/log", { method: "POST", json: { slot: kind } });
      setDay(d);
      loadSide();
      say(`记下了${kind}`);
    } catch (e) {
      say(errText(e), "error");
    }
  };

  const act = async (action: "confirm" | "undo") => {
    setReviewErr("");
    try {
      await api(action === "confirm" ? "/iron/api/diet/adjust" : "/iron/api/diet/adjust/undo", { method: "POST" });
      await loadAll(); // 目标变了：余额、计划、复盘都重读
    } catch (e) {
      setReviewErr(errText(e));
    }
  };

  const editPlan = async () => {
    const p = plan ?? (await api<DietPlan>("/iron/api/diet/plan").catch(() => null));
    if (p) open({ type: "plan", plan: p });
    else say("饮食计划这次没读到", "error");
  };

  if (!day) {
    return (
      <Panel>
        {loadErr ? (
          <>
            <Note tone="error">{`今天的饮食这次没读到：${loadErr}`}</Note>
            <View style={s.row}><Button title="再试一次" kind="ghost" small onPress={loadAll} /></View>
          </>
        ) : (
          <T muted>正在读今天的饮食…</T>
        )}
      </Panel>
    );
  }

  const body = (() => {
    if (!sheet) return null;
    switch (sheet.type) {
      case "write": return <WriteMeal day={day} kind0={sheet.kind} done={(d) => done(d)} onLeave={close} />;
      case "photo": return <PhotoMeal day={day} photo={sheet.photo} kind0={sheet.kind} done={(d) => done(d)} onLeave={close} />;
      case "pick": return <PickFoods day={day} kind0={sheet.kind} done={(d) => done(d)} />;
      case "usual": return <LogUsual day={day} usual={sheet.usual} kind0={sheet.kind} done={(d) => done(d)} />;
      case "add": {
        const kind = sheet.kind;
        return (
          <AddMeal
            onWrite={() => open({ type: "write", kind })}
            onPick={() => open({ type: "pick", kind })}
            onPhoto={(photo) => open({ type: "photo", kind, photo })}
            onUsual={(u) => open({ type: "usual", kind, usual: u })}
          />
        );
      }
      case "meal": return <MealDetail meal={sheet.meal} done={done} />;
      case "how": return <HowTarget metrics={metrics} />;
      case "plan": return <PlanEdit initial={sheet.plan} onChanged={setPlan} />;
      case "rec": return <RecommendMeal done={(d) => done(d, "记下了推荐的这一餐")} />;
    }
  })();

  const sheetView = (
    <Sheet title={sheet ? sheetTitle(sheet) : ""} visible={!!sheet} onClose={close}>
      <View key={sheetSeq}>{body}</View>
    </Sheet>
  );
  if (compact) {
    return (
      <View style={s.wrap}>
        <EatCard day={day} metrics={metrics} onWrite={() => open({ type: "write", kind: null })} onPhoto={(photo) => open({ type: "photo", kind: null, photo })} />
        {flash ? <Note tone={flash.tone}>{flash.text}</Note> : null}
        {sheetView}
      </View>
    );
  }
  return (
    <View style={s.wrap}>
      <TodayBudget day={day} metrics={metrics} onHow={() => open({ type: "how" })} />
      <Panel>
        <EntryBar
          onWrite={() => open({ type: "write", kind: null })}
          onPick={() => open({ type: "pick", kind: null })}
          onPhoto={(photo) => open({ type: "photo", kind: null, photo })}
        />
        <Button kind="ghost" small title="不知道吃什么？推荐这一餐" onPress={() => open({ type: "rec" })} />
      </Panel>
      <TodayPlan
        day={day}
        plan={plan}
        review={review}
        reviewErr={reviewErr}
        flash={flash}
        onEdit={editPlan}
        onMeal={(m) => open({ type: "meal", meal: m })}
        onLog={logPlan}
        onAdd={(kind) => open({ type: "add", kind })}
        onReview={act}
      />
      {sheetView}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { gap: space.l },
  row: { flexDirection: "row" },
});
