import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

describe("NoteComments 异常恢复、CSRF/身份冲突同步与并发竞态保护", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.sessionStorage.clear();
  });

  it("跨标签页登录触发 403 csrf_failed 与 409 身份变化均自动刷新 /api/me/，重试携带新令牌与身份", async () => {
    let meCalls = 0;
    let postCalls = 0;
    const postRequests: Array<{ headers: Record<string, string>; body: string }> = [];

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        if (meCalls === 1) {
          return Promise.resolve(
            jsonResponse({
              user: null,
              csrfToken: "csrf-initial",
              guestCommentsAllowed: true,
            }),
          );
        }
        if (meCalls === 2) {
          return Promise.resolve(
            jsonResponse({
              user: { id: 12, displayName: "跨标签登录同学", isCommentAdmin: false },
              csrfToken: "csrf-rotated",
              guestCommentsAllowed: true,
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
      }
      if (url === "/api/notes/node-event-loop/comments/" && init?.method === "POST") {
        postCalls += 1;
        postRequests.push({
          headers: (init.headers ?? {}) as Record<string, string>,
          body: String(init.body ?? ""),
        });
        if (postCalls === 1) {
          return Promise.resolve(
            jsonResponse(
              {
                code: "csrf_failed",
                message: "CSRF 安全校验未通过，请刷新页面后重试。",
              },
              403,
            ),
          );
        }
        if (postCalls === 2) {
          return Promise.resolve(
            jsonResponse(
              {
                code: "author_state_changed",
                actualAuthorKind: "guest",
                message: "当前登录状态已变化，请确认后再提交评论。",
              },
              409,
            ),
          );
        }
        return Promise.resolve(
          jsonResponse(
            {
              id: 77,
              body: "冲突同步后成功提交的草稿",
              createdAt: "2026-11-24T10:30:00Z",
              canDelete: false,
              author: { kind: "guest", id: null, displayName: "未登录用户" },
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
    fireEvent.change(textarea, { target: { value: "字".repeat(1001) } });
    expect(screen.getByText("1001 / 1000")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发表评论" })).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "冲突同步后成功提交的草稿" } });

    // 第 1 次提交：跨标签页登录导致 CSRF 轮换返回 403 csrf_failed -> 自动刷新为「跨标签登录同学」
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText(
        "登录状态已更新为「跨标签登录同学」，草稿已保留，请确认身份后再次点击发表。",
      ),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("冲突同步后成功提交的草稿");

    // 第 2 次提交：携带 csrf-rotated 与 expectedAuthorKind="member"，模拟会话过期返回 409 -> 自动切回访客
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText(
        "登录状态已变化（当前为「未登录用户」），草稿已保留，请确认身份后再次点击发表。",
      ),
    ).toBeInTheDocument();
    expect(postRequests[1].headers["X-CSRFToken"]).toBe("csrf-rotated");
    expect(JSON.parse(postRequests[1].body)).toMatchObject({
      expectedAuthorKind: "member",
    });

    // 第 3 次提交：携带 csrf-logged-out 与 expectedAuthorKind="guest" 成功发表
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(await screen.findByText("冲突同步后成功提交的草稿")).toBeInTheDocument();
    expect(postRequests[2].headers["X-CSRFToken"]).toBe("csrf-logged-out");
    expect(JSON.parse(postRequests[2].body)).toMatchObject({
      expectedAuthorKind: "guest",
    });
    expect(textarea).toHaveValue("");
  });

  it("400 校验失败、403 未验证邮箱/禁访客、429 限频、网络异常及刷新失败时均保留草稿且提示准确", async () => {
    let meCalls = 0;
    let postCalls = 0;

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        if (meCalls === 1) {
          return Promise.resolve(
            jsonResponse({
              user: { id: 5, displayName: "测试者", isCommentAdmin: false },
              csrfToken: "csrf-5",
              guestCommentsAllowed: true,
            }),
          );
        }
        return Promise.reject(new Error("me refresh down"));
      }
      if (url === "/api/notes/cc-source-analysis/comments/" && init?.method === "POST") {
        postCalls += 1;
        if (postCalls === 1) {
          return Promise.resolve(
            jsonResponse(
              { code: "invalid_body", message: "评论内容包含不支持的控制字符或不可见字符。" },
              400,
            ),
          );
        }
        if (postCalls === 2) {
          return Promise.resolve(
            jsonResponse(
              { code: "email_not_verified", message: "请先完成邮箱验证后再发表评论。" },
              403,
            ),
          );
        }
        if (postCalls === 3) {
          return Promise.resolve(
            jsonResponse(
              { code: "rate_limited", message: "评论提交过于频繁，请稍后再试。" },
              429,
              { "Retry-After": "30" },
            ),
          );
        }
        if (postCalls === 4) {
          return Promise.reject(new Error("network offline"));
        }
        return Promise.resolve(
          jsonResponse(
            { code: "csrf_failed", message: "CSRF 安全校验未通过，请刷新页面后重试。" },
            403,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    render(<NoteComments slug="cc-source-analysis" />);
    expect(await screen.findByText("测试者")).toBeInTheDocument();

    const textarea = screen.getByLabelText("评论内容");
    fireEvent.change(textarea, { target: { value: "始终不能丢失的草稿" } });

    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText("评论内容包含不支持的控制字符或不可见字符。"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("始终不能丢失的草稿");

    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText("请先完成邮箱验证后再发表评论。"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("始终不能丢失的草稿");

    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText("评论提交过于频繁，请稍后再试。（建议 30 秒后重试）"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("始终不能丢失的草稿");

    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText("评论提交未成功，草稿已保留，请稍后重试。"),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("始终不能丢失的草稿");

    // 触发 csrf_failed 但 /api/me/ 同步失败时，不得误报为「未登录用户」
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(
      await screen.findByText(
        "发言身份同步受阻，草稿已保留，请点击「重试连接」后再试。",
      ),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("始终不能丢失的草稿");
  });

  it("列表读取失败期间发表评论不掩盖历史重试入口，sessionStorage 异常与切页 POST 取消均安全", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("Quota", "QuotaExceededError");
    });

    let listAttempt = 0;
    let resolvePendingPostA: ((res: Response) => void) | undefined;
    const postSignals: AbortSignal[] = [];

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
      if (url === "/api/notes/slug-a/comments/" && init?.method === "POST") {
        if (init.signal) postSignals.push(init.signal);
        if (postSignals.length === 1) {
          return Promise.resolve(
            jsonResponse(
              {
                id: 90,
                body: "列表故障期间发出的新评论",
                createdAt: "2026-11-24T10:40:00Z",
                canDelete: false,
                author: { kind: "guest", id: null, displayName: "未登录用户" },
              },
              201,
            ),
          );
        }
        return new Promise<Response>((resolve) => {
          resolvePendingPostA = resolve;
        });
      }
      if (url === "/api/notes/slug-a/comments/") {
        listAttempt += 1;
        if (listAttempt === 1) {
          return Promise.reject(new Error("initial list 502"));
        }
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 12,
                body: "重试找回的历史评论",
                createdAt: "2026-11-24T08:00:00Z",
                canDelete: false,
                author: { kind: "member", id: 2, displayName: "老读者" },
              },
            ],
            nextBefore: null,
          }),
        );
      }
      return Promise.resolve(jsonResponse({ items: [], nextBefore: null }));
    });

    const { rerender } = render(<NoteComments slug="slug-a" />);
    expect(
      await screen.findByText("当前未登录，将以「未登录用户」身份直接发表"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("评论暂时无法读取，请稍后重试。"),
    ).toBeInTheDocument();

    // 在列表失败态下发表评论：新评论可见，且「重新读取」入口不被遮蔽
    const textarea = screen.getByLabelText("评论内容");
    fireEvent.change(textarea, { target: { value: "列表故障期间发出的新评论" } });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(await screen.findByText("列表故障期间发出的新评论")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新读取" })).toBeInTheDocument();

    // 点击「重新读取」后，刚才发的新评论与找回的历史评论合并展示且不丢失
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(await screen.findByText("重试找回的历史评论")).toBeInTheDocument();
    expect(screen.getByText("列表故障期间发出的新评论")).toBeInTheDocument();

    // 第二次提交在途时切换到 slug-b：在途 POST 被 abort，迟到响应不串入 slug-b
    fireEvent.change(textarea, { target: { value: "切页前挂起的提交" } });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));
    expect(postSignals[1].aborted).toBe(false);

    rerender(<NoteComments slug="slug-b" />);
    expect(postSignals[1].aborted).toBe(true);

    resolvePendingPostA?.(
      jsonResponse(
        {
          id: 91,
          body: "切页前挂起的提交",
          createdAt: "2026-11-24T10:41:00Z",
          canDelete: false,
          author: { kind: "guest", id: null, displayName: "未登录用户" },
        },
        201,
      ),
    );

    await waitFor(() => {
      expect(screen.queryByText("切页前挂起的提交")).toBeNull();
    });
  });

  it("已分页加载并在途加载第 3 页时触发 409 冲突刷新：绝不覆盖中间页或打断分页游标", async () => {
    let meCalls = 0;
    let resolvePage3: ((res: Response) => void) | undefined;

    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url === "/api/me/") {
        meCalls += 1;
        return Promise.resolve(
          jsonResponse(
            meCalls === 1
              ? { user: null, csrfToken: "csrf-1", guestCommentsAllowed: true }
              : {
                  user: { id: 8, displayName: "分页读者", isCommentAdmin: false },
                  csrfToken: "csrf-2",
                  guestCommentsAllowed: true,
                },
          ),
        );
      }
      if (url === "/api/notes/v8-gc-source/comments/" && init?.method === "POST") {
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
      if (url === "/api/notes/v8-gc-source/comments/?before=30") {
        return Promise.resolve(
          jsonResponse({
            items: [
              {
                id: 20,
                body: "第2页中间评论",
                createdAt: "2026-11-24T09:00:00Z",
                canDelete: false,
                author: { kind: "guest", id: null, displayName: "未登录用户" },
              },
            ],
            nextBefore: 20,
          }),
        );
      }
      if (url === "/api/notes/v8-gc-source/comments/?before=20") {
        return new Promise<Response>((resolve) => {
          resolvePage3 = resolve;
        });
      }
      return Promise.resolve(
        jsonResponse({
          items: [
            {
              id: 30,
              body: "第1页置顶评论",
              createdAt: "2026-11-24T10:00:00Z",
              canDelete: false,
              author: { kind: "member", id: 2, displayName: "读者甲" },
            },
          ],
          nextBefore: 30,
        }),
      );
    });

    render(<NoteComments slug="v8-gc-source" />);
    expect(await screen.findByText("第1页置顶评论")).toBeInTheDocument();

    // 加载第 2 页
    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    expect(await screen.findByText("第2页中间评论")).toBeInTheDocument();

    // 发起第 3 页在途请求，同时提交评论遇到 409 冲突刷新
    fireEvent.click(screen.getByRole("button", { name: "读取更多评论" }));
    fireEvent.change(screen.getByLabelText("评论内容"), {
      target: { value: "分页浏览途中的评论草稿" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发表评论" }));

    expect(
      await screen.findByText(
        "登录状态已更新为「分页读者」，草稿已保留，请确认身份后再次点击发表。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("第1页置顶评论")).toBeInTheDocument();
    expect(screen.getByText("第2页中间评论")).toBeInTheDocument();

    // 在途的第 3 页返回后，完整保留 1/2/3 页顺序，无缺页
    resolvePage3?.(
      jsonResponse({
        items: [
          {
            id: 10,
            body: "第3页底部评论",
            createdAt: "2026-11-24T08:00:00Z",
            canDelete: false,
            author: { kind: "guest", id: null, displayName: "未登录用户" },
          },
        ],
        nextBefore: null,
      }),
    );

    expect(await screen.findByText("第3页底部评论")).toBeInTheDocument();
    const cards = screen.getAllByRole("listitem");
    expect(cards.map((el) => el.textContent)).toEqual([
      expect.stringContaining("第1页置顶评论"),
      expect.stringContaining("第2页中间评论"),
      expect.stringContaining("第3页底部评论"),
    ]);
  });
});
