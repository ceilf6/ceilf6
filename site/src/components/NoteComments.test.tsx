import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { fetchViewerSession, type CommentItem } from "../data/comments";
import { NoteComments } from "./NoteComments";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
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
  });

  it("空列表渲染友好空态提示", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(jsonResponse({ items: [], nextBefore: null }));

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

    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
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

    const { container } = render(<NoteComments slug="cc-source-analysis" />);

    expect(await screen.findByText(xssPayload)).toBeInTheDocument();
    expect(screen.getByText(xssName)).toBeInTheDocument();
    expect(screen.getByText("未登录用户")).toBeInTheDocument();
    expect(screen.getByText("访客")).toBeInTheDocument();
    expect(screen.getByText("2026-11-24 17:05")).toBeInTheDocument();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
  });

  it("基于 nextBefore 游标追加下一页评论并在末尾隐藏分页按钮", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeComment({ id: 30, body: "第一页最新评论" })],
          nextBefore: 30,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeComment({ id: 21, body: "第二页历史评论" })],
          nextBefore: null,
        }),
      );

    render(<NoteComments slug="v8-gc-source" />);

    expect(await screen.findByText("第一页最新评论")).toBeInTheDocument();
    const moreBtn = screen.getByRole("button", { name: "读取更多评论" });
    fireEvent.click(moreBtn);

    expect(await screen.findByText("第二页历史评论")).toBeInTheDocument();
    expect(screen.getByText("第一页最新评论")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "读取更多评论" })).toBeNull();
    expect(fetchSpy).toHaveBeenNthCalledWith(
      2,
      "/api/notes/v8-gc-source/comments/?before=30",
      expect.objectContaining({ method: "GET", credentials: "same-origin" }),
    );
  });

  it("切换 slug 时立即 abort 旧请求且旧页数据不串入新札记", async () => {
    let resolveSlugA: ((res: Response) => void) | undefined;
    const signals: AbortSignal[] = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      if (init?.signal) signals.push(init.signal);
      const url = String(input);
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
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(false);

    rerender(<NoteComments slug="slug-b" />);
    expect(signals[0].aborted).toBe(true);

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
    vi.spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(
        jsonResponse({
          items: [makeComment({ id: 5, body: "重试后成功展示" })],
          nextBefore: null,
        }),
      );

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
});
