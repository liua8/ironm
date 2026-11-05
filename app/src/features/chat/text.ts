// 对话里给人看的文字（同网页版对话页、服务端 checks.plain）：去掉内部编号和出处标签，
// 把回答切成段落和列表行，时间写成"今天 08:30"这样。都是纯函数，方便测试。

// 内部编号：依据〔K03〕、计算〔C1〕、经验〔经验〕、记忆〔m20〕、数据行〔r3〕……一律不给用户看（spec §82 需求 4）
const ANY_MARK = /〔[^〔〕\n]{1,12}〕/g;
const CITE = /<cite>[\s\S]*?<\/cite>/g;
const STATEMENT_TAG = /<\/?statement>/g;
const SPACE_BEFORE_PUNCT = /[ \t]+([，。！？；：、）])/g;
// 删掉编号后前后标点挨在一起（"提醒一句：，先别…"）：留后面那个句末标点
const LOOSE_PUNCT = /[，、；：,]+([。！？；])|([，、；：])[，、；：,]+|([。！？])[。]+/g;
// 还在流式输出时，末尾可能停在半个编号或半个标签上（"……加重 2–10%〔K0"），先藏起来，等后面的字到了再看
const PARTIAL_MARK = /〔[^〔〕\n]{0,12}$/;
const PARTIAL_TAG = /<\/?[a-z]*$/;
const OPEN_CITE = /<cite>(?:(?!<\/cite>)[\s\S])*$/;  // 只开了头、还没收尾的 <cite>

/** 给用户看的正文：去掉内部编号和标签，只留话本身。partial=true 表示还在输出，末尾半截的编号先不显示。 */
export function cleanText(text: string, partial = false): string {
  let out = String(text ?? "");
  if (partial) out = out.replace(OPEN_CITE, "").replace(PARTIAL_MARK, "").replace(PARTIAL_TAG, "");
  out = out.replace(ANY_MARK, "").replace(CITE, "").replace(STATEMENT_TAG, "");
  out = out.replace(SPACE_BEFORE_PUNCT, "$1").replaceAll("（）", "").replaceAll("()", "");
  out = out.replace(LOOSE_PUNCT, (_m, a?: string, b?: string, c?: string) => a || b || c || "");
  return out.trim();
}

export type Span = { text: string; bold: boolean };
export type Line = { kind: "text" | "bullet" | "num" | "head"; mark: string; spans: Span[] };
export type Para = Line[];

/** 一行里的 **加粗**。 */
export function spans(line: string): Span[] {
  const out: Span[] = [];
  const re = /\*\*(.+?)\*\*/g;
  let at = 0;
  for (let m = re.exec(line); m; m = re.exec(line)) {
    if (m.index > at) out.push({ text: line.slice(at, m.index), bold: false });
    out.push({ text: m[1], bold: true });
    at = m.index + m[0].length;
  }
  if (at < line.length) out.push({ text: line.slice(at), bold: false });
  return out.length ? out : [{ text: "", bold: false }];
}

/** 回答切成段落（空行分段）；段里每一行认出列表（- 、• 、1. 、1、）和小标题（# 开头）。 */
export function paragraphs(text: string): Para[] {
  return text
    .trim()
    .split(/\n{2,}/)
    .map((p) =>
      p
        .split("\n")
        .filter((line) => line.trim())
        .map((raw): Line => {
          const line = raw.trim();
          const head = line.match(/^#{1,6}\s+(.*)$/);
          if (head) return { kind: "head", mark: "", spans: [{ text: head[1].replace(/\*\*/g, ""), bold: true }] };
          const bullet = line.match(/^[-•*·]\s+(.*)$/);
          if (bullet) return { kind: "bullet", mark: "•", spans: spans(bullet[1]) };
          const num = line.match(/^(\d{1,2})[.、)）]\s*(.+)$/);
          if (num) return { kind: "num", mark: `${num[1]}.`, spans: spans(num[2]) };
          return { kind: "text", mark: "", spans: spans(line) };
        }),
    )
    .filter((p) => p.length);
}

const pad2 = (n: number) => String(n).padStart(2, "0");
const isoDay = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;

/** 提问、回答、以前的对话的时间：今天的写"今天 08:30"，别的天写"11月3日 08:30"。 */
export function sessionTime(ts: string | undefined, now: Date = new Date()): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return "";
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
  return isoDay(d) === isoDay(now) ? `今天 ${hm}` : `${d.getMonth() + 1}月${d.getDate()}日 ${hm}`;
}

/** "2026-11-03" → "11月3日"。 */
export function monthDay(iso: string): string {
  const m = String(iso || "").match(/^\d{4}-(\d{2})-(\d{2})/);
  return m ? `${Number(m[1])}月${Number(m[2])}日` : "";
}
