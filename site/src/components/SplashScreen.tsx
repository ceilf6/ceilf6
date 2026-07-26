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
          <motion.span
            className="splash-name"
            initial={{ opacity: 0, letterSpacing: "0.6em", y: 8 }}
            animate={{ opacity: 1, letterSpacing: "0.18em", y: 0 }}
            transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
          >
            王景宏
          </motion.span>
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
