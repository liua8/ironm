// 首页·练、训练计划用到的接口数据（照 iron-m 的 /iron/api/brief、training、week、exercises、train-images、today）。
// 只写页面用到的字段。

export type PlanItem = { exercise: string; sets: number; reps: string; load?: string; note?: string };
export type Session = { day: number; name: string; minutes: number; items: PlanItem[] };
export type Plan = { title: string; goal?: string; days_per_week: number; sessions: Session[] };

export type Target = { text: string; why: string; action: string; weight_kg?: number | null; reps?: number | null; sets?: number | null; by?: string };
export type Workout = { id: string; day: string; done?: boolean; rest?: string | null; session?: string; line?: string };
export type Training = { plan: Plan | null; plan_lines?: string[]; targets: Record<string, Target>; workouts: Workout[] };

export type Warmup = { minutes: number; steps: string[]; basis: string };
export type Burn = { low: number; high: number; how: string };
export type WeekDay = {
  date: string;
  weekday: string;
  today: boolean;
  past?: boolean;
  done: boolean;
  session: Session | null;
  version: Session | null;
  changes: string[];
  reasons?: string[];
  edited: string[];
  warmup: Warmup | null;
  burn: Burn | null;
};
export type Week = { days: WeekDay[]; sick?: { mode?: string; why?: string } | null };

export type BriefTraining = { kind: string; name?: string; minutes?: number; done?: boolean; text?: string };
export type Brief = {
  today?: { training?: BriefTraining };
  week?: { planned?: number; due?: number; done?: number };
  alerts?: { key: string; title: string; text: string }[];
};

export type ImageRef = { url: string; author?: string; license?: string; page?: string };
export type Exercise = {
  id: string;
  name: string;
  part: string;
  muscles: string;
  equipment: string[];
  cues?: string[];
  timed?: boolean;
  images?: ImageRef[];
  gif?: ImageRef | null;
};
export type Library = { exercises: Exercise[] };
export type TrainImages = { images: Record<string, ImageRef> };

export type TodayVersion =
  | { status: "ok"; original: Session; today: Session; changed: boolean; changes: string[]; reasons: string[] }
  | { status: string; message?: string; why?: string };
