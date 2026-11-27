import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
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

// 最小 PNG 头:签名 + IHDR(宽高各 4 字节大端),足够尺寸读取器识别
function pngHeader(width, height) {
  const buf = Buffer.alloc(24);
  Buffer.from("89504e470d0a1a0a", "hex").copy(buf, 0);
  buf.writeUInt32BE(13, 8);
  buf.write("IHDR", 12, "ascii");
  buf.writeUInt32BE(width, 16);
  buf.writeUInt32BE(height, 20);
  return buf;
}

test("站内图片:从 <site>/public 读取尺寸写入 width/height,gallery 带 --r", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public", "notes", "g"), { recursive: true });
  writeFileSync(join(site, "public", "notes", "g", "a.png"), pngHeader(1600, 1200));
  writeFileSync(join(site, "public", "notes", "g", "b.png"), pngHeader(900, 1200));
  const md = join(dir, "g.md");
  writeFileSync(
    md,
    "---\ntitle: 图\ndate: 2026-11-27\nsummary: s\n---\n![甲](/notes/g/a.png)\n![乙](/notes/g/b.png)",
  );
  const { code } = mdNotes().load(posix(md));
  const html = JSON.parse(code.split("export const html = ")[1].replace(/;\s*$/, ""));
  assert.equal(
    html,
    '<figure class="note-gallery">'
      + '<img alt="甲" src="/notes/g/a.png" width="1600" height="1200" style="--r:1.3333" loading="lazy">'
      + '<img alt="乙" src="/notes/g/b.png" width="900" height="1200" style="--r:0.75" loading="lazy">'
      + "</figure>",
  );
});

test("站内图片缺失 → 构建期 fail loud,报错含文件路径与图片路径", () => {
  const md = join(notesDir(), "h.md");
  writeFileSync(md, "---\ntitle: 缺\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/none/x.webp)");
  const id = posix(md);
  assert.throws(
    () => mdNotes().load(id),
    (err) => err.message.includes(id) && err.message.includes("/notes/none/x.webp"),
  );
});

test("外链图片不读本地文件、不写尺寸", () => {
  const md = join(notesDir(), "i.md");
  writeFileSync(md, "---\ntitle: 外\ndate: 2026-11-27\nsummary: s\n---\n![x](https://a.b/x.png)");
  const { code } = mdNotes().load(posix(md));
  assert.ok(code.includes('src=\\"https://a.b/x.png\\" loading=\\"lazy\\"'));
});

test("图片路径越出 public(../)→ 构建期 fail loud,不读外部文件", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public"), { recursive: true });
  writeFileSync(join(site, "secret.png"), pngHeader(10, 10));
  const md = join(dir, "j.md");
  writeFileSync(md, "---\ntitle: 越\ndate: 2026-11-27\nsummary: s\n---\n![x](/../secret.png)");
  assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes("/../secret.png"));
});

test("/notes/ 之外的站内路径(如构建期打包的 /assets/)缺失时不报错、不写尺寸", () => {
  const md = join(notesDir(), "k.md");
  writeFileSync(md, "---\ntitle: 资\ndate: 2026-11-27\nsummary: s\n---\n![x](/assets/Profile.jpg)");
  const { code } = mdNotes().load(posix(md));
  assert.ok(code.includes('src=\\"/assets/Profile.jpg\\" loading=\\"lazy\\"'));
});

test("public 内的符号链接指向外部文件 → 构建期 fail loud", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public", "notes", "l"), { recursive: true });
  writeFileSync(join(site, "outside.png"), pngHeader(10, 10));
  symlinkSync(join(site, "outside.png"), join(site, "public", "notes", "l", "a.png"));
  const md = join(dir, "l.md");
  writeFileSync(md, "---\ntitle: 链\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/l/a.png)");
  assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes("越出 public"));
});

test("尺寸读取器不支持的格式(如 SVG)不报错、不写尺寸", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public"), { recursive: true });
  writeFileSync(join(site, "public", "chart.svg"), '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>');
  const md = join(dir, "m.md");
  writeFileSync(md, "---\ntitle: 矢\ndate: 2026-11-27\nsummary: s\n---\n![x](/chart.svg)");
  const { code } = mdNotes().load(posix(md));
  assert.ok(code.includes('src=\\"/chart.svg\\" loading=\\"lazy\\"'));
});

test("缺图判定按规范化路径:/assets/../notes/缺图 同样构建失败", () => {
  const dir = notesDir();
  mkdirSync(join(dir, "..", "..", "public"), { recursive: true });
  const md = join(dir, "n.md");
  writeFileSync(md, "---\ntitle: 绕\ndate: 2026-11-27\nsummary: s\n---\n![x](/assets/../notes/no-such.webp)");
  assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes("不存在"));
});

test("图片地址误指目录 → 构建期 fail loud(读取错误不被吞掉)", () => {
  const dir = notesDir();
  mkdirSync(join(dir, "..", "..", "public", "notes", "dir"), { recursive: true });
  const md = join(dir, "o.md");
  writeFileSync(md, "---\ntitle: 目\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/dir)");
  assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes("/notes/dir"));
});

test("以 .. 开头的普通文件名不算越界:/notes/..draft.webp 缺失照样报缺图", () => {
  const dir = notesDir();
  mkdirSync(join(dir, "..", "..", "public", "notes"), { recursive: true });
  const md = join(dir, "p.md");
  writeFileSync(md, "---\ntitle: 点\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/..draft.webp)");
  assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes("不存在"));
});

test("已识别格式但文件损坏(截断的 PNG)→ 构建期 fail loud,不当作不支持格式放过", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public", "notes", "q"), { recursive: true });
  writeFileSync(join(site, "public", "notes", "q", "bad.png"), pngHeader(10, 10).subarray(0, 12));
  const md = join(dir, "q.md");
  writeFileSync(md, "---\ntitle: 损\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/q/bad.png)");
  const id = posix(md);
  assert.throws(
    () => mdNotes().load(id),
    (err) => err.message.includes(id) && err.message.includes("/notes/q/bad.png"),
  );
});

test("图片路径含非法百分号编码 → 报错带札记路径与图片地址", () => {
  const md = join(notesDir(), "r.md");
  writeFileSync(md, "---\ntitle: 码\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/100%.webp)");
  const id = posix(md);
  assert.throws(
    () => mdNotes().load(id),
    (err) => err.message.includes(id) && err.message.includes("/notes/100%.webp"),
  );
});

test("截断的 JPEG / WebP 配图 → 构建期 fail loud", () => {
  const dir = notesDir();
  const site = join(dir, "..", "..");
  mkdirSync(join(site, "public", "notes", "t"), { recursive: true });
  writeFileSync(
    join(site, "public", "notes", "t", "a.jpg"),
    Buffer.from("ffd8ffe000104a46494600010100000100010000", "hex"),
  );
  writeFileSync(
    join(site, "public", "notes", "t", "b.webp"),
    Buffer.concat([Buffer.from("RIFF"), Buffer.alloc(4), Buffer.from("WEBPVP8X")]),
  );
  for (const name of ["a.jpg", "b.webp"]) {
    const md = join(dir, `t-${name}.md`);
    writeFileSync(md, `---\ntitle: 截\ndate: 2026-11-27\nsummary: s\n---\n![x](/notes/t/${name})`);
    assert.throws(() => mdNotes().load(posix(md)), (err) => err.message.includes(`/notes/t/${name}`));
  }
});
