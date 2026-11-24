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
      "/accounts/login/?next=%2Fnotes%2Fcc-source-analysis",
    );
    expect(signupLink).toHaveAttribute(
      "href",
      "/accounts/signup/?next=%2Fnotes%2Fcc-source-analysis",
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
      "/accounts/logout/?next=%2Fnotes%2Fv8-gc-source",
    );
    expect(logoutForm).toHaveAttribute("method", "post");
    expect(
      container.querySelector('input[name="csrfmiddlewaretoken"]'),
    ).toHaveValue("csrf-member-9");
    expect(container.querySelector('input[name="next"]')).toHaveValue(
      "/notes/v8-gc-source",
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

    // 切换到另一篇札记 slug-b 时，草稿互不覆盖
    rerender(<NoteComments slug="slug-b" />);
    expect(screen.getByLabelText("评论内容")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("评论内容"), {
      target: { value: "札记B独立草稿" },
    });

    // 模拟整页登录回跳重新挂载 slug-a：草稿自动恢复且按钮在登录态下可提交
    unmount();
    loggedIn = true;
    render(<NoteComments slug="slug-a" />);

    expect(await screen.findByText("已登录读者")).toBeInTheDocument();
    expect(screen.getByLabelText("评论内容")).toHaveValue("跳去登录前写好的长草稿A");
    expect(screen.getByRole("button", { name: "发表评论" })).not.toBeDisabled();
  });

  it("409 身份变化、429 限频、403 关闭访客及超过 1000 字上限均保护草稿不丢失", async () => {
    let meCalls = 0;
    let postCalls = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        return Promise.resolve(
          jsonResponse(
            meCalls === 1
              ? {
                  user: null,
                  csrfToken: "csrf-before",
                  guestCommentsAllowed: true,
                }
              : {
                  user: { id: 12, displayName: "后台已登录用户", isCommentAdmin: false },
                  csrfToken: "csrf-after",
                  guestCommentsAllowed: true,
                },
          ),
        );
      }
      if (url === "/api/notes/node-event-loop/comments/" && init?.method === "POST") {
        postCalls += 1;
        if (postCalls === 1) {
          return Promise.resolve(
            jsonResponse(
              {
                code: "author_state_changed",
                actualAuthorKind: "member",
                message: "当前登录状态已变化，请确认后再提交评论。",
              },
              409,
            ),
          );
        }
        if (postCalls === 2) {
          return Promise.resolve(
            jsonResponse(
              {
                code: "rate_limited",
                message: "评论提交过于频繁，请稍后再试。",
              },
              429,
              { "Retry-After": "45" },
            ),
          );
        }
        return Promise.resolve(
          jsonResponse(
            {
              id: 77,
              body: "确认新身份后成功提交的草稿",
              createdAt: "2026-11-24T10:30:00Z",
              canDelete: true,
              author: { kind: "member", id: 12, displayName: "后台已登录用户" },
            },
            201,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    render(<NoteComments slug="node-event-loop" />);
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();

    const textarea = screen.getByLabelText("评论内容");
    // 超过 1000 字上限时禁用提交按钮
    fireEvent.change(textarea, { target: { value: "字".repeat(1001) } });
    expect(screen.getByText("1001 / 1000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发表评论" })).toBeDisabled();

    // 改回合法草稿，第 1 次提交遇 409：草稿不丢，自动刷新为「后台已登录用户」
    fireEvent.change(textarea, { target: { value: "确认新身份后成功提交的草稿" } });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(
      await screen.findByText(
        "登录状态已更新为「后台已登录用户」，草稿已保留，请确认身份后再次点击发表。",
      ),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("确认新身份后成功提交的草稿");

    // 第 2 次提交遇 429 限频：提示建议等待秒数且草稿依旧保留
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText("评论提交过于频繁，请稍后再试。（建议 45 秒后重试）"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("确认新身份后成功提交的草稿");

    // 第 3 次提交成功（201）：使用更新后的 member 身份与新 CSRF 令牌成功发表
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(await screen.findByText("确认新身份后成功提交的草稿")).toBeInTheDocument();
    expect(textarea).toHaveValue("");
  });

  it("提交期间若后端动态切为 403 guest_comments_disabled，立即切换禁用提示且保留草稿", async () => {
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
