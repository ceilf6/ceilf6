import { useEffect } from "react";
import { PageTransition } from "../components/PageTransition";
import { WaterfallGallery } from "../components/WaterfallGallery";
import "./Awards.css";

export default function Awards() {
  useEffect(() => {
    document.title = "王景宏 · 证书画廊";
  }, []);

  return (
    <PageTransition testId="page-awards">
      <main className="awards-page">
        <h1 className="awards-title">证书画廊</h1>
        <div className="main-content">
          <WaterfallGallery />
        </div>
      </main>
    </PageTransition>
  );
}
