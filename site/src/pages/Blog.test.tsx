import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import type { ReactElement } from "react";
import Blog from "./Blog";
import Vlog from "./Vlog";

const wrap = (el: ReactElement) => render(<MemoryRouter>{el}</MemoryRouter>);

describe("Blog/Vlog 平台页", () => {
  it("blog 渲染 LINUX DO 与 CSDN 卡与返回链接", () => {
    wrap(<Blog />);
    expect(screen.getByText("看看我的博客")).toBeInTheDocument();
    expect(screen.getByLabelText("前往 LINUX DO 主页")).toHaveAttribute(
      "href",
      "https://linux.do/u/ceilf6/summary",
    );
    expect(screen.getByLabelText("前往 CSDN 博客主页")).toHaveAttribute(
      "href",
      "https://blog.csdn.net/2301_78856868",
    );
    expect(screen.getByText("返回主页").closest("a")).toHaveAttribute("href", "/");
  });

  it("blog 层序:平台卡区(main.stage)在 DOM 顺序上先于站内札记区(act-notes)", () => {
    // T6 评审预留:层序是对 spec 的有意偏差(平台卡为用户明示保护的长期入口,须在前)。
    // 文章落地后 NotesPreview 不再为 null,该断言才可测。
    const { container } = wrap(<Blog />);
    const stage = container.querySelector("main.stage");
    const notesAct = container.querySelector("section.act-notes");
    expect(stage).not.toBeNull();
    expect(notesAct).not.toBeNull();
    expect(
      stage!.compareDocumentPosition(notesAct!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("vlog 渲染抖音与 Bilibili 卡", () => {
    wrap(<Vlog />);
    expect(screen.getByText("看看我的视频")).toBeInTheDocument();
    expect(screen.getByLabelText("前往抖音主页")).toHaveAttribute(
      "href",
      "https://www.douyin.com/user/MS4wLjABAAAA1y3YuKPCNetqkJ0FC20HMHXx7lz_T1pQsgvloOaZn-Y",
    );
    expect(screen.getByLabelText("前往 Bilibili 主页")).toHaveAttribute(
      "href",
      "https://space.bilibili.com/3546602400647622",
    );
  });
});
