import { useEffect, useRef } from "react";
import { createField, linkPairs, rescaleField, stepField } from "./particles";
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
    let rectLeft = 0;
    let rectTop = 0;
    const resize = () => {
      const r = cv.getBoundingClientRect();
      rectLeft = r.left;
      rectTop = r.top;
      w = Math.max(1, r.width);
      h = Math.max(1, r.height);
      cv.width = w * dpr;
      cv.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ps = createField(n, w, h, Math.random);
    const mouse = { x: -1e4, y: -1e4 };
    // rect 用 resize 时的缓存,省逐 mousemove 的 getBoundingClientRect 强制回流。
    // 取舍:滚动会让缓存的 top 漂移,但 hero 铺满首屏、引力半径又有 130px,偏差不可感知。
    const onMove = (e: MouseEvent) => {
      mouse.x = e.clientX - rectLeft;
      mouse.y = e.clientY - rectTop;
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
    // 不能把重分布/补帧塞进 resize 本体:首挂载调 resize() 时 ps/draw 还在 TDZ
    const onResize = () => {
      const ow = w;
      const oh = h;
      resize();
      rescaleField(ps, ow, oh, w, h);
      if (quality !== "full") draw(); // lite 无 rAF 补帧,而 cv.width 赋值已清空画布,必须手动补一帧
    };
    window.addEventListener("resize", onResize);
    cv.addEventListener("mousemove", onMove);
    cv.addEventListener("mouseleave", onLeave);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      cv.removeEventListener("mousemove", onMove);
      cv.removeEventListener("mouseleave", onLeave);
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [count, quality]);

  return <canvas ref={ref} className="particle-field" aria-hidden="true" />;
}
