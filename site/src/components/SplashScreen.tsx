import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AuroraCanvas } from "../fx/AuroraCanvas";
import { NameParticles } from "../fx/NameParticles";

export const SPLASH_KEY = "wjh-splash-seen";
const SPLASH_MS = 1400;

/** 每会话只开屏一次；尊重系统「减少动态效果」偏好 */
function shouldShow(): boolean {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  return sessionStorage.getItem(SPLASH_KEY) === null;
}

export function SplashScreen() {
  const [visible, setVisible] = useState(shouldShow);
  // particles = 甲·像素粒子成名；chars = 原逐字浮现（canvas 不可用时的兜底）
  const [mode, setMode] = useState<"particles" | "chars">("particles");

  useEffect(() => {
    if (visible) sessionStorage.setItem(SPLASH_KEY, "1");
  }, [visible]);

  // chars 兜底沿用原开屏的定时收场；particles 模式由 onDone 收场
  useEffect(() => {
    if (!visible || mode !== "chars") return;
    const t = setTimeout(() => setVisible(false), SPLASH_MS);
    return () => clearTimeout(t);
  }, [visible, mode]);

  const handleDone = useCallback(() => setVisible(false), []);
  const handleUnsupported = useCallback(() => setMode("chars"), []);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          data-testid="splash"
          className="splash"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
        >
          <AuroraCanvas className="splash-aurora" />
          {mode === "particles" ? (
            <NameParticles text="王景宏" onDone={handleDone} onUnsupported={handleUnsupported} />
          ) : (
            <span className="splash-name">
              {/* 逐字 transform 汇聚：字距是布局属性，大号 CJK 字形上逐帧回流必掉帧 */}
              {["王", "景", "宏"].map((ch, i) => (
                <motion.span
                  key={ch}
                  className="splash-char"
                  initial={{ opacity: 0, x: (i - 1) * 26, y: 8 }}
                  animate={{ opacity: 1, x: 0, y: 0 }}
                  transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
                >
                  {ch}
                </motion.span>
              ))}
            </span>
          )}
          {/* 开屏时长有意分叉：particles 约 3.4s（主秀，onDone 收场）、chars 1.4s（保底速通，定时收场） */}
          <motion.span
            className="splash-sub"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.5 }}
          >
            WangJingHong.com
          </motion.span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
