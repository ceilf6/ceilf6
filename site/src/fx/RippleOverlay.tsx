import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { initQuadProgram } from "./webgl";
import { useFxQuality } from "./quality";

/** 乙·画廊波纹:全画廊共享一块 WebGL canvas(浏览器上下文数量有限,禁止每卡一个),
    hover 哪张卡就把它的缩略图(已下载资源,零新增请求)上传为纹理、canvas 移过去。
    DOM <img> 始终在场:触屏/无 WebGL/lite/reduced-motion 下覆盖层完全不激活。 */
const RIPPLE_FRAG = `precision mediump float; varying vec2 uv;
uniform sampler2D tex; uniform vec2 mouse; uniform highp float time; uniform vec2 res;
void main(){
  vec2 tuv = vec2(uv.x, 1.0 - uv.y);
  vec2 auv = tuv * res / min(res.x, res.y);
  vec2 am = mouse * res / min(res.x, res.y);
  float d = distance(auv, am);
  float ripple = sin(d * 42.0 - time * 5.0) * 0.012 * exp(-d * 4.5);
  vec2 dir = d > 0.0001 ? normalize(auv - am) : vec2(0.0);
  vec4 c = texture2D(tex, tuv + dir * ripple);
  c.rgb += vec3(1.0, 0.75, 0.41) * exp(-d * 6.0) * 0.14;
  gl_FragColor = c;
}`;

export function RippleOverlay({ containerRef }: { containerRef: RefObject<HTMLDivElement | null> }) {
  const cvRef = useRef<HTMLCanvasElement>(null);
  const quality = useFxQuality();

  useEffect(() => {
    const host = containerRef.current;
    const cv = cvRef.current;
    if (!host || !cv) return;
    // teardown 清态(评审阻塞项):effect 任何原因重跑(FPS 守卫 full→lite 是实证路径)
    // 或卸载时,canvas 必须回到失活态——否则冻结帧以 opacity:1 永久悬浮在旧位置。
    // 不依赖 WebGL init 成功:守卫早退路径同样返回它,保证任何分支都不留 is-on。
    const deactivate = () => cv.classList.remove("is-on");
    if (quality === "lite") return deactivate;
    if (window.matchMedia("(hover: none)").matches) return deactivate;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return deactivate;
    const prog = initQuadProgram(cv, RIPPLE_FRAG);
    if (!prog) return deactivate;
    const { gl } = prog;
    // 纹理句柄留存:webgl.destroy 只回收 program+buffer,纹理归本组件在 cleanup 释放
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    // 缩略图非 2 幂尺寸:WebGL1 下必须 CLAMP + LINEAR、不 mipmap
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const uMouse = prog.uniform("mouse");
    const uTime = prog.uniform("time");
    const uRes = prog.uniform("res");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let active: HTMLElement | null = null;
    const mouse = { x: 0.5, y: 0.5 };
    const drawFrame = (now: number) => {
      gl.viewport(0, 0, cv.width, cv.height);
      gl.uniform2f(uMouse, mouse.x, mouse.y);
      gl.uniform1f(uTime, now * 0.001);
      gl.uniform2f(uRes, cv.width, cv.height);
      prog.draw();
    };
    const loop = (now: number) => {
      drawFrame(now);
      raf = requestAnimationFrame(loop);
    };
    const leave = () => {
      active = null;
      cv.classList.remove("is-on");
      cancelAnimationFrame(raf);
    };
    const enter = (card: HTMLElement) => {
      const img = card.querySelector("img");
      if (!img || !img.complete || img.naturalWidth === 0) return;
      const cr = card.getBoundingClientRect();
      const hr = host.getBoundingClientRect();
      cv.style.left = `${cr.left - hr.left}px`;
      cv.style.top = `${cr.top - hr.top}px`;
      cv.style.width = `${cr.width}px`;
      cv.style.height = `${cr.height}px`;
      cv.width = cr.width * dpr;
      cv.height = cr.height * dpr;
      try {
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
      } catch {
        // 与 webgl.ts「任一失败→静态降级」口径一致:纹理上传在 handler 里抛
        // (如未来缩略图迁 CDN 引入跨域)不能冒泡成未捕获错误,收敛为失活。
        leave();
        return;
      }
      cv.classList.add("is-on");
      active = card;
      cancelAnimationFrame(raf);
      // resize canvas 已把像素清空:先同步画一帧再排 rAF,消掉激活瞬间的 1 帧空白
      drawFrame(performance.now());
      raf = requestAnimationFrame(loop);
    };
    const onOver = (e: MouseEvent) => {
      const card = (e.target as HTMLElement).closest?.(".card") as HTMLElement | null;
      if (card && card !== active) enter(card);
    };
    const onOut = (e: MouseEvent) => {
      if (!(e.relatedTarget as HTMLElement | null)?.closest?.(".card")) leave();
    };
    const onMove = (e: MouseEvent) => {
      if (!active) return;
      const r = active.getBoundingClientRect();
      mouse.x = (e.clientX - r.left) / r.width;
      mouse.y = (e.clientY - r.top) / r.height;
    };
    // 悬停中改窗口尺寸是罕见路径:失活即无错位,下次 mouseover 会重新定位
    const onResize = () => leave();
    host.addEventListener("mouseover", onOver);
    host.addEventListener("mouseout", onOut);
    host.addEventListener("mousemove", onMove);
    window.addEventListener("resize", onResize);
    return () => {
      // leave 一并清 is-on/active/rAF——不清 is-on 就是「冻结帧永久悬浮」事故本体
      leave();
      window.removeEventListener("resize", onResize);
      host.removeEventListener("mouseover", onOver);
      host.removeEventListener("mouseout", onOut);
      host.removeEventListener("mousemove", onMove);
      gl.deleteTexture(tex);
      prog.destroy();
    };
  }, [containerRef, quality]);

  return <canvas ref={cvRef} className="ripple-overlay" aria-hidden="true" />;
}
