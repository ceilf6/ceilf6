import { useEffect, useRef } from "react";
import { PageTransition } from "../components/PageTransition";
import { ReadmeCards } from "../components/ReadmeCards";
import { IcpFooter } from "../components/IcpFooter";
import { WaterfallGallery } from "../components/WaterfallGallery";
import { Hero } from "../components/Hero";
import { NotesPreview } from "../components/NotesPreview";
import { initScrollActs } from "../fx/scrollActs";
import { startFxProbe } from "../fx/quality";
import "./Home.css";

/** 五幕长卷:Hero → 四卡 → 证书画廊 → 札记精选 → 页脚。
    幕间进出场由 initScrollActs 编排;FPS 探针延迟到 LCP 之后再启动。 */
export default function Home() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.title = "王景宏 · 个人主页";
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    const probe = setTimeout(() => startFxProbe(), 3000);
    const cleanup = initScrollActs(root);
    return () => {
      clearTimeout(probe);
      cleanup();
    };
  }, []);

  return (
    <PageTransition testId="page-home">
      <div ref={rootRef} className="long-scroll">
        <section className="act act-hero">
          <Hero />
        </section>
        <section className="act act-cards" data-act-reveal>
          <div className="readme-section">
            <h2>
              👋 你好，我是<span className="accent">王景宏</span>！
            </h2>
            <ReadmeCards />
          </div>
        </section>
        <section className="act act-gallery" data-act-reveal>
          <h2 className="act-title">证书画廊</h2>
          <div className="main-content">
            <WaterfallGallery />
          </div>
        </section>
        <NotesPreview heading="札记精选" />
        <IcpFooter />
      </div>
    </PageTransition>
  );
}
