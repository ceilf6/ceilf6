// 札记 Markdown 编译器的规格测试:测试即规格,实现须以此为准。
import test from "node:test";
import assert from "node:assert/strict";
import { parseFrontmatter, mdToHtml, compileNote } from "./markdown.mjs";

test("parseFrontmatter 取出 meta 与正文", () => {
  const { meta, body } = parseFrontmatter("---\ntitle: 甲\ndate: 2026-07-27\n---\n正文");
  assert.equal(meta.title, "甲");
  assert.equal(meta.date, "2026-07-27");
  assert.equal(body, "正文");
});

test("无 frontmatter 时 meta 为空、正文原样", () => {
  const { meta, body } = parseFrontmatter("裸正文");
  assert.deepEqual(meta, {});
  assert.equal(body, "裸正文");
});

test("标题降一级:# → h2", () => {
  assert.equal(mdToHtml("# 标题"), "<h2>标题</h2>");
  assert.equal(mdToHtml("### 小节"), "<h4>小节</h4>");
});

test("段落与行内语法", () => {
  assert.equal(
    mdToHtml("**粗** *斜* `码` [链](https://a.b)"),
    '<p><strong>粗</strong> <em>斜</em> <code>码</code> <a href="https://a.b" target="_blank" rel="noopener noreferrer">链</a></p>',
  );
});

test("连续行合并为同一段落", () => {
  assert.equal(mdToHtml("第一行\n第二行"), "<p>第一行 第二行</p>");
});

test("无序列表", () => {
  assert.equal(mdToHtml("- 甲\n- 乙"), "<ul><li>甲</li><li>乙</li></ul>");
});

test("围栏代码块转义且不解析行内语法", () => {
  assert.equal(mdToHtml("```\n<b>&x\n```"), "<pre><code>&lt;b&gt;&amp;x</code></pre>");
});

test("HTML 注入被转义", () => {
  assert.equal(mdToHtml("<script>1</script>"), "<p>&lt;script&gt;1&lt;/script&gt;</p>");
});

test("compileNote = frontmatter + html", () => {
  const { meta, html } = compileNote("---\ntitle: 甲\n---\n# 见");
  assert.equal(meta.title, "甲");
  assert.equal(html, "<h2>见</h2>");
});
