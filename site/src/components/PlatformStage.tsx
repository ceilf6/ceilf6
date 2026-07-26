import { useEffect } from "react";
import type { CSSProperties } from "react";
import { motion, useReducedMotion, type Variants } from "framer-motion";
import { Link } from "react-router";
import type { StageData } from "../data/platforms";
import "./PlatformStage.css";

/** react-router 的 Link 套上 motion，才能进 stagger 队列且不额外包一层 DOM。
    必须在组件外创建，否则每次渲染都是新组件类型、子树会重挂载。 */
const MotionLink = motion.create(Link);

/** 旧站靠 .reveal + .d1–.d6 的 animation-delay 排进场顺序，这里换成 stagger 统一发牌：
    容器只负责节拍，子项各自位移淡入，节奏与旧站的 0.05→0.66s 阶梯相近。 */
const containerVariants: Variants = {
  hidden: {},
  show: { transition: { delayChildren: 0.05, staggerChildren: 0.08 } },
};

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 18 },
  show: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.5, ease: [0.22, 1, 0.36, 1] },
  },
};

/** 旧站在 prefers-reduced-motion 下把 .reveal 直接钉成终态；JS 动画不吃 CSS 媒体查询，
    所以这里显式换一套「原地显形」的变体，行为与旧站对齐。 */
const staticVariants: Variants = {
  hidden: { opacity: 1, y: 0 },
  show: { opacity: 1, y: 0 },
};

export function PlatformStage({
  eyebrow,
  headline,
  subtitle,
  docTitle,
  platforms,
}: StageData) {
  const reduceMotion = useReducedMotion();
  const item = reduceMotion ? staticVariants : itemVariants;

  useEffect(() => {
    document.title = docTitle;
  }, [docTitle]);

  return (
    <motion.main
      className="stage"
      variants={containerVariants}
      initial="hidden"
      animate="show"
    >
      <motion.span className="eyebrow" variants={item}>
        {eyebrow}
      </motion.span>
      <motion.h1 className="headline" variants={item}>
        {headline}
      </motion.h1>
      <motion.p className="subtitle" variants={item}>
        {subtitle}
      </motion.p>

      <div className="cards">
        {platforms.map((p) => (
          <motion.a
            key={p.url}
            className="card"
            variants={item}
            style={
              {
                "--brand": p.brand,
                "--brand-rgb": p.brandRgb,
                "--brand-2-rgb": p.brand2Rgb,
              } as CSSProperties
            }
            href={p.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={p.ariaLabel}
          >
            <span className="card-index">{p.index}</span>
            <span className="logo" aria-hidden="true">
              {p.logo}
            </span>
            <span className="card-name">{p.name}</span>
            <span className="card-handle">{p.handle}</span>
            <span className="card-foot">
              {p.footText} <span className="arrow">→</span>
            </span>
          </motion.a>
        ))}
      </div>

      <MotionLink className="home-link" to="/" variants={item}>
        <span aria-hidden="true">←</span> 返回主页
      </MotionLink>
    </motion.main>
  );
}
