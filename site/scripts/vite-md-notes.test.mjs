import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { mdNotes } from "./vite-md-notes.mjs";

test("load 把 content/notes 下的 md 编译为 meta/html 纯导出模块", () => {
  const dir = join(mkdtempSync(join(tmpdir(), "mdnotes-")), "content", "notes");
  mkdirSync(dir, { recursive: true });
  const md = join(dir, "a.md");
  writeFileSync(md, "---\ntitle: 甲\n---\n正文");
  const res = mdNotes().load(md);
  assert.ok(res.code.includes('export const meta = {"title":"甲"}'));
  assert.ok(res.code.includes('export const html = "<p>正文</p>"'));
  assert.equal(res.moduleSideEffects, false);
});

test("非 notes 路径不接管", () => {
  assert.equal(mdNotes().load("/x/README.md"), null);
});
