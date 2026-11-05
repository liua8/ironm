// 底部标签的图标：和网页版同一套线条（Lucide 风格，网页版 ICONS 里的 hexhome、atlas、record、pilot）。
import Svg, { Circle, Path, Polygon, Rect } from "react-native-svg";

export type IconName = "home" | "atlas" | "record" | "me" | "camera"; // camera：拍照的按钮（§164 第四期）

export function Icon({ name, size = 24, color }: { name: IconName; size?: number; color: string }) {
  const stroke = { stroke: color, strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === "home" && (
        <>
          <Polygon points="12,2 21,7 21,17 12,22 3,17 3,7" {...stroke} />
          <Circle cx="12" cy="12" r="3" {...stroke} />
        </>
      )}
      {name === "atlas" && (
        <>
          <Rect x="4" y="3" width="16" height="18" rx="1" {...stroke} />
          <Path d="M8 8h8M8 12h8M8 16h5" {...stroke} />
        </>
      )}
      {name === "record" && <Path d="M4 20V10M10 20V4M16 20V13M22 20H2" {...stroke} />}
      {name === "camera" && (
        <>
          <Path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" {...stroke} />
          <Circle cx="12" cy="13" r="3" {...stroke} />
        </>
      )}
      {name === "me" && (
        <>
          <Path d="M7 4h10l2 6-7 10-7-10z" {...stroke} />
          <Path d="M9 10h6" {...stroke} />
        </>
      )}
    </Svg>
  );
}
