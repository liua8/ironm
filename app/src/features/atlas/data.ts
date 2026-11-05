// 图鉴读数据：动作库一次读来大家共用（动作库、器械详情里的动作都用它）；useLoad 管"正在读、读不到、重试"。
import { router } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";

import type { ExerciseLib } from "./types";

let lib: Promise<ExerciseLib> | null = null;

/** 动作库（同网页 exercises()）：读到了就留着，读不到下次再读。 */
export function loadExercises(): Promise<ExerciseLib> {
  if (!lib) {
    lib = api<ExerciseLib>("/iron/api/exercises").catch((err: unknown) => {
      lib = null;
      throw err;
    });
  }
  return lib;
}

export function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export type Loaded<T> = { data: T | null; error: string | null; reload: () => void };

/** 读一次；deps 变了重读；页面关了不再写状态。 */
export function useLoad<T>(load: () => Promise<T>, deps: readonly unknown[] = []): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    const mine = ++seq.current;
    setError(null);
    load()
      .then((d) => { if (mine === seq.current) setData(d); })
      .catch((err: unknown) => { if (mine === seq.current) setError(errText(err)); });
  }, [tick, ...deps]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, reload };
}

/** 开始训练（同网页 startLive）：带上这个动作开一场训练，再去训练页；出错把说明交回去显示。 */
export async function startLive(body: { exercises?: string[]; free?: boolean }): Promise<void> {
  await api("/iron/api/live/start", { method: "POST", json: body });
  router.push("/live");
}

/** 有没有进行中的训练（有就写"继续训练"）。 */
export async function liveNow(): Promise<boolean> {
  try {
    const r = await api<{ live: unknown }>("/iron/api/live");
    return Boolean(r.live);
  } catch {
    return false;
  }
}

/** 带着一句话去和 IronM 对话（同网页 askCoach）：对话页从 q 参数里取这句话。 */
export function askCoach(question: string): void {
  router.push({ pathname: "/chat", params: { q: question } });
}
