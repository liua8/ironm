// 白底圆角卡片风（spec [2026-10-23] §175、§176）：颜色和网页版 style.css 的同一套。
// 旧的像素农场色名（grass、paper、wood……）保留，值换成新的一套，各页的样式不用逐个改名：
// grass = 页底，paper = 卡片，paperLight = 浅底，wood* = 细线，plank = 选中的深珊瑚红底（上面写白字），amber = 浅珊瑚红底。
export const color = {
  grass: "#f6f4fa",
  grassDark: "#ebe8f3",
  paper: "#ffffff",
  paperLight: "#f6f5fa",
  ink: "#1d1d26",
  ink2: "#474757",
  muted: "#757588",
  accent: "#f2603f",
  accentText: "#cc4125",
  accentInk: "#ffffff",
  accentSoft: "#fdece7",
  fire: "#d2452a",
  heat: "#d63b40",
  heatSoft: "#fdecec",
  wood: "#ebebf2",
  woodDark: "#e2e2ec",
  woodLight: "#f1f1f6",
  plank: "#d2452a",
  amber: "#fdece7",
  good: "#1e8a47",
  goodSoft: "#dff5e6",
  iconBg: "#eeebfa",
} as const;

export const font = {
  pixel: "System",  // §175 起不再用像素字；留着名字，旧样式里引用到也是系统字
} as const;

export const radius = { s: 14, m: 22, pill: 999 } as const;

export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24 } as const;

/** 卡片的淡阴影（手机和网页都认）。 */
export const shadow = {
  shadowColor: "#281e3c",
  shadowOpacity: 0.06,
  shadowRadius: 14,
  shadowOffset: { width: 0, height: 4 },
  elevation: 2,
} as const;
