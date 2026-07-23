# 黎明晨光主题 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** index.html 文案中文化（王景宏）+ 页面调成"黎明晨光"暖色深色调，viewer.html 同步色值，单条 commit 推 main 自动部署 ECS 并验证线上。

**Architecture:** 纯静态改动：index.html 内联 CSS 的色彩令牌与散落色值统一替换（青色交互 → 阳光金，光晕调暖，新增晨霞紫），h1 文案换中文；hint SVG 整文件重制为中文；viewer.html 只换色值不动结构。无构建步骤。

**Tech Stack:** 静态 HTML/CSS/SVG；node --test（已有 13 用例）；Playwright 截图目检；GitHub Actions 部署 ECS。

## Global Constraints

- 不动的文件：`assets/github-stats-card.svg`、`assets/huggingface-card.svg`、`assets/vlog-card.svg`、`assets/blog-card.svg`、`scripts/` 全部、`README.md`、`blog.html`、`vlog.html`、`index_backup.html`、简历仓库 `/Users/bytedance/Desktop/resume`。
- `docs/superpowers/` 下的 spec/plan 文档**永不 git add**（用户惯例）。禁止 `git add -A` / `git add .`，只 add 明确列出的三个文件。
- CSS 变量名 `--page-background`、`--bg-void`、`--bg-deep`、`--bg-midnight` 及 html/body 背景结构不得改名/重构（tests/index-gallery.test.mjs 断言了这些结构）。
- 标题文案逐字为：`👋 你好，我是<span class="accent">王景宏</span>！`
- 提示语文案逐字为：`所有卡片均可点击，`（加粗）+ `欢迎探索、进一步了解我。`
- 配色令牌（来自 spec）：bg 三色 `#0b1226 / #14224a / #1d3057`；文字 `#f5f8ff / #c2d2ea`；阳光金 `#ffc069`；朝霞橘 `#ff9a62`；晨霞紫 `rgba(191, 145, 243, x)`（呼应卡片 #bf91f3，卡片本体不动）。
- 最终只允许**一条 commit** 进 main（含 index.html、viewer.html、assets/hint-text-for-index.svg 三个文件）。
- 本机 DNS 走代理 fake-IP，线上验证必须用 `curl --resolve wangjinghong.com:80:47.103.28.157`。

---

### Task 1: hint SVG 中文重制

**Files:**
- Modify: `assets/hint-text-for-index.svg`（整文件覆写）

**Interfaces:**
- Consumes: 无
- Produces: 同路径同名 SVG，被 `index.html` 的 `.readme-hint img`（高度 20px）引用，引用方无需改动

- [ ] **Step 1: 覆写 SVG 为中文 + 暖金流光**

用 Write 整文件覆写为：

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="380" height="30" viewBox="0 0 380 30">
    <defs>
        <clipPath id="typing">
            <rect x="0" y="0" width="0" height="30">
                <animate attributeName="width" from="0" to="380" dur="2.2s" fill="freeze" />
            </rect>
        </clipPath>
        <linearGradient id="shimmer" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" style="stop-color:#FFC069">
                <animate attributeName="stop-color" values="#FFC069;#BF91F3;#FFC069" dur="5s" begin="2.2s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1; 0.4 0 0.6 1" />
            </stop>
            <stop offset="50%" style="stop-color:#FFC069">
                <animate attributeName="stop-color" values="#FFC069;#FF9A62;#BF91F3" dur="5s" begin="2.2s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1; 0.4 0 0.6 1" />
            </stop>
            <stop offset="100%" style="stop-color:#FFC069">
                <animate attributeName="stop-color" values="#FFC069;#BF91F3;#FFC069" dur="5s" begin="2.2s" repeatCount="indefinite" calcMode="spline" keySplines="0.4 0 0.6 1; 0.4 0 0.6 1" />
            </stop>
        </linearGradient>
    </defs>
    <style>
        .hint {
            font-family: 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Segoe UI', sans-serif;
            font-size: 17px;
            fill: url(#shimmer);
        }
        .highlight {
            font-weight: 700;
        }
    </style>
    <text x="0" y="21" class="hint" clip-path="url(#typing)">
        <tspan class="highlight">所有卡片均可点击，</tspan>
        <tspan>欢迎探索、进一步了解我。</tspan>
    </text>
</svg>
```

- [ ] **Step 2: 浏览器目检**

Run: `open /Users/bytedance/Desktop/ceilf6/assets/hint-text-for-index.svg`（或后续 Task 4 截图统一验证）
Expected: 中文完整显示不截断（21 字 ×17px ≈ 357px，画布 380px 留有余量）；打字机入场后流光循环。若截断，把 width/viewBox/animate to 值同步调大到 400。

**不单独 commit**（并入 Task 4 的唯一 commit）。

---

### Task 2: index.html 文案中文化 + 黎明配色

**Files:**
- Modify: `index.html`（仅 `<style>` 内色值与 533 行 h1 文案；布局/JS 不动）

**Interfaces:**
- Consumes: Task 1 的 SVG（引用路径不变，无需改动）
- Produces: 新 CSS 令牌 `--accent-gold: #ffc069`、`--accent-dawn: #ff9a62`（替代删除的 `--accent-cyan`、`--accent-amber`；改完后全文件不得再出现 accent-cyan/accent-amber 引用）

- [ ] **Step 1: 替换 :root 令牌**

Edit old → new：

```css
        --bg-void: #050914;
        --bg-deep: #0c1730;
        --bg-midnight: #132541;
        --text-main: #eef4ff;
        --text-muted: #afc3dd;
        --accent-cyan: #57e3cf;
        --accent-amber: #ffb262;
        --panel-bg: rgba(8, 19, 36, 0.56);
        --panel-border: rgba(171, 212, 240, 0.24);
```

→

```css
        --bg-void: #0b1226;
        --bg-deep: #14224a;
        --bg-midnight: #1d3057;
        --text-main: #f5f8ff;
        --text-muted: #c2d2ea;
        --accent-gold: #ffc069;
        --accent-dawn: #ff9a62;
        --panel-bg: rgba(13, 22, 44, 0.56);
        --panel-border: rgba(255, 214, 166, 0.2);
```

- [ ] **Step 2: --page-background 三层光晕调成黎明**

三个 radial-gradient 依次替换（linear-gradient 基底行不动，变量已换新值）：

1. `rgba(255, 178, 98, 0.24) 0%` → `rgba(255, 192, 105, 0.28) 0%`（左上暖金加强）
2. `rgba(86, 227, 207, 0.22) 0%` → `rgba(191, 145, 243, 0.18) 0%`（右上青色 → 晨霞紫）
3. 第三层整段（含定位）替换，这就是签名元素「地平线晨光」：

```css
          radial-gradient(
            90% 140% at 48% 100%,
            rgba(104, 145, 255, 0.14) 0%,
            transparent 56%
          ),
```

→

```css
          radial-gradient(
            90% 120% at 50% 104%,
            rgba(255, 154, 98, 0.32) 0%,
            transparent 58%
          ),
```

- [ ] **Step 3: 散落青色/冷色 → 阳光金（逐处 Edit）**

| 位置 | old | new |
| --- | --- | --- |
| ::selection | `background: var(--accent-cyan);` + `color: #06121f;` | `background: var(--accent-gold);` + `color: #0b1226;` |
| scrollbar-thumb | `rgba(175, 195, 221, 0.28)` | `rgba(194, 210, 234, 0.3)` |
| scrollbar-thumb:hover | `rgba(87, 227, 207, 0.45)` | `rgba(255, 192, 105, 0.5)` |
| body::after 光斑1 | `rgba(255, 178, 98, 0.16)` | `rgba(255, 192, 105, 0.22)` |
| body::after 光斑2 | `rgba(87, 227, 207, 0.14)` | `rgba(191, 145, 243, 0.16)` |
| body::after 光斑3 | `rgba(120, 166, 255, 0.1)` | `rgba(255, 154, 98, 0.14)` |
| html::after 网格线×2 | `rgba(145, 184, 214, 0.07)` / `rgba(145, 184, 214, 0.06)` | `rgba(226, 199, 161, 0.07)` / `rgba(226, 199, 161, 0.06)` |
| .card 底 | `rgba(10, 24, 42, 0.86),` + `rgba(15, 33, 56, 0.56)` | `rgba(18, 28, 54, 0.86),` + `rgba(26, 40, 74, 0.56)` |
| loader 底 shimmer | `rgba(87, 227, 207, 0.1) 42%,` + `rgba(255, 178, 98, 0.08) 72%,` | `rgba(255, 192, 105, 0.12) 42%,` + `rgba(191, 145, 243, 0.08) 72%,` |
| loader 底色 | `rgba(8, 19, 36, 0.42)` | `rgba(13, 22, 44, 0.42)` |
| loader 圈 | `border-top-color: rgba(87, 227, 207, 0.88);` + `box-shadow: 0 0 24px rgba(87, 227, 207, 0.18);` | `border-top-color: rgba(255, 192, 105, 0.9);` + `box-shadow: 0 0 24px rgba(255, 192, 105, 0.2);` |
| is-error 文字 | `rgba(255, 178, 98, 0.88)` | `rgba(255, 154, 98, 0.92)` |
| .card:hover 光环 | `0 0 0 1px rgba(87, 227, 207, 0.4);` + `border-color: rgba(87, 227, 207, 0.48);` | `0 0 0 1px rgba(255, 192, 105, 0.42);` + `border-color: rgba(255, 192, 105, 0.5);` |
| readme-section::before 渐变 | `rgba(87, 227, 207, 0.68),` / `rgba(255, 178, 98, 0.58),` / `rgba(87, 227, 207, 0.68)` | `rgba(255, 192, 105, 0.68),` / `rgba(191, 145, 243, 0.58),` / `rgba(255, 192, 105, 0.68)` |
| h1 .accent 渐变 | `var(--accent-amber) 10%,` + `var(--accent-cyan) 90%` | `#ffcf87 10%,` + `var(--accent-dawn) 90%` |
| .readme-card 边框 | `rgba(194, 220, 245, 0.34)` | `rgba(255, 214, 166, 0.3)` |
| .readme-card 底 | `rgba(10, 24, 42, 0.92),` + `rgba(15, 33, 56, 0.68)` | `rgba(18, 28, 54, 0.92),` + `rgba(26, 40, 74, 0.68)` |
| .readme-card:hover | `border-color: rgba(87, 227, 207, 0.45);` + `0 0 0 1px rgba(87, 227, 207, 0.35);` | `border-color: rgba(255, 192, 105, 0.48);` + `0 0 0 1px rgba(255, 192, 105, 0.38);` |
| focus-visible | `outline: 2px solid var(--accent-cyan);` | `outline: 2px solid var(--accent-gold);` |

- [ ] **Step 4: h1 文案中文化**

```html
      <h1>👋 Hi there, I'm <span class="accent">ceilf6</span>!</h1>
```

→

```html
      <h1>👋 你好，我是<span class="accent">王景宏</span>！</h1>
```

- [ ] **Step 5: 残留冷色扫描（应零输出）**

Run: `grep -nE 'accent-cyan|accent-amber|57e3cf|87, 227, 207|86, 227, 207|145, 184, 214|104, 145, 255|120, 166, 255|175, 195, 221' index.html`
Expected: 无任何输出。有输出说明漏改，回 Step 3 补。

- [ ] **Step 6: 跑既有测试**

Run: `node --test tests/*.mjs`
Expected: `pass 13`，`fail 0`（结构断言未破坏）。

**不单独 commit**（并入 Task 4）。

---

### Task 3: viewer.html 色值同步

**Files:**
- Modify: `viewer.html`（只换色值，结构/JS 不动；先 Read 全文再 Edit）

**Interfaces:**
- Consumes: 无（独立页面，经 index.html 卡片点击打开）
- Produces: 无

- [ ] **Step 1: 逐处 Edit 色值**

| 行(约) | old | new |
| --- | --- | --- |
| 16 | `background: rgba(12, 25, 41, 0.98);` | `background: rgba(13, 22, 44, 0.98);` |
| 40-41 | `0 25px 80px rgba(56, 189, 248, 0.3),` + `0 0 60px rgba(139, 92, 246, 0.2);` | `0 25px 80px rgba(255, 192, 105, 0.26),` + `0 0 60px rgba(191, 145, 243, 0.22);` |
| 78 | `border-top-color: rgba(87, 227, 207, 0.9);` | `border-top-color: rgba(255, 192, 105, 0.9);` |
| 80 | `box-shadow: 0 0 30px rgba(87, 227, 207, 0.22);` | `box-shadow: 0 0 30px rgba(255, 192, 105, 0.24);` |
| 143-144 | `background: rgba(56, 189, 248, 0.45);` + `border-color: rgba(56, 189, 248, 0.9);` | `background: rgba(255, 192, 105, 0.45);` + `border-color: rgba(255, 192, 105, 0.9);` |

- [ ] **Step 2: 残留冷色扫描（应零输出）**

Run: `grep -nE '56, 189, 248|87, 227, 207|12, 25, 41' viewer.html`
Expected: 无输出。

- [ ] **Step 3: 跑既有测试**

Run: `node --test tests/*.mjs`
Expected: `pass 13`，`fail 0`（viewer-close 用例只测行为不测色值）。

**不单独 commit**（并入 Task 4）。

---

### Task 4: 整体验证 + 单条 commit + 部署上线验证

**Files:**
- Commit: `index.html`、`viewer.html`、`assets/hint-text-for-index.svg`（仅此三个）

**Interfaces:**
- Consumes: Task 1-3 的全部改动
- Produces: main 分支一条新 commit；线上 wangjinghong.com 更新

- [ ] **Step 1: 本地起服务 + Playwright 截图目检**

```bash
cd /Users/bytedance/Desktop/ceilf6 && python3 -m http.server 8899 &
```

用 webapp-testing 技能（或临时 Playwright 脚本）截图检查：
- `http://localhost:8899/index.html` 桌面 1440×900：标题为「👋 你好，我是王景宏！」、hint 中文流光、背景是暖调黎明蓝（底部有橙金地平线光晕）、四张深色卡片无违和
- 同页 390×844：单列瀑布流正常
- `http://localhost:8899/viewer.html?img=0`：背景暖 navy、加载圈金色

Expected: 目检符合 spec 配色意图；检完 `kill %1` 收掉服务器。

- [ ] **Step 2: 确认暂存区干净、只 add 三个文件**

```bash
git status --short
git add index.html viewer.html assets/hint-text-for-index.svg
git status --short   # docs/superpowers/ 必须仍是未跟踪/未暂存状态
```

Expected: 暂存区仅三个文件；`docs/superpowers/specs/2026-07-23-dawn-theme-design.md` 与本 plan 不在暂存区。

- [ ] **Step 3: 单条 commit 并推送**

```bash
git commit -m "feat: 黎明晨光主题，首屏文案中文化

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git pull --rebase origin main   # CI 的 stats 定时提交可能领先，先 rebase
git push origin main
```

Expected: push 成功，自动触发 Verify 与 Deploy to Alibaba Cloud ECS 两个 workflow。

- [ ] **Step 4: 等 CI 部署完成**

Run: `gh run list --limit 3` 直到 Deploy to Alibaba Cloud ECS 显示 completed/success（通常 1-2 分钟；可 `gh run watch <id>`）。
Expected: deploy workflow success。若失败，`gh run view <id> --log-failed` 排查。

- [ ] **Step 5: 线上验证（必须 --resolve，本机 DNS 是代理 fake-IP）**

```bash
curl -s --resolve wangjinghong.com:80:47.103.28.157 http://wangjinghong.com/ | grep -o '王景宏' | head -1
curl -s --resolve wangjinghong.com:80:47.103.28.157 http://wangjinghong.com/assets/hint-text-for-index.svg | grep -o '所有卡片均可点击'
```

Expected: 分别输出 `王景宏` 与 `所有卡片均可点击`。

---

## 完成定义

- 线上 http://wangjinghong.com/ 首屏中文文案 + 黎明配色生效，卡片原样。
- main 上只多一条内容 commit；spec/plan 未被提交。
- `node --test` 13/13 通过。
- 简历仓库零改动（用户暂缓）。
