import { useEffect, useRef } from "react";
import { samplePoints } from "./nameSampler";

const ASSEMBLE = 1400;
const HOLD = 900;
const DISSOLVE = 1100;

/** 甲·开屏姓名：文字画进离屏 canvas → 像素采样 → 粒子四散汇聚成字、停驻、溶解。
    canvas 2D 拿不到（旧环境/jsdom）立刻 onUnsupported，开屏退回逐字浮现。 */
export function NameParticles({
  text,
  onDone,
  onUnsupported,
}: {
  text: string;
  onDone: () => void;
  onUnsupported: () => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const done = useRef(false);

  useEffect(() => {
    const cv = ref.current;
    const ctx = cv?.getContext("2d");
    if (!cv || !ctx) {
      onUnsupported();
      return;
    }
    let cancelled = false;
    let raf = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const W = window.innerWidth;
    const H = window.innerHeight;
    cv.width = W * dpr;
    cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const start = () => {
      if (cancelled) return;
      const off = document.createElement("canvas");
      off.width = W;
      off.height = H;
      const octx = off.getContext("2d");
      if (!octx) {
        onUnsupported();
        return;
      }
      const size = Math.min(130, W / 5);
      octx.fillStyle = "#fff";
      octx.font = `700 ${size}px "ZCOOL XiaoWei", "KaiTi", serif`;
      octx.textAlign = "center";
      octx.textBaseline = "middle";
      octx.fillText(text, W / 2, H / 2);
      const pts = samplePoints(octx.getImageData(0, 0, W, H), 3);
      if (pts.length === 0) {
        onUnsupported();
        return;
      }
      const ps = pts.map((t) => ({
        ...t,
        x: Math.random() * W,
        y: Math.random() * H,
        vx: 0,
        vy: 0,
        gold: Math.random() < 0.45,
        jit: Math.random() * Math.PI * 2,
      }));
      // t0 不预取:rAF 回调的 now 是帧起点,可早于采样后的 performance.now()——
      // 负 t 会让 lerp 变负把粒子推离目标(真机实测姓名不聚)。首帧就地定零。
      let t0: number | null = null;
      const ease = (u: number) => 1 - Math.pow(1 - u, 3);
      const tick = (now: number) => {
        if (t0 === null) t0 = now;
        const t = now - t0;
        ctx.clearRect(0, 0, W, H);
        const phase = t < ASSEMBLE ? 0 : t < ASSEMBLE + HOLD ? 1 : 2;
        for (const p of ps) {
          let dx = p.x;
          let dy = p.y;
          if (phase === 0) {
            const u = ease(Math.max(0, Math.min(1, t / ASSEMBLE)));
            p.x += (p.tx - p.x) * (0.06 + u * 0.12);
            p.y += (p.ty - p.y) * (0.06 + u * 0.12);
            dx = p.x;
            dy = p.y;
          } else if (phase === 1) {
            // 抖动只进绘制偏移不累积进坐标:呼吸感保留、字形锚定,
            // DISSOLVE 自然从未被污染的真实坐标出发
            dx = p.x + Math.sin(now * 0.002 + p.jit) * 1.5;
            dy = p.y + Math.cos(now * 0.0023 + p.jit) * 1.5;
          } else {
            const u = (t - ASSEMBLE - HOLD) / DISSOLVE;
            p.vx += Math.sin(p.jit) * 0.05 + (Math.random() - 0.5) * 0.04;
            p.vy += -0.055 * u + (Math.random() - 0.5) * 0.04;
            p.x += p.vx;
            p.y += p.vy;
            dx = p.x;
            dy = p.y;
          }
          const alpha = phase === 2 ? Math.max(0, 0.9 * (1 - (t - ASSEMBLE - HOLD) / DISSOLVE)) : 0.9;
          ctx.fillStyle = p.gold
            ? `rgba(255,192,105,${alpha.toFixed(3)})`
            : `rgba(245,248,255,${(alpha * 0.85).toFixed(3)})`;
          ctx.fillRect(dx, dy, 1.7, 1.7);
        }
        if (t >= ASSEMBLE + HOLD + DISSOLVE) {
          if (!done.current) {
            done.current = true;
            onDone();
          }
          return;
        }
        raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    // 等 webfont 就绪再采样，800ms 兜底照跑（楷体系统字形足够形似）
    let kicked = false;
    const kick = () => {
      if (!kicked) {
        kicked = true;
        start();
      }
    };
    document.fonts?.ready.then(kick).catch(kick);
    const timer = setTimeout(kick, 800);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      cancelAnimationFrame(raf);
    };
  }, [text, onDone, onUnsupported]);

  return <canvas ref={ref} className="splash-canvas" aria-hidden="true" />;
}
