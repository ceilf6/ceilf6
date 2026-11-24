export const DEFAULT_API_ORIGIN = "http://127.0.0.1:8000";
export const REMOTE_ASSETS_ORIGIN = "https://www.wangjinghong.com";

const SAFE_ADMIN_SEGMENT_RE = /^[A-Za-z0-9/_-]+$/;
const RESERVED_FRONTEND_ROOTS = new Set([
  "api",
  "accounts",
  "static",
  "django-static",
  "assets",
  "blog",
  "vlog",
  "viewer",
  "notes",
  "harness",
  "resume-awards",
  "index.html",
  "blog.html",
  "vlog.html",
  "viewer.html",
]);

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function boundaryRegexKey(prefixPath) {
  const clean = prefixPath.replace(/^\/+|\/+$/g, "");
  return `^/${escapeRegExp(clean)}(?:/|\\?|$)`;
}

export function resolveApiOrigin(rawOrigin) {
  const trimmed = typeof rawOrigin === "string" ? rawOrigin.trim() : "";
  if (!trimmed) return DEFAULT_API_ORIGIN;

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error(
      `Invalid VITE_API_ORIGIN "${trimmed}": expected an http:// or https:// origin (e.g. ${DEFAULT_API_ORIGIN}).`,
    );
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(
      `Unsupported protocol "${parsed.protocol}" in VITE_API_ORIGIN "${trimmed}": expected http: or https:.`,
    );
  }
  if (parsed.username || parsed.password) {
    throw new Error("VITE_API_ORIGIN must not embed credentials.");
  }
  if ((parsed.pathname && parsed.pathname !== "/") || parsed.search || parsed.hash) {
    throw new Error(
      `VITE_API_ORIGIN "${trimmed}" must be a bare origin without pathname, query, or hash.`,
    );
  }
  return parsed.origin;
}

export function resolveAdminProxyPrefix(rawAdminPath) {
  const trimmed = typeof rawAdminPath === "string" ? rawAdminPath.trim() : "";
  const cleaned = trimmed.replace(/^\/+|\/+$/g, "") || "admin";

  if (
    !SAFE_ADMIN_SEGMENT_RE.test(cleaned) ||
    cleaned.includes("//") ||
    cleaned.split("/").some((part) => part === "." || part === "..")
  ) {
    throw new Error(
      `Invalid admin proxy path "${rawAdminPath}": expected letters, digits, '/', '_', or '-'.`,
    );
  }

  const firstSegment = cleaned.split("/")[0].toLowerCase();
  if (RESERVED_FRONTEND_ROOTS.has(firstSegment)) {
    throw new Error(
      `Admin proxy path "/${cleaned}/" collides with reserved frontend/API prefix "/${firstSegment}".`,
    );
  }
  return `/${cleaned}`;
}

/**
 * 构建 Vite dev 与 preview 共用的同源代理表：
 * - `/assets` 继续代理到线上站点以展示真实 GitHub stats 卡片；
 * - `/api`、`/accounts`、`/django-static` 与后台入口保持 `changeOrigin: false`，
 *   确保浏览器同源 `Host` 与 `Origin` 完全一致，Django Session Cookie、CSRF Origin
 *   校验及 allauth 邮件确认回跳链接在本地零配置闭环可用。
 */
export function buildSiteProxy(env = process.env) {
  const apiOrigin = resolveApiOrigin(env?.VITE_API_ORIGIN);
  const adminPrefix = resolveAdminProxyPrefix(
    env?.VITE_ADMIN_PATH || env?.DJANGO_ADMIN_PATH,
  );
  const backendRule = { target: apiOrigin, changeOrigin: false };

  return {
    "/assets": { target: REMOTE_ASSETS_ORIGIN, changeOrigin: true },
    [boundaryRegexKey("/api")]: { ...backendRule },
    [boundaryRegexKey("/accounts")]: { ...backendRule },
    [boundaryRegexKey("/django-static")]: { ...backendRule },
    [boundaryRegexKey(adminPrefix)]: { ...backendRule },
  };
}
