import { useEffect, useRef } from "react";
import { createField, linkPairs, stepField } from "./particles";
import { useFxQuality } from "./quality";

/** 星座粒子画布。降级阶梯：reduced-motion→不渲染；lite→静态一帧；
    移动端粒子减半；tab 隐藏暂停 rAF；DPR 上限 2。父容器需 position:relative。 */
export function ParticleField({ count = 70 }: { count?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const quality = useFxQuality();

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const n = window.matchMedia("(max-width: 768px)").matches ? Math.floor(count / 2) : count;
    let w = 1;
    let h = 1;
    const resize = () => {
      const r = cv.getBoundingClientRect();
      w = Math.max(1, r.width);
      h = Math.max(1, r.height);
      cv.width = w * dpr;
      cv.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ps = createField(n, w, h, Math.random);
    const mouse = { x: -1e4, y: -1e4 };
    const onMove = (e: MouseEvent) => {
      const r = cv.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    };
    const onLeave = () => {
      mouse.x = -1e4;
      mouse.y = -1e4;
    };
    const draw = () => {
      ctx.clearRect(0, 0, w, h);
      for (const [i, j, a] of linkPairs(ps, 90)) {
        ctx.strokeStyle = `rgba(255,192,105,${(a * 0.32).toFixed(3)})`;
        ctx.lineWidth = 0.7;
        ctx.beginPath();
        ctx.moveTo(ps[i].x, ps[i].y);
        ctx.lineTo(ps[j].x, ps[j].y);
        ctx.stroke();
      }
      for (const p of ps) {
        ctx.fillStyle = p.gold ? "rgba(255,192,105,.95)" : "rgba(245,248,255,.8)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fill();
      }
    };
    let raf = 0;
    let last = performance.now();
    const loop = (now: number) => {
      stepField(ps, w, h, mouse, Math.min(now - last, 50));
      last = now;
      draw();
      raf = requestAnimationFrame(loop);
    };
    const onVis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && quality === "full") {
        last = performance.now();
        raf = requestAnimationFrame(loop);
      }
    };
    if (quality === "full") raf = requestAnimationFrame(loop);
    else draw(); // lite：静态一帧当氛围底
    window.addEventListener("resize", resize);
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("mouseleave", onLeave);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      cv.removeEventListener("mousemove", onMove);
      cv.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [count, quality]);

  return <canvas ref={ref} className="particle-field" aria-hidden="true" />;
}
