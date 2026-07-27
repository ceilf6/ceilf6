import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Hero } from "./Hero";

describe("Hero", () => {
  it("渲染姓名与 bio,@提及是外链", () => {
    render(<Hero />);
    expect(screen.getByRole("heading", { level: 1, name: "王景宏" })).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "@FrontAgent" });
    expect(link).toHaveAttribute("href", "https://github.com/ceilf6/FrontAgent");
    expect(link).toHaveAttribute("target", "_blank");
  });
});
