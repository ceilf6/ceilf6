import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/** 五幕滚动编排:触发式进出场,不 pin、不 snap、不劫持滚动(触控板党的血泪审美)。
    reduced-motion 整体跳过;vitest 环境默认跳过(jsdom 无布局),测试用 force 打开。
    重要:入场初态由 gsap.from 在 JS 侧设置——绝不能写 [data-act-reveal]{opacity:0} 的 CSS,
    否则 /blog 上同属性的 NotesPreview(那里不跑本编排)会永久隐形。 */
export function initScrollActs(root: HTMLElement, { force = false } = {}): () => void {
  if (!force && import.meta.env.VITEST) return () => {};
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => {};
  gsap.registerPlugin(ScrollTrigger);
  const ctx = gsap.context(() => {
    /* clearProps:入场结束即释放 inline transform/opacity——残留的 transform
       会永久压过 CSS 的 hover 效果(画廊卡上浮实证翻车过),交还样式主权。 */
    root.querySelectorAll<HTMLElement>("[data-act-reveal]").forEach((el) => {
      gsap.from(el, {
        opacity: 0,
        y: 44,
        duration: 0.7,
        ease: "power3.out",
        clearProps: "transform,opacity",
        scrollTrigger: { trigger: el, start: "top 78%" },
      });
    });
    const cards = root.querySelectorAll(".gallery .card");
    if (cards.length)
      gsap.from(cards, {
        opacity: 0,
        y: 36,
        duration: 0.55,
        ease: "power3.out",
        stagger: 0.06,
        clearProps: "transform,opacity",
        scrollTrigger: { trigger: ".act-gallery", start: "top 70%" },
      });
    const bg = root.querySelector(".hero-bg");
    if (bg)
      gsap.to(bg, {
        yPercent: 18,
        ease: "none",
        scrollTrigger: { trigger: ".act-hero", start: "top top", end: "bottom top", scrub: true },
      });
  }, root);
  return () => ctx.revert();
}
