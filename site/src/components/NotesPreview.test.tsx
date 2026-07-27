import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { NotesPreview } from "./NotesPreview";
import Blog from "../pages/Blog";

const ITEMS = [
  {
    slug: "a",
    title: "文章甲",
    date: "2026-07-27",
    summary: "摘要甲",
    source: "LinuxDo",
    sourceUrl: "https://linux.do/t/topic/1",
  },
];

describe("NotesPreview", () => {
  it("渲染标题、来源徽标与 /notes/:slug 链接", () => {
    render(
      <MemoryRouter>
        <NotesPreview heading="札记精选" items={ITEMS} />
      </MemoryRouter>,
    );
    expect(screen.getByText("札记精选")).toBeInTheDocument();
    expect(screen.getByText("LinuxDo")).toBeInTheDocument();
    expect(screen.getByText("文章甲").closest("a")).toHaveAttribute("href", "/notes/a");
  });

  it("空列表渲染 null(文章未落地前站点与现状一致)", () => {
    const { container } = render(
      <MemoryRouter>
        <NotesPreview heading="札记精选" items={[]} />
      </MemoryRouter>,
    );
    expect(container.firstChild).toBeNull();
  });
});

describe("Blog 两层升级不变项", () => {
  it("平台卡与返回链接原样保留", () => {
    render(
      <MemoryRouter>
        <Blog />
      </MemoryRouter>,
    );
    expect(screen.getByLabelText("前往 LINUX DO 主页")).toHaveAttribute(
      "href",
      "https://linux.do/u/ceilf6/summary",
    );
    expect(screen.getByLabelText("前往 CSDN 博客主页")).toHaveAttribute(
      "href",
      "https://blog.csdn.net/2301_78856868",
    );
  });
});
