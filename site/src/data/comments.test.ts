import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchViewerSession, isValidAvatarColor, parseCommentItem } from "./comments";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("isValidAvatarColor 头像十六进制色值校验", () => {
  it.each([
    "#4F46E5",
    "#0f766e",
    "#7C3AED",
    "#0369A1",
    "#047857",
    "#B45309",
    "#BE123C",
    "#475569",
    "#a1B2c3",
  ])("接受合法 6 位十六进制颜色 %s", (color) => {
    expect(isValidAvatarColor(color)).toBe(true);
  });

  it.each<unknown[]>([
    [undefined],
    [null],
    [""],
    ["#fff"],
    ["#ffff"],
    ["#4F46E5FF"],
    ["4F46E5"],
    ["#4F46EG"],
    ["red"],
    ["rgb(79, 70, 229)"],
    ["var(--accent-gold)"],
    ["#4F46E5; background:url(x)"],
    ["#4F46E5; color:red"],
    ["url(javascript:alert(1))"],
    [" #4F46E5"],
    ["#4F46E5 "],
    ["#4F46E5\n"],
    [123],
    [true],
    [{}],
    [[]],
  ])("拒绝非法或含样式注入的值 %j", (invalid) => {
    expect(isValidAvatarColor(invalid)).toBe(false);
  });
});

describe("fetchViewerSession 解析可选 avatarColor", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each(["#4F46E5", "#0f766e"])(
    "当 data.user.avatarColor 为合法色值 %s 时保留在 SessionUser 上",
    async (avatarColor) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({
          user: {
            id: 1,
            displayName: "王景宏",
            isCommentAdmin: true,
            avatarColor,
          },
          csrfToken: "csrf-ok",
          guestCommentsAllowed: true,
        }),
      );

      const session = await fetchViewerSession();
      expect(session).toEqual({
        user: {
          id: 1,
          displayName: "王景宏",
          isCommentAdmin: true,
          avatarColor,
        },
        csrfToken: "csrf-ok",
        guestCommentsAllowed: true,
      });
    },
  );

  it("当后端未返回 avatarColor 时不报错且不挂载多余字段（兼容旧后端）", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      jsonResponse({
        user: { id: 2, displayName: "读者甲", isCommentAdmin: false },
        csrfToken: "csrf-legacy",
        guestCommentsAllowed: true,
      }),
    );

    const session = await fetchViewerSession();
    expect(session).toEqual({
      user: { id: 2, displayName: "读者甲", isCommentAdmin: false },
      csrfToken: "csrf-legacy",
      guestCommentsAllowed: true,
    });
    expect("avatarColor" in session.user!).toBe(false);
  });

  it.each([
    null,
    "",
    "#fff",
    "red",
    "#4F46E5; background:url(x)",
    "#4F46E5; color:red",
    "url(javascript:alert(1))",
    42,
  ])(
    "当 data.user.avatarColor 为非法值 %j 时静默丢弃而不抛错",
    async (badColor) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        jsonResponse({
          user: {
            id: 3,
            displayName: "安全测试",
            isCommentAdmin: false,
            avatarColor: badColor,
          },
          csrfToken: "csrf-safe",
          guestCommentsAllowed: false,
        }),
      );

      const session = await fetchViewerSession();
      expect(session).toEqual({
        user: { id: 3, displayName: "安全测试", isCommentAdmin: false },
        csrfToken: "csrf-safe",
        guestCommentsAllowed: false,
      });
      expect(session.user?.avatarColor).toBeUndefined();
      expect("avatarColor" in session.user!).toBe(false);
    },
  );
});

describe("parseCommentItem 解析可选 author.avatarColor", () => {
  it("成员评论带合法 #RRGGBB avatarColor 时保留，缺失或非法时静默丢弃而不使整条评论报错", () => {
    const valid = parseCommentItem({
      id: 10,
      body: "正常评论",
      createdAt: "2026-11-26T00:00:00Z",
      canDelete: false,
      author: {
        kind: "member",
        id: 5,
        displayName: "竹林听雨",
        avatarColor: "#0F766E",
      },
    });
    expect(valid.author).toEqual({
      kind: "member",
      id: 5,
      displayName: "竹林听雨",
      avatarColor: "#0F766E",
    });

    for (const bad of [
      undefined,
      null,
      "",
      "red",
      "#fff",
      "#fff; background:url(x)",
      42,
    ]) {
      const parsed = parseCommentItem({
        id: 11,
        body: "兜底测试",
        createdAt: "2026-11-26T00:00:00Z",
        canDelete: false,
        author: {
          kind: "member",
          id: 5,
          displayName: "竹林听雨",
          ...(bad !== undefined ? { avatarColor: bad } : {}),
        },
      });
      expect(parsed.author).toEqual({
        kind: "member",
        id: 5,
        displayName: "竹林听雨",
      });
      expect("avatarColor" in parsed.author).toBe(false);
    }
  });

  it("访客评论无论 avatarColor 为 null 还是伪造色值，一律不保留 avatarColor", () => {
    for (const guestColor of [undefined, null, "#4F46E5", "red"]) {
      const guest = parseCommentItem({
        id: 12,
        body: "访客留言",
        createdAt: "2026-11-26T00:00:00Z",
        canDelete: false,
        author: {
          kind: "guest",
          id: null,
          displayName: "未登录用户",
          ...(guestColor !== undefined ? { avatarColor: guestColor } : {}),
        },
      });
      expect(guest.author).toEqual({
        kind: "guest",
        id: null,
        displayName: "未登录用户",
      });
      expect("avatarColor" in guest.author).toBe(false);
    }
  });
});
