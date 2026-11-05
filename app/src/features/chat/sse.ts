// 读对话的流式回答（同网页版 stream）：服务端一行一个 "data: {...}"，每行一块 JSON；心跳块不要。
// 手机上的 JS 引擎不一定有 TextDecoder，这里自己按 UTF-8 解码，一个汉字被切在两段数据里也能接上。

export type ChatBlock = { type: string; [key: string]: unknown };

/** 流式 UTF-8 解码：每次给一段字节，返回能完整解出来的字，半个字留到下一段。 */
export class Utf8Stream {
  private rest: Uint8Array = new Uint8Array(0);

  decode(chunk: Uint8Array, last = false): string {
    let buf = chunk;
    if (this.rest.length) {
      buf = new Uint8Array(this.rest.length + chunk.length);
      buf.set(this.rest);
      buf.set(chunk, this.rest.length);
      this.rest = new Uint8Array(0);
    }
    const codes: number[] = [];
    let out = "";
    const flush = () => {
      if (codes.length) out += String.fromCodePoint(...codes);
      codes.length = 0;
    };
    let i = 0;
    while (i < buf.length) {
      const b = buf[i];
      const need = b < 0x80 ? 0 : b >= 0xc0 && b < 0xe0 ? 1 : b >= 0xe0 && b < 0xf0 ? 2 : b >= 0xf0 && b < 0xf8 ? 3 : -1;
      if (need < 0) {
        codes.push(0xfffd); // 不该出现在开头的字节
        i += 1;
      } else if (i + need >= buf.length && need > 0) {
        if (last) codes.push(0xfffd);
        else this.rest = buf.slice(i); // 半个字：等下一段
        break;
      } else {
        let cp = need === 0 ? b : b & (0x3f >> need);
        let ok = true;
        for (let k = 1; k <= need; k += 1) {
          const c = buf[i + k];
          if ((c & 0xc0) !== 0x80) {
            ok = false;
            break;
          }
          cp = (cp << 6) | (c & 0x3f);
        }
        if (!ok || cp > 0x10ffff) {
          codes.push(0xfffd);
          i += 1;
        } else {
          codes.push(cp);
          i += need + 1;
        }
      }
      if (codes.length >= 2048) flush();
    }
    flush();
    return out;
  }
}

/** 一行 SSE："data: {...}" → 那块 JSON；别的行、坏的 JSON、心跳都返回 null。 */
export function parseSseLine(raw: string): ChatBlock | null {
  const line = raw.trim();
  if (!line.startsWith("data:")) return null;
  let block: unknown;
  try {
    block = JSON.parse(line.slice(5));
  } catch {
    return null;
  }
  if (!block || typeof block !== "object" || Array.isArray(block)) return null;
  const b = block as ChatBlock;
  if (typeof b.type !== "string" || b.type === "heartbeat") return null;
  return b;
}

/** 把一段段文字拼成行，交出完整的行里的块；最后一行没换行的留着，结束时 end() 交出。 */
export class SseParser {
  private buf = "";

  push(text: string): ChatBlock[] {
    this.buf += text;
    const out: ChatBlock[] = [];
    let i = this.buf.indexOf("\n");
    while (i >= 0) {
      const b = parseSseLine(this.buf.slice(0, i));
      if (b) out.push(b);
      this.buf = this.buf.slice(i + 1);
      i = this.buf.indexOf("\n");
    }
    return out;
  }

  end(): ChatBlock[] {
    const b = parseSseLine(this.buf);
    this.buf = "";
    return b ? [b] : [];
  }
}

type ByteReader = { read(): Promise<{ done: boolean; value?: Uint8Array }> };
export type StreamBody = { getReader(): ByteReader };

/** 从响应体一路读到底，每解出一块就交给 onBlock。 */
export async function readSse(body: StreamBody, onBlock: (b: ChatBlock) => void): Promise<void> {
  const reader = body.getReader();
  const text = new Utf8Stream();
  const lines = new SseParser();
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    if (value) for (const b of lines.push(text.decode(value))) onBlock(b);
  }
  for (const b of lines.push(text.decode(new Uint8Array(0), true))) onBlock(b);
  for (const b of lines.end()) onBlock(b);
}

/** 整段文字一次解析（响应不支持流式读取时的退路）。 */
export function parseSseText(all: string): ChatBlock[] {
  const lines = new SseParser();
  return [...lines.push(all), ...lines.end()];
}
