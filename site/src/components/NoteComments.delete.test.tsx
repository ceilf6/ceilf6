import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { deleteComment } from "../data/comments";
import { NoteComments } from "./NoteComments";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SAMPLE_ITEMS = [
  {
    id: 301,
    body: "访客留下的讨论",
    createdAt: "2026-11-24T10:10:00Z",
    canDelete: false,
    author: { kind: "guest", id: null, displayName: "未登录用户" },
  },
  {
    id: 302,
    body: "成员甲（本人）的评论",
    createdAt: "2026-11-24T10:05:00Z",
    canDelete: true,
    author: { kind: "member", id: 9, displayName: "成员甲" },
  },
  {
    id: 303,
    body: "成员乙（他人）的评论",
    createdAt: "2026-11-24T10:00:00Z",
    canDelete: false,
    author: { kind: "member", id: 18, displayName: "成员乙" },
  },
];

describe("NoteComments 作者删评与站主逐条管理", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.sessionStorage.clear();
  });

  it("未登录访客不显示任何删除按钮", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (String(input) === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: null,
            csrfToken: "csrf-guest",
            guestCommentsAllowed: true,
          }),
        );
      }
      return Promise.resolve(jsonResponse({ items: SAMPLE_ITEMS, nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("访客留下的讨论")).toBeInTheDocument();
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "删除" })).toBeNull();
  });

  it("普通成员仅对本人评论显示删除按钮，支持二次确认取消与 POST 204 即时移除", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: { id: 9, displayName: "成员甲", isCommentAdmin: false },
            csrfToken: "csrf-member-9",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/comments/302/delete/" && init?.method === "POST") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(jsonResponse({ items: SAMPLE_ITEMS, nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("成员甲（本人）的评论")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();

    const cards = screen.getAllByRole("listitem");
    expect(within(cards[0]).queryByRole("button", { name: "删除" })).toBeNull();
    expect(within(cards[1]).getByRole("button", { name: "删除" })).toBeInTheDocument();
    expect(within(cards[2]).queryByRole("button", { name: "删除" })).toBeNull();

    // 先点「删除」展开二次确认，再点「取消」不发请求
    fireEvent.click(within(cards[1]).getByRole("button", { name: "删除" }));
    expect(within(cards[1]).getByText("确认删除？")).toBeInTheDocument();
    fireEvent.click(within(cards[1]).getByRole("button", { name: "取消" }));
    expect(within(cards[1]).queryByText("确认删除？")).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalledWith(
      "/api/comments/302/delete/",
      expect.anything(),
    );

    // 再次点击「删除」并「确认删除」-> POST /api/comments/302/delete/ 返回 204，即时移除
    fireEvent.click(within(cards[1]).getByRole("button", { name: "删除" }));
    fireEvent.click(within(cards[1]).getByRole("button", { name: "确认删除" }));

    await waitFor(() => {
      expect(screen.queryByText("成员甲（本人）的评论")).toBeNull();
    });
    expect(screen.getByText("访客留下的讨论")).toBeInTheDocument();
    expect(screen.getByText("成员乙（他人）的评论")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/comments/302/delete/",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "X-CSRFToken": "csrf-member-9",
        }),
      }),
    );
  });

  it("站主管理账号（isCommentAdmin=true）对访客、他人与本人评论均显示删除入口并可逐条删除", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: { id: 1, displayName: "王景宏(站主)", isCommentAdmin: true },
            csrfToken: "csrf-admin-1",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/comments/301/delete/" && init?.method === "POST") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "/api/comments/303/delete/" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ code: "comment_not_found", message: "未找到对应的评论。" }, 404),
        );
      }
      return Promise.resolve(jsonResponse({ items: SAMPLE_ITEMS, nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("访客留下的讨论")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole("button", { name: "删除" });
    expect(deleteButtons).toHaveLength(3);

    // 站主删除访客评论（204）
    const guestCard = screen.getByText("访客留下的讨论").closest("li")!;
    fireEvent.click(within(guestCard).getByRole("button", { name: "删除" }));
    fireEvent.click(within(guestCard).getByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(screen.queryByText("访客留下的讨论")).toBeNull();
    });

    // 目标评论已在后台被删返回 404 时幂等清理本地条目
    const otherCard = screen.getByText("成员乙（他人）的评论").closest("li")!;
    fireEvent.click(within(otherCard).getByRole("button", { name: "删除" }));
    fireEvent.click(within(otherCard).getByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(screen.queryByText("成员乙（他人）的评论")).toBeNull();
    });
  });

  it("403 csrf_failed 自动刷新令牌重试、403 权限拒绝/401 过期/网络异常均展示非破坏性行内提示", async () => {
    let meCalls = 0;
    let delCalls = 0;
    const delHeaders: Array<Record<string, string>> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        if (meCalls <= 2) {
          return Promise.resolve(
            jsonResponse({
              user: { id: 9, displayName: "成员甲", isCommentAdmin: false },
              csrfToken: meCalls === 1 ? "csrf-stale" : "csrf-fresh",
              guestCommentsAllowed: true,
            }),
          );
        }
        return Promise.resolve(
          jsonResponse({
            user: null,
            csrfToken: "csrf-anon",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/comments/302/delete/" && init?.method === "POST") {
        delCalls += 1;
        delHeaders.push((init.headers ?? {}) as Record<string, string>);
        if (delCalls === 1) {
          return Promise.resolve(
            jsonResponse(
              { code: "csrf_failed", message: "CSRF 安全校验未通过，请刷新页面后重试。" },
              403,
            ),
          );
        }
        if (delCalls === 2) {
          return Promise.reject(new Error("network broken"));
        }
        if (delCalls === 3) {
          return Promise.resolve(
            jsonResponse(
              { code: "permission_denied", message: "无权删除该条评论。" },
              403,
            ),
          );
        }
        return Promise.resolve(
          jsonResponse(
            { code: "authentication_required", message: "请先登录后再删除评论。" },
            401,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: SAMPLE_ITEMS, nextBefore: null }));
    });

    render(<NoteComments slug="slug-a" />);
    expect(await screen.findByText("成员甲（本人）的评论")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();

    const ownCard = screen.getByText("成员甲（本人）的评论").closest("li")!;

    // 第 1 次确认删除：403 csrf_failed -> 自动刷新 /api/me/ 拿到 csrf-fresh 并保持确认面板可重试
    fireEvent.click(within(ownCard).getByRole("button", { name: "删除" }));
    fireEvent.click(within(ownCard).getByRole("button", { name: "确认删除" }));
    expect(
      await within(ownCard).findByText("安全令牌已更新，请再次点击「确认删除」。"),
    ).toBeInTheDocument();
    expect(delHeaders[0]["X-CSRFToken"]).toBe("csrf-stale");

    // 第 2 次确认删除：携带新令牌 csrf-fresh，遇网络错误 -> 保留确认态与评论并显示行内提示
    fireEvent.click(within(ownCard).getByRole("button", { name: "确认删除" }));
    expect(
      await within(ownCard).findByText("评论删除未成功，请稍后重试。"),
    ).toBeInTheDocument();
    expect(delHeaders[1]["X-CSRFToken"]).toBe("csrf-fresh");
    expect(screen.getByText("成员甲（本人）的评论")).toBeInTheDocument();

    // 第 3 次确认删除：403 permission_denied -> 收起确认框并保留错误提示
    fireEvent.click(within(ownCard).getByRole("button", { name: "确认删除" }));
    expect(
      await within(ownCard).findByText("无权删除该条评论。"),
    ).toBeInTheDocument();

    // 第 4 次重新点删除并确认：会话已过期返回 401 -> 同步顶部为未登录态并在卡片保留错误原因
    fireEvent.click(within(ownCard).getByRole("button", { name: "删除" }));
    fireEvent.click(within(ownCard).getByRole("button", { name: "确认删除" }));
    expect(
      await within(ownCard).findByText("请先登录后再删除评论。"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
  });

  it("deleteComment 拒绝非 204 的异常 200 HTML 误判，且在途删评切页自动触发 signal.aborted", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("<html>spa fallback</html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(deleteComment(302, "csrf-token")).rejects.toMatchObject({
      code: "unexpected_delete_status",
    });

    const signals: AbortSignal[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: { id: 1, displayName: "站主", isCommentAdmin: true },
            csrfToken: "csrf-admin",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/comments/301/delete/") {
        if (init?.signal) signals.push(init.signal);
        return new Promise<Response>(() => {});
      }
      return Promise.resolve(jsonResponse({ items: SAMPLE_ITEMS, nextBefore: null }));
    });

    const { rerender } = render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("访客留下的讨论")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();

    const firstCard = screen.getByText("访客留下的讨论").closest("li")!;
    fireEvent.click(within(firstCard).getByRole("button", { name: "删除" }));
    fireEvent.click(within(firstCard).getByRole("button", { name: "确认删除" }));
    expect(signals).toHaveLength(1);
    expect(signals[0].aborted).toBe(false);

    rerender(<NoteComments slug="v8-gc-source" />);
    expect(signals[0].aborted).toBe(true);
  });

  it("非 comment_not_found 的 HTML 404 不误删评论；删空首屏且 nextBefore 非空时保留读取更多；并发 csrf_failed 合并重拉", async () => {
    let meCalls = 0;
    let del302Calls = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        return Promise.resolve(
          jsonResponse({
            user: { id: 1, displayName: "站主", isCommentAdmin: true },
            csrfToken: meCalls === 1 ? "csrf-old" : "csrf-merged",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/notes/cc-source-analysis/comments/?before=302") {
        return Promise.resolve(
          jsonResponse({
            items: [SAMPLE_ITEMS[2]],
            nextBefore: null,
          }),
        );
      }
      if (url === "/api/comments/301/delete/" && init?.method === "POST") {
        const token = (init.headers as Record<string, string>)["X-CSRFToken"];
        if (token === "csrf-old") {
          return Promise.resolve(
            jsonResponse(
              { code: "csrf_failed", message: "CSRF 安全校验未通过，请刷新页面后重试。" },
              403,
            ),
          );
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      if (url === "/api/comments/302/delete/" && init?.method === "POST") {
        del302Calls += 1;
        if (del302Calls === 1) {
          return Promise.resolve(
            jsonResponse(
              { code: "csrf_failed", message: "CSRF 安全校验未通过，请刷新页面后重试。" },
              403,
            ),
          );
        }
        if (del302Calls === 2) {
          return Promise.resolve(
            new Response("<html>404 Not Found</html>", {
              status: 404,
              headers: { "Content-Type": "text/html" },
            }),
          );
        }
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(
        jsonResponse({
          items: [SAMPLE_ITEMS[0], SAMPLE_ITEMS[1]],
          nextBefore: 302,
        }),
      );
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("访客留下的讨论")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "退出登录" })).toBeInTheDocument();

    const card301 = screen.getByText("访客留下的讨论").closest("li")!;
    const card302 = screen.getByText("成员甲（本人）的评论").closest("li")!;

    // 两张卡片并发遇到 403 csrf_failed：共享同一次 /api/me/ 重拉，均不会因互相 abort 而误报同步受阻
    fireEvent.click(within(card301).getByRole("button", { name: "删除" }));
    fireEvent.click(within(card302).getByRole("button", { name: "删除" }));
    fireEvent.click(within(card301).getByRole("button", { name: "确认删除" }));
    fireEvent.click(within(card302).getByRole("button", { name: "确认删除" }));

    expect(
      await within(card301).findByText("安全令牌已更新，请再次点击「确认删除」。"),
    ).toBeInTheDocument();
    expect(
      await within(card302).findByText("安全令牌已更新，请再次点击「确认删除」。"),
    ).toBeInTheDocument();
    expect(meCalls).toBe(2);

    // 301 用新令牌成功删除；302 遇到反代 HTML 404 时绝不误删，保留条目并显示格式异常提示
    fireEvent.click(within(card301).getByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(screen.queryByText("访客留下的讨论")).toBeNull();
    });

    fireEvent.click(within(card302).getByRole("button", { name: "确认删除" }));
    expect(
      await within(card302).findByText("服务响应格式异常，请稍后重试。"),
    ).toBeInTheDocument();
    expect(screen.getByText("成员甲（本人）的评论")).toBeInTheDocument();

    // 再次删除 302 后首屏可见条目清空，但因 nextBefore=302 仍可点击「读取更多评论」加载后续页
    fireEvent.click(within(card302).getByRole("button", { name: "删除" }));
    fireEvent.click(within(card302).getByRole("button", { name: "确认删除" }));
    await waitFor(() => {
      expect(screen.queryByText("成员甲（本人）的评论")).toBeNull();
    });
    expect(
      screen.queryByText("还没有评论，欢迎留下第一条讨论。"),
    ).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    expect(await screen.findByText("成员乙（他人）的评论")).toBeInTheDocument();
  });
});
