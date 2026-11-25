import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NoteComments } from "./NoteComments";

function jsonResponse(
  payload: unknown,
  status = 200,
  extraHeaders: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}

describe("NoteComments 发表交互、回跳链接与草稿保护", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.sessionStorage.clear();
  });

  it("未登录访客可直接发表评论，成功后即时置顶并清空草稿，登录/注册链接精确带 next", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: null,
            csrfToken: "csrf-guest-1",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/notes/cc-source-analysis/comments/" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: 51,
              body: "访客直接提交的新评论",
              createdAt: "2026-11-24T10:00:00Z",
              canDelete: false,
              author: { kind: "guest", id: null, displayName: "未登录用户" },
            },
            201,
          ),
        );
      }
      return Promise.resolve(
        jsonResponse({
          items: [
            {
              id: 10,
              body: "早期历史评论",
              createdAt: "2026-11-24T08:00:00Z",
              canDelete: false,
              author: { kind: "member", id: 2, displayName: "老读者" },
            },
          ],
          nextBefore: null,
        }),
      );
    });

    render(<NoteComments slug="cc-source-analysis" />);

    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(await screen.findByText("早期历史评论")).toBeInTheDocument();

    const loginLink = screen.getByRole("link", { name: "登录" });
    const signupLink = screen.getByRole("link", { name: "注册" });
    expect(loginLink).toHaveAttribute(
      "href",
      "/accounts/login/?next=%2Fblog%2Fcc-source-analysis",
    );
    expect(signupLink).toHaveAttribute(
      "href",
      "/accounts/signup/?next=%2Fblog%2Fcc-source-analysis",
    );

    const textarea = screen.getByLabelText("评论内容");
    fireEvent.change(textarea, { target: { value: "访客直接提交的新评论" } });
    expect(
      globalThis.sessionStorage.getItem(
        "wangjinghong:note-comment-draft:cc-source-analysis",
      ),
    ).toBe("访客直接提交的新评论");
    expect(screen.getByText("10 / 1000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(await screen.findByText("访客直接提交的新评论")).toBeInTheDocument();
    expect(textarea).toHaveValue("");
    expect(
      globalThis.sessionStorage.getItem(
        "wangjinghong:note-comment-draft:cc-source-analysis",
      ),
    ).toBeNull();

    const cards = screen.getAllByRole("listitem");
    expect(cards[0]).toHaveTextContent("访客直接提交的新评论");
    expect(cards[1]).toHaveTextContent("早期历史评论");

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/notes/cc-source-analysis/comments/",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-CSRFToken": "csrf-guest-1",
        }),
        body: JSON.stringify({
          body: "访客直接提交的新评论",
          expectedAuthorKind: "guest",
          website: "",
        }),
      }),
    );
  });

  it("已登录成员显示身份与带 CSRF/next 的 POST 退出表单，可提交成员评论", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: { id: 9, displayName: "景宏同学", isCommentAdmin: false },
            csrfToken: "csrf-member-9",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/notes/v8-gc-source/comments/" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              id: 66,
              body: "登录成员发表的技术讨论",
              createdAt: "2026-11-24T10:15:00Z",
              canDelete: true,
              author: { kind: "member", id: 9, displayName: "景宏同学" },
            },
            201,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    const { container } = render(<NoteComments slug="v8-gc-source" />);

    expect(await screen.findByText("景宏同学")).toBeInTheDocument();
    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    const logoutForm = logoutBtn.closest("form");
    expect(logoutForm).toHaveAttribute(
      "action",
      "/accounts/logout/?next=%2Fblog%2Fv8-gc-source",
    );
    expect(logoutForm).toHaveAttribute("method", "post");
    expect(
      container.querySelector('input[name="csrfmiddlewaretoken"]'),
    ).toHaveValue("csrf-member-9");
    expect(container.querySelector('input[name="next"]')).toHaveValue(
      "/blog/v8-gc-source",
    );

    fireEvent.change(screen.getByLabelText("评论内容"), {
      target: { value: "登录成员发表的技术讨论" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(await screen.findByText("登录成员发表的技术讨论")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/notes/v8-gc-source/comments/",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          body: "登录成员发表的技术讨论",
          expectedAuthorKind: "member",
          website: "",
        }),
      }),
    );
  });

  it("guestCommentsAllowed=false 时禁用访客提交并保留草稿，登录返回后自动恢复草稿且按 slug 隔离", async () => {
    let loggedIn = false;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse(
            loggedIn
              ? {
                  user: { id: 3, displayName: "已登录读者", isCommentAdmin: false },
                  csrfToken: "csrf-3",
                  guestCommentsAllowed: false,
                }
              : {
                  user: null,
                  csrfToken: "csrf-0",
                  guestCommentsAllowed: false,
                },
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    const { rerender, unmount } = render(<NoteComments slug="slug-a" />);
    expect(
      await screen.findByText(
        "当前已暂停未登录访客发表评论，请先登录后发言（草稿将自动保留）",
      ),
    ).toBeInTheDocument();

    const textareaA = screen.getByLabelText("评论内容");
    fireEvent.change(textareaA, { target: { value: "跳去登录前写好的长草稿A" } });
    expect(screen.getByRole("button", { name: "发表评论" })).toBeDisabled();

    rerender(<NoteComments slug="slug-b" />);
    expect(screen.getByLabelText("评论内容")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("评论内容"), {
      target: { value: "札记B独立草稿" },
    });

    unmount();
    loggedIn = true;
    render(<NoteComments slug="slug-a" />);

    expect(await screen.findByText("已登录读者")).toBeInTheDocument();
    expect(screen.getByLabelText("评论内容")).toHaveValue("跳去登录前写好的长草稿A");
    expect(screen.getByRole("button", { name: "发表评论" })).not.toBeDisabled();
  });

  it("提交期间若后端动态切为 403 guest_comments_disabled，立即切换禁用态且完整保留草稿", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        return Promise.resolve(
          jsonResponse({
            user: null,
            csrfToken: "csrf-guest",
            guestCommentsAllowed: true,
          }),
        );
      }
      if (url === "/api/notes/cc-source-analysis/comments/" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse(
            {
              code: "guest_comments_disabled",
              message: "当前已暂停未登录访客发表评论，请登录后发言。",
            },
            403,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();

    const textarea = screen.getByLabelText("评论内容");
    fireEvent.change(textarea, { target: { value: "需要保留的访客草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(
      await screen.findByText("当前已暂停未登录访客发表评论，请登录后发言。"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("需要保留的访客草稿");
    expect(screen.getByRole("button", { name: "发表评论" })).toBeDisabled();
  });
});
