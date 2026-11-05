// 网页预览载入缝合像素字体（OFL，woff2）。手机上见 fonts.ts。
import { useFonts } from "expo-font";

import { font } from "./theme";

const FONTS = { [font.pixel]: require("../../assets/fonts/fusion-pixel-12px-zh_hans.woff2") };

/** 字体载入好了没有；载入失败也放行，退回系统字体。 */
export function usePixelFont(): boolean {
  const [loaded, error] = useFonts(FONTS);
  return loaded || !!error;
}
