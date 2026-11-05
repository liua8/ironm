// 训练相关的小图标：和网页版 ICONS 同一套线条（Lucide 风格）。
import Svg, { Circle, Path } from "react-native-svg";

const PATHS = {
  timer: ["M12 9v4l2 2", "M10 2h4"],
  check: ["M20 6 9 17l-5-5"],
  x: ["M18 6 6 18", "m6 6 12 12"],
  up: ["m18 15-6-6-6 6"],
  down: ["m6 9 6 6 6-6"],
  plus: ["M5 12h14", "M12 5v14"],
  back: ["m15 18-6-6 6-6"],
  chevron: ["m9 18 6-6-6-6"],
  edit: ["M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z", "m15 5 4 4"],
  alert: ["m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3", "M12 9v4", "M12 17h.01"],
  bell: ["M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.94 1.94 0 0 0 3.4 0"],
  mute: ["M6 8a6 6 0 0 1 9.3-5", "M18 8c0 7 3 9 3 9H9", "M10.3 21a1.94 1.94 0 0 0 3.4 0", "m2 2 20 20"],
  trophy: ["M6 9H4.5a2.5 2.5 0 0 1 0-5H6", "M18 9h1.5a2.5 2.5 0 0 0 0-5H18", "M4 22h16", "M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22", "M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22", "M18 2H6v7a6 6 0 0 0 12 0V2Z"],
} as const;

export type LiveIconName = keyof typeof PATHS;

export function LiveIcon({ name, size = 18, color }: { name: LiveIconName; size?: number; color: string }) {
  const stroke = { stroke: color, strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === "timer" ? <Circle cx="12" cy="13" r="8" {...stroke} /> : null}
      {PATHS[name].map((d) => <Path key={d} d={d} {...stroke} />)}
    </Svg>
  );
}
