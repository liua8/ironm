// 底部标签和几处按钮的图标：和网页版同一套线条（Lucide 造型，ISC 许可，网页版 ICONS 里的 dumbbell、bubble、book、bars、user，§175）。
import Svg, { Circle, Path, Rect } from "react-native-svg";

export type IconName = "home" | "chat" | "atlas" | "record" | "me" | "camera" | "coach" | "bell" | "info" | "wave" | "upload" | "note" | "sun"; // 后几个是"我"里各行的图标（§176）

export function Icon({ name, size = 24, color }: { name: IconName; size?: number; color: string }) {
  const stroke = { stroke: color, strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24">
      {name === "home" && (
        <>
          <Path d="M17.596 12.768a2 2 0 1 0 2.829-2.829l-1.768-1.767a2 2 0 0 0 2.828-2.829l-2.828-2.828a2 2 0 0 0-2.829 2.828l-1.767-1.768a2 2 0 1 0-2.829 2.829z" {...stroke} />
          <Path d="m2.5 21.5 1.4-1.4" {...stroke} />
          <Path d="m20.1 3.9 1.4-1.4" {...stroke} />
          <Path d="M5.343 21.485a2 2 0 1 0 2.829-2.828l1.767 1.768a2 2 0 1 0 2.829-2.829l-6.364-6.364a2 2 0 1 0-2.829 2.829l1.768 1.767a2 2 0 0 0-2.828 2.829z" {...stroke} />
          <Path d="m9.6 14.4 4.8-4.8" {...stroke} />
        </>
      )}
      {name === "chat" && <Path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" {...stroke} />}
      {name === "atlas" && (
        <>
          <Path d="M12 7v14" {...stroke} />
          <Path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" {...stroke} />
        </>
      )}
      {name === "record" && (
        <>
          <Path d="M3 3v16a2 2 0 0 0 2 2h16" {...stroke} />
          <Path d="M18 17V9M13 17V5M8 17v-3" {...stroke} />
        </>
      )}
      {name === "camera" && (
        <>
          <Path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" {...stroke} />
          <Circle cx="12" cy="13" r="3" {...stroke} />
        </>
      )}
      {name === "coach" && (
        <>
          <Path d="M12 8V4H8M2 14h2M20 14h2M15 13v2M9 13v2" {...stroke} />
          <Rect width="16" height="12" x="4" y="8" rx="2" {...stroke} />
        </>
      )}
      {name === "bell" && <Path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 0 0 3.4 0" {...stroke} />}
      {name === "info" && (
        <>
          <Circle cx="12" cy="12" r="10" {...stroke} />
          <Path d="M12 16v-4M12 8h.01" {...stroke} />
        </>
      )}
      {name === "wave" && <Path d="M22 12h-4l-3 9L9 3l-3 9H2" {...stroke} />}
      {name === "upload" && <Path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" {...stroke} />}
      {name === "note" && <Path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7ZM14 2v4a2 2 0 0 0 2 2h4M10 9H8M16 13H8M16 17H8" {...stroke} />}
      {name === "sun" && (
        <>
          <Circle cx="12" cy="12" r="4" {...stroke} />
          <Path d="M12 2v2M12 20v2m-7.07-17.07 1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" {...stroke} />
        </>
      )}
      {name === "me" && (
        <>
          <Path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" {...stroke} />
          <Circle cx="12" cy="7" r="4" {...stroke} />
        </>
      )}
    </Svg>
  );
}
