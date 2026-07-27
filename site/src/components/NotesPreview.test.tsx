import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { NotesPreview } from "./NotesPreview";

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

const TWO_ITEMS = [
  ...ITEMS,
  {
    slug: "b",
    title: "文章乙",
    date: "2026-07-26",
    summary: "摘要乙",
    source: "CSDN",
    sourceUrl: "https://blog.csdn.net/2301_78856868/article/details/2",
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

  it("双条目渲染 2 张卡,各自链接正确(覆盖 map/key 路径)", () => {
    const { container } = render(
      <MemoryRouter>
        <NotesPreview heading="札记精选" items={TWO_ITEMS} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll("a.note-card")).toHaveLength(2);
    expect(screen.getByText("文章甲").closest("a")).toHaveAttribute("href", "/notes/a");
    expect(screen.getByText("文章乙").closest("a")).toHaveAttribute("href", "/notes/b");
  });
});
