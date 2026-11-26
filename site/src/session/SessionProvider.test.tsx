import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { SiteHeader } from "../components/SiteHeader";
import type { ViewerSession } from "../data/comments";
import { SessionProvider, useSession } from "./SessionProvider";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function SessionProbe({
  onSnapshot,
}: {
  onSnapshot?: (ctx: ReturnType<typeof useSession>) => void;
}) {
  const ctx = useSession();
  onSnapshot?.(ctx);
  return (
    <div>
      <span data-testid="status">{ctx.status}</span>
      <span data-testid="user">{ctx.session?.user?.displayName ?? "none"}</span>
      <span data-testid="csrf">{ctx.session?.csrfToken ?? "none"}</span>
      <button type="button" onClick={() => void ctx.refresh()}>
        do-refresh
      </button>
      <button
        type="button"
        onClick={() =>
          ctx.syncSession({
            user: { id: 99, displayName: "同步用户", isCommentAdmin: false },
            csrfToken: "csrf-synced",
            guestCommentsAllowed: true,
          })
        }
      >
        do-sync
      </button>
    </div>
  );
}

describe("SessionProvider 与 useSession", () => {
  afterEach(() => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("未包裹 SessionProvider 时返回引用稳定的 idle 空操作上下文且不发请求", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const snapshots: Array<ReturnType<typeof useSession>> = [];

    const { rerender } = render(
      <SessionProbe onSnapshot={(ctx) => snapshots.push(ctx)} />,
    );
    rerender(<SessionProbe onSnapshot={(ctx) => snapshots.push(ctx)} />);

    expect(screen.getByTestId("status")).toHaveTextContent("idle");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(snapshots).toHaveLength(2);
    expect(snapshots[0]).toBe(snapshots[1]);
    expect(snapshots[0].refresh).toBe(snapshots[1].refresh);
    expect(snapshots[0].syncSession).toBe(snapshots[1].syncSession);

    await act(async () => {
      await snapshots[0].refresh();
      snapshots[0].syncSession({
        user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
        csrfToken: "csrf",
        guestCommentsAllowed: true,
      });
    });

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.getByTestId("status")).toHaveTextContent("idle");
  });

  it("首次加载返回 500 或网络错误时 status 为 error，顶栏降级显示「登录」；lastFetchedAtRef 初始为 0，切回前台立即重试", async () => {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);

    // 1) 首次加载 500 -> error + 顶栏显示「登录」
    const spy500 = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ code: "server_error" }, 500));

    const view500 = render(
      <MemoryRouter initialEntries={["/blog"]}>
        <SessionProvider>
          <SiteHeader />
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("error");
    });
    expect(screen.getByRole("link", { name: "登录" })).toBeInTheDocument();
    expect(spy500).toHaveBeenCalledTimes(1);
    view500.unmount();
    spy500.mockRestore();

    // 2) 首次加载网络错误后，仅过 1 秒（< 10s）触发 visibilitychange：因 lastFetchedAtRef 初始为 0，立即发起重试
    let attempt = 0;
    const retrySpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      attempt += 1;
      if (attempt === 1) {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      return Promise.resolve(
        jsonResponse({
          user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
          csrfToken: "csrf-recovered",
          guestCommentsAllowed: true,
        }),
      );
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <SessionProvider>
          <SiteHeader />
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("error");
    });
    expect(screen.getByRole("link", { name: "登录" })).toBeInTheDocument();
    expect(retrySpy).toHaveBeenCalledTimes(1);

    // 仅过 1 秒（未满 10 秒）立即切回前台，不被节流挡住
    now += 1_000;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(retrySpy).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();
  });

  it("已登录后后台刷新遇到 500、网络错误或格式异常时保留原 session 与 ready 状态及头像，且不更新 lastFetchedAtRef", async () => {
    let now = 2_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);

    let call = 0;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      call += 1;
      if (call === 1) {
        return Promise.resolve(
          jsonResponse({
            user: {
              id: 1,
              displayName: "王景宏",
              isCommentAdmin: true,
              avatarColor: "#4F46E5",
            },
            csrfToken: "csrf-initial",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (call === 2) {
        return Promise.resolve(
          jsonResponse({ code: "server_error", message: "boom" }, 500),
        );
      }
      if (call === 3) {
        return Promise.reject(new TypeError("Network offline"));
      }
      if (call === 4) {
        return Promise.resolve(
          new Response("not-json", {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          user: null,
          csrfToken: "csrf-logged-out",
          guestCommentsAllowed: true,
        }),
      );
    });

    render(
      <MemoryRouter initialEntries={["/blog"]}>
        <SessionProvider>
          <SiteHeader />
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(
      screen.getByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    // 超过 10s 后切回前台：第 2 次请求返回 500 -> 保留 ready、user 与头像，且不更新 lastFetchedAtRef
    now += 11_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(screen.getByTestId("user")).toHaveTextContent("王景宏");
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-initial");
    expect(
      screen.getByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "登录" })).toBeNull();

    // 仅再过 1s（距离上次成功已 12s > 10s，证明失败未更新 lastFetchedAtRef）再次切回前台：发起第 3 次请求（网络错误）
    now += 1_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(
      screen.getByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();

    // 第 4 次请求（JSON 格式异常）：仍保留已登录头像
    now += 1_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(4);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(
      screen.getByRole("button", { name: "账号：王景宏" }),
    ).toBeInTheDocument();

    // 第 5 次请求成功返回 user: null（真实登出）：正常切回「登录」并更新 lastFetchedAtRef
    now += 1_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await waitFor(() => {
      expect(screen.getByRole("link", { name: "登录" })).toBeInTheDocument();
    });
    expect(fetchSpy).toHaveBeenCalledTimes(5);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(screen.getByTestId("user")).toHaveTextContent("none");
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-logged-out");

    // 真实登出成功后 2s 内切回前台：被 10s 节流拦截
    now += 2_000;
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(5);
  });

  it("首次请求尚未完成时先调用 syncSession：取消在途请求，且后续后台刷新返回 500 时仍保留头像不掉回「登录」", async () => {
    let resolveInitial: ((res: Response) => void) | undefined;
    const signals: AbortSignal[] = [];
    let call = 0;

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((_input, init) => {
        call += 1;
        if (init?.signal) signals.push(init.signal);
        if (call === 1) {
          return new Promise<Response>((resolve) => {
            resolveInitial = resolve;
          });
        }
        return Promise.resolve(
          jsonResponse({ code: "server_error", message: "boom" }, 500),
        );
      });

    render(
      <MemoryRouter initialEntries={["/blog/cc-source-analysis"]}>
        <SessionProvider>
          <SiteHeader />
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(false);

    // 首次请求未完成前先由评论区调用 syncSession
    await act(async () => {
      screen.getByRole("button", { name: "do-sync" }).click();
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(true);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(screen.getByTestId("user")).toHaveTextContent("同步用户");
    expect(
      screen.getByRole("button", { name: "账号：同步用户" }),
    ).toBeInTheDocument();

    // 即使在途慢响应迟到返回 user: null，也被丢弃
    await act(async () => {
      resolveInitial?.(
        jsonResponse({
          user: null,
          csrfToken: "csrf-stale",
          guestCommentsAllowed: true,
        }),
      );
      await Promise.resolve();
    });
    expect(screen.getByTestId("user")).toHaveTextContent("同步用户");

    // 后续触发后台刷新返回 500：因 syncSession 已将 hasReadySessionRef 置为 true，顶栏仍然保留头像
    await act(async () => {
      screen.getByRole("button", { name: "do-refresh" }).click();
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(screen.getByTestId("user")).toHaveTextContent("同步用户");
    expect(
      screen.getByRole("button", { name: "账号：同步用户" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "登录" })).toBeNull();
  });

  it("visibilitychange 遵循 10 秒节流，且并发刷新时慢响应不会覆盖新响应", async () => {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);

    const pendingResolvers: Array<(res: Response) => void> = [];
    const signals: AbortSignal[] = [];

    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation((_input, init) => {
        if (init?.signal) signals.push(init.signal);
        if (pendingResolvers.length === 0 && signals.length === 1) {
          return Promise.resolve(
            jsonResponse({
              user: null,
              csrfToken: "csrf-init",
              guestCommentsAllowed: true,
            }),
          );
        }
        return new Promise<Response>((resolve) => {
          pendingResolvers.push(resolve);
        });
      });

    render(
      <SessionProvider>
        <SessionProbe />
      </SessionProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    // 5 秒内切回前台：节流拦截，不发请求
    now += 5_000;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    // 超过 10 秒但切到 hidden：不发请求
    now += 6_000;
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    // 超过 10 秒且回到 visible：发起第 2 次请求（慢请求）
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
    expect(signals[1]?.aborted).toBe(false);

    // 紧接着手动触发第 3 次 refresh：取消第 2 次慢请求，且第 3 次先返回
    act(() => {
      screen.getByRole("button", { name: "do-refresh" }).click();
    });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(signals[1]?.aborted).toBe(true);

    const freshSession: ViewerSession = {
      user: { id: 2, displayName: "新响应用户", isCommentAdmin: false },
      csrfToken: "csrf-fresh",
      guestCommentsAllowed: true,
    };

    await act(async () => {
      pendingResolvers[1]?.(jsonResponse(freshSession));
      await Promise.resolve();
    });
    expect(screen.getByTestId("user")).toHaveTextContent("新响应用户");

    // 第 2 次慢请求此时迟到返回，不得覆盖第 3 次的新结果
    await act(async () => {
      pendingResolvers[0]?.(
        jsonResponse({
          user: { id: 3, displayName: "过期慢响应", isCommentAdmin: false },
          csrfToken: "csrf-old",
          guestCommentsAllowed: true,
        }),
      );
      await Promise.resolve();
    });
    expect(screen.getByTestId("user")).toHaveTextContent("新响应用户");
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-fresh");
  });
});
