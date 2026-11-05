// 服务地址：开发时连本机的 iron-m（18090），打包时用 EXPO_PUBLIC_API_BASE 换成正式地址（spec §164）。
export const API_BASE = (process.env.EXPO_PUBLIC_API_BASE ?? "http://127.0.0.1:18090").replace(/\/$/, "");
