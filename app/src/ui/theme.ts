// 像素农场风（spec [2026-11-03] §131）：颜色和网页版 style.css 的同一套；像素字只给大字（§135），字号用 12 的整数倍。
export const color = {
  grass: "#7ec850",
  grassDark: "#74bd48",
  paper: "#f7e2a8",
  paperLight: "#fbefc8",
  ink: "#4a2a10",
  muted: "#7a5432",
  accent: "#5da130",
  accentText: "#336a14",
  accentInk: "#fff6d8",
  fire: "#3e7a1c",
  heat: "#b5341f",
  heatSoft: "#f6d9cf",
  wood: "#8a4b1c",
  woodDark: "#5a2e0e",
  woodLight: "#e4b868",
  plank: "#b8692a",
  amber: "#f2c14e",
  goodSoft: "#e4f2c8",
} as const;

export const font = {
  pixel: "FusionPixel",
} as const;

export const space = { xs: 4, s: 8, m: 12, l: 16, xl: 24 } as const;
