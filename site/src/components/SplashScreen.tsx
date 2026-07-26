import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

export const SPLASH_KEY = "wjh-splash-seen";
const SPLASH_MS = 1400;

/** 每会话只开屏一次；尊重系统「减少动态效果」偏好 */
function shouldShow(): boolean {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return false;
  return sessionStorage.getItem(SPLASH_KEY) === null;
}

export function SplashScreen() {
  const [visible, setVisible] = useState(shouldShow);

  useEffect(() => {
    if (!visible) return;
    sessionStorage.setItem(SPLASH_KEY, "1");
    const t = setTimeout(() => setVisible(false), SPLASH_MS);
    return () => clearTimeout(t);
  }, [visible]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          data-testid="splash"
          className="splash"
          exit={{ opacity: 0 }}
          transition={{ duration: 0.4 }}
        >
          <span className="splash-name">
            {/* 逐字 transform 汇聚取代 letter-spacing 动画：字距是布局属性，
                大号 CJK 字形上逐帧回流必掉帧；x/opacity 走合成器满帧 */}
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
