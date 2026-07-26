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
