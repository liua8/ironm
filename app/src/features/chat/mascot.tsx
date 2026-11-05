// IronM 头像（§121 需求 5，同网页版 mech）：自己画的头盔，绿色面罩、钛金天线、下巴绿灯。
import { useId } from "react";
import { View } from "react-native";
import Svg, { Defs, LinearGradient, Path, Rect, Stop } from "react-native-svg";

export function Mascot({ size = 34 }: { size?: number }) {
  // 同一页有好几个头像：渐变的编号各用各的（冒号在 url(#…) 里不认，去掉）
  const id = `mh${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  return (
    // 读屏跳过：属性放外层 View（直接写在 Svg 上，网页预览会原样塞进 DOM 报警告）
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Defs>
        <LinearGradient id={`${id}a`} x1="0" y1="0" x2="1" y2="1">
          <Stop offset="0" stopColor="#6a645b" />
          <Stop offset="0.45" stopColor="#3a3530" />
          <Stop offset="1" stopColor="#1a1715" />
        </LinearGradient>
        <LinearGradient id={`${id}b`} x1="0" y1="0" x2="1" y2="0">
          <Stop offset="0" stopColor="#0a7f4b" />
          <Stop offset="0.5" stopColor="#7ff0b8" />
          <Stop offset="1" stopColor="#0a7f4b" />
        </LinearGradient>
      </Defs>
      <Path d="M32 3 L35 10 L29 10 Z" fill="#e2b866" />
      <Path d="M14 18 L22 9 L42 9 L50 18 L53 34 L48 47 L40 55 L24 55 L16 47 L11 34 Z" fill={`url(#${id}a)`} stroke="#8c857a" strokeWidth={1} />
      <Path d="M22 9 L32 14 L42 9" fill="none" stroke="#8c857a" strokeWidth={0.8} />
      <Path d="M15 27 L49 27 L47 35 L17 35 Z" fill="#0a0908" stroke="#4a4238" strokeWidth={0.8} />
      <Rect x="16" y="27.5" width="32" height="7" rx="3" fill="#12b76a" opacity={0.3} />
      <Rect x="18" y="29" width="28" height="4" rx="1" fill={`url(#${id}b)`} />
      <Path d="M8 26 L12 24 L12 40 L8 38 Z M56 26 L52 24 L52 40 L56 38 Z" fill="#2a2622" stroke="#6e685e" strokeWidth={0.8} />
      <Path d="M9 29 H11 M9 32 H11 M9 35 H11 M53 29 H55 M53 32 H55 M53 35 H55" stroke="#12b76a" strokeWidth={0.8} opacity={0.8} />
      <Path d="M24 43 L40 43 L37 50 L27 50 Z" fill="#1f1c19" stroke="#6e685e" strokeWidth={0.8} />
      <Path d="M28 46 H36" stroke="#7cff4f" strokeWidth={1} />
    </Svg>
    </View>
  );
}
