import { useEffect, useRef } from "react";
import { PageTransition } from "../components/PageTransition";
import { ReadmeCards } from "../components/ReadmeCards";
import { HarnessBanner } from "../components/HarnessBanner";
import { IcpFooter } from "../components/IcpFooter";
import { WaterfallGallery } from "../components/WaterfallGallery";
import { Hero } from "../components/Hero";
import { NotesPreview } from "../components/NotesPreview";
import { startFxProbe } from "../fx/quality";
import "./Home.css";

/** 五幕长卷:Hero → 四卡 → 证书画廊 → 札记精选 → 页脚。
    幕间进出场由 initScrollActs 编排——动态 import 把 gsap 挪出主包与 LCP 路径;
    FPS 探针延迟到 LCP 之后再启动。 */
export default function Home() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = "王景宏 · 个人主页";
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const probe = setTimeout(() => startFxProbe(), 3000);
    let cancelled = false;
    let cleanup: (() => void) | undefined;
    import("../fx/scrollActs").then((m) => {
      if (!cancelled) cleanup = m.initScrollActs(root);
    });
    return () => {
      cancelled = true;
      cleanup?.();
      clearTimeout(probe);
    };
  }, []);

  return (
    <PageTransition testId="page-home">
      <div ref={rootRef} className="long-scroll">
        <section className="act act-hero">
          <Hero />
        </section>
        {/* 窗帘层:hero 钉住(sticky),后续幕作为不透明幕布从其上滑过,幕间背景断层从根上消失 */}
        <div className="acts-curtain">
          <section className="act act-cards" data-act-reveal>
            <div className="readme-section">
              <h2>
                👋 你好，我是<span className="accent">王景宏</span>！
              </h2>
              <ReadmeCards />
              <HarnessBanner />
            </div>
          </section>
          <section className="act act-gallery" data-act-reveal>
            <h2 className="act-title">证书画廊</h2>
            <div className="main-content">
              <WaterfallGallery />
            </div>
          </section>
          <NotesPreview heading="札记精选" max={6} />
          <IcpFooter />
        </div>
      </div>
    </PageTransition>
  );
}
