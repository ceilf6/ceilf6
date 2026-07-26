import { motion } from "framer-motion";
import type { ReactNode } from "react";

export function PageTransition({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <motion.div
      data-testid={testId}
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.32, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
