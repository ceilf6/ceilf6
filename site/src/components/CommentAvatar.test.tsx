import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { parseCommentItem, type CommentItem } from "../data/comments";
import { CommentAvatar } from "./CommentAvatar";
import { NoteCommentCard } from "./NoteCommentCard";

const rawAvatarCss = readFileSync(
  resolve(process.cwd(), "src/components/CommentAvatar.css"),
  "utf8",
);
const rawCommentsCss = readFileSync(
  resolve(process.cwd(), "src/components/NoteComments.css"),
  "utf8",
);

const noopRefresh = () => Promise.resolve(null);
const noopDeleted = () => {};

describe("CommentAvatar 与 NoteCommentCard 评论者头像及防溢出布局", () => {
  it("成员评论渲染 28px 首字母头像，背景色等于 avatarColor，文字为白色，且头像带 aria-hidden=true", () => {
    const item: CommentItem = {
      id: 1,
      body: "成员带色评论",
      createdAt: "2026-11-26T05:00:00Z",
      canDelete: false,
      author: {
        kind: "member",
        id: 7,
        displayName: "竹林听雨",
        avatarColor: "#4F46E5",
      },
    };

    const { container } = render(
      <ul>
        <NoteCommentCard
          item={item}
          viewerStatus="ready"
          viewer={{ user: null, csrfToken: "csrf", guestCommentsAllowed: true }}
          onRefreshViewerAfterConflict={noopRefresh}
          onCommentDeleted={noopDeleted}
        />
      </ul>,
    );

    const avatar = container.querySelector(".comment-avatar") as HTMLElement;
    expect(avatar).not.toBeNull();
    expect(avatar).toHaveAttribute("aria-hidden", "true");
    expect(avatar).toHaveClass("comment-avatar", "is-member", "has-custom-color");
    expect(avatar).toHaveTextContent("竹");
    expect(avatar).toHaveStyle({ backgroundColor: "#4F46E5" });

    // CSS 原文断言：28px 尺寸与自定义底色下的白色文字
    expect(rawAvatarCss).toMatch(/\.comment-avatar\s*\{[^}]*width:\s*28px\b/s);
    expect(rawAvatarCss).toMatch(/\.comment-avatar\s*\{[^}]*height:\s*28px\b/s);
    expect(rawAvatarCss).toMatch(
      /\.comment-avatar\.has-custom-color\s*\{[^}]*color:\s*#(?:fff|ffffff)\b/is,
    );

    // 读屏按作者名查找仍然只有作者名文字节点（单字昵称「竹」时也只命中非 aria-hidden 的作者名）
    const singleCharItem: CommentItem = {
      ...item,
      id: 2,
      author: { kind: "member", id: 8, displayName: "竹", avatarColor: "#0F766E" },
    };
    const singleView = render(
      <ul>
        <NoteCommentCard
          item={singleCharItem}
          viewerStatus="ready"
          viewer={{ user: null, csrfToken: "csrf", guestCommentsAllowed: true }}
          onRefreshViewerAfterConflict={noopRefresh}
          onCommentDeleted={noopDeleted}
        />
      </ul>,
    );
    const authorSpan = singleView.container.querySelector(".note-comment-author")!;
    expect(authorSpan).toHaveTextContent("竹");
    expect(authorSpan.closest('[aria-hidden="true"]')).toBeNull();
    const hiddenAvatar = singleView.container.querySelector(".comment-avatar")!;
    expect(hiddenAvatar).toHaveAttribute("aria-hidden", "true");
  });

  it("访客评论渲染人形 SVG 图标、不显示文字，且保留「访客」标签", () => {
    const guestItem: CommentItem = {
      id: 3,
      body: "路过留爪",
      createdAt: "2026-11-26T05:10:00Z",
      canDelete: false,
      author: {
        kind: "guest",
        id: null,
        displayName: "未登录用户",
      },
    };

    const { container } = render(
      <ul>
        <NoteCommentCard
          item={guestItem}
          viewerStatus="ready"
          viewer={{ user: null, csrfToken: "csrf", guestCommentsAllowed: true }}
          onRefreshViewerAfterConflict={noopRefresh}
          onCommentDeleted={noopDeleted}
        />
      </ul>,
    );

    const avatar = container.querySelector(".comment-avatar") as HTMLElement;
    expect(avatar).not.toBeNull();
    expect(avatar).toHaveAttribute("aria-hidden", "true");
    expect(avatar).toHaveClass("comment-avatar", "is-guest");
    expect(avatar.querySelector("svg")).not.toBeNull();
    expect(avatar.textContent).toBe("");
    expect(avatar.getAttribute("style")).toBeNull();

    expect(screen.getByText("未登录用户")).toBeInTheDocument();
    expect(screen.getByText("访客")).toHaveClass("note-comment-badge");
  });

  it.each([
    undefined,
    "",
    "red",
    "#fff",
    "#fff; background:url(x)",
    "url(javascript:alert(1))",
  ])(
    "avatarColor 为 %j 时评论正常显示、使用金底深字兜底样式且非法值绝不进入内联样式",
    (badColor) => {
      // 1) 经 parseCommentItem 解析层守卫
      const parsed = parseCommentItem({
        id: 4,
        body: "兜底配色正文",
        createdAt: "2026-11-26T05:20:00Z",
        canDelete: false,
        author: {
          kind: "member",
          id: 9,
          displayName: "明月",
          ...(badColor !== undefined ? { avatarColor: badColor } : {}),
        },
      });
      const view1 = render(
        <ul>
          <NoteCommentCard
            item={parsed}
            viewerStatus="ready"
            viewer={{ user: null, csrfToken: "csrf", guestCommentsAllowed: true }}
            onRefreshViewerAfterConflict={noopRefresh}
            onCommentDeleted={noopDeleted}
          />
        </ul>,
      );
      expect(screen.getByText("兜底配色正文")).toBeInTheDocument();
      const av1 = view1.container.querySelector(".comment-avatar") as HTMLElement;
      expect(av1).toHaveClass("comment-avatar", "is-member");
      expect(av1).not.toHaveClass("has-custom-color");
      expect(av1.getAttribute("style")).toBeNull();
      view1.unmount();

      // 2) 组件侧二次守卫：直接把非法 avatarColor 传给 CommentAvatar
      const view2 = render(
        <CommentAvatar
          author={{
            kind: "member",
            id: 9,
            displayName: "明月",
            avatarColor: badColor,
          }}
        />,
      );
      const av2 = view2.container.querySelector(".comment-avatar") as HTMLElement;
      expect(av2).not.toHaveClass("has-custom-color");
      expect(av2.getAttribute("style")).toBeNull();
      view2.unmount();
    },
  );

  it("兜底样式与卡片网格护栏：正文含 300 字符无空格连续串时右列具备 min-width: 0 且样式职责分离", () => {
    expect(rawAvatarCss).toContain("var(--accent-gold)");
    expect(rawAvatarCss).toContain("var(--bg-void)");
    expect(rawCommentsCss).not.toContain(".comment-avatar");

    expect(rawCommentsCss).toMatch(
      /\.note-comment-card\s*\{[^}]*display:\s*grid\b[^}]*grid-template-columns:\s*28px\s+minmax\(0,\s*1fr\)/s,
    );
    expect(rawCommentsCss).toMatch(
      /\.note-comment-main\s*\{[^}]*min-width:\s*0\b/s,
    );
    expect(rawCommentsCss).toMatch(
      /\.note-comment-body\s*\{[^}]*overflow-wrap:\s*anywhere\b/s,
    );

    const unbroken300 = "x".repeat(300);
    const { container } = render(
      <ul>
        <NoteCommentCard
          item={{
            id: 5,
            body: unbroken300,
            createdAt: "2026-11-26T05:30:00Z",
            canDelete: false,
            author: {
              kind: "member",
              id: 3,
              displayName: "长串测试者",
              avatarColor: "#0369A1",
            },
          }}
          viewerStatus="ready"
          viewer={{ user: null, csrfToken: "csrf", guestCommentsAllowed: true }}
          onRefreshViewerAfterConflict={noopRefresh}
          onCommentDeleted={noopDeleted}
        />
      </ul>,
    );

    const card = container.querySelector(".note-comment-card")!;
    const mainCol = card.querySelector(".note-comment-main")!;
    expect(mainCol).not.toBeNull();
    expect(mainCol.querySelector(".note-comment-body")).toHaveTextContent(
      unbroken300,
    );
  });
});
