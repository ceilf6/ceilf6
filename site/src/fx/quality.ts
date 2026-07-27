/** 性能红线的执行器：LCP 后采样 ~2s 帧率，不达标全站动效降档一次（full→lite）。
    只降不升——升档会造成可感知的「突然变卡又变好」抖动。 */
import { useEffect, useState } from "react";

export type FxQuality = "full" | "lite";

export function createFpsMeter({
  sampleMs = 2000,
  threshold = 40,
  maxFrameMs = 200,
} = {}) {
  let last: number | null = null;
  let elapsed = 0;
  let frames = 0;
  return {
    frame(now: number): FxQuality | null {
      if (last === null) {
        last = now;
        return null;
      }
      // 单帧间隔按 maxFrameMs 封顶：标签页挂起、shader 编译这类停摆不是稳态帧率。
      // 不封顶的话一次 5s 空档会被算成 0.2fps，而降档只降不升、误判无法回滚。
      // 200ms(=5fps)远低于任何真实帧距，封顶不会遮蔽真卡顿。
      // 已知盲区：周期性长帧(如每 30 帧一次 800ms 停顿)会被判 full。方向偏保守是
      // 有意取舍——误 full 下次进站可自愈，误 lite 只降不升、不可回滚。
      elapsed += Math.min(now - last, maxFrameMs);
      last = now;
      frames++;
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
