import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { awards } from "../data/awards";
import Awards from "./Awards";

describe("Awards 独立页", () => {
  it("渲染证书画廊标题、全部证书卡并设置浏览器标题", () => {
    render(
      <MemoryRouter initialEntries={["/awards"]}>
        <Awards />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("page-awards")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "证书画廊" })).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(awards.length);
    expect(screen.getByAltText(awards[0].alt)).toBeInTheDocument();
    expect(document.title).toBe("王景宏 · 证书画廊");
  });
});
