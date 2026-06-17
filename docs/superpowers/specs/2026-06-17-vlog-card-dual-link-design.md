# Vlog-card 双平台跳转设计

日期：2026-06-17

## 背景

vlog-card 当前在两处被一个 `<a>` 包裹，只能跳转到单一 Bilibili 链接：

- `README.md:5` —— GitHub 渲染
- `index.html:555-562` —— 个人站点（`https://ceilf6.github.io/ceilf6/`）

需求：点击 vlog-card 时，能选择跳转到 Bilibili 或抖音。

约束：一个 `<img>` 外包一个 `<a>` 只能导航到一个 URL；且 GitHub 的 README 会过滤 JavaScript 与大部分交互，无法用悬浮弹窗/脚本实现多目标。

## 方案：中间选择页（Approach A）

vlog-card 改为链接到一个新的静态页面 `vlog.html`，页面上有两个按钮，分别跳转到 Bilibili 和抖音。普通链接在 GitHub 与站点上行为一致，绕开 GitHub 不能跑 JS 的限制。

权衡：多一次点击、多一个待维护页面；换来跨环境一致、可自由设计样式。

（已否决：B. 把卡片切成左右两个可点区域 —— 不直观、SVG 链接在 GitHub sanitizer 下不稳定；C. 额外加一个小图标卡 —— 破坏当前三卡布局。）

## 改动清单（外科手术式）

1. **新增** `vlog.html`（仓库根目录）→ 上线地址 `https://ceilf6.github.io/ceilf6/vlog.html`
   - 两个按钮/卡片：
     - Bilibili → `https://space.bilibili.com/3546602400647622`
     - 抖音 → `https://www.douyin.com/user/MS4wLjABAAAA1y3YuKPCNetqkJ0FC20HMHXx7lz_T1pQsgvloOaZn-Y`
   - 两个按钮均 `target="_blank" rel="noopener noreferrer"`（新标签页打开）
   - 暗色主题，沿用现有配色（背景 `#1a1b27`，强调色 `#70a5fd` / `#bf91f3`）；含平台名称/图标
   - 一个低存在感的「返回主页」链接指向 `https://ceilf6.github.io/ceilf6/`
   - 使用 frontend-design skill 完成视觉
2. **修改** `README.md:5` —— vlog 的 `<a href>` 改为绝对地址 `https://ceilf6.github.io/ceilf6/vlog.html`（GitHub 需绝对路径）。`<img>`、`width="33%"`、三卡布局保持不变。
3. **修改** `index.html:557` —— vlog 的 `<a href>` 改为相对地址 `vlog.html`。其余属性（`class`、`target`、`rel`、loader、`<img>` 尺寸）保持不变。

注：`assets/vlog-card.svg` 及其生成脚本 `scripts/generate-svg-cards.py` 不涉及 href，无需改动。

## 验收标准（可验证）

- [ ] `vlog.html` 存在于仓库根目录，本地打开渲染出两个按钮 + 返回链接。
- [ ] 点击 Bilibili 按钮 → 在新标签页打开 `space.bilibili.com/3546602400647622`。
- [ ] 点击抖音按钮 → 在新标签页打开给定的抖音用户主页。
- [ ] `README.md:5` 的 vlog href = `https://ceilf6.github.io/ceilf6/vlog.html`；该行其余内容（img、33% 宽度、三卡同行）逐字不变。
- [ ] `index.html:557` 的 vlog href = `vlog.html`；周围属性与布局不变。
- [ ] 现有测试（`tests/*.mjs`）仍全部通过，且未引用被改动的 href。
- [ ] 部署后 `https://ceilf6.github.io/ceilf6/vlog.html` 可访问（实现阶段验证 Pages 已启用）。

## 假设

1. GitHub Pages 已为 `ceilf6/ceilf6` 启用并服务仓库根目录（README 现有链接 `https://ceilf6.github.io/ceilf6/` 佐证）。实现阶段需访问线上 URL 确认。
2. 页面为纯静态 HTML/CSS，无构建步骤，与 `index.html` 一致。
