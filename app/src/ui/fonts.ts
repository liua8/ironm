// 手机上载入缝合像素字体（OFL，许可见 assets/fonts/fusion-pixel-LICENSE.txt）：
// 网页用的 woff2 手机不认，本地用 fonttools 转成 otf 随 App 带（spec §164 第四期）。网页见 fonts.web.ts。
import { useFonts } from "expo-font";

import { font } from "./theme";

const FONTS = { [font.pixel]: require("../../assets/fonts/fusion-pixel-12px-zh_hans.otf") };

/** 字体载入好了没有；载入失败也放行，退回系统字体。 */
export function usePixelFont(): boolean {
  const [loaded, error] = useFonts(FONTS);
  return loaded || !!error;
}
