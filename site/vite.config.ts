/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // 哈希产物收进 /static/，把 /assets/ 留给 README stats 卡片（bot 持续更新，Nginx 短缓存）
  build: { assetsDir: "static" },
  // 开发期把 /assets 代理到线上，本地能看到真实 stats 卡片
  server: {
    proxy: {
      "/assets": { target: "https://wangjinghong.com", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
