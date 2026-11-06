// IronM 头像（§175 需求 3，同网页版 mech）：自己画的黄色胖企鹅——纯黄、浅黄圆肚子、头顶一滴牛奶；不仿现成角色。
import { View } from "react-native";
import Svg, { Circle, Ellipse, Path } from "react-native-svg";

export function Mascot({ size = 34 }: { size?: number }) {
  return (
    // 读屏跳过：属性放外层 View（直接写在 Svg 上，网页预览会原样塞进 DOM 报警告）
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={size} height={size} viewBox="0 0 64 64">
        <Path d="M19.5 37 C15.5 41 15.5 46.5 18.5 49.5 C20 50.5 21.8 49.6 21.6 47.6 Z M44.5 37 C48.5 41 48.5 46.5 45.5 49.5 C44 50.5 42.2 49.6 42.4 47.6 Z" fill="#f4b400" stroke="#d49600" strokeWidth={0.8} />
        <Path d="M32 12 C22.5 12 19.5 19.5 19.5 26.5 C19.5 33.5 12.5 38.5 12.5 47.5 C12.5 57.5 21.5 62.5 32 62.5 C42.5 62.5 51.5 57.5 51.5 47.5 C51.5 38.5 44.5 33.5 44.5 26.5 C44.5 19.5 41.5 12 32 12 Z" fill="#ffd83d" stroke="#e0a800" strokeWidth={1} />
        <Ellipse cx="32" cy="48" rx="13" ry="11.5" fill="#ffefa6" />
        <Ellipse cx="26.5" cy="24.5" rx="2.2" ry="2.6" fill="#2a2420" />
        <Ellipse cx="37.5" cy="24.5" rx="2.2" ry="2.6" fill="#2a2420" />
        <Circle cx="27.2" cy="23.6" r="0.8" fill="#fff" />
        <Circle cx="38.2" cy="23.6" r="0.8" fill="#fff" />
        <Ellipse cx="23" cy="29" rx="2.4" ry="1.3" fill="#ffae8a" opacity={0.75} />
        <Ellipse cx="41" cy="29" rx="2.4" ry="1.3" fill="#ffae8a" opacity={0.75} />
        <Path d="M29.8 27.6 C31 26.8 33 26.8 34.2 27.6 C33.6 29.2 32.8 29.9 32 29.9 C31.2 29.9 30.4 29.2 29.8 27.6 Z" fill="#ff9f2e" stroke="#e07f10" strokeWidth={0.5} />
        <Path d="M32 2.5 C30.4 5.8 28.4 7.8 28.4 10.2 C28.4 12.3 30 13.8 32 13.8 C34 13.8 35.6 12.3 35.6 10.2 C35.6 7.8 33.6 5.8 32 2.5 Z" fill="#fff" stroke="#cbd5dd" strokeWidth={0.8} />
      </Svg>
    </View>
  );
}
