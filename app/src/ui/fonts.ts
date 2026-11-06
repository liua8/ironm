// §175 起不再加载像素字体（字体文件已删），都用系统字体。保留这个钩子，调用处不用改。
/** 字体好了没有：系统字体不用等。 */
export function usePixelFont(): boolean {
  return true;
}
