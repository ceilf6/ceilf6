import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router";
import type { SessionUser } from "../data/comments";
import { AccountPanel, extractAvatarInitial } from "./AccountPanel";
import rawHeaderCss from "./SiteHeader.css?raw";

const headerCss =
  rawHeaderCss ||
  readFileSync(resolve(process.cwd(), "src/components/SiteHeader.css"), "utf8");

function mockMatchMedia(fineHover: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(hover: hover) and (pointer: fine)" ? fineHover : false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    onchange: null,
    dispatchEvent: () => false,
  }));
}

const adminUser: SessionUser = {
  id: 1,
  displayName: "王景宏",
  isCommentAdmin: true,
};

const memberUser: SessionUser = {
  id: 12,
  displayName: "用户 #12",
  isCommentAdmin: false,
};

describe("extractAvatarInitial 首字母取字", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const standardCases: Array<[string, string]> = [
    ["王景宏", "王"],
    ["王", "王"],
    ["abc", "A"],
    ["🇨🇳", "🇨🇳"],
    ["🇨🇳旅行者", "🇨🇳"],
    ["👋🏽", "👋🏽"],
    ["👋🏽你好", "👋🏽"],
    ["👨‍👩‍👧", "👨‍👩‍👧"],
    ["e\u0301", "E\u0301"],
    ["ß", "SS"],
    ["用户 #12", "用"],
  ];

  it.each(standardCases)("Intl.Segmenter 路径：%j -> %j", (input, expected) => {
    expect(extractAvatarInitial(input)).toBe(expected);
  });

  it("空串或纯空白防御返回 ?", () => {
    expect(extractAvatarInitial("")).toBe("?");
    expect(extractAvatarInitial("   ")).toBe("?");
  });

  it.each(standardCases)("无 Intl.Segmenter 回退路径：%j -> %j", (input, expected) => {
    const originalSegmenter = Intl.Segmenter;
    Object.defineProperty(Intl, "Segmenter", {
      configurable: true,
      value: undefined,
    });
    try {
      expect(extractAvatarInitial(input)).toBe(expected);
    } finally {
      Object.defineProperty(Intl, "Segmenter", {
        configurable: true,
        value: originalSegmenter,
      });
    }
  });
});

describe("AccountPanel Disclosure 面板与交互", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("遵循 WAI-ARIA Disclosure 模式：常驻 DOM + hidden 控制、无 menu 角色、区分站主与普通用户且含 POST 退出表单", () => {
    mockMatchMedia(false);
    const { container, rerender } = render(
      <MemoryRouter initialEntries={["/blog?tag=ai"]}>
        <AccountPanel
          user={adminUser}
          csrfToken="csrf-admin"
          nextTarget="/blog?tag=ai"
        />
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    expect(trigger).toHaveAttribute("aria-label", "账号：王景宏");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveAttribute("aria-controls", "account-panel");
    expect(trigger).not.toHaveAttribute("aria-haspopup");
    expect(trigger).toHaveTextContent("王");
    expect(trigger).toHaveClass("account-trigger");

    // 收起时 #account-panel 仍常驻 DOM 且带 hidden 属性
    const panel = container.querySelector("#account-panel") as HTMLElement;
    expect(panel).not.toBeNull();
    expect(panel.hidden).toBe(true);
    expect(panel).not.toHaveAttribute("role", "menu");
    expect(panel).toHaveClass("account-panel", "account-panel-frosted");

    // 校验 CSS 原文兜底色变量与 #account-panel[hidden] 强隐藏规则
    expect(headerCss).toMatch(/#account-panel\[hidden\]\s*\{[^}]*display:\s*none\s*!important/s);
    expect(headerCss).toContain("var(--accent-gold)");
    expect(headerCss).toContain("var(--bg-void)");

    // 点击展开后检查身份标签与 POST 退出表单（第 02 步不含设置链接）
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel.hidden).toBe(false);
    expect(panel).toHaveTextContent("王景宏");
    expect(panel).toHaveTextContent("站主");
    expect(screen.queryByRole("link", { name: /设置/ })).toBeNull();

    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    const form = logoutBtn.closest("form")!;
    expect(form).toHaveAttribute("method", "post");
    expect(form).toHaveAttribute(
      "action",
      `/accounts/logout/?next=${encodeURIComponent("/blog?tag=ai")}`,
    );
    expect(
      form.querySelector('input[name="csrfmiddlewaretoken"]'),
    ).toHaveValue("csrf-admin");
    expect(form.querySelector('input[name="next"]')).toHaveValue("/blog?tag=ai");

    // 切换为普通用户显示「用户」
    rerender(
      <MemoryRouter initialEntries={["/blog?tag=ai"]}>
        <AccountPanel
          user={memberUser}
          csrfToken="csrf-member"
          nextTarget="/blog?tag=ai"
        />
      </MemoryRouter>,
    );
    expect(panel).toHaveTextContent("用户 #12");
    expect(panel).toHaveTextContent("用户");
    expect(panel).not.toHaveTextContent("站主");
  });

  it("精确指针 hover 展开、移出 150ms 后收起；hover 后点击转为固定展开不误关，再次点击收起", () => {
    vi.useFakeTimers();
    mockMatchMedia(true);

    const { container } = render(
      <MemoryRouter>
        <AccountPanel user={adminUser} csrfToken="csrf-1" nextTarget="/" />
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    const wrapper = trigger.parentElement!;
    const panel = container.querySelector("#account-panel") as HTMLElement;

    // 移入展开
    fireEvent.mouseEnter(wrapper);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel.hidden).toBe(false);

    // 移出 100ms 内移回：取消关闭定时器
    fireEvent.mouseLeave(wrapper);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(panel.hidden).toBe(false);

    fireEvent.mouseEnter(wrapper);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(panel.hidden).toBe(false);

    // 完整移出 150ms 后收起
    fireEvent.mouseLeave(wrapper);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    // 再次 hover 展开后点击头像按钮：必须转为 pinned 固定展开，不得把面板关掉！
    fireEvent.mouseEnter(wrapper);
    expect(panel.hidden).toBe(false);
    fireEvent.click(trigger);
    expect(panel.hidden).toBe(false);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // 处于 pinned 态时，鼠标移出超过 150ms 仍保持展开
    fireEvent.mouseLeave(wrapper);
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(panel.hidden).toBe(false);

    // 再次点击固定展开的头像按钮：收起面板
    fireEvent.click(trigger);
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("Esc 收起并归还焦点给头像按钮，点击外部收起，点击面板内非聚焦文本不误关", async () => {
    mockMatchMedia(false);
    const user = userEvent.setup();

    const { container } = render(
      <MemoryRouter>
        <div>
          <button type="button">外部按钮</button>
          <AccountPanel user={adminUser} csrfToken="csrf-1" nextTarget="/" />
        </div>
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    const panel = container.querySelector("#account-panel") as HTMLElement;

    await user.click(trigger);
    expect(panel.hidden).toBe(false);

    // 焦点移入退出按钮后按 Esc：面板收起且焦点回到头像按钮
    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    logoutBtn.focus();
    expect(document.activeElement).toBe(logoutBtn);

    await user.keyboard("{Escape}");
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);

    // 再次打开：点击面板内昵称文本不应误关面板
    await user.click(trigger);
    expect(panel.hidden).toBe(false);
    await user.click(screen.getByText("王景宏"));
    expect(panel.hidden).toBe(false);

    // 点击容器外部：面板收起
    await user.click(screen.getByRole("button", { name: "外部按钮" }));
    expect(panel.hidden).toBe(true);
  });

  it("从面板最后一项按 Tab 移出容器时自动收起（无论后续有无其他可聚焦元素），路由切换也自动收起", async () => {
    mockMatchMedia(false);
    const user = userEvent.setup();

    function RouteSwitcher() {
      const navigate = useNavigate();
      return (
        <button type="button" onClick={() => navigate("/awards")}>
          go-awards
        </button>
      );
    }

    // 场景 1：独立渲染 AccountPanel（面板后无其他可聚焦元素，Tab 落到 body）
    const { container, unmount } = render(
      <MemoryRouter>
        <AccountPanel user={adminUser} csrfToken="csrf-1" nextTarget="/" />
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    const panel = container.querySelector("#account-panel") as HTMLElement;

    await user.click(trigger);
    expect(panel.hidden).toBe(false);
    expect(document.activeElement).toBe(trigger);

    // 第 1 次 Tab 进入面板内的「退出登录」按钮，保持展开
    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "退出登录" }),
    );
    expect(panel.hidden).toBe(false);

    // 第 2 次 Tab 离开容器最后一项：可靠收起面板
    await user.tab();
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    unmount();

    // 场景 2：路由切换自动收起
    const view2 = render(
      <MemoryRouter initialEntries={["/"]}>
        <AccountPanel user={adminUser} csrfToken="csrf-1" nextTarget="/" />
        <RouteSwitcher />
      </MemoryRouter>,
    );
    const trigger2 = screen.getByRole("button", { name: /账号/ });
    const panel2 = view2.container.querySelector("#account-panel") as HTMLElement;

    fireEvent.click(trigger2);
    expect(panel2.hidden).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "go-awards" }));
    expect(panel2.hidden).toBe(true);
  });
});
