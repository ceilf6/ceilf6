/// <reference types="vitest/config" />
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { mdNotes } from "./scripts/vite-md-notes.mjs";

export default defineConfig({
  plugins: [react(), mdNotes()],
  // 哈希产物收进 /static/，把 /assets/ 留给 README stats 卡片（bot 持续更新，Nginx 短缓存）
  build: { assetsDir: "static" },
  // 开发期把 /assets 代理到线上，本地能看到真实 stats 卡片
  server: {
    proxy: {
      "/assets": { target: "https://wangjinghong.com", changeOrigin: true },
    },
  },
  // preview 同款代理：server.proxy 只作用于 dev，不补这条 preview 下 /assets/*.svg 会 404
  preview: {
    proxy: {
      "/assets": { target: "https://wangjinghong.com", changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    // scripts/*.test.mjs 是 node:test 用例（node --test 跑），不归 vitest 收集
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
