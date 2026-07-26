import { useEffect } from "react";
import { PageTransition } from "../components/PageTransition";
import { ReadmeCards } from "../components/ReadmeCards";
import { IcpFooter } from "../components/IcpFooter";
import { WaterfallGallery } from "../components/WaterfallGallery";
import "./Home.css";

export default function Home() {
  useEffect(() => {
    document.title = "王景宏简历附件";
  }, []);

  return (
    <PageTransition testId="page-home">
      <div className="readme-section">
        <h1>
          👋 你好，我是<span className="accent">王景宏</span>！
        </h1>
        <ReadmeCards />
      </div>
      <div className="main-content">
        <WaterfallGallery />
      </div>
      <IcpFooter />
    </PageTransition>
  );
}
