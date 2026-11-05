// 排行榜的地址（同网页 tierHref / itemHref）：/rank 首页、/rank/<榜>（动作榜 ?part=部位）、/rank/<榜>/<条目>。
import { type Href, router } from "expo-router";

export function boardHref(board: string, part = ""): Href {
  return part ? { pathname: "/rank/[board]", params: { board, part } } : { pathname: "/rank/[board]", params: { board } };
}

export function itemHref(board: string, key: string): Href {
  return { pathname: "/rank/[board]/[item]", params: { board, item: key } };
}

/** 返回：有上一页回上一页，直接打开的回到 fallback。 */
export function goBack(fallback: Href): void {
  if (router.canGoBack()) router.back();
  else router.replace(fallback);
}

/** 地址参数可能是数组，取第一个。 */
export function one(v: string | string[] | undefined): string {
  return (Array.isArray(v) ? v[0] : v) ?? "";
}
