// 与 vite-local-proxy.mjs 同名同目录——TS NodeNext 解析规则下给 vite.config.ts 的 tsc -b 提供类型
import type { ProxyOptions } from "vite";

export declare const DEFAULT_API_ORIGIN: string;
export declare const REMOTE_ASSETS_ORIGIN: string;
export declare function resolveApiOrigin(rawOrigin?: string): string;
export declare function resolveAdminProxyPrefix(rawAdminPath?: string): string;
export declare function buildSiteProxy(
  env?: Record<string, string | undefined>,
): Record<string, ProxyOptions>;
