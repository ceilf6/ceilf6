import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import {
  DEFAULT_API_ORIGIN,
  REMOTE_ASSETS_ORIGIN,
  buildSiteProxy,
  resolveAdminProxyPrefix,
  resolveApiOrigin,
} from "./vite-local-proxy.mjs";

const SITE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), "..");

test("buildSiteProxy 默认同源代理到本地 127.0.0.1:8000 并保留 /assets 线上代理", () => {
  const proxy = buildSiteProxy({});
  assert.deepEqual(proxy["/assets"], {
    target: REMOTE_ASSETS_ORIGIN,
    changeOrigin: true,
  });

  for (const key of [
    "^/api(?:/|\\?|$)",
    "^/accounts(?:/|\\?|$)",
    "^/django-static(?:/|\\?|$)",
    "^/admin(?:/|\\?|$)",
  ]) {
    assert.deepEqual(proxy[key], {
      target: DEFAULT_API_ORIGIN,
      changeOrigin: false,
    });
  }
});

test("resolveApiOrigin 与 resolveAdminProxyPrefix 支持合法自定义并拒绝越界/冲突配置", () => {
  assert.equal(resolveApiOrigin("  http://localhost:8001/ "), "http://localhost:8001");
  assert.equal(resolveAdminProxyPrefix(" /ops-console/ "), "/ops-console");

  const customProxy = buildSiteProxy({
    VITE_API_ORIGIN: "http://127.0.0.1:9009/",
    DJANGO_ADMIN_PATH: "ops-console/",
  });
  assert.deepEqual(customProxy["^/ops-console(?:/|\\?|$)"], {
    target: "http://127.0.0.1:9009",
    changeOrigin: false,
  });

  for (const badOrigin of [
    "not-a-url",
    "ftp://127.0.0.1:8000",
    "http://user:pass@127.0.0.1:8000",
    "http://127.0.0.1:8000/api",
    "http://127.0.0.1:8000?x=1",
  ]) {
    assert.throws(() => resolveApiOrigin(badOrigin));
  }

  for (const badAdmin of [
    "/blog/",
    "/notes/",
    "/api/",
    "/assets/",
    "../escape",
    "ops//console",
    "bad space",
  ]) {
    assert.throws(() => resolveAdminProxyPrefix(badAdmin));
  }
});

test(
  "真实 Vite server 代理透传同源 Host/Cookie/CSRF 且不误劫持相邻前端路由",
  { timeout: 15000 },
  async () => {
    const received = [];
    const backend = http.createServer((req, res) => {
      const chunks = [];
      req.on("data", (chunk) => chunks.push(chunk));
      req.on("end", () => {
        received.push({
          method: req.method,
          url: req.url,
          host: req.headers.host,
          origin: req.headers.origin ?? null,
          cookie: req.headers.cookie ?? null,
          csrf: req.headers["x-csrftoken"] ?? null,
          body: Buffer.concat(chunks).toString("utf8"),
        });
        res.writeHead(200, {
          "Content-Type": "application/json",
          Connection: "close",
          "Cache-Control": "private, no-store, no-cache, must-revalidate",
          "Set-Cookie": "csrftoken=test-csrf-cookie; Path=/; SameSite=Lax",
        });
        res.end(JSON.stringify({ proxied: true, path: req.url }));
      });
    });

    await new Promise((r) => backend.listen(0, "127.0.0.1", r));
    const backendPort = backend.address().port;
    const prevOrigin = process.env.VITE_API_ORIGIN;
    process.env.VITE_API_ORIGIN = `http://127.0.0.1:${backendPort}`;

    let viteServer;
    try {
      viteServer = await createServer({
        root: SITE_DIR,
        configFile: resolve(SITE_DIR, "vite.config.ts"),
        logLevel: "silent",
        optimizeDeps: { noDiscovery: true },
        server: {
          host: "127.0.0.1",
          port: 0,
          strictPort: false,
          hmr: false,
          watch: null,
        },
      });
      await viteServer.listen();
      const vitePort = viteServer.httpServer.address().port;
      const viteBase = `http://127.0.0.1:${vitePort}`;

      // 1. GET /api/me/ 转发到后端，且保持前端同源 Host（changeOrigin: false）
      const meRes = await fetch(`${viteBase}/api/me/`);
      assert.equal(meRes.status, 200);
      assert.match(meRes.headers.get("set-cookie") ?? "", /csrftoken=test-csrf-cookie/);
      assert.deepEqual(await meRes.json(), { proxied: true, path: "/api/me/" });
      assert.equal(received[0].host, `127.0.0.1:${vitePort}`);

      // 2. POST /api/notes/cc-source-analysis/comments/ 完整透传 Origin / Cookie / X-CSRFToken
      const postRes = await fetch(`${viteBase}/api/notes/cc-source-analysis/comments/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Origin: viteBase,
          Cookie: "csrftoken=test-csrf-cookie; sessionid=s1",
          "X-CSRFToken": "token-abc",
        },
        body: JSON.stringify({ body: "同源代理联调评论", expectedAuthorKind: "guest" }),
      });
      assert.equal(postRes.status, 200);
      assert.equal(received[1].host, `127.0.0.1:${vitePort}`);
      assert.equal(received[1].origin, viteBase);
      assert.equal(received[1].cookie, "csrftoken=test-csrf-cookie; sessionid=s1");
      assert.equal(received[1].csrf, "token-abc");

      // 3. /accounts/*、/django-static/*、/admin/* 同样转发到后端
      for (const backendPath of [
        "/accounts/login/?next=%2Fnotes%2Fcc-source-analysis",
        "/django-static/admin/css/base.css",
        "/admin/login/",
      ]) {
        const r = await fetch(`${viteBase}${backendPath}`);
        assert.equal(r.status, 200);
        assert.deepEqual(await r.json(), { proxied: true, path: backendPath });
      }
      const countBeforeSpa = received.length;

      // 4. 前端 SPA 路由与同前缀非边界路径（如 /api-docs、/admin-guide）绝不被误转发到 Django
      for (const spaPath of ["/notes/cc-source-analysis", "/api-docs", "/admin-guide"]) {
        const htmlRes = await fetch(`${viteBase}${spaPath}`, {
          headers: { Accept: "text/html" },
        });
        assert.equal(htmlRes.status, 200);
        assert.match(htmlRes.headers.get("content-type") ?? "", /text\/html/);
        await htmlRes.text();
      }
      assert.equal(received.length, countBeforeSpa);
    } finally {
      if (prevOrigin === undefined) delete process.env.VITE_API_ORIGIN;
      else process.env.VITE_API_ORIGIN = prevOrigin;
      if (viteServer) {
        viteServer.httpServer?.closeAllConnections?.();
        await viteServer.close();
      }
      backend.closeAllConnections?.();
      await new Promise((r) => backend.close(r));
    }
  },
);
