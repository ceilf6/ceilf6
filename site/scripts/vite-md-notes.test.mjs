import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, sep } from "node:path";
import { mdNotes } from "./vite-md-notes.mjs";

// 插件契约是 posix id(Vite 内部统一正斜杠):win32 下 join 产反斜杠,
// 喂进插件会误判为「非 notes 路径」,故显式归一——这也钉住了该契约。
const posix = (p) => p.split(sep).join("/");

function notesDir() {
  const dir = join(mkdtempSync(join(tmpdir(), "mdnotes-")), "content", "notes");
  mkdirSync(dir, { recursive: true });
  return dir;
}

test("load 把 content/notes 下的 md 编译为 meta/html 纯导出模块", () => {
  const md = join(notesDir(), "a.md");
  writeFileSync(md, "---\ntitle: 甲\ndate: 2026-07-27\nsummary: 摘要\n---\n正文");
  const res = mdNotes().load(posix(md));
  assert.ok(
    res.code.includes(
      'export const meta = {"title":"甲","date":"2026-07-27","summary":"摘要"}',
    ),
  );
  assert.ok(res.code.includes('export const html = "<p>正文</p>"'));
  assert.equal(res.moduleSideEffects, false);
});

test("?meta 查询只 emit meta 导出——主包物理上不含 html", () => {
  const md = join(notesDir(), "c.md");
  writeFileSync(md, "---\ntitle: 丙\ndate: 2026-07-27\nsummary: 摘要\n---\n正文");
  const res = mdNotes().load(`${posix(md)}?meta`);
  assert.ok(
    res.code.includes('export const meta = {"title":"丙","date":"2026-07-27","summary":"摘要"}'),
  );
  assert.ok(!res.code.includes("export const html"));
  assert.equal(res.moduleSideEffects, false);
});

test("?meta 分支同样跑 frontmatter 守卫", () => {
  const md = join(notesDir(), "d.md");
  writeFileSync(md, "没有 frontmatter 的正文");
  assert.throws(
    () => mdNotes().load(`${posix(md)}?meta`),
    (err) => err.message.includes("title/date/summary"),
  );
});

test("?meta&t=1(HMR 追参)仍只 emit meta", () => {
  const md = join(notesDir(), "e.md");
  writeFileSync(md, "---\ntitle: 戊\ndate: 2026-07-27\nsummary: s\n---\n正文");
  const res = mdNotes().load(`${posix(md)}?meta&t=1`);
  assert.ok(res.code.includes("export const meta"));
  assert.ok(!res.code.includes("export const html"));
});

test("date 非 YYYY-MM-DD → 构建期 fail loud,报错含路径与实际值", () => {
  const md = join(notesDir(), "f.md");
  writeFileSync(md, "---\ntitle: 己\ndate: 2026-7-5\nsummary: s\n---\n正文");
  const id = posix(md);
  assert.throws(
    () => mdNotes().load(id),
    (err) => err.message.includes(id) && err.message.includes("2026-7-5"),
  );
});

test("缺必填 frontmatter 键 → 构建期 fail loud,报错含文件路径", () => {
  const md = join(notesDir(), "b.md");
  writeFileSync(md, "没有 frontmatter 的正文");
  const id = posix(md);
  assert.throws(
    () => mdNotes().load(id),
    (err) => err.message.includes(id) && err.message.includes("title/date/summary"),
  );
});

test("非 notes 路径不接管", () => {
  assert.equal(mdNotes().load("/x/README.md"), null);
});
