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

    // 点击展开后检查身份标签、设置入口与 POST 退出表单（操作项顺序：设置 -> 退出登录）
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel.hidden).toBe(false);
    expect(panel).toHaveTextContent("王景宏");
    expect(panel).toHaveTextContent("站主");

    const settingsLink = screen.getByRole("link", { name: "设置" });
    expect(settingsLink.tagName).toBe("A");
    expect(settingsLink).toHaveClass("account-panel-item");
    expect(settingsLink).toHaveAttribute(
      "href",
      `/accounts/settings/?next=${encodeURIComponent("/blog?tag=ai")}`,
    );

    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    const focusableItems = Array.from(
      panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([type="hidden"]), select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    );
    expect(focusableItems).toEqual([settingsLink, logoutBtn]);

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

  it("精确指针 pointer hover 展开、移出 150ms 后收起；Tab 进面板后移出指针不丢焦点；hover 后点击固定展开", async () => {
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

    // 仅派发旧 mouseEnter 不应重复触发（统一归口 Pointer 事件）
    fireEvent.mouseEnter(wrapper);
    expect(panel.hidden).toBe(true);

    // 指针移入展开
    fireEvent.pointerOver(wrapper, { pointerType: "mouse" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel.hidden).toBe(false);

    // 移出 100ms 内移回：取消关闭定时器
    fireEvent.pointerOut(wrapper, { pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(panel.hidden).toBe(false);

    fireEvent.pointerOver(wrapper, { pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(panel.hidden).toBe(false);

    // 悬停展开后若键盘焦点进入面板内部（如退出按钮），移开鼠标超过 150ms 不得自动关闭抢断焦点
    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    logoutBtn.focus();
    expect(document.activeElement).toBe(logoutBtn);
    fireEvent.pointerOut(wrapper, { pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(panel.hidden).toBe(false);

    // 焦点真实移出容器（blur 归还到 body）后自动关闭
    await act(async () => {
      logoutBtn.blur();
      await Promise.resolve();
    });
    expect(document.activeElement).toBe(document.body);
    expect(panel.hidden).toBe(true);

    // 重新指针移入 + 完整移出 150ms（焦点不在面板内）后收起
    fireEvent.pointerOver(wrapper, { pointerType: "mouse" });
    expect(panel.hidden).toBe(false);
    fireEvent.pointerOut(wrapper, { pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    // 再次 hover 展开后点击头像按钮：必须转为 pinned 固定展开，不得把面板关掉！
    fireEvent.pointerOver(wrapper, { pointerType: "mouse" });
    expect(panel.hidden).toBe(false);
    fireEvent.click(trigger);
    expect(panel.hidden).toBe(false);
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    // 处于 pinned 态时，指针移出超过 150ms 仍保持展开
    fireEvent.pointerOut(wrapper, { pointerType: "mouse" });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(panel.hidden).toBe(false);

    // 再次点击固定展开的头像按钮：收起面板
    fireEvent.click(trigger);
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("Esc 收起：pinned 或焦点在容器内时归还焦点给头像按钮，仅 hover 且焦点在外部输入框时不抢焦点", async () => {
    mockMatchMedia(true);
    const user = userEvent.setup();

    const { container } = render(
      <MemoryRouter>
        <div>
          <textarea aria-label="外部评论框" />
          <button type="button">外部按钮</button>
          <AccountPanel user={adminUser} csrfToken="csrf-1" nextTarget="/" />
        </div>
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    const wrapper = trigger.parentElement!;
    const panel = container.querySelector("#account-panel") as HTMLElement;
    const externalInput = screen.getByLabelText("外部评论框");

    // 1) 用户正在外部评论框输入，仅鼠标擦过顶栏触发 hover 展开：按 Esc 收起面板但不抢走外部评论框焦点
    externalInput.focus();
    expect(document.activeElement).toBe(externalInput);
    fireEvent.pointerOver(wrapper, { pointerType: "mouse" });
    expect(panel.hidden).toBe(false);

    await user.keyboard("{Escape}");
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(externalInput);

    // 2) 点击固定展开（pinned），焦点在退出按钮（或外部）时按 Esc：收起并把焦点归还给头像按钮
    await user.click(trigger);
    expect(panel.hidden).toBe(false);

    const logoutBtn = screen.getByRole("button", { name: "退出登录" });
    logoutBtn.focus();
    expect(document.activeElement).toBe(logoutBtn);

    await user.keyboard("{Escape}");
    expect(panel.hidden).toBe(true);
    expect(document.activeElement).toBe(trigger);

    // 3) 再次打开：点击面板内昵称文本不应误关面板；点击容器外部收起
    await user.click(trigger);
    expect(panel.hidden).toBe(false);
    await user.click(screen.getByText("王景宏"));
    expect(panel.hidden).toBe(false);

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

    // 场景 1：独立渲染 AccountPanel（未传 nextTarget 时默认取 location.pathname + location.search）
    const { container, unmount } = render(
      <MemoryRouter initialEntries={["/blog?page=2"]}>
        <AccountPanel user={adminUser} csrfToken="csrf-1" />
      </MemoryRouter>,
    );

    const trigger = screen.getByRole("button", { name: /账号/ });
    const panel = container.querySelector("#account-panel") as HTMLElement;

    await user.click(trigger);
    expect(panel.hidden).toBe(false);
    expect(document.activeElement).toBe(trigger);

    const settingsLink = screen.getByRole("link", { name: "设置" });
    expect(settingsLink).toHaveAttribute(
      "href",
      `/accounts/settings/?next=${encodeURIComponent("/blog?page=2")}`,
    );

    // 第 1 次 Tab 进入面板第 1 项「设置」链接，保持展开
    await user.tab();
    expect(document.activeElement).toBe(settingsLink);
    expect(panel.hidden).toBe(false);

    // 第 2 次 Tab 从「设置」切到「退出登录」按钮，保持展开
    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "退出登录" }),
    );
    expect(panel.hidden).toBe(false);

    // 第 3 次 Tab 离开容器最后一项：可靠收起面板
    await user.tab();
    expect(panel.hidden).toBe(true);
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    unmount();

    // 场景 2：面板后存在外部可聚焦元素时，从「设置」Tab 到「退出登录」不收起，再 Tab 到外部元素时收起
    const withAfter = render(
      <MemoryRouter initialEntries={["/awards"]}>
        <AccountPanel user={adminUser} csrfToken="csrf-1" />
        <button type="button">正文后续按钮</button>
      </MemoryRouter>,
    );
    const triggerAfter = screen.getByRole("button", { name: /账号/ });
    const panelAfter = withAfter.container.querySelector(
      "#account-panel",
    ) as HTMLElement;

    await user.click(triggerAfter);
    expect(panelAfter.hidden).toBe(false);

    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "设置" }));
    expect(panelAfter.hidden).toBe(false);

    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "退出登录" }),
    );
    expect(panelAfter.hidden).toBe(false);

    await user.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "正文后续按钮" }),
    );
    expect(panelAfter.hidden).toBe(true);

    withAfter.unmount();

    // 场景 3：路由切换自动收起
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

  it("合法 avatarColor 渲染为头像按钮背景色与白色首字母类名，且 8 色满足 WCAG AA 对比度", () => {
    const paletteHexes = [
      "#4F46E5",
      "#7C3AED",
      "#0369A1",
      "#0f766e",
      "#047857",
      "#B45309",
      "#BE123C",
      "#475569",
    ];

    function relativeLuminance(hex: string): number {
      const clean = hex.slice(1);
      const channels = [0, 2, 4].map((offset) => {
        const srgb = Number.parseInt(clean.slice(offset, offset + 2), 16) / 255;
        return srgb <= 0.03928 ? srgb / 12.92 : ((srgb + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    }

    function contrastRatio(hexA: string, hexB: string): number {
      const lumA = relativeLuminance(hexA);
      const lumB = relativeLuminance(hexB);
      const lighter = Math.max(lumA, lumB);
      const darker = Math.min(lumA, lumB);
      return (lighter + 0.05) / (darker + 0.05);
    }

    // 校验 CSS 原文中 .account-trigger.has-custom-color 声明白色首字母与 .account-panel-item 无下划线规则
    expect(headerCss).toMatch(
      /\.account-trigger\.has-custom-color\s*\{[^}]*color:\s*#(?:fff|ffffff)\b/is,
    );
    expect(headerCss).toMatch(
      /\.account-panel-item[^{]*\{[^}]*text-decoration:\s*none\b/s,
    );

    for (const hex of paletteHexes) {
      expect(contrastRatio(hex, "#ffffff")).toBeGreaterThanOrEqual(4.5);

      const { unmount } = render(
        <MemoryRouter>
          <AccountPanel
            user={{ ...adminUser, avatarColor: hex }}
            csrfToken="csrf-color"
          />
        </MemoryRouter>,
      );

      const trigger = screen.getByRole("button", { name: /账号/ });
      expect(trigger).toHaveClass("account-trigger", "has-custom-color");
      expect(trigger).toHaveStyle({ backgroundColor: hex });
      unmount();
    }

    // 兜底色 #ffc069 配 #0b1226 对比度同样 >= 4.5
    expect(contrastRatio("#ffc069", "#0b1226")).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    undefined,
    "",
    "#fff",
    "red",
    "#4F46E5; color:red",
    "#4F46E5; background:url(x)",
    "url(javascript:alert(1))",
  ])(
    "组件侧二次守卫：avatarColor 为 %j 时回退金底深字兜底样式且 style 属性为空",
    (badColor) => {
      render(
        <MemoryRouter>
          <AccountPanel
            user={{ ...adminUser, avatarColor: badColor }}
            csrfToken="csrf-fallback"
          />
        </MemoryRouter>,
      );

      const trigger = screen.getByRole("button", { name: /账号/ });
      expect(trigger).toHaveClass("account-trigger");
      expect(trigger).not.toHaveClass("has-custom-color");
      expect(trigger.getAttribute("style")).toBeNull();
    },
  );
});
