import { describe, expect, it } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { awards } from "./awards";

describe("awards manifest", () => {
  it("有 15 条完整记录，路径契约与旧站一致", () => {
    expect(awards).toHaveLength(15);
    for (const a of awards) {
      expect(a.src).toMatch(/^\/resume-awards\/imgs\//);
      expect(a.thumb).toMatch(/^\/resume-awards\/imgs\/thumbs\//);
      expect(a.display).toMatch(/^\/resume-awards\/imgs\/display\/.+\.jpg$/);
      expect(a.alt).toBeTruthy();
      for (const n of [a.width, a.height, a.thumbWidth, a.thumbHeight]) {
        expect(n).toBeGreaterThan(0);
      }
    }
  });

  it("清单里的每个文件都真实存在于 public/", () => {
    const publicDir = join(__dirname, "../../public");
    for (const a of awards) {
      expect(existsSync(join(publicDir, a.src)), a.src).toBe(true);
      expect(existsSync(join(publicDir, a.thumb)), a.thumb).toBe(true);
      expect(existsSync(join(publicDir, a.display)), a.display).toBe(true);
    }
  });
});
