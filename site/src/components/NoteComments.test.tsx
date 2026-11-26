import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  fetchNoteComments,
  fetchViewerSession,
  type CommentItem,
} from "../data/comments";
import { NoteComments } from "./NoteComments";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function guestSessionResponse(): Response {
  return jsonResponse({
    user: null,
    csrfToken: "csrf-guest",
    guestCommentsAllowed: true,
  });
}

function makeComment(overrides: Partial<CommentItem> & { id: number }): CommentItem {
  return {
    id: overrides.id,
    body: overrides.body ?? `评论正文-${overrides.id}`,
    createdAt: overrides.createdAt ?? "2026-11-24T08:30:00Z",
    canDelete: overrides.canDelete ?? false,
    author: overrides.author ?? {
      kind: "member",
      id: 7,
      displayName: "测试同学",
    },
  };
}

describe("NoteComments 列表、分页与异常隔离", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.sessionStorage.clear();
  });

  it("空列表渲染友好空态提示", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") return Promise.resolve(guestSessionResponse());
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(screen.getByText("正在读取评论…")).toBeInTheDocument();

    expect(
      await screen.findByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/notes/cc-source-analysis/comments/",
      expect.objectContaining({
        method: "GET",
        credentials: "same-origin",
      }),
    );
  });

  it("同时展示访客与成员评论，且评论正文与昵称以纯文本渲染（阻断 XSS）", async () => {
    const xssPayload = '<img src=x onerror="window.__xss=1"><script>alert(1)</script>';
    const xssName = "<svg onload=alert(2)>";

    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/me/") return Promise.resolve(guestSessionResponse());
      return Promise.resolve(
        jsonResponse({
          items: [
            makeComment({
              id: 12,
              body: xssPayload,
              createdAt: "2026-11-24T09:05:00Z",
              author: { kind: "member", id: 3, displayName: xssName },
            }),
            makeComment({
              id: 11,
              body: "未登录访客的第一条观察",
              createdAt: "2026-11-24T08:00:00Z",
              author: { kind: "guest", id: null, displayName: "未登录用户" },
            }),
          ],
          nextBefore: null,
        }),
      );
    });

    const { container } = render(<NoteComments slug="cc-source-analysis" />);

    expect(await screen.findByText(xssPayload)).toBeInTheDocument();
    expect(screen.getByText(xssName)).toBeInTheDocument();
    expect(screen.getByText("未登录用户")).toBeInTheDocument();
    expect(screen.getByText("访客")).toBeInTheDocument();
    expect(screen.getByText("2026-11-24 17:05")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg[onload]")).toBeNull();
    expect(container.querySelector(".note-comment-main svg")).toBeNull();
    expect(
      Array.from(container.querySelectorAll("svg")).every((el) =>
        Boolean(el.closest(".comment-avatar.is-guest")),
      ),
    ).toBe(true);
  });

  it("基于 nextBefore 游标追加下一页评论并在末尾隐藏分页按钮", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") return Promise.resolve(guestSessionResponse());
      if (url === "/api/notes/v8-gc-source/comments/?before=30") {
        return Promise.resolve(
          jsonResponse({
            items: [makeComment({ id: 21, body: "第二页历史评论" })],
            nextBefore: null,
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          items: [makeComment({ id: 30, body: "第一页最新评论" })],
          nextBefore: 30,
        }),
      );
    });

    render(<NoteComments slug="v8-gc-source" />);

    expect(await screen.findByText("第一页最新评论")).toBeInTheDocument();
    const moreBtn = screen.getByRole("button", { name: "读取更多评论" });
    fireEvent.click(moreBtn);

    expect(await screen.findByText("第二页历史评论")).toBeInTheDocument();
    expect(screen.getByText("第一页最新评论")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "读取更多评论" })).toBeNull();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/notes/v8-gc-source/comments/?before=30",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  it("切换 slug 时立即 abort 旧请求且旧页数据不串入新札记", async () => {
    let resolveSlugA: ((res: Response) => void) | undefined;
    const commentSignals: AbortSignal[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") return Promise.resolve(guestSessionResponse());
      if (init?.signal) commentSignals.push(init.signal);
      if (url.includes("/notes/slug-a/")) {
        return new Promise<Response>((resolve) => {
          resolveSlugA = resolve;
        });
      }
      return Promise.resolve(
        jsonResponse({
          items: [makeComment({ id: 99, body: "新札记B的评论" })],
          nextBefore: null,
        }),
      );
    });

    const { rerender } = render(<NoteComments slug="slug-a" />);
    expect(commentSignals).toHaveLength(1);
    expect(commentSignals[0].aborted).toBe(false);

    rerender(<NoteComments slug="slug-b" />);
    expect(commentSignals[0].aborted).toBe(true);

    expect(await screen.findByText("新札记B的评论")).toBeInTheDocument();

    resolveSlugA?.(
      jsonResponse({
        items: [makeComment({ id: 1, body: "旧札记A迟到的评论" })],
        nextBefore: null,
      }),
    );

    await waitFor(() => {
      expect(screen.queryByText("旧札记A迟到的评论")).toBeNull();
    });
  });

  it("接口失败时仅渲染局部降级提示并支持点击重新读取恢复", async () => {
    let listAttempt = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/me/") return Promise.resolve(guestSessionResponse());
      listAttempt += 1;
      if (listAttempt === 1) {
        return Promise.reject(new Error("network down"));
      }
      return Promise.resolve(
        jsonResponse({
          items: [makeComment({ id: 5, body: "重试后成功展示" })],
          nextBefore: null,
        }),
      );
    });

    render(<NoteComments slug="node-event-loop" />);

    expect(
      await screen.findByText("评论暂时无法读取，请稍后重试。"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));

    expect(await screen.findByText("重试后成功展示")).toBeInTheDocument();
  });

  it("fetchViewerSession 解析同源 /api/me/ 登录态与 CSRF 令牌", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
        csrfToken: "csrf-123",
        guestCommentsAllowed: true,
      }),
    );

    const session = await fetchViewerSession();
    expect(session).toEqual({
      user: { id: 1, displayName: "王景宏", isCommentAdmin: true },
      csrfToken: "csrf-123",
      guestCommentsAllowed: true,
    });
  });

  it("分页加载进行中切换 slug 时立即 abort 分页请求且旧分页数据不串入新札记", async () => {
    let resolvePage2A: ((res: Response) => void) | undefined;
    const commentSignals: AbortSignal[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") return Promise.resolve(guestSessionResponse());
      if (init?.signal) commentSignals.push(init.signal);
      if (url === "/api/notes/slug-a/comments/") {
        return Promise.resolve(
          jsonResponse({
            items: [makeComment({ id: 30, body: "札记A第一页" })],
            nextBefore: 30,
          }),
        );
      }
      if (url === "/api/notes/slug-a/comments/?before=30") {
        return new Promise<Response>((resolve) => {
          resolvePage2A = resolve;
        });
      }
      return Promise.resolve(
        jsonResponse({
          items: [makeComment({ id: 88, body: "札记B首屏评论" })],
          nextBefore: null,
        }),
      );
    });

    const { rerender } = render(<NoteComments slug="slug-a" />);
    expect(await screen.findByText("札记A第一页")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    expect(commentSignals).toHaveLength(2);
    expect(commentSignals[1].aborted).toBe(false);

    rerender(<NoteComments slug="slug-b" />);
    expect(commentSignals[1].aborted).toBe(true);
    expect(await screen.findByText("札记B首屏评论")).toBeInTheDocument();

    resolvePage2A?.(
      jsonResponse({
        items: [makeComment({ id: 15, body: "札记A迟到的第二页" })],
        nextBefore: null,
      }),
    );

    await waitFor(() => {
      expect(screen.queryByText("札记A迟到的第二页")).toBeNull();
    });
  });

  it("分页加载失败保留已有列表并提示错误，再次点击可恢复加载", async () => {
    let page2Calls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") return Promise.resolve(guestSessionResponse());
      if (url === "/api/notes/v8-gc-source/comments/?before=30") {
        page2Calls += 1;
        if (page2Calls === 1) {
          return Promise.reject(new Error("page 2 timeout"));
        }
        return Promise.resolve(
          jsonResponse({
            items: [makeComment({ id: 20, body: "重试成功的第二页评论" })],
            nextBefore: null,
          }),
        );
      }
      return Promise.resolve(
        jsonResponse({
          items: [makeComment({ id: 30, body: "已展示的第一页评论" })],
          nextBefore: 30,
        }),
      );
    });

    render(<NoteComments slug="v8-gc-source" />);
    expect(await screen.findByText("已展示的第一页评论")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    expect(
      await screen.findByText("更多评论暂时无法读取，请重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("已展示的第一页评论")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    expect(await screen.findByText("重试成功的第二页评论")).toBeInTheDocument();
    expect(screen.queryByText("更多评论暂时无法读取，请重试。")).toBeNull();
  });

  it("响应体读取阶段触发 AbortError 时原样抛出而不误判为 JSON 格式异常", async () => {
    const ctrl = new AbortController();
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => {
        ctrl.abort();
        return Promise.reject(new DOMException("Aborted", "AbortError"));
      },
    } as unknown as Response);

    await expect(
      fetchNoteComments("cc-source-analysis", { signal: ctrl.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });
});
