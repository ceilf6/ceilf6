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

  // 主页精选窗口:items 按数据层契约已日期倒序,max 截取即取最新;/blog 不传 max 才是全集
  const SEVEN_ITEMS = Array.from({ length: 7 }, (_, i) => ({
    slug: `n${i}`,
    title: `文章${i}`,
    date: `2026-07-2${7 - i}`, // 27..21 倒序,n6 最旧
    summary: `摘要${i}`,
    source: "站内",
    sourceUrl: "",
  }));

  it("max={6} 时恰渲染 6 张卡,且为日期最新的 6 个(主页精选窗口)", () => {
    const { container } = render(
      <MemoryRouter>
        <NotesPreview heading="札记精选" items={SEVEN_ITEMS} max={6} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll("a.note-card")).toHaveLength(6);
    expect(screen.getByText("文章0")).toBeInTheDocument(); // 最新在列
    expect(screen.queryByText("文章6")).toBeNull(); // 最旧被窗口截断
  });

  it("不传 max 全量渲染(/blog 才是全集)", () => {
    const { container } = render(
      <MemoryRouter>
        <NotesPreview heading="全部札记" items={SEVEN_ITEMS} />
      </MemoryRouter>,
    );
    expect(container.querySelectorAll("a.note-card")).toHaveLength(7);
  });
});
