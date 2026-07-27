/** 甲·文字像素采样：把离屏 canvas 上画好的字逐像素扫成粒子目标点。
    结构化入参（非 DOM ImageData 类型）以便单测直接构造。 */

export interface SampleSource {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

export interface SamplePoint {
  tx: number;
  ty: number;
}

export function samplePoints(img: SampleSource, gap: number, alphaThreshold = 128): SamplePoint[] {
  const out: SamplePoint[] = [];
  for (let y = 0; y < img.height; y += gap)
    for (let x = 0; x < img.width; x += gap)
      if (img.data[(y * img.width + x) * 4 + 3] > alphaThreshold) out.push({ tx: x, ty: y });
  return out;
}
