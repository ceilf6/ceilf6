import { AuroraCanvas } from "../fx/AuroraCanvas";
import { ParticleField } from "../fx/ParticleField";
import { bioSegments } from "../data/bio";
import "./Hero.css";

/** 第一幕:姓名 + GitHub bio 原文 + 滚动提示;极光/粒子只是背景层,内容全在 DOM。 */
export function Hero() {
  return (
    <div className="hero">
      <div className="hero-bg" aria-hidden="true">
        <AuroraCanvas className="hero-aurora" />
        {/* count 走组件默认值(130,2026-07-28 星空增强),不再显式覆盖 */}
        <ParticleField />
      </div>
      <div className="hero-content">
        <p className="hero-eyebrow">WANGJINGHONG.COM</p>
        <h1 className="hero-name">王景宏</h1>
        <p className="hero-bio">
          {bioSegments().map((s, i) =>
            s.type === "mention" ? (
              <a key={i} className="hero-mention" href={s.href} target="_blank" rel="noopener noreferrer">
                @{s.value}
              </a>
            ) : (
              <span key={i}>{s.value}</span>
            ),
          )}
        </p>
      </div>
      <span className="hero-scroll-hint" aria-hidden="true">↓ 滚动认识我</span>
    </div>
  );
}
