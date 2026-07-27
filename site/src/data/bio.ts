/** Hero 身份文案 = 用户 GitHub bio 原文,一字不改(跨 JD 不变项,2026-07-27 用户拍板)。
    @提及渲染为金色外链;词表外的 @ 保持文本,避免猜错链接。 */

export const BIO =
  "Generalist constantly learning, building and thinking. Founder of @FrontAgent. Currently @bytedance, previously @meituan, @qiniu.";

export const MENTIONS: Record<string, string> = {
  FrontAgent: "https://github.com/ceilf6/FrontAgent",
  bytedance: "https://github.com/bytedance",
  meituan: "https://github.com/meituan",
  qiniu: "https://github.com/qiniu",
};

export interface BioSegment {
  type: "text" | "mention";
  value: string;
  href?: string;
}

export function bioSegments(bio: string = BIO): BioSegment[] {
  const out: BioSegment[] = [];
  const re = /@([A-Za-z0-9-]+)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(bio))) {
    if (m.index > last) out.push({ type: "text", value: bio.slice(last, m.index) });
    const href = MENTIONS[m[1]];
    if (href) out.push({ type: "mention", value: m[1], href });
    else out.push({ type: "text", value: m[0] });
    last = m.index + m[0].length;
  }
  if (last < bio.length) out.push({ type: "text", value: bio.slice(last) });
  return out;
}
