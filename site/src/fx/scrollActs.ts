import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

/** 五幕滚动编排:触发式进出场,不 snap、不劫持滚动(触控板党的血泪审美)。
    hero 的钉住由 CSS position:sticky 完成(窗帘结构),本编排不再做 hero-bg 视差——
    sticky 下 hero 本身不动,视差与钉住语义冲突。
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
    /* 迟到入场防重闪:chunk 迟到或用户已滚到画廊时(init 晚于内容进视口),
       再跑 stagger 会把正被观看的卡压回 opacity:0 重浮——可见的闪断,整段跳过。
       直接几何判断:act 已与视口相交(top 进入下沿且 bottom 未出上沿)即算已见。 */
    const act = root.querySelector<HTMLElement>(".act-gallery");
    const rect = act?.getBoundingClientRect();
    const galleryInView = !!rect && rect.top < window.innerHeight && rect.bottom > 0;
    const cards = root.querySelectorAll(".gallery .card");
    if (cards.length && !galleryInView)
      gsap.from(cards, {
        opacity: 0,
        y: 36,
        duration: 0.55,
        ease: "power3.out",
        stagger: 0.06,
        clearProps: "transform,opacity",
        scrollTrigger: { trigger: ".act-gallery", start: "top 70%" },
      });
  }, root);
  return () => ctx.revert();
}
