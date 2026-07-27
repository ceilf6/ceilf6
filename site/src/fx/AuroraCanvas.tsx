import { useEffect, useRef, useState } from "react";
import { initQuadProgram } from "./webgl";
import { useFxQuality } from "./quality";

/** 手写片元着色器极光：四团金/紫/暖橙/靛蓝高斯光斑在深蓝底上缓慢游移。
    颜色与 tokens 同源（#0b1226 底、#ffc069 金、#ff9a62 暖橙）；
    靛蓝 vec3(0.31,0.51,1.0)=#4f82ff 为极光补色，非 tokens 命名色。
    time 单独 highp：移动 GPU mediump=fp16，几分钟后精度不足产生可见跳变。
    构图按 aspect 做相似变换（中心 x、漂移振幅、半径全乘 a，y 向不动）：
    窄屏时斑随宽度等比变小变散，防四斑叠加成亮雾压垮前景文字对比度。 */
const AURORA_FRAG = `precision mediump float; varying vec2 uv;
uniform highp float time; uniform vec2 res;
vec3 blob(vec2 p, vec2 c, vec3 col, float r){ float d = distance(p, c); return col * exp(-d*d/(r*r)); }
void main(){
  float a = res.x / res.y;
  vec2 p = uv; p.x *= a;
  vec3 col = vec3(0.043, 0.071, 0.149);
  col += blob(p, vec2((0.35 + 0.12*sin(time*0.21))*a, 0.55 + 0.10*cos(time*0.17)), vec3(1.0, 0.75, 0.41)*0.50, 0.34*a);
  col += blob(p, vec2((0.95 + 0.15*cos(time*0.13))*a, 0.45 + 0.12*sin(time*0.19)), vec3(0.75, 0.57, 0.95)*0.45, 0.40*a);
  col += blob(p, vec2((0.65 + 0.18*sin(time*0.11))*a, 0.85 + 0.10*cos(time*0.23)), vec3(1.0, 0.60, 0.38)*0.40, 0.30*a);
  col += blob(p, vec2((1.25 + 0.10*sin(time*0.16))*a, 0.75), vec3(0.31, 0.51, 1.0)*0.35, 0.42*a);
  gl_FragColor = vec4(col, 1.0);
}`;

export function AuroraCanvas({ className = "" }: { className?: string }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  const quality = useFxQuality();

  useEffect(() => {
    const cv = ref.current;
    if (!cv || failed) return;
    if (quality === "lite" || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setFailed(true);
      return;
    }
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      const r = cv.getBoundingClientRect();
      cv.width = Math.max(1, r.width * dpr);
      cv.height = Math.max(1, r.height * dpr);
    };
    resize();
    const prog = initQuadProgram(cv, AURORA_FRAG);
    if (!prog) {
      setFailed(true);
      return;
    }
    // uniform() 每次调用都查驱动，必须在 rAF 循环外 hoist
    const uTime = prog.uniform("time");
    const uRes = prog.uniform("res");
    let raf = 0;
    const loop = (now: number) => {
      prog.gl.viewport(0, 0, cv.width, cv.height);
      prog.gl.uniform1f(uTime, now * 0.001);
      prog.gl.uniform2f(uRes, cv.width, cv.height);
      prog.draw();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    const onVis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) raf = requestAnimationFrame(loop);
    };
    // ResizeObserver 而非 window resize：元素级布局变化（开屏遮罩卸载、容器动画结束）
    // 不派发 window resize；RO 也天然覆盖窗口缩放。补帧不需要——rAF 每帧重设 viewport 重画。
    const ro = new ResizeObserver(resize);
    ro.observe(cv);
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
      prog.destroy();
    };
  }, [failed, quality]);

  if (failed) return <div className={`${className} aurora-fallback`} aria-hidden="true" />;
  return <canvas ref={ref} className={className} aria-hidden="true" />;
}
