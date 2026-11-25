import { afterEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
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

  it("挂载初始为 loading，拉取成功后进入 ready，500 或异常时降级为 error 且清空旧会话", async () => {
    let call = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
      call += 1;
      if (call === 1) {
        return Promise.resolve(
          jsonResponse({
            user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
            csrfToken: "csrf-1",
            guestCommentsAllowed: true,
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({ code: "server_error", message: "boom" }, 500),
      );
    });

    render(
      <SessionProvider>
        <SessionProbe />
      </SessionProvider>,
    );

    expect(screen.getByTestId("status")).toHaveTextContent("loading");

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("ready");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("王景宏");
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-1");

    await act(async () => {
      screen.getByRole("button", { name: "do-refresh" }).click();
    });

    await waitFor(() => {
      expect(screen.getByTestId("status")).toHaveTextContent("error");
    });
    expect(screen.getByTestId("user")).toHaveTextContent("none");
  });

  it("syncSession 直接写入会话、取消在途旧请求并阻止慢响应覆盖，自身绝不发起网络请求", async () => {
    let resolveInitial: ((res: Response) => void) | undefined;
    const signals: AbortSignal[] = [];

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
      if (init?.signal) signals.push(init.signal);
      return new Promise<Response>((resolve) => {
        resolveInitial = resolve;
      });
    });

    render(
      <SessionProvider>
        <SessionProbe />
      </SessionProvider>,
    );

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(false);

    await act(async () => {
      screen.getByRole("button", { name: "do-sync" }).click();
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(signals[0]?.aborted).toBe(true);
    expect(screen.getByTestId("status")).toHaveTextContent("ready");
    expect(screen.getByTestId("user")).toHaveTextContent("同步用户");
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-synced");

    // 即使底层慢响应无视 signal 迟到返回，也绝不能覆盖刚同步的新会话
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
    expect(screen.getByTestId("csrf")).toHaveTextContent("csrf-synced");
  });

  it("visibilitychange 遵循 10 秒节流，且并发刷新时慢响应不会覆盖新响应", async () => {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);

    const pendingResolvers: Array<(res: Response) => void> = [];
    const signals: AbortSignal[] = [];

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((_input, init) => {
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
