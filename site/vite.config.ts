/// <reference types="vitest/config" />
import { resolve } from "node:path";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { buildSiteProxy } from "./scripts/vite-local-proxy.mjs";
import { mdNotes } from "./scripts/vite-md-notes.mjs";

export default defineConfig(({ mode }) => {
  const serverAdminEnv = loadEnv(
    mode,
    resolve(import.meta.dirname, "server"),
    "DJANGO_ADMIN_PATH",
  );
  const fileEnv = loadEnv(mode, import.meta.dirname, "");
  const proxy = buildSiteProxy({ ...serverAdminEnv, ...fileEnv, ...process.env });

  return {
    plugins: [react(), mdNotes()],
    // 哈希产物收进 /static/，把 /assets/ 留给 README stats 卡片（bot 持续更新，Nginx 短缓存）
    build: { assetsDir: "static" },
    // 开发期与 preview 共用同源代理：/assets 走线上卡片，/api、/accounts、/django-static 与后台走本地 Django
    server: { proxy },
    preview: { proxy },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: "./src/test/setup.ts",
      // scripts/*.test.mjs 是 node:test 用例（node --test 跑），不归 vitest 收集
      include: ["src/**/*.{test,spec}.{ts,tsx}"],
    },
  };
});
