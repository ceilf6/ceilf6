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

test("frontmatter 容忍 CRLF", () => {
  const { meta, body } = parseFrontmatter("---\r\ntitle: 甲\r\n---\r\n正文");
  assert.equal(meta.title, "甲");
  assert.equal(body, "正文");
});

test("frontmatter 闭合定界符须整行:---- 不闭合", () => {
  const { meta, body } = parseFrontmatter("---\ntitle: x\n----\nbody");
  assert.deepEqual(meta, {});
  assert.equal(body, "---\ntitle: x\n----\nbody");
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

test("strong/em 不渗入链接与图片标记", () => {
  assert.equal(
    mdToHtml("[a*b](c) *x*"),
    '<p><a href="c" target="_blank" rel="noopener noreferrer">a*b</a> <em>x</em></p>',
  );
  assert.equal(
    mdToHtml("[x](https://a.b/*p*)"),
    '<p><a href="https://a.b/*p*" target="_blank" rel="noopener noreferrer">x</a></p>',
  );
  assert.equal(mdToHtml("![a*b](c)"), '<p><img alt="a*b" src="c" loading="lazy"></p>');
});

test("链接文本内的 strong 正常解析", () => {
  assert.equal(
    mdToHtml("[**a**](b)"),
    '<p><a href="b" target="_blank" rel="noopener noreferrer"><strong>a</strong></a></p>',
  );
});

test("引用块多行合并", () => {
  assert.equal(mdToHtml("> 甲\n> 乙"), "<blockquote><p>甲 乙</p></blockquote>");
});

test("图片:标准段落包裹", () => {
  assert.equal(mdToHtml("![图](x.png)"), '<p><img alt="图" src="x.png" loading="lazy"></p>');
});

test("行内 code 不二次解析其它行内语法", () => {
  assert.equal(mdToHtml("`[x](y)`"), "<p><code>[x](y)</code></p>");
  assert.equal(mdToHtml("`a**b**c`"), "<p><code>a**b**c</code></p>");
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
