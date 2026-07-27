/** 性能红线的执行器：LCP 后采样 ~2s 帧率，不达标全站动效降档一次（full→lite）。
    只降不升——升档会造成可感知的「突然变卡又变好」抖动。 */
import { useEffect, useState } from "react";

export type FxQuality = "full" | "lite";

export function createFpsMeter({ sampleMs = 2000, threshold = 40 } = {}) {
  let start: number | null = null;
  let frames = 0;
  return {
    frame(now: number): FxQuality | null {
      if (start === null) {
        start = now;
        return null;
      }
      frames++;
      const elapsed = now - start;
      if (elapsed < sampleMs) return null;
      return (frames * 1000) / elapsed < threshold ? "lite" : "full";
    },
  };
}

let quality: FxQuality = "full";
let started = false;
const subs = new Set<(q: FxQuality) => void>();

export function getFxQuality(): FxQuality {
  return quality;
}

export function startFxProbe(sampleMs = 2000, threshold = 40): void {
  if (started || typeof requestAnimationFrame === "undefined") return;
  started = true;
  const meter = createFpsMeter({ sampleMs, threshold });
  const loop = (now: number) => {
    const verdict = meter.frame(now);
    if (verdict === null) {
      requestAnimationFrame(loop);
      return;
    }
    if (verdict === "lite") {
      quality = "lite";
      subs.forEach((s) => s(quality));
    }
  };
  requestAnimationFrame(loop);
}

export function useFxQuality(): FxQuality {
  const [q, setQ] = useState<FxQuality>(quality);
  useEffect(() => {
    subs.add(setQ);
    // 订阅是 passive effect，可能被推迟到探针降档之后；补读一次单例免得漏掉那次广播
    setQ(quality);
    return () => {
      subs.delete(setQ);
    };
  }, []);
  return q;
}

/** 仅供测试重置单例状态 */
export function __resetFxQuality(): void {
  quality = "full";
  started = false;
  subs.clear();
}
