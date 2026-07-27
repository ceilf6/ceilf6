/** 四卡 3D:mousemove → CSS 变量,transform 全走样式层。
    触屏与 reduced-motion 直接不挂——tilt 是 hover 语义。 */
export function attachTilt(el: HTMLElement, maxDeg = 10): () => void {
  if (
    window.matchMedia("(hover: none)").matches ||
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )
    return () => {};
  const move = (e: MouseEvent) => {
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--tilt-ry", `${(px * maxDeg * 2).toFixed(2)}deg`);
    el.style.setProperty("--tilt-rx", `${(-py * maxDeg * 1.6).toFixed(2)}deg`);
    el.style.setProperty("--gx", `${((px + 0.5) * 100).toFixed(1)}%`);
    el.style.setProperty("--gy", `${((py + 0.5) * 100).toFixed(1)}%`);
  };
  const leave = () => {
    el.style.setProperty("--tilt-ry", "0deg");
    el.style.setProperty("--tilt-rx", "0deg");
  };
  el.addEventListener("mousemove", move);
  el.addEventListener("mouseleave", leave);
  return () => {
    el.removeEventListener("mousemove", move);
    el.removeEventListener("mouseleave", leave);
    leave();
  };
}
